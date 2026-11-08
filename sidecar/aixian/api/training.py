"""Training configs (JSON Schema <-> YAML), runs, checkpoints, model registry."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import yaml
from fastapi import Body
from sqlalchemy import select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import Checkpoint, DatasetVersion, Run, Script, TrainingConfig
from ..services import training as service
from ..services.common import infer_params_schema
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@contextmanager
def run_ctx(ident: str) -> Iterator[tuple[str, Any, Run]]:
    pid = entity_project(Run, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, Run, ident, "训练任务")


def _config_public(row: TrainingConfig) -> dict[str, Any]:
    data = as_dict(row)
    data["params_yaml"] = yaml.safe_dump(row.params_json or {}, allow_unicode=True, sort_keys=False)
    return data


@router.get("/projects/{pid}/configs")
def list_configs(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(TrainingConfig).where(TrainingConfig.project_id == pid).order_by(TrainingConfig.created_at.desc())
        return paginate(session, query, page, size, _config_public)


@router.post("/projects/{pid}/configs")
def create_config(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name", "script_id")
    with project_session(pid) as session:
        get_or_404(session, Script, data["script_id"], "脚本")
        params = data.get("params") or {}
        if data.get("params_yaml"):
            params = yaml.safe_load(data["params_yaml"]) or {}
        row = TrainingConfig(
            id=uid(), project_id=pid, name=data["name"], script_id=data["script_id"],
            params_json=params,
            params_schema_json=data.get("params_schema_json") or infer_params_schema(params),
            env_json=data.get("env_json") or {}, runner_type=data.get("runner_type", "local"),
        )
        session.add(row)
        session.commit()
        return _config_public(row)


@router.get("/configs/{id}")
def get_config(id: str) -> Any:
    pid = entity_project(TrainingConfig, id)
    with project_session(pid) as session:
        return _config_public(get_or_404(session, TrainingConfig, id, "训练配置"))


@router.get("/configs/{id}/schema")
def config_schema(id: str) -> Any:
    pid = entity_project(TrainingConfig, id)
    with project_session(pid) as session:
        row = get_or_404(session, TrainingConfig, id, "训练配置")
        return row.params_schema_json or infer_params_schema(row.params_json or {})


@router.put("/configs/{id}")
def update_config(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    pid = entity_project(TrainingConfig, id)
    with project_session(pid) as session:
        row = get_or_404(session, TrainingConfig, id, "训练配置")
        if "params_yaml" in payload:
            row.params_json = yaml.safe_load(payload["params_yaml"]) or {}
        if "params" in payload:
            row.params_json = payload["params"]
        for key in ("name", "params_schema_json", "env_json", "runner_type"):
            if key in payload:
                setattr(row, key, payload[key])
        row.version = (row.version or 1) + 1
        session.commit()
        record(session, "config.update", "training_config", id, {"version": row.version}, pid)
        return _config_public(row)


@router.get("/projects/{pid}/runs")
def list_runs(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(Run).where(Run.project_id == pid).order_by(Run.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/runs")
async def create_run(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "config_id")
    version_ids = data.get("dataset_version_ids") or []
    if not version_ids:
        raise ApiError("RUN_LINEAGE", "Run 必须引用至少一个 DatasetVersion", 422)
    format_warnings: list[dict[str, Any]] = []
    with project_session(pid) as session:
        config = get_or_404(session, TrainingConfig, data["config_id"], "训练配置")
        for vid in version_ids:
            get_or_404(session, DatasetVersion, vid, "数据集版本")
        if config.finetune_json:
            from ..services import finetune as finetune_service
            fmt = str(config.finetune_json.get("dataset_format") or "custom")
            for vid in version_ids:
                check = finetune_service.check_dataset(session, vid, fmt)
                if not check["ok"]:
                    format_warnings.append({"dataset_version_id": vid, **check})
        row = Run(
            id=uid(), project_id=pid, name=data.get("name") or f"{config.name} 实验",
            config_id=config.id, dataset_version_ids_json=version_ids,
            runner_type=data.get("runner_type") or config.runner_type or "local",
            status="queued", metrics_json={}, artifacts_json={},
        )
        session.add(row)
        session.commit()
        run_id = row.id
    workspace.ensure_workspace(pid)

    async def worker(ctx):
        return await service.run_worker(pid, run_id, ctx)

    job = jobs.submit(pid, "training.run", {"run_id": run_id, "config_id": config.id,
                                            "dataset_version_ids": version_ids}, worker,
                      runner_type=row.runner_type)
    with project_session(pid) as session:
        row = session.get(Run, run_id)
        row.job_id = job["id"]
        session.commit()
    return {"run_id": run_id, "job_id": job["id"], "status": "queued",
            "runner_type": row.runner_type, "format_warnings": format_warnings}


@router.get("/runs/{id}")
def get_run(id: str) -> Any:
    with run_ctx(id) as (_, session, row):
        data = as_dict(row)
        config = session.get(TrainingConfig, row.config_id)
        data["config"] = _config_public(config) if config else None
        data["checkpoints"] = [as_dict(c) for c in session.execute(
            select(Checkpoint).where(Checkpoint.run_id == id)).scalars().all()]
        return data


@router.post("/runs/{id}/cancel")
def cancel_run(id: str) -> Any:
    with run_ctx(id) as (pid, session, row):
        if row.job_id:
            jobs.cancel(row.job_id)
        row.status = "cancelled"
        session.commit()
        record(session, "run.cancel", "run", id, project_id=pid)
        return {"run_id": id, "status": "cancelled"}


@router.get("/runs/{id}/metrics")
def run_metrics(id: str) -> Any:
    with run_ctx(id) as (_, _, row):
        return {"run_id": id, "metrics": row.metrics_json or {}, "status": row.status}


@router.get("/runs/{id}/artifacts")
def run_artifacts(id: str) -> Any:
    with run_ctx(id) as (_, _, row):
        return {"run_id": id, "artifacts": row.artifacts_json or {}}


@router.post("/runs/{id}/register-model")
def register_model(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    with run_ctx(id) as (pid, session, run):
        checkpoint = service.register_model(session, pid, id, payload.get("checkpoint_id"), data["name"])
        record(session, "model.register", "checkpoint", checkpoint.id, {"name": data["name"]}, pid)
        # Also publish the checkpoint into the model registry so it can be
        # referenced by eval / A-B / judge without re-typing its path.
        from .. import workspace
        from ..services import registry as model_registry
        path = workspace.resolve(pid, checkpoint.path)
        registered = model_registry.register_checkpoint(
            session, pid, run, str(path), data["name"],
            params={"step": checkpoint.step, "metrics": checkpoint.metrics_json or {}})
        record(session, "model.registry.create", "model", registered["id"],
               {"name": data["name"], "from_checkpoint": checkpoint.id}, pid)
        return {**as_dict(checkpoint), "registry_model": registered}


@router.get("/projects/{pid}/checkpoints")
def list_checkpoints(pid: str = ProjectId) -> Any:
    with project_session(pid) as session:
        runs = session.execute(select(Run).where(Run.project_id == pid)).scalars().all()
        run_ids = {r.id for r in runs}
        return [as_dict(c) for c in session.execute(select(Checkpoint)).scalars().all() if c.run_id in run_ids]


@router.get("/projects/{pid}/metrics-dashboard")
def dashboard(pid: str = ProjectId) -> Any:
    with project_session(pid) as session:
        return service.metrics_dashboard(session, pid)
