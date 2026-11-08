"""Immutable dataset versions, manifest/lineage, statistics, preview and export."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import String, cast, func, insert, select
from sqlalchemy.orm import Session

from .. import workspace
from ..errors import ApiError
from ..events import hub
from ..models import Dataset, DatasetVersion, Record
from ..util import as_dict, canonical, now, sha256_file, stable_hash, uid, write_json

SUPPORTED_IMPORT = ("jsonl", "json", "csv", "parquet", "txt", "dir")
SUPPORTED_EXPORT = ("jsonl", "csv", "alpaca", "sharegpt", "custom")


def read_records(path: str | Path, fmt: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise ApiError("FILE_NOT_FOUND", f"文件不存在: {source}", 404)
    fmt = (fmt or _guess_format(source)).lower()
    rows: list[dict[str, Any]] = []
    if fmt == "dir":
        for file in sorted(source.rglob("*")):
            if file.suffix.lower() in (".txt", ".md", ".json", ".jsonl"):
                rows.append({"text": file.read_text(encoding="utf-8", errors="replace"), "source": file.name})
    elif fmt == "txt":
        rows = [{"text": line} for line in source.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    elif fmt == "jsonl":
        with source.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    value = json.loads(line)
                    rows.append(value if isinstance(value, dict) else {"text": value})
    elif fmt == "json":
        data = json.loads(source.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            data = data.get("data", data.get("records", [data]))
        rows = [r if isinstance(r, dict) else {"text": r} for r in data]
    elif fmt == "csv":
        with source.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
    elif fmt == "parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ApiError("MISSING_DEPENDENCY", "读取 Parquet 需要安装 pyarrow", 500, str(exc)) from exc
        rows = pq.read_table(source).to_pylist()
    else:
        raise ApiError("UNSUPPORTED_FORMAT", f"不支持的导入格式: {fmt}", 422, {"supported": SUPPORTED_IMPORT})
    return rows[:limit] if limit else rows


def _guess_format(path: Path) -> str:
    if path.is_dir():
        return "dir"
    suffix = path.suffix.lower().lstrip(".")
    aliases = {"ndjson": "jsonl", "text": "txt"}
    return aliases.get(suffix, suffix or "txt")


def _get_field(record: dict[str, Any], key: str) -> Any:
    if key in record:
        return record[key]
    value: Any = record
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def apply_field_mapping(rows: Iterable[dict[str, Any]], mapping: dict[str, str] | None) -> list[dict[str, Any]]:
    if not mapping:
        return [dict(row) for row in rows]
    result = []
    for row in rows:
        item: dict[str, Any] = {}
        for target, source in mapping.items():
            if isinstance(source, str) and source.startswith("$const:"):
                item[target] = source[7:]
            else:
                item[target] = _get_field(row, str(source))
        result.append(item)
    return result


def infer_schema(records: list[dict[str, Any]]) -> dict[str, Any]:
    keys: dict[str, dict[str, Any]] = {}
    for record in records[:2000]:
        for key, value in record.items():
            entry = keys.setdefault(key, {"type": _type_name(value), "coverage": 0, "examples": []})
            entry["coverage"] += 1
            if len(entry["examples"]) < 3 and value not in entry["examples"]:
                entry["examples"].append(value)
    sample = min(len(records), 2000) or 1
    for entry in keys.values():
        entry["coverage"] = round(entry["coverage"] / sample, 4)
    return {"fields": keys, "field_count": len(keys)}


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return "string"


def compute_stats(records: list[dict[str, Any]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
    hashes = [stable_hash(r) for r in records]
    lengths: list[int] = []
    labels: dict[str, int] = {}
    splits = {"train": 0, "val": 0, "test": 0}
    for record in records:
        for key in ("text", "content", "prompt", "instruction", "output"):
            if isinstance(record.get(key), str):
                lengths.append(len(record[key]))
                break
        label = record.get("label") or record.get("labels")
        if isinstance(label, (str, int, float, bool)):
            labels[str(label)] = labels.get(str(label), 0) + 1
        split = record.get("split", "train")
        if split in splits:
            splits[split] += 1
    return {
        "record_count": len(records),
        "duplicate_count": len(hashes) - len(set(hashes)),
        "avg_text_length": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        "max_text_length": max(lengths) if lengths else 0,
        "label_distribution": labels,
        "split_distribution": splits,
        "schema": schema or infer_schema(records),
    }


def _split_for(value: str) -> str:
    ratio = int(value[:2], 16) / 255 if value else 0.0
    return "train" if ratio < 0.8 else ("val" if ratio < 0.9 else "test")


def next_version(session: Session, dataset_id: str) -> tuple[int, str | None]:
    current = session.scalar(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.version.desc())
    )
    if current is None:
        return 1, None
    return current.version + 1, current.id


def create_version(
    session: Session,
    project_id: str,
    dataset: Dataset,
    records: list[dict[str, Any]],
    changelog: str = "",
    created_by_job_id: str | None = None,
    source: str = "import",
) -> DatasetVersion:
    """Write an immutable version (never mutate an existing one)."""
    records = [r if isinstance(r, dict) else {"text": r} for r in records]
    version_no, parent_id = next_version(session, dataset.id)
    root = workspace.ensure_workspace(project_id)
    folder = root / "datasets" / dataset.id / f"v{version_no}"
    folder.mkdir(parents=True, exist_ok=True)
    data_path = folder / "data.jsonl"
    with data_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    schema = infer_schema(records)
    stats = compute_stats(records, schema)
    content_hash = sha256_file(data_path)
    manifest = {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "version": version_no,
        "parent_version_id": parent_id,
        "created_at": now().isoformat(),
        "created_by_job_id": created_by_job_id,
        "changelog": changelog,
        "source": source,
        "record_count": len(records),
        "content_hash": content_hash,
        "schema": schema,
        "stats": stats,
        "immutable": True,
    }
    manifest_path = write_json(folder / "manifest.json", manifest)

    version = DatasetVersion(
        dataset_id=dataset.id,
        version=version_no,
        parent_version_id=parent_id,
        manifest_path=workspace.relative(project_id, manifest_path),
        data_path=workspace.relative(project_id, data_path),
        record_count=len(records),
        stats_json=stats,
        created_by_job_id=created_by_job_id,
        content_hash=content_hash,
        changelog=changelog,
    )
    session.add(version)
    session.flush()

    stamp = now()
    for start in range(0, len(records), 1000):
        chunk = []
        for record in records[start:start + 1000]:
            digest = stable_hash(record)
            chunk.append({
                "id": uid(),
                "created_at": stamp,
                "updated_at": stamp,
                "dataset_version_id": version.id,
                "external_id": str(record.get("id", "")) or None,
                "payload_json": record,
                "label_json": record.get("label_json") or {},
                "split": str(record.get("split") or _split_for(digest)),
                "hash": digest,
            })
        if chunk:
            session.execute(insert(Record), chunk)
    dataset.schema_json = schema
    session.commit()
    hub.emit("resource.changed", {"kind": "dataset_version", "id": version.id, "dataset_id": dataset.id}, project_id)
    return version


def get_version(session: Session, version_id: str) -> DatasetVersion:
    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise ApiError("NOT_FOUND", "数据集版本不存在", 404, version_id)
    return version


def query_records(
    session: Session,
    version_id: str,
    page: int = 1,
    size: int = 50,
    split: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    query = select(Record).where(Record.dataset_version_id == version_id)
    if split:
        query = query.where(Record.split == split)
    if search:
        query = query.where(cast(Record.payload_json, String).like(f"%{search}%"))
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = session.scalar(count_query) or 0
    rows = session.execute(query.order_by(Record.created_at, Record.id).offset((page - 1) * size).limit(size)).scalars().all()
    return {
        "items": [as_dict(r) for r in rows],
        "page": page,
        "size": size,
        "total": total,
    }


def all_records(session: Session, version_id: str) -> list[dict[str, Any]]:
    return [
        r.payload_json
        for r in session.execute(select(Record).where(Record.dataset_version_id == version_id)).scalars().all()
    ]


def export_version(
    session: Session,
    project_id: str,
    version_id: str,
    fmt: str = "jsonl",
    mapping: dict[str, str] | None = None,
    template: str = "",
    split: str | None = None,
) -> dict[str, Any]:
    fmt = fmt.lower()
    if fmt not in SUPPORTED_EXPORT:
        raise ApiError("UNSUPPORTED_FORMAT", f"不支持的导出格式: {fmt}", 422, {"supported": SUPPORTED_EXPORT})
    version = get_version(session, version_id)
    query = select(Record).where(Record.dataset_version_id == version_id)
    if split:
        query = query.where(Record.split == split)
    records = [r.payload_json for r in session.execute(query).scalars().all()]
    mapping = mapping or {}
    field = lambda row, key, default="": row.get(mapping.get(key, key)) or default  # noqa: E731
    converted: list[Any] = []
    for row in records:
        if fmt == "alpaca":
            converted.append({
                "instruction": field(row, "instruction"),
                "input": field(row, "input"),
                "output": field(row, "output"),
            })
        elif fmt == "sharegpt":
            converted.append({"conversations": [
                {"from": "human", "value": field(row, "prompt") or field(row, "instruction")},
                {"from": "gpt", "value": field(row, "output") or field(row, "response")},
            ]})
        elif fmt == "custom":
            tpl = template or "{text}"
            def repl(match):  # noqa: ANN001, ANN202
                return str(row.get(match.group(1), ""))
            converted.append({"text": re.sub(r"\{(\w+)\}", repl, tpl)})
        else:
            converted.append(row)
    suffix = "csv" if fmt == "csv" else "jsonl"
    target = workspace.new_asset_path(project_id, "exports", f"{version_id}_{fmt}.{suffix}")
    if fmt == "csv" and converted and isinstance(converted[0], dict):
        fields = sorted({k for item in converted for k in item})
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(converted)
    else:
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            for item in converted:
                handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    hub.emit("resource.changed", {"kind": "export", "version_id": version_id, "format": fmt}, project_id)
    return {
        "path": workspace.relative(project_id, target),
        "uri": workspace.uri(project_id, "export", f"{version_id}:{fmt}"),
        "format": fmt,
        "record_count": len(converted),
        "preview": converted[:3],
        "dataset_version_id": version.id,
        "dataset_version": version.version,
        "content_hash": version.content_hash,
    }
