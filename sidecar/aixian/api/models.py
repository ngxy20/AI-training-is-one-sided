"""Model registry API: register a path/endpoint once, reference it everywhere."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Body, Query
from sqlalchemy import select

from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..models import Model
from ..services import identity, model_adapters, registry as service
from ..util import as_dict, paginate, require
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@router.get("/projects/{pid}/model-kinds")
def model_kinds(pid: str = ProjectId) -> Any:
    """Metadata for the registration form."""
    return {"kinds": list(service.KINDS), "statuses": list(service.STATUSES),
            "adapters": model_adapters.describe()}


@router.get("/projects/{pid}/models")
def list_models(pid: str = ProjectId, page: int = 1, size: int = 50,
                kind: str | None = None, status: str | None = None,
                q: str = Query("", max_length=200)) -> Any:
    with project_session(pid) as session:
        query = select(Model).where(Model.project_id == pid)
        if kind:
            query = query.where(Model.kind == kind)
        if status:
            query = query.where(Model.status == status)
        else:
            query = query.where(Model.status != "archived")
        if q:
            query = query.where(Model.name.like(f"%{q}%"))
        result = paginate(session, query.order_by(Model.created_at.desc()), page, size)
        for item in result["items"]:
            item["path_status"] = service.path_status(item.get("ref_json") or {})
            item["usage"] = service.usage(session, item["id"])
        return result


@router.post("/projects/{pid}/models")
def create_model(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    require(payload, "name")
    with project_session(pid) as session:
        row = service.create(session, pid, payload)
        record(session, "model.create", "model", row["id"],
               {"name": row["name"], "type": row["ref_json"].get("type")}, pid,
               actor=identity.actor_name())
        return row


@router.get("/models/{id}")
def get_model(id: str) -> Any:
    pid = entity_project(Model, id)
    with project_session(pid) as session:
        return service.detail(session, pid, id)


@router.put("/models/{id}")
def update_model(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    pid = entity_project(Model, id)
    with project_session(pid) as session:
        row = service.update(session, pid, id, payload)
        record(session, "model.update", "model", id, {"version": row["version"]}, pid,
               actor=identity.actor_name())
        return row


@router.delete("/models/{id}")
def archive_model(id: str) -> Any:
    pid = entity_project(Model, id)
    with project_session(pid) as session:
        row = get_or_404(session, Model, id, "模型")
        row.status = "archived"
        session.commit()
        record(session, "model.archive", "model", id, {}, pid, actor=identity.actor_name())
        return as_dict(row)


@router.get("/models/{id}/usage")
def model_usage(id: str) -> Any:
    pid = entity_project(Model, id)
    with project_session(pid) as session:
        get_or_404(session, Model, id, "模型")
        return service.usage(session, id)


@router.post("/models/{id}/test")
async def test_model(id: str, payload: dict[str, Any] = Body(default={})) -> Any:
    pid = entity_project(Model, id)
    prompt = str(payload.get("prompt") or "你好，请用一句话介绍自己。")
    with project_session(pid) as session:
        # resolve under the session, then run the possibly slow call off-loop
        ref, row = service.resolve(session, pid, id)
        prepared = model_adapters.prepare(ref, session)
        model_name = row.name if row else id
    case = {"id": "registry-test", "input": prompt, "expected": "", "category": "general"}

    def invoke() -> str:
        try:
            return model_adapters.generate(case, prepared, project_id=pid, index=0)
        except Exception as exc:  # noqa: BLE001
            return f"[模型调用失败: {type(exc).__name__}: {exc}]"

    output = await asyncio.to_thread(invoke)
    with project_session(pid) as session:
        row = session.get(Model, id)
        if row:
            from ..util import now
            row.last_tested_at = now()
            if not output.startswith("[模型调用失败") and row.status == "missing":
                row.status = "active"
            session.commit()
        record(session, "model.test", "model", id, {"ok": not output.startswith("[模型调用失败")},
               pid, actor=identity.actor_name())
    return {"model_id": id, "name": model_name, "prompt": prompt, "output": output,
            "ok": not output.startswith("[模型调用失败")}
