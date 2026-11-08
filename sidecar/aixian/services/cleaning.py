"""Versioned, re-runnable cleaning pipelines with built-in + plugin operators."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from ..errors import ApiError
from ..plugin_loader import registry
from ..util import stable_hash

_OPERATORS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]] = {}


def operator(name: str):
    def register(fn):
        _OPERATORS[name] = fn
        return fn
    return register


def _field(record: dict[str, Any], name: str) -> str:
    value = record.get(name, "")
    return "" if value is None else str(value)


@operator("strip_whitespace")
def _strip(record, params):
    fields = params.get("fields") or ["text", "content", "prompt", "output"]
    out = dict(record)
    for name in fields:
        if name in out and isinstance(out[name], str):
            out[name] = re.sub(r"\s+", " ", out[name]).strip()
    return out


@operator("normalize_unicode")
def _normalize(record, params):
    fields = params.get("fields") or [k for k, v in record.items() if isinstance(v, str)]
    out = dict(record)
    for name in fields:
        if isinstance(out.get(name), str):
            out[name] = unicodedata.normalize("NFKC", out[name])
    return out


@operator("dedup")
def _dedup(record, params):
    key = params.get("field")
    digest = stable_hash(record.get(key)) if key else stable_hash(record)
    seen = params.setdefault("_seen", set())
    if digest in seen:
        return None
    seen.add(digest)
    return record


@operator("filter_regex")
def _filter_regex(record, params):
    pattern = params.get("pattern", "")
    field = params.get("field", "text")
    mode = params.get("mode", "keep")
    if not pattern:
        return record
    matched = bool(re.search(pattern, _field(record, field), re.IGNORECASE if params.get("ignore_case") else 0))
    return record if (matched if mode == "keep" else not matched) else None


@operator("regex_replace")
def _regex_replace(record, params):
    field = params.get("field", "text")
    out = dict(record)
    if field in out and isinstance(out[field], str):
        out[field] = re.sub(params.get("pattern", ""), params.get("replacement", ""), out[field])
    return out


@operator("length_range")
def _length(record, params):
    field = params.get("field", "text")
    length = len(_field(record, field))
    minimum = int(params.get("min", 0))
    maximum = int(params.get("max", 1000000))
    return record if minimum <= length <= maximum else None


@operator("language_filter")
def _language(record, params):
    field = params.get("field", "text")
    allow = set(params.get("allow", ["zh", "en"]))
    value = _field(record, field)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    detected = "zh" if cjk >= latin else "en" if latin > 0 else "other"
    return record if detected in allow else None


@operator("desensitize")
def _desensitize(record, params):
    fields = params.get("fields") or [k for k, v in record.items() if isinstance(v, str)]
    replacements = [
        (r"1[3-9]\d{9}", "[PHONE]"),
        (r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"),
        (r"\b\d{17}[\dXx]\b", "[ID]"),
    ]
    out = dict(record)
    for name in fields:
        if isinstance(out.get(name), str):
            value = out[name]
            for pattern, mask in replacements:
                value = re.sub(pattern, mask, value)
            out[name] = value
    return out


@operator("field_map")
def _field_map(record, params):
    rename = params.get("rename", {})
    drop = set(params.get("drop", []))
    return {rename.get(k, k): v for k, v in record.items() if k not in drop}


@operator("drop_empty")
def _drop_empty(record, params):
    fields = params.get("fields") or [k for k in record if isinstance(record[k], str)]
    return record if all(_field(record, f).strip() for f in fields) else None


BUILTIN_META = [
    {"op": "strip_whitespace", "label": "空白归一化", "params": {"fields": ["text"]}},
    {"op": "normalize_unicode", "label": "Unicode NFKC", "params": {}},
    {"op": "dedup", "label": "去重", "params": {"field": "text"}},
    {"op": "filter_regex", "label": "正则过滤", "params": {"field": "text", "pattern": "", "mode": "keep"}},
    {"op": "regex_replace", "label": "正则替换", "params": {"field": "text", "pattern": "", "replacement": ""}},
    {"op": "length_range", "label": "长度过滤", "params": {"field": "text", "min": 1, "max": 8192}},
    {"op": "language_filter", "label": "语言过滤", "params": {"field": "text", "allow": ["zh", "en"]}},
    {"op": "desensitize", "label": "脱敏", "params": {}},
    {"op": "field_map", "label": "字段映射", "params": {"rename": {}, "drop": []}},
    {"op": "drop_empty", "label": "空值剔除", "params": {}},
]


def list_operators(enabled_ids: set[str] | None = None) -> list[dict[str, Any]]:
    result = [dict(item, source="builtin") for item in BUILTIN_META]
    for plugin, extension, impl in registry.implementations("cleaning_operator", enabled_ids):
        result.append({
            "op": f"plugin:{plugin.id}:{extension.get('impl', '')}",
            "label": extension.get("label") or plugin.name,
            "params": {},
            "source": "plugin",
            "plugin_id": plugin.id,
        })
    return result


def apply_pipeline(
    records: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    enabled_ids: set[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (cleaned_records, per-node statistics). Nodes with stateful params
    (dedup) receive a private copy so re-runs are deterministic."""
    current = [dict(r) for r in records]
    stats: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        if node.get("enabled") is False:
            stats.append({"index": index, "op": node.get("op"), "skipped": True})
            continue
        op_name = node.get("op", "")
        params = dict(node.get("params") or {})
        if op_name.startswith("plugin:"):
            _, plugin_id, impl_ref = op_name.split(":", 2)
            plugin = next((p for p in registry.discover() if p.id == plugin_id), None)
            if plugin is None:
                raise ApiError("PLUGIN_NOT_FOUND", f"清洗算子插件未安装: {plugin_id}", 404)
            registry.require_permission(plugin, "fs:read")
            impl = registry.implementation(plugin, impl_ref)
            fn = impl.apply
        elif op_name in _OPERATORS:
            fn = _OPERATORS[op_name]
        else:
            raise ApiError("UNKNOWN_OPERATOR", f"未知清洗算子: {op_name}", 422)
        before = len(current)
        kept: list[dict[str, Any]] = []
        for record in current:
            result = fn(dict(record), params)
            if result is not None:
                kept.append(result)
        current = kept
        entry = {"index": index, "op": op_name, "input": before, "output": len(current), "dropped": before - len(current)}
        stats.append(entry)
        if log:
            log(f"[clean] 节点 {index + 1} {op_name}: {before} -> {len(current)} (丢弃 {before - len(current)})")
    return current, stats
