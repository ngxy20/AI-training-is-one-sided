"""Small shared helpers (serialization, pagination, hashing, validation)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .errors import ApiError


def uid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def require(data: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    payload = data or {}
    missing = [k for k in keys if payload.get(k) in (None, "", [], {})]
    if missing:
        raise ApiError("VALIDATION_ERROR", f"缺少必填字段: {', '.join(missing)}", 422, {"fields": missing})
    return payload


def as_dict(obj: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for column in obj.__table__.columns:
        if column.name in exclude:
            continue
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            value = value.isoformat(timespec="seconds")
        out[column.name] = value
    return out


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def paginate(session: Session, query: Any, page: int, size: int, mapper: Any = as_dict) -> dict[str, Any]:
    page = max(1, page)
    size = min(max(1, size), 1000)
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = session.execute(query.offset((page - 1) * size).limit(size)).scalars().all()
    return {"items": [mapper(r) for r in rows], "page": page, "size": size, "total": total}


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target


def read_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
