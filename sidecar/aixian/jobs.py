"""Lightweight Job table + asyncio executor with file/WS log streaming and cancel."""
from __future__ import annotations

import asyncio
import inspect
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from . import workspace
from .database import project_session
from .events import hub
from .models import Job
from .util import as_dict, now, uid, write_json

Worker = Callable[["RunContext"], Awaitable[Any] | Any]


@dataclass
class RunContext:
    job_id: str
    project_id: str
    log_path: Path

    def log(self, message: str) -> None:
        line = str(message).rstrip("\r\n")
        with self.log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(line + "\n")
        hub.emit("job.log", {"job_id": self.job_id, "line": line}, self.project_id)

    def progress(self, value: float) -> None:
        with project_session(self.project_id) as session:
            job = session.get(Job, self.job_id)
            if job:
                job.progress = max(0.0, min(1.0, float(value)))
                session.commit()
        hub.emit("job.progress", {"job_id": self.job_id, "progress": value}, self.project_id)

    async def exec(self, command: list[str], cwd: str | Path, env: dict[str, str] | None = None) -> int:
        import os

        merged = {**os.environ, **(env or {})}
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=merged,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert process.stdout is not None
        async for raw in process.stdout:
            self.log(raw.decode("utf-8", errors="replace"))
        return await process.wait()

    def write_result(self, name: str, value: Any) -> Path:
        path = self.log_path.parent / f"{self.job_id}_{name}.json"
        return write_json(path, value)


class JobManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(
        self,
        project_id: str,
        job_type: str,
        payload: dict[str, Any],
        worker: Worker,
        runner_type: str = "local",
        log: bool = True,
    ) -> dict[str, Any]:
        job_id = uid()
        root = workspace.ensure_workspace(project_id)
        log_path = root / "logs" / f"{job_id}.log"
        if log:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch()
        with project_session(project_id) as session:
            job = Job(
                id=job_id,
                project_id=project_id,
                type=job_type,
                payload_json=payload,
                runner_type=runner_type,
                status="queued",
                log_path=workspace.relative(project_id, log_path),
            )
            session.add(job)
            session.commit()
            result = as_dict(job)
        task = asyncio.create_task(self._execute(job_id, project_id, worker, log_path), name=job_id)
        self._tasks[job_id] = task
        hub.emit("job.status", {"job_id": job_id, "status": "queued", "type": job_type}, project_id)
        return result

    async def _execute(self, job_id: str, project_id: str, worker: Worker, log_path: Path) -> None:
        ctx = RunContext(job_id, project_id, log_path)
        self._set_state(job_id, project_id, "running", started=True)
        try:
            if inspect.iscoroutinefunction(worker):
                result = await worker(ctx)
            else:
                result = await asyncio.to_thread(worker, ctx)
            if inspect.isawaitable(result):
                result = await result
            self._set_state(job_id, project_id, "succeeded", progress=1.0, result=result)
            ctx.log(f"[aixian] Job {job_id} 完成")
        except asyncio.CancelledError:
            self._set_state(job_id, project_id, "cancelled")
            ctx.log("[aixian] 任务已取消")
        except Exception as exc:  # noqa: BLE001 - surface every failure to the UI
            message = f"{type(exc).__name__}: {exc}"
            self._set_state(job_id, project_id, "failed", error=message)
            ctx.log("[aixian] 任务失败: " + message)
            ctx.log(traceback.format_exc())
        finally:
            self._tasks.pop(job_id, None)

    def _set_state(
        self,
        job_id: str,
        project_id: str,
        status: str,
        started: bool = False,
        progress: float | None = None,
        error: str = "",
        result: Any = None,
    ) -> None:
        with project_session(project_id) as session:
            job = session.get(Job, job_id)
            if not job:
                return
            job.status = status
            if started:
                job.started_at = now()
            if progress is not None:
                job.progress = progress
            if status in ("succeeded", "failed", "cancelled"):
                job.finished_at = now()
            if error:
                job.error = error
            if result is not None:
                job.payload_json = {**(job.payload_json or {}), "result": result}
            session.commit()
        hub.emit("job.status", {"job_id": job_id, "status": status, "error": error}, project_id)

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def running(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())


def job_logs(project_id: str, job_id: str, tail: int = 2000) -> list[str]:
    with project_session(project_id) as session:
        job = session.scalar(select(Job).where(Job.id == job_id))
        if job is None:
            return []
        path = workspace.resolve(project_id, job.log_path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-tail:]


jobs = JobManager()
