"""Eval suites / runs / A-B tests / metric dashboard."""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Body
from sqlalchemy import select

from ..audit import record
from ..database import project_session
from ..errors import ApiError
from ..jobs import jobs
from ..models import ABTest, EvalRun, EvalSuite, Model, Report
from ..plugin_loader import registry
from ..services import evaluation as service
from ..services import model_adapters, registry as registry_service
from ..services import reports as report_service
from ..util import as_dict, paginate, require, uid
from .common import ProjectId, entity_project, get_or_404, make_router

router = make_router()

SUITE_TYPES = ("ab", "boundary", "accuracy")


@router.get("/projects/{pid}/model-adapters")
def list_model_adapters(pid: str = ProjectId) -> Any:
    """Adapter catalog + plugin-provided adapters, consumed by the UI form."""
    with project_session(pid) as session:
        enabled = registry.enabled_ids(session)
    plugins = [{"id": plugin.id, "name": plugin.name, "extension": ext.get("label") or ext.get("point")}
               for plugin, ext, _ in registry.implementations("model_adapter", enabled)]
    return {"items": model_adapters.describe(), "plugins": plugins,
            "scorers": list(service.SCORER_TYPES)}


@router.post("/projects/{pid}/model-adapters/test")
async def test_model_adapter(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    """One-shot connectivity check for an adapter config."""
    ref = payload.get("model_ref_json")
    if not isinstance(ref, dict):
        raise ApiError("VALIDATION_ERROR", "model_ref_json 必须是对象", 422)
    case = {"id": "test", "input": payload.get("prompt") or "你好，请用一句话介绍自己。",
            "expected": "", "category": "general"}
    with project_session(pid) as session:
        prepared = model_adapters.prepare(ref, session)
    output = await asyncio.to_thread(model_adapters.generate, case, prepared, project_id=pid, index=0)
    return {"type": ref.get("type"), "prompt": case["input"], "output": output, "ok": True}


@contextmanager
def suite_ctx(ident: str) -> Iterator[tuple[str, Any, EvalSuite]]:
    pid = entity_project(EvalSuite, ident)
    with project_session(pid) as session:
        yield pid, session, get_or_404(session, EvalSuite, ident, "评测套件")


@router.get("/projects/{pid}/eval-suites")
def list_eval_suites(pid: str = ProjectId, page: int = 1, size: int = 50) -> Any:
    with project_session(pid) as session:
        query = select(EvalSuite).where(EvalSuite.project_id == pid).order_by(EvalSuite.created_at.desc())
        return paginate(session, query, page, size)


@router.post("/projects/{pid}/eval-suites")
def create_eval_suite(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "name")
    suite_type = data.get("type", "accuracy")
    if suite_type not in SUITE_TYPES:
        raise ApiError("VALIDATION_ERROR", f"评测套件类型仅支持 {SUITE_TYPES}", 422)
    with project_session(pid) as session:
        row = EvalSuite(id=uid(), project_id=pid, name=data["name"], type=suite_type,
                        description=data.get("description", ""),
                        cases_json=data.get("cases_json") or [], version=1)
        session.add(row)
        session.commit()
        return as_dict(row)


@router.get("/eval-suites/{id}")
def get_eval_suite(id: str) -> Any:
    with suite_ctx(id) as (_, session, row):
        data = as_dict(row)
        data["runs"] = [as_dict(r) for r in session.execute(
            select(EvalRun).where(EvalRun.suite_id == id).order_by(EvalRun.created_at.desc())).scalars().all()]
        return data


@router.put("/eval-suites/{id}")
def update_eval_suite(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    with suite_ctx(id) as (pid, session, row):
        if payload.get("cases_json") is not None and payload["cases_json"] != row.cases_json:
            row.version = (row.version or 1) + 1
        for key in ("name", "description", "cases_json", "type"):
            if key in payload:
                setattr(row, key, payload[key])
        session.commit()
        record(session, "eval_suite.update", "eval_suite", id, {"version": row.version}, pid)
        return as_dict(row)


def _model_ref(session, pid: str, model_id: Any, inline: Any, label: str) -> tuple[dict[str, Any], str | None]:
    """Resolve a registry id, or accept an inline adapter config (legacy)."""
    if model_id:
        ref, _ = registry_service.resolve(session, pid, str(model_id))
        return ref, str(model_id)
    if inline is None:
        raise ApiError("VALIDATION_ERROR", f"请提供 {label}_id（注册表）或内联适配器配置", 422)
    if not isinstance(inline, dict):
        raise ApiError("VALIDATION_ERROR", f"{label} 适配器必须是对象", 422)
    if inline.get("type") not in model_adapters.ADAPTER_TYPES:
        raise ApiError("UNSUPPORTED_MODEL_REF",
                       f"未知模型适配器 {inline.get('type')}，可用: {model_adapters.ADAPTER_TYPES}", 422)
    return inline, None


def _resolve_scorer(session, pid: str, scorer: dict[str, Any]) -> dict[str, Any]:
    """llm_judge may point at a registered judge model instead of an inline ref."""
    resolved = dict(scorer or {})
    if resolved.get("type") == "llm_judge" and resolved.get("judge_model_id"):
        ref, _ = registry_service.resolve(session, pid, str(resolved["judge_model_id"]))
        resolved["judge_model_ref"] = ref
    return resolved


@router.post("/eval-suites/{id}/runs")
async def create_eval_run(id: str, payload: dict[str, Any] = Body(default={})) -> Any:
    with suite_ctx(id) as (pid, session, suite):
        suite_id = suite.id
        inline = payload.get("model_ref_json")
        if inline is None and not payload.get("model_id"):
            inline = {"type": "echo"}  # backward-compatible default
        model_ref, model_id = _model_ref(session, pid, payload.get("model_id"), inline, "model")
        dataset_versions = payload.get("dataset_version_ids") or []
        scorer = _resolve_scorer(session, pid, payload.get("scorer_json") or {"type": "exact_match"})
        if scorer.get("type") not in service.SCORER_TYPES:
            raise ApiError("UNSUPPORTED_SCORER", f"未知评分器 {scorer.get('type')}", 422)
        row = EvalRun(
            id=uid(), project_id=pid, suite_id=suite_id,
            model_id=model_id, model_ref_json=model_ref,
            dataset_version_ids_json=dataset_versions,
            scorer_json=scorer,
            status="queued", metrics_json={}, results_json=[],
        )
        session.add(row)
        session.commit()
        run_id = row.id

    async def worker(ctx):
        result = await service.run_suite_worker(pid, run_id, ctx)
        with project_session(pid) as session:
            record(session, "eval.run", "eval_run", run_id, {"metrics": result["metrics"]}, pid)
        return result

    job = jobs.submit(pid, "evaluation.suite", {"eval_run_id": run_id, "suite_id": suite_id}, worker)
    with project_session(pid) as session:
        row = session.get(EvalRun, run_id)
        row.job_id = job["id"]
        session.commit()
    return {"eval_run_id": run_id, "job_id": job["id"], "status": "queued"}


@router.get("/eval-runs/{id}")
def get_eval_run(id: str) -> Any:
    pid = entity_project(EvalRun, id)
    with project_session(pid) as session:
        row = get_or_404(session, EvalRun, id, "评测任务")
        data = as_dict(row)
        data["report"] = as_dict(session.get(Report, row.report_id)) if row.report_id else None
        if row.model_id:
            model = session.get(Model, row.model_id)
            data["model"] = {"id": model.id, "name": model.name, "kind": model.kind} if model else None
        return data


@router.post("/projects/{pid}/ab-tests")
async def create_ab_test(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    """Two modes: legacy (pre-recorded scores) and generated (call both models)."""
    data = dict(payload)
    if not data.get("prompt_set_json"):
        raise ApiError("VALIDATION_ERROR", "A/B 测试需要 prompt_set_json", 422)
    generated = bool(data.get("generate"))
    with project_session(pid) as session:
        scorer = _resolve_scorer(session, pid, data.get("scorer_json") or {"type": "exact_match"})
        if scorer.get("type") not in service.SCORER_TYPES:
            raise ApiError("UNSUPPORTED_SCORER", f"未知评分器 {scorer.get('type')}", 422)
        if generated:
            ref_a, id_a = _model_ref(session, pid, data.get("model_a_id"), data.get("model_a_ref"), "model_a")
            ref_b, id_b = _model_ref(session, pid, data.get("model_b_id"), data.get("model_b_ref"), "model_b")
            data["model_a_ref"], data["model_b_ref"] = ref_a, ref_b
            row = ABTest(
                id=uid(), project_id=pid, name=data.get("name") or "A/B 测试（自动生成）",
                model_a_id=id_a, model_b_id=id_b,
                model_a_ref=json.dumps(ref_a, ensure_ascii=False),
                model_b_ref=json.dumps(ref_b, ensure_ascii=False),
                prompt_set_json=data["prompt_set_json"], scorer_json=scorer,
                generated=1, status="queued",
            )
            session.add(row)
            session.commit()
            ab_id = row.id

            async def worker(ctx):
                result = await service.ab_worker(pid, ab_id, ctx)
                with project_session(pid) as inner:
                    record(inner, "ab.run", "ab_test", ab_id, {"result": result["result"]}, pid)
                return result

            job = jobs.submit(pid, "evaluation.ab", {"ab_test_id": ab_id}, worker)
            row = session.get(ABTest, ab_id)
            row.job_id = job["id"]
            session.commit()
            return {"ab_test_id": ab_id, "job_id": job["id"], "status": "queued", "generated": True}

        # Legacy mode: refs are plain labels (or pre-recorded inline results).
        ref_a, ref_b = data.get("model_a_ref") or "", data.get("model_b_ref") or ""
        id_a, id_b = data.get("model_a_id"), data.get("model_b_id")
        for side, model_id in (("a", id_a), ("b", id_b)):
            if model_id and not (ref_a if side == "a" else ref_b):
                model = session.get(Model, str(model_id))
                if side == "a":
                    ref_a = model.name if model else str(model_id)
                else:
                    ref_b = model.name if model else str(model_id)
        if not ref_a or not ref_b:
            raise ApiError("VALIDATION_ERROR", "A/B 测试需要 model_a_ref / model_b_ref 或注册表 ID", 422)
        data["model_a_ref"], data["model_b_ref"] = ref_a, ref_b
        row = ABTest(
            id=uid(), project_id=pid, name=data.get("name") or "A/B 测试",
            model_a_id=id_a, model_b_id=id_b,
            model_a_ref=json.dumps(ref_a, ensure_ascii=False) if isinstance(ref_a, dict) else str(ref_a),
            model_b_ref=json.dumps(ref_b, ensure_ascii=False) if isinstance(ref_b, dict) else str(ref_b),
            prompt_set_json=data["prompt_set_json"], status="running",
        )
        session.add(row)
        session.commit()
        ab_id = row.id
        result = service.compute_ab(session, pid, data, ab_id)
        report = report_service.create_report(session, pid, {
            "name": f"{row.name} 报告", "type": "ab",
            "linked_entities_json": [{"type": "ab_test", "id": ab_id}],
            "summary_json": {"metrics": {k: v for k, v in result.items() if isinstance(v, (int, float))},
                             "model_a": ref_a, "model_b": ref_b},
            "sections": [{"title": "逐提示结果", "table": data["prompt_set_json"][:100]}],
        })
        row = session.get(ABTest, ab_id)
        row.report_id = report.id
        session.commit()
        return {**as_dict(row), "report_id": report.id}


@router.get("/ab-tests/{id}")
def get_ab_test(id: str) -> Any:
    pid = entity_project(ABTest, id)
    with project_session(pid) as session:
        row = get_or_404(session, ABTest, id, "A/B 测试")
        data = as_dict(row)
        data["model_a"] = service.parse_model_ref(row.model_a_ref)
        data["model_b"] = service.parse_model_ref(row.model_b_ref)
        for side, model_id in (("model_a", row.model_a_id), ("model_b", row.model_b_id)):
            if model_id:
                model = session.get(Model, model_id)
                data[f"{side}_registry"] = {"id": model.id, "name": model.name} if model else None
        data["report"] = as_dict(session.get(Report, row.report_id)) if row.report_id else None
        return data


@router.get("/projects/{pid}/metrics")
def metric_dashboard(pid: str = ProjectId) -> Any:
    from ..services import training as training_service

    with project_session(pid) as session:
        runs = training_service.metrics_dashboard(session, pid)
        evals = session.execute(select(EvalRun).where(EvalRun.project_id == pid)).scalars().all()
        abs_ = session.execute(select(ABTest).where(ABTest.project_id == pid)).scalars().all()
        return {
            "training": runs,
            "evaluation": [{"id": e.id, "status": e.status, "metrics": e.metrics_json} for e in evals],
            "ab": [{"id": a.id, "result": a.result_json} for a in abs_],
            "latest_accuracy": next((e.metrics_json.get("accuracy") for e in reversed(evals) if e.metrics_json), None),
        }
