"""Fine-tune API: templates -> config -> one-click run -> adapter registered."""
from __future__ import annotations

from typing import Any

from fastapi import Body
from sqlalchemy import select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import DatasetVersion, Model, Run, Script, TrainingConfig
from ..services import finetune as service
from ..services import identity, training as training_service
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, get_or_404, make_router

router = make_router()


@router.get("/projects/{pid}/finetune-templates")
def list_templates(pid: str = ProjectId) -> Any:
    with project_session(pid) as session:
        return {"items": service.templates(session, pid),
                "methods": list(service.METHODS), "formats": list(service.FORMATS)}


@router.post("/projects/{pid}/finetune-templates")
def create_template(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    with project_session(pid) as session:
        row = service.create_template(session, pid, payload)
        record(session, "finetune_template.create", "finetune_template", row["id"],
               {"name": row["name"]}, pid, actor=identity.actor_name())
        return row


@router.post("/projects/{pid}/finetune-templates/instantiate")
def instantiate(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    """Produce a TrainingConfig from a template without starting a run."""
    with project_session(pid) as session:
        row = service.instantiate(session, pid, payload)
        record(session, "finetune.instantiate", "training_config", row["id"],
               {"template": row["finetune_json"].get("template_id")}, pid,
               actor=identity.actor_name())
        return row


@router.post("/projects/{pid}/dataset-versions/{vid}/check-format")
def check_format(pid: str = ProjectId, vid: str = "", fmt: str = "alpaca") -> Any:
    with project_session(pid) as session:
        return service.check_dataset(session, vid, fmt)


@router.post("/projects/{pid}/finetune-runs")
async def create_finetune_run(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    """One click: template + base model + dataset version -> config + Run + Job."""
    data = require(payload, "dataset_version_ids")
    version_ids = data["dataset_version_ids"]
    if not version_ids:
        raise ApiError("RUN_LINEAGE", "微调必须引用至少一个 DatasetVersion", 422)
    format_warnings: list[dict[str, Any]] = []
    with project_session(pid) as session:
        config_data = service.instantiate(session, pid, payload)
        fmt = str(config_data["finetune_json"].get("dataset_format") or "custom")
        for vid in version_ids:
            get_or_404(session, DatasetVersion, vid, "数据集版本")
            check = service.check_dataset(session, vid, fmt)
            if not check["ok"]:
                format_warnings.append({"dataset_version_id": vid, **check})
        config = session.get(TrainingConfig, config_data["id"])
        row = Run(
            id=uid(), project_id=pid,
            name=data.get("name") or f"{config.name} 微调",
            config_id=config.id, dataset_version_ids_json=version_ids,
            runner_type=data.get("runner_type") or config.runner_type or "local",
            status="queued", metrics_json={}, artifacts_json={},
        )
        session.add(row)
        session.commit()
        run_id, config_id = row.id, config.id
        record(session, "finetune.run.create", "run", run_id,
               {"template": config.finetune_json.get("template_id"),
                "base_model_id": config.finetune_json.get("base_model_id")}, pid,
               actor=identity.actor_name())
    workspace.ensure_workspace(pid)

    async def worker(ctx):
        return await training_service.run_worker(pid, run_id, ctx)

    job = jobs.submit(pid, "training.finetune", {"run_id": run_id, "config_id": config_id,
                                                 "dataset_version_ids": version_ids}, worker,
                      runner_type=row.runner_type)
    with project_session(pid) as session:
        row = session.get(Run, run_id)
        row.job_id = job["id"]
        session.commit()
    return {"run_id": run_id, "config_id": config_id, "job_id": job["id"],
            "status": "queued", "format_warnings": format_warnings}


@router.get("/projects/{pid}/finetune-runs")
def list_finetune_runs(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        config_ids = {c.id for c in session.execute(
            select(TrainingConfig).where(TrainingConfig.project_id == pid)).scalars().all()
            if c.finetune_json}
        query = select(Run).where(Run.project_id == pid).order_by(Run.created_at.desc())
        result = paginate(session, query, page, size)
        result["items"] = [item for item in result["items"] if item["config_id"] in config_ids]
        return result
