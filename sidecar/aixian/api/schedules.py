"""Project-scoped cron schedules."""
from __future__ import annotations

from typing import Any

from fastapi import Body
from sqlalchemy import select

from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..models import Schedule
from ..services import identity, scheduler
from ..util import as_dict, now, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@router.get("/projects/{pid}/schedule-types")
def schedule_types(pid: str = ProjectId) -> Any:
    return {"items": scheduler.SCHEDULE_TYPES}


@router.get("/projects/{pid}/schedules")
def list_schedules(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(Schedule).where(Schedule.project_id == pid).order_by(Schedule.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/schedules")
def create_schedule(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name", "type", "cron_expr")
    if data["type"] not in scheduler.SCHEDULE_TYPE_NAMES:
        raise ApiError("UNSUPPORTED_SCHEDULE",
                       f"调度类型仅支持 {scheduler.SCHEDULE_TYPE_NAMES}", 422)
    descriptor = next(d for d in scheduler.SCHEDULE_TYPES if d["type"] == data["type"])
    if descriptor["needs_target"] and not data.get("target_id"):
        raise ApiError("VALIDATION_ERROR", "该调度类型需要 target_id", 422)
    body = data.get("payload_json") or {}
    for key in descriptor["needs"]:
        if not body.get(key):
            raise ApiError("VALIDATION_ERROR", f"payload_json 缺少必填项 {key}", 422)
    next_run = scheduler.next_after(data["cron_expr"], now()) if data.get("enabled", 1) else None
    with project_session(pid) as session:
        row = Schedule(
            id=uid(), project_id=pid, name=data["name"], type=data["type"],
            cron_expr=data["cron_expr"], target_id=data.get("target_id") or "",
            payload_json=body, enabled=1 if data.get("enabled", 1) else 0,
            next_run_at=next_run, created_by=identity.actor_name(),
        )
        session.add(row)
        session.commit()
        record(session, "schedule.create", "schedule", row.id,
               {"cron": row.cron_expr, "type": row.type}, pid, actor=identity.actor_name())
        return as_dict(row)


@router.patch("/schedules/{id}")
def update_schedule(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    pid = entity_project(Schedule, id)
    with project_session(pid) as session:
        row = get_or_404(session, Schedule, id, "定时任务")
        if "cron_expr" in payload:
            scheduler.parse_cron(payload["cron_expr"])
            row.cron_expr = payload["cron_expr"]
            row.next_run_at = scheduler.next_after(row.cron_expr, now())
        for key in ("name", "target_id", "payload_json"):
            if key in payload:
                setattr(row, key, payload[key])
        if "enabled" in payload:
            row.enabled = 1 if payload["enabled"] else 0
            row.next_run_at = scheduler.next_after(row.cron_expr, now()) if row.enabled else None
        session.commit()
        record(session, "schedule.update", "schedule", id, {"enabled": row.enabled}, pid,
               actor=identity.actor_name())
        return as_dict(row)


@router.delete("/schedules/{id}")
def delete_schedule(id: str) -> Any:
    pid = entity_project(Schedule, id)
    with project_session(pid) as session:
        row = get_or_404(session, Schedule, id, "定时任务")
        session.delete(row)
        session.commit()
        record(session, "schedule.delete", "schedule", id, {}, pid, actor=identity.actor_name())
        return {"id": id, "deleted": True}


@router.post("/schedules/{id}/run-now")
async def run_now(id: str) -> Any:
    pid = entity_project(Schedule, id)
    with project_session(pid) as session:
        row = get_or_404(session, Schedule, id, "定时任务")
        item = as_dict(row)
    job_id = await scheduler.dispatch(pid, item)
    with project_session(pid) as session:
        row = session.get(Schedule, id)
        row.run_count = (row.run_count or 0) + 1
        row.last_run_at = now()
        row.last_job_id = job_id or None
        row.last_error = ""
        session.commit()
        record(session, "schedule.run", "schedule", id, {"job_id": job_id}, pid,
               actor=identity.actor_name())
    return {"schedule_id": id, "job_id": job_id, "status": "queued"}
