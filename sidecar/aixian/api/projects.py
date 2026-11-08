"""Project lifecycle, workspace isolation, resource tree, lineage, settings."""
from __future__ import annotations

from typing import Any

from fastapi import Body, Query
from sqlalchemy import func, select

from .. import config, workspace
from ..audit import record
from ..database import init_project_db, project_session, registry_session
from ..errors import ApiError
from ..models import (
    ABTest, AnnotationSchema, AnnotationTask, CleaningPipeline, DataSource, Dataset,
    DatasetVersion, EvalRun, EvalSuite, Job, Model, Project, Report, Run, Script,
    TrainingConfig,
)
from ..util import as_dict, require, uid, write_json
from .common import ProjectId, get_or_404, make_router

router = make_router("/projects")

TREE_MODELS = [
    ("datasource", "数据源", DataSource),
    ("dataset", "数据集", Dataset),
    ("pipeline", "清洗 Pipeline", CleaningPipeline),
    ("annotation", "标注任务", AnnotationTask),
    ("annotation_schema", "标注模板", AnnotationSchema),
    ("script", "脚本", Script),
    ("config", "训练配置", TrainingConfig),
    ("model", "模型", Model),
    ("run", "实验", Run),
    ("eval_suite", "评测套件", EvalSuite),
    ("eval_run", "评测任务", EvalRun),
    ("ab_test", "A/B 测试", ABTest),
    ("report", "报告", Report),
]


def _project_detail(project: Project) -> dict[str, Any]:
    data = as_dict(project)
    with project_session(project.id) as session:
        data["counts"] = {
            "datasets": session.scalar(select(func.count()).select_from(Dataset)) or 0,
            "dataset_versions": session.scalar(select(func.count()).select_from(DatasetVersion)) or 0,
            "runs": session.scalar(select(func.count()).select_from(Run)) or 0,
            "reports": session.scalar(select(func.count()).select_from(Report)) or 0,
            "jobs": session.scalar(select(func.count()).select_from(Job)) or 0,
        }
    return data


@router.get("")
def list_projects(status: str | None = None) -> Any:
    with registry_session() as session:
        query = select(Project).order_by(Project.created_at.desc())
        if status:
            query = query.where(Project.status == status)
        return [as_dict(p) for p in session.execute(query).scalars().all()]


