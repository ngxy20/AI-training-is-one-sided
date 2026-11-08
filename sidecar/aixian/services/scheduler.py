"""Cron scheduler: 5-field expressions, due scans, dispatch through the Job table.

No third-party scheduler dependency: a single asyncio task scans every 20s and
reuses the existing endpoint handlers so scheduled runs create real Jobs/logs.
"""
from __future__ import annotations

import asyncio
import subprocess
import traceback
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from .. import config, workspace
from ..database import project_session, registry_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import Project, Schedule
from ..util import as_dict, now

SCHEDULE_TYPES: list[dict[str, Any]] = [
    {"type": "script.run", "label": "运行数据收集脚本", "needs_target": True,
     "target_endpoint": "/projects/{pid}/scripts", "needs": [],
     "payload_template": {"params": {}}},
    {"type": "pipeline.run", "label": "复跑清洗 Pipeline", "needs_target": True,
     "target_endpoint": "/projects/{pid}/pipelines", "needs": ["source_version_id"],
     "payload_template": {"source_version_id": ""}},
    {"type": "eval.run", "label": "运行评测套件", "needs_target": True,
     "target_endpoint": "/projects/{pid}/eval-suites", "needs": ["model_ref_json"],
     "payload_template": {"model_ref_json": {"type": "inline", "field": "output"},
                          "scorer_json": {"type": "exact_match"}, "dataset_version_ids": []}},
    {"type": "command", "label": "执行本地命令", "needs_target": False,
     "target_endpoint": "", "needs": ["command"],
     "payload_template": {"command": "echo hello"}},
]
SCHEDULE_TYPE_NAMES = tuple(item["type"] for item in SCHEDULE_TYPES)


