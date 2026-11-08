"""Fine-tune orchestration: templates, dataset-format checks, adapter registration.

The platform never implements training algorithms. It wires the trainer's own
script + base-model path + dataset version + hyper-parameters, then registers
whatever adapter/checkpoint the script produced back into the model registry.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import workspace
from ..errors import ApiError
from ..models import DatasetVersion, FineTuneTemplate, Model, Record, Run, TrainingConfig
from ..util import as_dict, uid
from . import registry as model_registry

METHODS = ("lora", "qlora", "full", "freeze")
FORMATS = ("alpaca", "sharegpt", "jsonl", "custom")

_REQUIRED_FIELDS = {
    "alpaca": ("instruction", "output"),
    "sharegpt": ("conversations",),
    "jsonl": ("text",),
    "custom": (),
}

BUILTINS: list[dict[str, Any]] = [
    {"id": "builtin:lora", "name": "LoRA · 通用指令微调", "method": "lora",
     "description": "低秩适配，显存占用小，产出 adapter 目录",
     "dataset_format": "alpaca", "builtin": 1,
     "defaults_json": {"learning_rate": 0.0002, "num_epochs": 3, "batch_size": 4,
                       "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05,
                       "max_seq_len": 1024},
     "params_schema_json": {"type": "object", "properties": {
         "learning_rate": {"type": "number"}, "num_epochs": {"type": "integer"},
         "batch_size": {"type": "integer"}, "lora_r": {"type": "integer"},
         "lora_alpha": {"type": "integer"}, "lora_dropout": {"type": "number"},
         "max_seq_len": {"type": "integer"}}}},
    {"id": "builtin:qlora", "name": "QLoRA · 4bit 量化微调", "method": "qlora",
     "description": "4bit 量化基座 + LoRA，单卡可跑较大模型",
     "dataset_format": "alpaca", "builtin": 1,
     "defaults_json": {"learning_rate": 0.0002, "num_epochs": 3, "batch_size": 2,
                       "lora_r": 32, "lora_alpha": 64, "lora_dropout": 0.05,
                       "max_seq_len": 1024, "quant_bits": 4},
     "params_schema_json": {"type": "object", "properties": {
         "learning_rate": {"type": "number"}, "num_epochs": {"type": "integer"},
         "batch_size": {"type": "integer"}, "lora_r": {"type": "integer"},
         "quant_bits": {"type": "integer"}}}},
    {"id": "builtin:full", "name": "全参数微调", "method": "full",
     "description": "全量权重更新，产出完整 checkpoint",
     "dataset_format": "alpaca", "builtin": 1,
     "defaults_json": {"learning_rate": 0.00002, "num_epochs": 2, "batch_size": 1,
                       "max_seq_len": 2048, "gradient_accumulation": 8},
     "params_schema_json": {"type": "object", "properties": {
         "learning_rate": {"type": "number"}, "num_epochs": {"type": "integer"},
         "gradient_accumulation": {"type": "integer"}}}},
    {"id": "builtin:freeze", "name": "冻结层微调", "method": "freeze",
     "description": "冻结大部分层，只训练头部，适合小数据快速验证",
     "dataset_format": "jsonl", "builtin": 1,
     "defaults_json": {"learning_rate": 0.001, "num_epochs": 5, "batch_size": 8,
                       "freeze_layers": 0.8},
     "params_schema_json": {"type": "object", "properties": {
         "learning_rate": {"type": "number"}, "num_epochs": {"type": "integer"},
         "freeze_layers": {"type": "number"}}}},
]


def templates(session: Session, project_id: str) -> list[dict[str, Any]]:
    custom = [as_dict(row) for row in session.execute(
        select(FineTuneTemplate).where(FineTuneTemplate.project_id == project_id)).scalars().all()]
    return [*BUILTINS, *custom]


def get_template(session: Session, project_id: str, template_id: str) -> dict[str, Any]:
    if template_id.startswith("builtin:"):
        match = next((t for t in BUILTINS if t["id"] == template_id), None)
        if match is None:
            raise ApiError("NOT_FOUND", "内置微调模板不存在", 404, template_id)
        return dict(match)
    row = session.get(FineTuneTemplate, template_id)
    if row is None or row.project_id != project_id:
        raise ApiError("NOT_FOUND", "微调模板不存在", 404, template_id)
    return as_dict(row)


def create_template(session: Session, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError("VALIDATION_ERROR", "模板名称必填", 422)
    method = str(payload.get("method") or "lora")
    if method not in METHODS:
        raise ApiError("VALIDATION_ERROR", f"微调方法仅支持 {METHODS}", 422)
    fmt = str(payload.get("dataset_format") or "alpaca")
    if fmt not in FORMATS:
        raise ApiError("VALIDATION_ERROR", f"训练格式仅支持 {FORMATS}", 422)
    row = FineTuneTemplate(
        id=uid(), project_id=project_id, name=name, method=method,
        description=str(payload.get("description") or ""), dataset_format=fmt,
        defaults_json=payload.get("defaults_json") or {},
        params_schema_json=payload.get("params_schema_json") or {}, builtin=0)
    session.add(row)
    session.commit()
    return as_dict(row)


def check_dataset(session: Session, version_id: str, fmt: str) -> dict[str, Any]:
    """Warn (not fail hard) when a dataset does not match the template format."""
    required = _REQUIRED_FIELDS.get(fmt, ())
    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise ApiError("NOT_FOUND", "数据集版本不存在", 404, version_id)
    rows = session.execute(select(Record).where(
        Record.dataset_version_id == version_id).limit(20)).scalars().all()
    if not rows:
        return {"ok": False, "format": fmt, "checked": 0,
                "missing": list(required), "message": "该版本没有记录"}
    missing = sorted({field for field in required
                      if not any(field in (row.payload_json or {}) for row in rows)})
    return {"ok": not missing, "format": fmt, "checked": len(rows), "missing": missing,
            "message": "" if not missing else f"缺少字段：{', '.join(missing)}；可先导出为 {fmt} 格式"}


def instantiate(session: Session, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a TrainingConfig carrying the fine-tune spec; script stays the trainer's."""
    template = get_template(session, project_id, str(payload.get("template_id") or "builtin:lora"))
    script_id = payload.get("script_id")
    if not script_id:
        raise ApiError("VALIDATION_ERROR", "微调需要 script_id（训练脚本由训练师自己提供）", 422)
    from ..models import Script
    script = session.get(Script, script_id)
    if script is None or script.project_id != project_id:
        raise ApiError("NOT_FOUND", "训练脚本不存在", 404, script_id)
    base_model_id = payload.get("base_model_id")
    if base_model_id:
        base = session.get(Model, base_model_id)
        if base is None or base.project_id != project_id:
            raise ApiError("NOT_FOUND", "基座模型不存在", 404, base_model_id)
    params = {**(template.get("defaults_json") or {}), **(payload.get("params") or {})}
    adapter_output = str(payload.get("adapter_output") or "adapters/final")
    spec = {
        "template_id": template["id"], "template_name": template["name"],
        "method": template["method"], "dataset_format": template["dataset_format"],
        "base_model_id": base_model_id, "adapter_output": adapter_output,
        "params": params,
    }
    row = TrainingConfig(
        id=uid(), project_id=project_id,
        name=payload.get("name") or f"{template['name']} · {script.name}",
        script_id=script_id, params_json=params,
        params_schema_json=template.get("params_schema_json") or {},
        env_json=payload.get("env_json") or {}, finetune_json=spec,
        runner_type=payload.get("runner_type") or "local")
    session.add(row)
    session.commit()
    return {**as_dict(row), "warnings": []}


