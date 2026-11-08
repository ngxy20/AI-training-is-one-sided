"""Collection script CRUD, version snapshots and execution."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body
from sqlalchemy import select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import Script
from ..services import scripts as service
from ..services.common import infer_params_schema
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()

DEFAULT_PY = '''"""数据收集脚本模板：把产物写入 AIXIAN_OUTPUT (JSONL)。"""
import json
import os

params = json.load(open(os.environ["AIXIAN_PARAMS"], encoding="utf-8"))
n = int(params.get("n", 10))
with open(os.environ["AIXIAN_OUTPUT"], "w", encoding="utf-8") as f:
    for i in range(n):
        f.write(json.dumps({"text": f"样本 {i}", "label": "example"}, ensure_ascii=False) + "\\n")
print(f"生成 {n} 条记录")
'''

DEFAULT_SQL = "-- 在此编写只读 SQL，结果将落盘为数据集版本\nSELECT 1 AS id, 'hello' AS text;\n"


@contextmanager
def script_ctx(ident: str) -> Iterator[tuple[str, Any, Script]]:
    pid = entity_project(Script, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, Script, ident, "脚本")


@router.get("/projects/{pid}/scripts")
def list_scripts(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(Script).where(Script.project_id == pid).order_by(Script.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/scripts")
def create_script(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    script_type = data.get("type", "py")
    if script_type not in ("py", "sql"):
        raise ApiError("VALIDATION_ERROR", "脚本类型仅支持 py / sql", 422)
    script_id = uid()
    content = data.get("content") or (DEFAULT_SQL if script_type == "sql" else DEFAULT_PY)
    workspace.ensure_workspace(pid)
    row = Script(id=script_id, project_id=pid, name=data["name"], type=script_type,
                 path=f"scripts/{script_id}.{'sql' if script_type == 'sql' else 'py'}",
                 params_schema_json=data.get("params_schema_json") or infer_params_schema(data.get("params") or {}),
                 description=data.get("description", ""), version=1)
    with project_session(pid) as session:
        session.add(row)
        session.commit()
    service.save_content(pid, row, content)
    service.snapshot_version(pid, row, content)
    return {**as_dict(row), "content": content}


@router.get("/scripts/{id}")
def get_script(id: str) -> Any:
    with script_ctx(id) as (pid, _, row):
        return {**as_dict(row), "content": service.read_content(pid, row),
                "versions": service.list_versions(pid, id)}


@router.get("/scripts/{id}/versions")
def script_versions(id: str) -> Any:
    with script_ctx(id) as (pid, _, _):
        return service.list_versions(pid, id)


@router.put("/scripts/{id}")
def update_script(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    with script_ctx(id) as (pid, session, row):
        if "content" in payload:
            previous = service.read_content(pid, row)
            service.snapshot_version(pid, row, previous)
            service.save_content(pid, row, payload["content"])
            row.version = (row.version or 1) + 1
        for key in ("name", "description", "params_schema_json"):
            if key in payload:
                setattr(row, key, payload[key])
        session.commit()
        record(session, "script.update", "script", id, {"version": row.version}, pid)
        return {**as_dict(row), "content": service.read_content(pid, row)}


@router.post("/scripts/{id}/run")
async def run_script(id: str, payload: dict[str, Any] = Body(default={})) -> Any:
    with script_ctx(id) as (pid, _, row):
        script_id = row.id
        params = {**({"n": 10} if row.type == "py" else {}), **(payload.get("params") or {})}
        script_type = row.type
    workspace.ensure_workspace(pid)

    async def worker(ctx):
        result = await service.run_worker(pid, script_id, params, ctx)
        with project_session(pid) as session:
            record(session, "script.run", "script", script_id, result, pid)
        return result

    job = jobs.submit(pid, f"script.{script_type}", {"script_id": script_id, "params": params}, worker)
    return {"job_id": job["id"], "status": "queued", "script_id": script_id}