def _field(expr: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    if expr == "*":
        return set(range(low, high + 1))
    for chunk in expr.split(","):
        step = 1
        if "/" in chunk:
            chunk, raw_step = chunk.split("/", 1)
            step = max(1, int(raw_step))
        if chunk == "*":
            start, end = low, high
        elif "-" in chunk:
            left, right = chunk.split("-", 1)
            start, end = int(left), int(right)
        else:
            value = int(chunk)
            if step > 1:
                start, end = value, high
            else:
                values.add(value)
                continue
        values.update(range(start, min(end, high) + 1, step))
    return values


def parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    parts = str(expr or "").split()
    if len(parts) != 5:
        raise ApiError("INVALID_CRON", "cron 表达式需要 5 段：分 时 日 月 周", 422, expr)
    minute = _field(parts[0], 0, 59)
    hour = _field(parts[1], 0, 23)
    dom = _field(parts[2], 1, 31)
    month = _field(parts[3], 1, 12)
    dow = _field(parts[4].replace("7", "0"), 0, 7)
    return minute, hour, dom, month, dow, parts[2] != "*", parts[4] != "*"


def matches(expr: str, moment: datetime) -> bool:
    minute, hour, dom, month, dow, dom_restricted, dow_restricted = parse_cron(expr)
    if moment.minute not in minute or moment.hour not in hour or moment.month not in month:
        return False
    weekday = (moment.weekday() + 1) % 7  # cron: 0 = Sunday
    dom_ok = moment.day in dom
    dow_ok = weekday in dow or (weekday == 0 and 7 in dow)
    if dom_restricted and dow_restricted:
        return dom_ok or dow_ok
    if dom_restricted:
        return dom_ok
    if dow_restricted:
        return dow_ok
    return True


def next_after(expr: str, after: datetime) -> datetime:
    """Return the next matching minute, or raise if none within a year."""
    minute, hour, dom, month, dow, dom_restricted, dow_restricted = parse_cron(expr)
    candidate = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limit = after + timedelta(days=366)
    while candidate < limit:
        if candidate.month not in month:
            candidate = (candidate.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        if candidate.hour not in hour:
            candidate = (candidate + timedelta(hours=1)).replace(minute=0)
            continue
        if candidate.minute not in minute:
            candidate += timedelta(minutes=1)
            continue
        weekday = (candidate.weekday() + 1) % 7
        dom_ok = candidate.day in dom
        dow_ok = weekday in dow or (weekday == 0 and 7 in dow)
        if (dom_restricted and dow_restricted and not (dom_ok or dow_ok)) or \
           (dom_restricted and not dow_restricted and not dom_ok) or \
           (dow_restricted and not dom_restricted and not dow_ok):
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        return candidate
    raise ApiError("INVALID_CRON", "该 cron 表达式在未来一年内没有匹配时间", 422, expr)


async def _command_job(pid: str, payload: dict[str, Any]) -> str:
    command = str(payload.get("command") or "").strip()
    if not command or len(command) > 2000:
        raise ApiError("VALIDATION_ERROR", "命令为空或过长", 422)

    async def worker(ctx):
        root = workspace.ensure_workspace(pid)

        def run() -> subprocess.CompletedProcess:
            return subprocess.run(command, shell=True, cwd=str(root), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=300)

        completed = await asyncio.to_thread(run)
        ctx.log((completed.stdout or "")[-10000:])
        if completed.returncode != 0:
            raise ApiError("SCHEDULE_COMMAND_FAILED",
                           f"命令退出码 {completed.returncode}", 500, completed.stderr or "")
        return {"exit_code": completed.returncode, "command": command}

    return jobs.submit(pid, "scheduled.command", {"command": command}, worker)["id"]


async def dispatch(pid: str, item: dict[str, Any]) -> str:
    """Trigger one schedule by reusing the existing endpoint handlers."""
    kind = item["type"]
    payload = dict(item.get("payload_json") or {})
    target = item.get("target_id") or ""
    if kind == "script.run":
        from ..api.scripts import run_script

        result = await run_script(target, {"params": payload.get("params") or {}})
    elif kind == "pipeline.run":
        from ..api.pipelines import run_pipeline

        result = await run_pipeline(target, {
            "source_version_id": payload.get("source_version_id"),
            "dataset_id": payload.get("dataset_id"),
        })
    elif kind == "eval.run":
        from ..api.evaluation import create_eval_run

        result = await create_eval_run(target, {
            "model_ref_json": payload.get("model_ref_json") or {"type": "inline", "field": "output"},
            "scorer_json": payload.get("scorer_json") or {"type": "exact_match"},
            "dataset_version_ids": payload.get("dataset_version_ids") or [],
        })
    elif kind == "command":
        return await _command_job(pid, payload)
    else:
        raise ApiError("UNSUPPORTED_SCHEDULE", f"未知调度类型: {kind}", 422)
    return str(result.get("job_id", ""))


class Scheduler:
    def __init__(self, interval: float = 20.0) -> None:
        self.interval = interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="aixian-scheduler")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive bad schedules
                traceback.print_exc()
            await asyncio.sleep(self.interval)

    async def tick(self) -> int:
        moment = now()
        with registry_session() as registry:
            project_ids = [p.id for p in registry.execute(select(Project)).scalars().all()]
        fired = 0
        for pid in project_ids:
            with project_session(pid) as session:
                due = session.execute(select(Schedule).where(
                    Schedule.enabled == 1, Schedule.next_run_at <= moment)).scalars().all()
                items: list[dict[str, Any]] = []
                for row in due:
                    try:
                        row.next_run_at = next_after(row.cron_expr, moment)
                    except ApiError as exc:
                        row.enabled = 0
                        row.last_error = str(exc)
                        continue
                    row.last_run_at = moment
                    items.append(as_dict(row))
                session.commit()
            for item in items:
                fired += 1
                try:
                    job_id = await dispatch(pid, item)
                    error = ""
                except Exception as exc:  # noqa: BLE001
                    job_id, error = "", f"{type(exc).__name__}: {exc}"
                with project_session(pid) as session:
                    row = session.get(Schedule, item["id"])
                    if row:
                        row.run_count = (row.run_count or 0) + 1
                        row.last_job_id = job_id or None
                        row.last_error = error
                        session.commit()
        return fired


scheduler = Scheduler()
