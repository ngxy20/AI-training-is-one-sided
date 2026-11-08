"""Shared domain helpers: dataset resolution, JSON-Schema inference, statistics."""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import Dataset, DatasetVersion, EvalRun, Report, Run
from ..util import uid


def get_or_create_dataset(
    session: Session,
    project_id: str,
    name: str,
    dataset_id: str | None = None,
    source_type: str = "import",
    description: str = "",
) -> Dataset:
    if dataset_id:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            raise ApiError("NOT_FOUND", "数据集不存在", 404, dataset_id)
        return dataset
    dataset = Dataset(
        id=uid(), project_id=project_id, name=name,
        description=description, source_type=source_type, schema_json={},
    )
    session.add(dataset)
    session.commit()
    return dataset


def infer_params_schema(params: dict[str, Any]) -> dict[str, Any]:
    """Generate a JSON Schema from concrete params (form <-> YAML two-way binding)."""
    properties: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, bool):
            spec: dict[str, Any] = {"type": "boolean", "default": value}
        elif isinstance(value, int):
            spec = {"type": "integer", "default": value}
        elif isinstance(value, float):
            spec = {"type": "number", "default": value}
        elif isinstance(value, list):
            spec = {"type": "array", "items": {"type": "string"}, "default": value}
        elif isinstance(value, dict):
            spec = {"type": "object", "default": value}
        else:
            spec = {"type": "string", "default": str(value)}
        spec["title"] = key.replace("_", " ").title()
        properties[key] = spec
    return {"type": "object", "properties": properties, "required": [], "additionalProperties": True}


def cohen_kappa(pairs: list[tuple[Any, Any]]) -> float:
    """Cohen's Kappa for two annotators (ported from the legacy prototype)."""
    if not pairs:
        return 0.0
    labels = sorted({str(a) for a, _ in pairs} | {str(b) for _, b in pairs})
    total = len(pairs)
    agree = sum(1 for a, b in pairs if str(a) == str(b))
    po = agree / total
    count_a: dict[str, int] = {}
    count_b: dict[str, int] = {}
    for a, b in pairs:
        count_a[str(a)] = count_a.get(str(a), 0) + 1
        count_b[str(b)] = count_b.get(str(b), 0) + 1
    pe = sum((count_a.get(k, 0) / total) * (count_b.get(k, 0) / total) for k in labels)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0


def two_proportion_z(success_a: int, total_a: int, success_b: int, total_b: int) -> dict[str, Any]:
    if not total_a or not total_b:
        return {"p_value": 1.0, "significant": False, "z": 0.0}
    pa, pb = success_a / total_a, success_b / total_b
    pooled = (success_a + success_b) / (total_a + total_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / total_a + 1 / total_b)) or 1e-12
    z = (pa - pb) / se
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return {"p_value": round(p_value, 6), "significant": p_value < 0.05, "z": round(z, 4)}


def lineage_nodes(session: Session, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from ..util import as_dict

    table_map = {
        "dataset": Dataset,
        "dataset_version": DatasetVersion,
        "run": Run,
        "eval_run": EvalRun,
        "report": Report,
    }
    nodes = []
    for entity in entities:
        model = table_map.get(entity.get("type"))
        ident = entity.get("id")
        if model and ident:
            row = session.get(model, ident)
            if row:
                nodes.append({"type": entity["type"], "id": ident, "label": getattr(row, "name", None) or str(getattr(row, "version", ident)), "data": as_dict(row)})
    return nodes