def resolve_base_model(session: Session, project_id: str, config: TrainingConfig) -> dict[str, Any]:
    spec = config.finetune_json or {}
    out: dict[str, Any] = {"path": "", "name": "", "method": spec.get("method", ""),
                           "format": spec.get("dataset_format", "custom"),
                           "adapter_output": spec.get("adapter_output") or "adapters/final"}
    base_id = spec.get("base_model_id")
    if not base_id:
        return out
    base = session.get(Model, base_id)
    if base is None:
        return out
    ref = base.ref_json or {}
    out["name"] = base.name
    out["path"] = str(ref.get("model") or ref.get("url") or ref.get("base_url") or "")
    return out


def register_adapters(session: Session, project_id: str, run: Run,
                      config: TrainingConfig, run_dir: Path) -> list[dict[str, Any]]:
    """Publish produced adapters/checkpoints into the model registry."""
    spec = config.finetune_json or {}
    if not spec:
        return []
    folders = [run_dir / "adapters", run_dir / "checkpoints"]
    candidates: list[Path] = []
    for folder in folders:
        if not folder.exists():
            continue
        candidates.extend(sorted(p for p in folder.iterdir() if p.is_dir()))
    if not candidates:
        # a single-file adapter artifact is still a valid output
        for folder in folders:
            if folder.exists():
                candidates.extend(sorted(p for p in folder.iterdir()
                                         if p.is_file() and p.suffix in (".bin", ".safetensors", ".pt")))
    registered: list[dict[str, Any]] = []
    for index, path in enumerate(candidates[:20]):
        name = f"{run.name or run.id[:8]} · {spec.get('method', 'finetune')} · {path.name}"
        try:
            row = model_registry.create(session, project_id, {
                "name": name,
                "kind": "adapter" if spec.get("method") in ("lora", "qlora") else "finetuned",
                "adapter_type": spec.get("method") or "full",
                "description": f"由实验 {run.name or run.id[:8]} 自动登记",
                "ref_json": {"type": "transformers", "model": str(path),
                             "task": "text-generation", "base_model": run_dir.as_posix()},
                "base_model_id": spec.get("base_model_id"),
                "source_run_id": run.id,
                "params_json": {"finetune": spec, "artifact": path.name},
                "tags_json": ["微调产物", str(spec.get("method") or "full")],
            })
            registered.append({"id": row["id"], "name": name, "path": str(path)})
        except ApiError as exc:
            if exc.code != "DUPLICATE_NAME":
                raise
    return registered
