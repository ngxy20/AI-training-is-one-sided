"""Router helpers: project validation, automatic audit, pagination, 404s."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Request
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record
from ..database import project_session, registry_session
from ..errors import ApiError, not_found
from ..models import Project
from ..util import as_dict, paginate, require

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _entity_type(path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    for candidate in reversed(parts):
        if candidate not in ("api", "v1", "projects") and not candidate.startswith("v1"):
            return candidate.rstrip("s") if candidate.endswith("s") else candidate
    return "asset"


class AuditedRoute(APIRoute):
    """Every successful mutation is written to the project audit log."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            from ..services import identity

            pid = request.path_params.get("pid") or request.path_params.get("project_id")
            identity.enforce(pid, request.method, request.url.path)
            response = await original(request)
            if pid and request.method in MUTATING and 200 <= response.status_code < 400:
                try:
                    with project_session(pid) as session:
                        record(
                            session,
                            action=f"{request.method} {request.url.path}",
                            entity_type=_entity_type(request.url.path),
                            entity_id=request.path_params.get("id"),
                            detail={"method": request.method, "path": request.url.path},
                            project_id=pid,
                            actor=identity.actor_name(),
                        )
                except Exception:
                    pass  # auditing must never break the request
            return response

        return handler


def make_router(prefix: str = "") -> APIRouter:
    return APIRouter(prefix=prefix, route_class=AuditedRoute)


def ensure_project(pid: str) -> Project:
    with registry_session() as session:
        project = session.get(Project, pid)
        if project is None:
            raise not_found("项目", pid)
        return project


def project_dep(pid: str = Path(...)) -> str:
    ensure_project(pid)
    return pid


ProjectId = Depends(project_dep)


def entity_project(model: Any, ident: str) -> str:
    """Locate which project owns a resource addressed without a pid in the URL."""
    with registry_session() as registry:
        projects = [p.id for p in registry.execute(select(Project)).scalars().all()]
    for pid in projects:
        with project_session(pid) as session:
            if session.get(model, ident) is not None:
                return pid
    raise not_found(model.__name__, ident)


def get_or_404(session: Session, model: Any, ident: str, label: str | None = None):
    row = session.get(model, ident)
    if row is None:
        raise not_found(label or model.__name__, ident)
    return row


def list_rows(session: Session, model: Any, pid: str, page: int = 1, size: int = 50) -> dict[str, Any]:
    query = select(model).where(model.project_id == pid).order_by(model.created_at.desc())
    return paginate(session, query, page, size)


def ok(data: Any, **extra: Any) -> dict[str, Any]:
    return {"data": data, **extra}
