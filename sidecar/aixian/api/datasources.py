"""Existing-database connections, schema browsing, SQL editor and import."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body, Query
from sqlalchemy import select

from .. import config, security
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..models import DataSource, Dataset
from ..services import datasets as dataset_service
from ..services import datasources as service
from ..services.common import get_or_create_dataset
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@contextmanager
def source_ctx(ident: str) -> Iterator[tuple[str, Any, DataSource]]:
    pid = entity_project(DataSource, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, DataSource, ident, "数据源")


def _public(row: DataSource) -> dict[str, Any]:
    data = as_dict(row, exclude=("conn_json",))
    data["config"] = security.mask_config(service.connection_config(row))
    data["uri"] = "aixian://project/{}/datasource/{}".format(row.project_id, row.id)
    return data


@router.get("/projects/{pid}/datasources")
def list_datasources(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(DataSource).where(DataSource.project_id == pid).order_by(DataSource.created_at.desc())
        result = paginate(session, query, page, size, _public)
        return result


@router.post("/projects/{pid}/datasources")
def create_datasource(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name", "type", "config")
    row = DataSource(
        id=uid(), project_id=pid, name=data["name"], type=data["type"],
        conn_json=security.encrypt_obj(data["config"]),
        plugin_id=data.get("plugin_id"), status="untested",
    )
    with project_session(pid) as session:
        session.add(row)
        session.commit()
        return _public(row)


@router.get("/datasources/{id}")
def get_datasource(id: str) -> Any:
    with source_ctx(id) as (_, _, row):
        return _public(row)


@router.patch("/datasources/{id}")
def update_datasource(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    with source_ctx(id) as (pid, session, row):
        for key in ("name", "type", "plugin_id"):
            if key in payload:
                setattr(row, key, payload[key])
        if "config" in payload:
            row.conn_json = security.encrypt_obj(payload["config"])
            row.status = "untested"
        session.commit()
        record(session, "datasource.update", "datasource", id, project_id=pid)
        return _public(row)


@router.delete("/datasources/{id}")
def delete_datasource(id: str) -> Any:
    with source_ctx(id) as (pid, session, row):
        session.delete(row)
        session.commit()
        record(session, "datasource.delete", "datasource", id, project_id=pid)
        return {"id": id, "deleted": True}


@router.post("/datasources/{id}/test")
def test_datasource(id: str) -> Any:
    with source_ctx(id) as (pid, session, row):
        try:
            result = service.test_connection(row)
            row.status = "ok" if result.get("ok") else "failed"
        except Exception as exc:
            row.status = "failed"
            session.commit()
            record(session, "datasource.test", "datasource", id, {"ok": False}, pid)
            raise ApiError("CONNECTION_FAILED", f"连接失败: {exc}", 400, str(exc)) from exc
        from ..util import now
        row.last_tested_at = now()
        session.commit()
        record(session, "datasource.test", "datasource", id, {"ok": True}, pid)
        return {"ok": True, "status": row.status, **result}


@router.get("/datasources/{id}/schema")
def datasource_schema(id: str) -> Any:
    with source_ctx(id) as (_, _, row):
        return service.list_schema(row)


@router.post("/datasources/{id}/query")
def datasource_query(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "sql")
    max_rows = int(data.get("max_rows") or config.load_settings().get("max_query_rows", 500))
    with source_ctx(id) as (pid, session, row):
        result = service.query(row, data["sql"], max_rows)
        record(session, "datasource.query", "datasource", id,
               {"rows": result["row_count"], "truncated": result["truncated"]}, pid)
        return result


@router.post("/datasources/{id}/import")
def import_query_result(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "sql")
    with source_ctx(id) as (pid, session, row):
        result = service.query(row, data["sql"], int(data.get("max_rows", 10000)))
        rows = dataset_service.apply_field_mapping(result["rows"], data.get("field_mapping"))
        dataset = get_or_create_dataset(session, pid, data.get("dataset_name") or f"{row.name} 查询结果",
                                        data.get("dataset_id"), "datasource")
        version = dataset_service.create_version(
            session, pid, dataset, rows,
            changelog=data.get("changelog") or f"从数据源 {row.name} 导入 {len(rows)} 条",
            source="datasource",
        )
        record(session, "dataset.import", "dataset_version", version.id,
               {"rows": len(rows), "datasource_id": id}, pid)
        return {"dataset_id": dataset.id, "dataset_version_id": version.id, "record_count": version.record_count}