@router.post("")
def create_project(payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    project_id = uid()
    root = workspace.ensure_workspace(project_id)
    init_project_db(project_id)
    project = Project(
        id=project_id, name=data["name"], description=data.get("description", ""),
        workspace_path=str(root), status="active", settings_json=data.get("settings_json") or {},
    )
    with registry_session() as session:
        session.add(project)
        session.commit()
    write_json(root / "project.json", {"id": project_id, "name": data["name"], "schema_version": "0.1"})
    with project_session(project_id) as session:
        record(session, action="project.create", entity_type="project", entity_id=project_id,
               detail={"name": data["name"]}, project_id=project_id)
    config.save_settings({"active_project_id": project_id})
    return _project_detail(project)


@router.get("/{pid}")
def get_project(pid: str) -> Any:
    with registry_session() as session:
        project = get_or_404(session, Project, pid, "项目")
        return _project_detail(project)


@router.patch("/{pid}")
def update_project(pid: str, payload: dict[str, Any] = Body(...)) -> Any:
    with registry_session() as session:
        project = get_or_404(session, Project, pid, "项目")
        for key in ("name", "description", "status", "settings_json"):
            if key in payload:
                setattr(project, key, payload[key])
        session.commit()
        return _project_detail(project)


@router.delete("/{pid}")
def archive_project(pid: str) -> Any:
    with registry_session() as session:
        project = get_or_404(session, Project, pid, "项目")
        project.status = "archived"
        session.commit()
        return {"id": pid, "status": "archived", "workspace_preserved": True}


@router.post("/{pid}/open")
def open_project(pid: str) -> Any:
    with registry_session() as session:
        project = get_or_404(session, Project, pid, "项目")
    config.save_settings({"active_project_id": pid})
    return _project_detail(project)


@router.get("/{pid}/tree")
def resource_tree(pid: str = ProjectId) -> Any:
    groups = []
    with project_session(pid) as session:
        for kind, label, model in TREE_MODELS:
            rows = session.execute(select(model).order_by(model.created_at.desc()).limit(500)).scalars().all()
            items = []
            for row in rows:
                items.append({
                    "id": row.id,
                    "name": getattr(row, "name", None) or f"v{getattr(row, 'version', '')}" or row.id[:8],
                    "uri": workspace.uri(pid, kind, row.id),
                    "kind": kind,
                    "status": getattr(row, "status", None),
                    "version": getattr(row, "version", None),
                    "updated_at": row.updated_at.isoformat(timespec="seconds"),
                })
            groups.append({"key": kind, "label": label, "count": len(items), "items": items})
    return {"project_id": pid, "groups": groups}


@router.get("/{pid}/lineage")
def lineage(pid: str = ProjectId) -> Any:
    """Asset reference graph: dataset versions -> runs -> checkpoints -> eval -> report."""
    from ..models import Checkpoint

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    with project_session(pid) as session:
        for version in session.execute(select(DatasetVersion)).scalars().all():
            nodes.append({"id": version.id, "type": "dataset_version", "label": f"v{version.version}"})
            if version.parent_version_id:
                edges.append({"source": version.parent_version_id, "target": version.id, "label": "派生"})
        for run in session.execute(select(Run)).scalars().all():
            nodes.append({"id": run.id, "type": "run", "label": run.name or run.id[:8]})
            for vid in run.dataset_version_ids_json or []:
                edges.append({"source": vid, "target": run.id, "label": "训练数据"})
            if run.config_id:
                edges.append({"source": run.config_id, "target": run.id, "label": "配置"})
        for cp in session.execute(select(Checkpoint)).scalars().all():
            nodes.append({"id": cp.id, "type": "checkpoint", "label": f"step {cp.step}"})
            edges.append({"source": cp.run_id, "target": cp.id, "label": "产物"})
        for model in session.execute(select(Model)).scalars().all():
            nodes.append({"id": model.id, "type": "model", "label": model.name})
            if model.base_model_id:
                edges.append({"source": model.base_model_id, "target": model.id, "label": "微调自"})
            if model.source_run_id:
                edges.append({"source": model.source_run_id, "target": model.id, "label": "训练产出"})
            if model.source_checkpoint_id:
                edges.append({"source": model.source_checkpoint_id, "target": model.id, "label": "checkpoint"})
        for ev in session.execute(select(EvalRun)).scalars().all():
            nodes.append({"id": ev.id, "type": "eval_run", "label": ev.id[:8]})
            for vid in ev.dataset_version_ids_json or []:
                edges.append({"source": vid, "target": ev.id, "label": "评测集"})
            if ev.model_id:
                edges.append({"source": ev.model_id, "target": ev.id, "label": "评测模型"})
        for ab in session.execute(select(ABTest)).scalars().all():
            for mid in (ab.model_a_id, ab.model_b_id):
                if mid:
                    edges.append({"source": mid, "target": ab.id, "label": "A/B 模型"})
        for report in session.execute(select(Report)).scalars().all():
            nodes.append({"id": report.id, "type": "report", "label": report.name})
            for linked in report.linked_entities_json or []:
                edges.append({"source": linked["id"], "target": report.id, "label": "报告引用"})
    return {"nodes": nodes, "edges": edges}


@router.get("/{pid}/settings")
def project_settings(pid: str = ProjectId) -> Any:
    with registry_session() as session:
        return as_dict(get_or_404(session, Project, pid, "项目"))["settings_json"]


@router.patch("/{pid}/settings")
def update_project_settings(pid: str, payload: dict[str, Any] = Body(...)) -> Any:
    with registry_session() as session:
        project = get_or_404(session, Project, pid, "项目")
        project.settings_json = {**(project.settings_json or {}), **payload}
        session.commit()
        return project.settings_json


@router.get("/{pid}/stats")
def project_stats(pid: str = ProjectId) -> Any:
    counts = {}
    with project_session(pid) as session:
        for kind, _, model in TREE_MODELS:
            counts[kind] = session.scalar(select(func.count()).select_from(model)) or 0
    return {"project_id": pid, "counts": counts}


@router.get("/{pid}/search")
def global_search(pid: str = ProjectId, q: str = Query("", min_length=0)) -> Any:
    term = f"%{q}%"
    results = []
    with project_session(pid) as session:
        for kind, _, model in TREE_MODELS:
            if not hasattr(model, "name"):
                continue
            rows = session.execute(select(model).where(model.name.like(term)).limit(20)).scalars().all()
            for row in rows:
                results.append({"kind": kind, "id": row.id, "name": row.name,
                                "uri": workspace.uri(pid, kind, row.id)})
    return {"query": q, "items": results}
