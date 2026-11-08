"""A/B, boundary and accuracy evaluation with pluggable scorers."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from sqlalchemy import select

from ..database import project_session
from ..errors import ApiError
from ..models import ABTest, EvalRun, EvalSuite, Record, Report
from ..plugin_loader import registry
from ..plugin_sdk import EvalCase
from ..util import as_dict, now, uid
from . import model_adapters, reports as report_service
from .common import two_proportion_z

SCORER_TYPES = ("exact_match", "contains", "regex", "judge", "llm_judge", "plugin")


def model_output(case: dict[str, Any], model_ref: dict[str, Any], session, index: int,
                 project_id: str | None = None, log=None) -> str:
    """Backward-compatible single-case wrapper around the adapter layer."""
    try:
        return model_adapters.generate(case, model_ref, session=session,
                                       project_id=project_id, index=index, log=log)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        return f"[模型调用失败: {exc}]"


def score_case(case: dict[str, Any], output: str, scorer: dict[str, Any],
               enabled_ids: set[str] | None = None, *, session=None,
               project_id: str | None = None, log=None) -> dict[str, Any]:
    kind = scorer.get("type", "exact_match")
    expected = str(case.get("expected", ""))
    passed: bool | None = None
    value = 0.0
    if kind == "exact_match":
        value = 1.0 if output.strip() == expected.strip() else 0.0
        passed = value > 0
    elif kind == "contains":
        value = 1.0 if expected and expected in output else 0.0
        passed = value > 0
    elif kind == "regex":
        value = 1.0 if re.search(scorer.get("pattern", ""), output or "", re.IGNORECASE) else 0.0
        passed = value > 0
    elif kind == "judge":
        value = float(case.get("judge_score", 0.0))
        passed = value >= float(scorer.get("threshold", 0.7))
    elif kind == "llm_judge":
        value = model_adapters.judge_score(case, output, scorer, session=session,
                                           project_id=project_id, log=log)
        passed = value >= float(scorer.get("threshold", 0.7))
    elif kind == "plugin":
        plugin_id = scorer.get("plugin_id", "")
        matches = [impl for _, _, impl in registry.implementations("eval_metric", enabled_ids)
                   if plugin_id in ("", getattr(impl, "__aixian_plugin__", ""))]
        impl = matches[0] if matches else next(
            (i for _, _, i in registry.implementations("eval_metric", enabled_ids)), None)
        if impl is None:
            raise ApiError("PLUGIN_NOT_FOUND", "没有可用的评测指标插件", 404)
        result = impl.score(EvalCase(
            id=str(case.get("id", "")), input=str(case.get("input", "")),
            expected=case.get("expected"), category=str(case.get("category", "general")),
            metadata=case.get("metadata") or {},
        ), output)
        value = float(result.value)
        passed = result.passed
    else:
        raise ApiError("UNSUPPORTED_SCORER", f"未知评分器: {kind}", 422)
    return {"name": kind, "value": round(value, 6), "passed": passed, "detail": {"expected": expected}}


def suite_metrics(results: list[dict[str, Any]], started: float) -> dict[str, Any]:
    total = len(results) or 1
    scores = [r["score"]["value"] for r in results]
    passed = [r["score"]["passed"] for r in results if r["score"]["passed"] is not None]
    by_category: dict[str, list[float]] = {}
    for result in results:
        by_category.setdefault(result.get("category", "general"), []).append(result["score"]["value"])
    return {
        "case_count": len(results),
        "accuracy": round(sum(scores) / total, 4),
        "pass_rate": round(sum(1 for p in passed if p) / (len(passed) or 1), 4),
        "win_rate": round(sum(scores) / total, 4),
        "consistency": round(min(scores), 4) if scores else 0.0,
        "latency_ms": round((time.perf_counter() - started) * 1000 / total, 3),
        "cost": 0.0,
        "by_category": {k: round(sum(v) / len(v), 4) for k, v in by_category.items()},
    }


async def run_suite_worker(project_id: str, eval_run_id: str, ctx) -> dict[str, Any]:
    started = time.perf_counter()
    with project_session(project_id) as session:
        run = session.get(EvalRun, eval_run_id)
        if run is None:
            raise ApiError("NOT_FOUND", "评测任务不存在", 404, eval_run_id)
        suite = session.get(EvalSuite, run.suite_id)
        if suite is None:
            raise ApiError("NOT_FOUND", "评测套件不存在", 404, run.suite_id)
        run.status = "running"
        session.commit()
        cases = list(suite.cases_json or [])
        model_ref = run.model_ref_json or {}
        scorer = run.scorer_json or {"type": "exact_match"}
        enabled = registry.enabled_ids(session)
        prepared_ref = model_adapters.prepare(model_ref, session)
        model_kind = prepared_ref.get("type", "echo")
        ctx.log(f"[eval] 模型适配器 {model_kind} · {len(cases)} 个用例 · 并发 {prepared_ref.get('concurrency', 1)}")
        # Generation may be network bound; run it outside the DB session lock.
        outputs = model_adapters.generate_batch(cases, prepared_ref, project_id=project_id, log=ctx.log)
        results: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            output = outputs[index]
            score = score_case(case, output, scorer, enabled, session=session,
                               project_id=project_id, log=ctx.log)
            results.append({
                "case_id": case.get("id", str(index)), "category": case.get("category", "general"),
                "input": case.get("input", ""), "expected": case.get("expected"),
                "output": output, "score": score, "model_ref_type": model_kind,
            })
            ctx.log(f"[eval] 用例 {index + 1}/{len(cases)} {case.get('id')} score={score['value']} passed={score['passed']}")
            ctx.progress((index + 1) / max(1, len(cases)))
        metrics = suite_metrics(results, started)
        metrics["model_ref_type"] = model_kind
        run.metrics_json = metrics
        run.results_json = results
        run.status = "succeeded"
        session.commit()
        suite_name, suite_version = suite.name, suite.version
        linked = [{"type": "eval_run", "id": run.id}, {"type": "eval_suite", "id": suite.id}]
        dataset_versions = run.dataset_version_ids_json or []
        linked.extend({"type": "dataset_version", "id": vid} for vid in dataset_versions)
    with project_session(project_id) as session:
        report = report_service.create_report(session, project_id, {
            "name": f"{suite_name} v{suite_version} 评测报告",
            "type": suite.type if hasattr(suite, "type") else "evaluation",
            "linked_entities_json": linked,
            "summary_json": {"metrics": metrics, "suite": suite_name, "case_count": len(results)},
            "sections": [{"title": "逐用例结果", "table": results[:100]}],
        })
        run = session.get(EvalRun, eval_run_id)
        run.report_id = report.id
        session.commit()
        run_dict = as_dict(run)
    return {"eval_run_id": eval_run_id, "report_id": report.id, "metrics": metrics, **{k: run_dict[k] for k in ("status", "id")}}


def compute_ab(session, project_id: str, payload: dict[str, Any], ab_id: str | None = None) -> dict[str, Any]:
    prompts = payload.get("prompt_set_json") or []
    if not prompts:
        raise ApiError("VALIDATION_ERROR", "A/B 测试需要 prompt_set_json", 422)
    wins_a = wins_b = ties = 0
    scores_a: list[float] = []
    scores_b: list[float] = []
    for item in prompts:
        a = float(item.get("score_a", 0) or 0)
        b = float(item.get("score_b", 0) or 0)
        scores_a.append(a)
        scores_b.append(b)
        winner = item.get("winner") or ("a" if a > b else "b" if b > a else "tie")
        if winner == "a":
            wins_a += 1
        elif winner == "b":
            wins_b += 1
        else:
            ties += 1
    total = len(prompts)
    significance = two_proportion_z(wins_a, total, wins_b, total)
    result = {
        "total": total, "wins_a": wins_a, "wins_b": wins_b, "ties": ties,
        "win_rate_a": round(wins_a / total, 4), "win_rate_b": round(wins_b / total, 4),
        "avg_score_a": round(sum(scores_a) / total, 4), "avg_score_b": round(sum(scores_b) / total, 4),
        "significance": significance,
    }
    if ab_id:
        ab = session.get(ABTest, ab_id)
        if ab is None:
            raise ApiError("NOT_FOUND", "A/B 测试不存在", 404, ab_id)
        ab.result_json = result
        ab.status = "completed"
        session.commit()
    return result


def parse_model_ref(value: Any) -> dict[str, Any]:
    """Legacy A/B refs are plain strings; generated mode uses adapter dicts."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
        return {"type": "inline", "field": "output", "label": value}
    return {"type": "echo"}


