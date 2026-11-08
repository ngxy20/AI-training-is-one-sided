"""Agent sessions: plan -> human review -> execute through existing endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import Body
from sqlalchemy import select

from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import AgentSession
from ..services import agent as service
from ..services import identity
from ..util import as_dict, paginate, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@router.get("/projects/{pid}/agent/tools")
def agent_tools(pid: str = ProjectId) -> Any:
    return {"items": service.describe(), "high_risk": sorted(service.HIGH_RISK)}


@router.post("/projects/{pid}/agent/plan")
def create_plan(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    goal = str(payload.get("goal") or "").strip()
    model_id = payload.get("model_id") or None
    with project_session(pid) as session:
        plan = service.build_plan(goal, model_id, session, pid)
        row = AgentSession(
            id=uid(), project_id=pid, goal=goal, model_id=model_id,
            plan_json=plan["steps"], source=plan["source"], status="planned")
        session.add(row)
        session.commit()
        record(session, "agent.plan", "agent_session", row.id,
               {"source": plan["source"], "steps": len(plan["steps"])}, pid,
               actor=identity.actor_name())
        return {**as_dict(row), "warnings": plan["warnings"]}


@router.get("/projects/{pid}/agent/sessions")
def list_sessions(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        return paginate(session, select(AgentSession).where(
            AgentSession.project_id == pid).order_by(AgentSession.created_at.desc()), page, size)


@router.get("/agent/sessions/{id}")
def get_session(id: str) -> Any:
    pid = entity_project(AgentSession, id)
    with project_session(pid) as session:
        return as_dict(get_or_404(session, AgentSession, id, "Agent 会话"))


@router.put("/agent/sessions/{id}/plan")
def update_plan(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    pid = entity_project(AgentSession, id)
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ApiError("VALIDATION_ERROR", "steps 必须是数组", 422)
    with project_session(pid) as session:
        row = get_or_404(session, AgentSession, id, "Agent 会话")
        for step in steps:
            if not isinstance(step, dict) or step.get("tool") not in service.TOOL_NAMES:
                raise ApiError("AGENT_TOOL", f"未知工具: {step.get('tool') if isinstance(step, dict) else step}", 422)
        row.plan_json = steps
        session.commit()
        record(session, "agent.plan.edit", "agent_session", id, {"steps": len(steps)}, pid,
               actor=identity.actor_name())
        return as_dict(row)


@router.post("/agent/sessions/{id}/execute")
async def execute_session(id: str, payload: dict[str, Any] = Body(default={})) -> Any:
    pid = entity_project(AgentSession, id)
    confirmed = bool(payload.get("confirmed"))
    continue_on_error = bool(payload.get("continue_on_error"))
    with project_session(pid) as session:
        row = get_or_404(session, AgentSession, id, "Agent 会话")
        steps = list(row.plan_json or [])
        if not steps:
            raise ApiError("VALIDATION_ERROR", "该会话还没有计划", 422)
        row.status = "running"
        row.error = ""
        session.commit()

    async def worker(ctx):
        results = await service.execute(steps, pid, ctx, confirmed=confirmed,
                                        continue_on_error=continue_on_error)
        with project_session(pid) as inner:
            session_row = inner.get(AgentSession, id)
            session_row.result_json = results
            failed = [r for r in results if r["status"] == "failed"]
            pending = [r for r in results if r["status"] == "needs_confirmation"]
            session_row.status = "needs_confirmation" if pending else "failed" if failed else "succeeded"
            if failed:
                session_row.error = str(failed[0].get("error") or failed[0].get("result") or "执行失败")[:500]
            inner.commit()
            record(inner, "agent.execute", "agent_session", id,
                   {"status": session_row.status, "steps": len(results)}, pid,
                   actor=identity.actor_name())
        return {"session_id": id, "status": session_row.status, "results": results}

    job = jobs.submit(pid, "agent.execute", {"session_id": id, "steps": len(steps)}, worker)
    with project_session(pid) as session:
        row = session.get(AgentSession, id)
        row.job_id = job["id"]
        session.commit()
    return {"session_id": id, "job_id": job["id"], "status": "queued", "confirmed": confirmed}
