"""Cleaning pipeline CRUD, operator catalogue and re-runnable jobs."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body
from sqlalchemy import select

from .. import workspace
from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import CleaningPipeline, Dataset, PipelineRun
from ..plugin_loader import registry
from ..services import cleaning, datasets
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()


@contextmanager
def pipeline_ctx(ident: str) -> Iterator[tuple[str, Any, CleaningPipeline]]:
    pid = entity_project(CleaningPipeline, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, CleaningPipeline, ident, "清洗 Pipeline")


@router.get("/projects/{pid}/pipelines")
def list_pipelines(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(CleaningPipeline).where(CleaningPipeline.project_id == pid).order_by(CleaningPipeline.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/pipelines")
def create_pipeline(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    with project_session(pid) as session:
        row = CleaningPipeline(id=uid(), project_id=pid, name=data["name"],
                               description=data.get("description", ""),
                               nodes_json=data.get("nodes_json") or [], version=1)
        session.add(row)
        session.commit()
        return as_dict(row)


@router.get("/projects/{pid}/cleaning-operators")
def operator_catalog(pid: str = ProjectId) -> Any:
    with project_session(pid) as session:
        return {"items": cleaning.list_operators(registry.enabled_ids(session))}


@router.get("/pipelines/{id}")
def get_pipeline(id: str) -> Any:
    with pipeline_ctx(id) as (pid, session, row):
        data = as_dict(row)
        data["operators"] = cleaning.list_operators(registry.enabled_ids(session))
        return data


@router.put("/pipelines/{id}")
def update_pipeline(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    with pipeline_ctx(id) as (pid, session, row):
        if payload.get("nodes_json") is not None and payload["nodes_json"] != row.nodes_json:
            snapshot = workspace.new_asset_path(pid, "tmp", f"pipeline_{row.id}_v{row.version}.json")
            from ..util import write_json
            write_json(snapshot, {"version": row.version, "nodes_json": row.nodes_json})
            row.version = (row.version or 1) + 1
        for key in ("name", "description", "nodes_json"):
            if key in payload:
                setattr(row, key, payload[key])
        session.commit()
        record(session, "pipeline.update", "pipeline", id, {"version": row.version}, pid)
        return as_dict(row)


@router.post("/pipelines/{id}/run")
async def run_pipeline(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "source_version_id")
    with pipeline_ctx(id) as (pid, session, row):
        pipeline_id = row.id
        pipeline_name = row.name
        enabled = registry.enabled_ids(session)
        nodes = list(row.nodes_json or [])
        source_version_id = data["source_version_id"]
        dataset_id = data.get("dataset_id")
    workspace.ensure_workspace(pid)

    async def worker(ctx):
        with project_session(pid) as session:
            version = datasets.get_version(session, source_version_id)
            records = datasets.all_records(session, source_version_id)
            dataset = session.get(Dataset, dataset_id) if dataset_id else session.get(Dataset, version.dataset_id)
            if dataset is None:
                raise ApiError("NOT_FOUND", "目标数据集不存在", 404, dataset_id)
            pipeline_run = PipelineRun(
                pipeline_id=pipeline_id, source_version_id=source_version_id,
                job_id=ctx.job_id, status="running",
            )
            session.add(pipeline_run)
            session.commit()
            run_id = pipeline_run.id
        ctx.log(f"[aixian] 清洗 Pipeline {pipeline_name}: 输入 {len(records)} 条，节点 {len(nodes)} 个")
        cleaned, stats = await asyncio.to_thread(cleaning.apply_pipeline, records, nodes, enabled, ctx.log)
        with project_session(pid) as session:
            dataset = session.get(Dataset, dataset.id)
            new_version = datasets.create_version(
                session, pid, dataset, cleaned,
                changelog=f"清洗 Pipeline {pipeline_name} 复跑：{len(records)} -> {len(cleaned)}",
                created_by_job_id=ctx.job_id, source="cleaning_pipeline",
            )
            pipeline_run = session.get(PipelineRun, run_id)
            pipeline_run.output_version_id = new_version.id
            pipeline_run.status = "succeeded"
            pipeline_run.stats_json = {"nodes": stats, "input": len(records), "output": len(cleaned)}
            session.commit()
            result = {"pipeline_run_id": run_id, "output_version_id": new_version.id,
                      "input": len(records), "output": len(cleaned), "stats": stats}
        ctx.write_result("pipeline", result)
        return result

    job = jobs.submit(pid, "cleaning.pipeline", {"pipeline_id": pipeline_id, **data}, worker)
    return {"job_id": job["id"], "status": "queued", "pipeline_id": pipeline_id}


@router.get("/pipelines/{id}/runs")
def list_pipeline_runs(id: str) -> Any:
    with pipeline_ctx(id) as (_, session, _):
        rows = session.execute(select(PipelineRun).where(PipelineRun.pipeline_id == id)
                               .order_by(PipelineRun.created_at.desc())).scalars().all()
        return [as_dict(r) for r in rows]
