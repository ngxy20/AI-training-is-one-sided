"""Dataset / immutable version / record preview / training-format export."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body, Query
from sqlalchemy import select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..models import Dataset, DatasetVersion, Record
from ..services import datasets as service
from ..util import as_dict, paginate, require, uid, write_json
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@contextmanager
def dataset_ctx(ident: str) -> Iterator[tuple[str, Any, Dataset]]:
    pid = entity_project(Dataset, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, Dataset, ident, "数据集")


@contextmanager
def version_ctx(ident: str) -> Iterator[tuple[str, Any, DatasetVersion]]:
    pid = entity_project(DatasetVersion, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, DatasetVersion, ident, "数据集版本")


@router.get("/projects/{pid}/datasets")
def list_datasets(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(Dataset).where(Dataset.project_id == pid).order_by(Dataset.created_at.desc())
        return paginate(session, query, page, size)


@router.get("/projects/{pid}/dataset-versions")
def list_all_versions(pid: str = ProjectId, page: int = 1, size: int = 200) -> Any:
    """Flat version list used by selectors across the UI."""
    with project_session(pid) as session:
        query = select(DatasetVersion).order_by(DatasetVersion.created_at.desc())
        result = paginate(session, query, page, size)
        for item in result["items"]:
            dataset = session.get(Dataset, item["dataset_id"])
            item["name"] = f"{dataset.name if dataset else item['dataset_id'][:8]} · v{item['version']}"
        return result


@router.post("/projects/{pid}/datasets")
def create_dataset(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    with project_session(pid) as session:
        row = Dataset(id=uid(), project_id=pid, name=data["name"],
                      description=data.get("description", ""),
                      schema_json=data.get("schema_json") or {},
                      source_type=data.get("source_type", "manual"))
        session.add(row)
        session.commit()
        return as_dict(row)


@router.get("/datasets/{id}")
def get_dataset(id: str) -> Any:
    with dataset_ctx(id) as (_, session, row):
        data = as_dict(row)
        data["versions"] = [as_dict(v) for v in session.execute(
            select(DatasetVersion).where(DatasetVersion.dataset_id == id).order_by(DatasetVersion.version)
        ).scalars().all()]
        return data


@router.post("/datasets/{id}/versions")
def create_dataset_version(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    """Import from a workspace/external file, or from inline ``records``."""
    with dataset_ctx(id) as (pid, session, dataset):
        if isinstance(payload.get("records"), list):
            rows = payload["records"]
            source = "inline"
        elif payload.get("path"):
            path = workspace.resolve(pid, payload["path"]) if payload.get("workspace_relative", True) else payload["path"]
            from pathlib import Path
            rows = service.read_records(Path(path), payload.get("fmt"))
            source = f"file:{Path(path).name}"
        else:
            raise ApiError("VALIDATION_ERROR", "需要 records 或 path", 422)
        rows = service.apply_field_mapping(rows, payload.get("field_mapping"))
        version = service.create_version(
            session, pid, dataset, rows,
            changelog=payload.get("changelog", ""),
            created_by_job_id=payload.get("job_id"), source=source,
        )
        record(session, "dataset.version.create", "dataset_version", version.id,
               {"record_count": version.record_count, "version": version.version}, pid)
        return as_dict(version)


@router.get("/datasets/{id}/versions")
def list_dataset_versions(id: str) -> Any:
    with dataset_ctx(id) as (_, session, _):
        rows = session.execute(
            select(DatasetVersion).where(DatasetVersion.dataset_id == id).order_by(DatasetVersion.version)
        ).scalars().all()
        return [as_dict(v) for v in rows]


@router.get("/dataset-versions/{id}")
def get_dataset_version(id: str) -> Any:
    with version_ctx(id) as (_, _, row):
        return as_dict(row)


@router.get("/dataset-versions/{id}/manifest")
def get_manifest(id: str) -> Any:
    with version_ctx(id) as (pid, _, row):
        from ..util import read_json
        return read_json(workspace.resolve(pid, row.manifest_path), {})


@router.get("/dataset-versions/{id}/records")
def list_records(
    id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    split: str | None = None,
    search: str | None = None,
) -> Any:
    with version_ctx(id) as (_, session, _):
        return service.query_records(session, id, page, size, split, search)


@router.post("/dataset-versions/{id}/export")
def export_dataset_version(id: str, payload: dict[str, Any] = Body(default={})) -> Any:
    with version_ctx(id) as (pid, session, _):
        result = service.export_version(
            session, pid, id, payload.get("format", "jsonl"),
            payload.get("mapping"), payload.get("template", ""), payload.get("split"),
        )
        record(session, "dataset.export", "dataset_version", id,
               {"format": result["format"], "count": result["record_count"]}, pid)
        return result
