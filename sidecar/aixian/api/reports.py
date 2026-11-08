"""Report CRUD and HTML / PDF / JSON / Markdown export."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..models import Report
from ..services import reports as service
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@contextmanager
def report_ctx(ident: str) -> Iterator[tuple[str, Any, Report]]:
    pid = entity_project(Report, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, Report, ident, "报告")


@router.get("/projects/{pid}/reports")
def list_reports(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(Report).where(Report.project_id == pid).order_by(Report.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/reports")
def create_report(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "linked_entities_json")
    with project_session(pid) as session:
        row = service.create_report(session, pid, data)
        record(session, "report.create", "report", row.id,
               {"type": row.type, "linked": row.linked_entities_json}, pid)
        return as_dict(row)


@router.get("/reports/{id}")
def get_report(id: str) -> Any:
    with report_ctx(id) as (_, _, row):
        return as_dict(row)


@router.get("/reports/{id}/export")
def export_report(id: str, format: str = Query("html", alias="format"), download: bool = False) -> Any:
    with report_ctx(id) as (pid, _, row):
        relative = service.export_path(row, format)
        if not relative:
            raise ApiError("EXPORT_UNAVAILABLE", f"该报告没有 {format} 产物（可能缺少 PDF 渲染依赖）", 404)
        path = workspace.resolve(pid, relative)
        if not path.exists():
            raise ApiError("FILE_NOT_FOUND", "报告文件丢失", 404, str(path))
        kwargs: dict[str, Any] = {"media_type": service.FORMAT_MIME[format]}
        if download or format != "html":
            kwargs["filename"] = f"{row.name}.{format}"
        return FileResponse(str(path), **kwargs)


@router.post("/reports/{id}/regenerate")
def regenerate_report(id: str) -> Any:
    with report_ctx(id) as (pid, session, row):
        service.regenerate(session, pid, row)
        record(session, "report.regenerate", "report", id, project_id=pid)
        return as_dict(row)
