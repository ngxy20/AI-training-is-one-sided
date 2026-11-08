"""Model registry: user-owned models are referenced by path/endpoint, never copied.

The platform stores a name, an adapter config and lineage links; weights stay
where the trainer put them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import ABTest, EvalRun, Model, Run
from ..util import as_dict, now, uid
from . import model_adapters

KINDS = ("base", "finetuned", "adapter", "endpoint", "external")
STATUSES = ("active", "archived", "missing")

# Which ref key holds a local filesystem path for each adapter type.
_PATH_ADAPTERS = {
    "transformers": "model",
    "subprocess": "command",
    "dataset": "dataset_version_id",
}


def validate_ref(ref: Any) -> tuple[dict[str, Any], list[str]]:
    """Validate an adapter config; return it plus non-fatal warnings."""
    if not isinstance(ref, dict) or not ref:
        raise ApiError("VALIDATION_ERROR", "ref_json 必须是非空的适配器配置对象", 422)
    kind = str(ref.get("type") or "")
    if kind not in model_adapters.ADAPTER_TYPES:
        raise ApiError("VALIDATION_ERROR",
                       f"未知模型适配器类型 {kind!r}，可用：{model_adapters.ADAPTER_TYPES}", 422)
    warnings: list[str] = []

    if kind in ("openai", "vllm", "http"):
        url = str(ref.get("url") or ref.get("base_url") or "")
        if not url.startswith(("http://", "https://")):
            raise ApiError("VALIDATION_ERROR", "远端模型需要 http(s) 开头的 url / base_url", 422)
    if kind in ("transformers", "subprocess"):
        key = _PATH_ADAPTERS[kind]
        value = ref.get(key)
        if not value:
            raise ApiError("VALIDATION_ERROR", f"{kind} 适配器需要字段 {key}", 422)
        raw = value[0] if isinstance(value, list) and value else str(value)
        candidate = Path(str(raw))
        if candidate.is_absolute() and not candidate.exists():
            warnings.append(f"本地路径暂不存在：{candidate}（可稍后再放置权重）")
    if kind == "dataset" and not ref.get("dataset_version_id"):
        raise ApiError("VALIDATION_ERROR", "dataset 适配器需要 dataset_version_id", 422)
    return dict(ref), warnings


def path_status(ref: dict[str, Any]) -> str:
    """Whether the referenced local model path currently exists."""
    kind = str(ref.get("type") or "")
    key = _PATH_ADAPTERS.get(kind)
    if not key:
        return "ok"
    value = ref.get(key)
    raw = value[0] if isinstance(value, list) and value else str(value or "")
    if not raw:
        return "missing"
    candidate = Path(raw)
    if not candidate.is_absolute():
        return "ok"  # Hub id / command on PATH / version id
    return "ok" if candidate.exists() else "missing"


def create(session: Session, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError("VALIDATION_ERROR", "模型名称必填", 422)
    exists = session.scalar(select(func.count()).select_from(Model).where(
        Model.project_id == project_id, Model.name == name, Model.status != "archived"))
    if exists:
        raise ApiError("DUPLICATE_NAME", f"项目内已存在同名模型：{name}", 409)
    kind = str(payload.get("kind") or "base")
    if kind not in KINDS:
        raise ApiError("VALIDATION_ERROR", f"模型类型仅支持 {KINDS}", 422)
    ref, warnings = validate_ref(payload.get("ref_json"))
    row = Model(
        id=uid(), project_id=project_id, name=name,
        description=str(payload.get("description") or ""), kind=kind,
        adapter_type=str(payload.get("adapter_type") or ""),
        ref_json=ref, base_model_id=payload.get("base_model_id"),
        source_run_id=payload.get("source_run_id"),
        source_checkpoint_id=payload.get("source_checkpoint_id"),
        params_json=payload.get("params_json") or {},
        tags_json=payload.get("tags_json") or [],
        status="missing" if path_status(ref) == "missing" else "active",
    )
    if row.base_model_id:
        base = session.get(Model, row.base_model_id)
        if base is None or base.project_id != project_id:
            raise ApiError("NOT_FOUND", "基座模型不存在", 404, row.base_model_id)
    session.add(row)
    session.commit()
    return {**as_dict(row), "warnings": warnings, "path_status": path_status(ref)}


def update(session: Session, project_id: str, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = session.get(Model, model_id)
    if row is None or row.project_id != project_id:
        raise ApiError("NOT_FOUND", "模型不存在", 404, model_id)
    warnings: list[str] = []
    if "ref_json" in payload:
        ref, warnings = validate_ref(payload["ref_json"])
        if ref != row.ref_json:
            row.parent_version_id = row.id
            row.version = (row.version or 1) + 1
        row.ref_json = ref
        row.status = "missing" if path_status(ref) == "missing" else "active"
    for key in ("name", "description", "kind", "adapter_type", "params_json", "tags_json", "status"):
        if key in payload:
            setattr(row, key, payload[key])
    if row.status not in STATUSES:
        raise ApiError("VALIDATION_ERROR", f"状态仅支持 {STATUSES}", 422)
    session.commit()
    return {**as_dict(row), "warnings": warnings, "path_status": path_status(row.ref_json)}


def resolve(session: Session, project_id: str, model_id: str | None,
            inline_ref: dict[str, Any] | None = None) -> tuple[dict[str, Any], Model | None]:
    """model_id wins; inline_ref is kept for backward compatibility."""
    if model_id:
        row = session.get(Model, model_id)
        if row is None or row.project_id != project_id:
            raise ApiError("NOT_FOUND", "注册表里没有该模型", 404, model_id)
        if row.status == "archived":
            raise ApiError("MODEL_ARCHIVED", f"模型「{row.name}」已归档，无法调用", 409)
        return dict(row.ref_json or {}), row
    if inline_ref:
        ref, _ = validate_ref(inline_ref)
        return ref, None
    raise ApiError("MODEL_REQUIRED", "请提供 model_id 或 model_ref_json", 422)


def usage(session: Session, model_id: str) -> dict[str, Any]:
    evals = session.scalar(select(func.count()).select_from(EvalRun).where(EvalRun.model_id == model_id)) or 0
    ab = session.scalar(select(func.count()).select_from(ABTest).where(
        or_(ABTest.model_a_id == model_id, ABTest.model_b_id == model_id))) or 0
    children = session.execute(select(Model).where(Model.base_model_id == model_id)).scalars().all()
    return {"eval_runs": evals, "ab_tests": ab, "derived_models": len(children),
            "children": [{"id": m.id, "name": m.name} for m in children]}


def detail(session: Session, project_id: str, model_id: str) -> dict[str, Any]:
    row = session.get(Model, model_id)
    if row is None or row.project_id != project_id:
        raise ApiError("NOT_FOUND", "模型不存在", 404, model_id)
    data = {**as_dict(row), "path_status": path_status(row.ref_json or {}),
            "usage": usage(session, model_id)}
    if row.base_model_id:
        base = session.get(Model, row.base_model_id)
        data["base_model"] = {"id": base.id, "name": base.name} if base else None
    if row.source_run_id:
        run = session.get(Run, row.source_run_id)
        data["source_run"] = {"id": run.id, "name": run.name} if run else None
    return data


def register_checkpoint(session: Session, project_id: str, run: Run,
                        checkpoint_path: str, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Auto-register a training checkpoint so it becomes a reusable registry asset."""
    return create(session, project_id, {
        "name": name, "kind": "finetuned", "adapter_type": "full",
        "description": f"由实验 {run.name or run.id[:8]} 产出",
        "ref_json": {"type": "transformers", "model": checkpoint_path,
                     "task": "text-generation", "max_new_tokens": 256},
        "source_run_id": run.id, "params_json": params or {},
        "tags_json": ["训练产物"],
    })


def test(session: Session, project_id: str, model_id: str, prompt: str) -> dict[str, Any]:
    ref, row = resolve(session, project_id, model_id)
    prepared = model_adapters.prepare(ref, session)
    case = {"id": "registry-test", "input": prompt, "expected": "", "category": "general"}
    started = now()
    output = model_adapters.generate(case, prepared, project_id=project_id, index=0)
    if row:
        row.last_tested_at = started
        row.status = "active" if not str(output).startswith("[模型调用失败") else row.status
        session.commit()
    return {"model_id": model_id, "prompt": prompt, "output": output,
            "ok": not str(output).startswith("[模型调用失败")}
