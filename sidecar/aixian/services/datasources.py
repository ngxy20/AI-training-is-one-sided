"""Connect to existing SQLite / PostgreSQL / MySQL databases (plugin-overridable)."""
from __future__ import annotations

import datetime as dt
import decimal
import re
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text

from .. import config, security
from ..errors import ApiError
from ..models import DataSource
from ..plugin_loader import registry
from ..plugin_sdk import QueryResult

_READ_ONLY_SQL = re.compile(r"^\s*(select|with|show|describe|explain|pragma)\b", re.IGNORECASE)
_FORBIDDEN_SQL = re.compile(r";|\b(insert|update|delete|drop|alter|create|truncate|attach|grant)\b", re.IGNORECASE)


def connection_config(source: DataSource) -> dict[str, Any]:
    return security.decrypt_obj(source.conn_json)


def build_url(source_type: str, conf: dict[str, Any]) -> str:
    kind = source_type.lower()
    if kind == "sqlite":
        path = str(conf.get("path") or conf.get("database") or "")
        if not path:
            raise ApiError("BAD_CONNECTION", "SQLite 需要 path 字段", 422)
        if not (path.startswith("/") or ":" in path[1:3]):
            path = str((config.REPO_ROOT / path).resolve())
        return f"sqlite:///{path}"
    user = quote_plus(str(conf.get("user", "")))
    password = quote_plus(str(conf.get("password", "")))
    host = conf.get("host", "127.0.0.1")
    port = conf.get("port") or (5432 if kind in ("pg", "postgresql") else 3306)
    database = conf.get("database", "")
    auth = f"{user}:{password}@" if user else ""
    if kind in ("pg", "postgresql"):
        return f"postgresql+psycopg2://{auth}{host}:{port}/{database}"
    if kind in ("mysql", "mariadb"):
        return f"mysql+pymysql://{auth}{host}:{port}/{database}"
    if conf.get("url"):
        return str(conf["url"])
    raise ApiError("UNSUPPORTED_DATASOURCE", f"不支持的数据源类型: {source_type}", 422)


def _engine(source: DataSource):
    conf = connection_config(source)
    return create_engine(build_url(source.type, conf), pool_pre_ping=True, future=True)


def _plugin(source: DataSource):
    """Only opt-in plugin data sources are routed to a plugin implementation."""
    if not source.plugin_id and source.type not in ("plugin", "custom"):
        return None, None
    for plugin, extension, impl in registry.implementations("data_source"):
        if source.plugin_id and plugin.id != source.plugin_id:
            continue
        return plugin, impl
    return None, None


def to_plain(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def test_connection(source: DataSource) -> dict[str, Any]:
    plugin, impl = _plugin(source)
    if impl:
        ok = bool(impl.test_connection(connection_config(source)))
        return {"ok": ok, "type": "plugin", "plugin_id": plugin.id}
    engine = _engine(source)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "url": security.mask_config(connection_config(source)).get("url", engine.url.render_as_string(hide_password=True))}
    finally:
        engine.dispose()


def list_schema(source: DataSource) -> dict[str, Any]:
    plugin, impl = _plugin(source)
    if impl:
        tables = [t.to_dict() if hasattr(t, "to_dict") else t for t in impl.list_schema(connection_config(source))]
        return {"tables": tables, "plugin_id": plugin.id}
    engine = _engine(source)
    try:
        inspector = inspect(engine)
        tables = []
        for name in inspector.get_table_names():
            columns = []
            pk = set(inspector.get_pk_constraint(name).get("constrained_columns") or [])
            for col in inspector.get_columns(name):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": bool(col.get("nullable", True)),
                    "primary_key": col["name"] in pk,
                })
            tables.append({"name": name, "columns": columns, "row_count": None})
        return {"tables": tables, "plugin_id": None}
    finally:
        engine.dispose()


def query(source: DataSource, sql: str, max_rows: int = 500) -> dict[str, Any]:
    if not _READ_ONLY_SQL.match(sql or ""):
        raise ApiError("SQL_NOT_READONLY", "数据源查询仅允许 SELECT / WITH / SHOW / EXPLAIN", 403)
    if _FORBIDDEN_SQL.search(sql):
        raise ApiError("SQL_FORBIDDEN", "检测到多语句或写操作，已拒绝执行", 403)
    plugin, impl = _plugin(source)
    if impl:
        result: QueryResult = impl.query(connection_config(source), sql)
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        rows = payload.get("rows", [])[:max_rows]
        return {"columns": payload.get("columns", []), "rows": rows,
                "row_count": len(rows), "truncated": len(rows) >= max_rows, "plugin_id": plugin.id}
    engine = _engine(source)
    try:
        with engine.connect() as conn:
            cursor = conn.execute(text(sql))
            columns = list(cursor.keys())
            rows: list[dict[str, Any]] = []
            for raw in cursor:
                if len(rows) >= max_rows:
                    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": True}
                rows.append({key: to_plain(value) for key, value in zip(columns, raw)})
        return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": False}
    finally:
        engine.dispose()