async def ab_worker(project_id: str, ab_id: str, ctx) -> dict[str, Any]:
    """Generate both models' outputs, score them, then compute win rates."""
    with project_session(project_id) as session:
        ab = session.get(ABTest, ab_id)
        if ab is None:
            raise ApiError("NOT_FOUND", "A/B 测试不存在", 404, ab_id)
        ref_a = parse_model_ref(ab.model_a_ref)
        ref_b = parse_model_ref(ab.model_b_ref)
        prompts = list(ab.prompt_set_json or [])
        scorer = dict(ab.scorer_json or {"type": "exact_match"})
        enabled = registry.enabled_ids(session)
        prepared_a = model_adapters.prepare(ref_a, session)
        prepared_b = model_adapters.prepare(ref_b, session)
        ab.status = "running"
        session.commit()
        name = ab.name

    cases = [{
        "id": item.get("id", str(index)),
        "input": item.get("input", item.get("prompt", "")),
        "expected": item.get("expected", ""),
        "category": item.get("category", "general"),
        "metadata": item.get("metadata") or {},
    } for index, item in enumerate(prompts)]
    ctx.log(f"[ab] A={ref_a.get('type')} B={ref_b.get('type')} · {len(cases)} 条提示")
    outputs_a = model_adapters.generate_batch(cases, prepared_a, project_id=project_id, log=ctx.log)
    outputs_b = model_adapters.generate_batch(cases, prepared_b, project_id=project_id, log=ctx.log)

    enriched: list[dict[str, Any]] = []
    with project_session(project_id) as session:
        for index, (item, case, out_a, out_b) in enumerate(zip(prompts, cases, outputs_a, outputs_b)):
            score_a = score_case(case, out_a, scorer, enabled, session=session,
                                 project_id=project_id, log=ctx.log)["value"]
            score_b = score_case(case, out_b, scorer, enabled, session=session,
                                 project_id=project_id, log=ctx.log)["value"]
            enriched.append({**item, "input": case["input"], "output_a": out_a, "output_b": out_b,
                             "score_a": score_a, "score_b": score_b,
                             "winner": "a" if score_a > score_b else "b" if score_b > score_a else "tie"})
            ctx.progress((index + 1) / max(1, len(cases)))
        result = compute_ab(session, project_id, {"prompt_set_json": enriched}, ab_id)
        row = session.get(ABTest, ab_id)
        row.prompt_set_json = enriched
        session.commit()

    with project_session(project_id) as session:
        report = report_service.create_report(session, project_id, {
            "name": f"{name} 报告（自动生成）", "type": "ab",
            "linked_entities_json": [{"type": "ab_test", "id": ab_id}],
            "summary_json": {"metrics": {k: v for k, v in result.items() if isinstance(v, (int, float))},
                             "model_a": ref_a, "model_b": ref_b, "generated": True},
            "sections": [{"title": "逐提示结果", "table": enriched[:100]}],
        })
        row = session.get(ABTest, ab_id)
        row.report_id = report.id
        session.commit()
    return {"ab_test_id": ab_id, "report_id": report.id, "result": result}
