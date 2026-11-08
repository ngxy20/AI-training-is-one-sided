"""IDE-style theme registry: built-in presets + user-defined color tokens.

Themes are stored in the global settings file; the desktop applies them as CSS
custom properties so Monaco and every panel stay in sync.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import Body
from fastapi.responses import JSONResponse

from .. import config
from ..errors import ApiError
from ..util import uid
from .common import make_router

router = make_router()

TOKEN_KEYS = (
    "bg", "panel", "panel2", "panel3", "line", "text", "muted", "dim",
    "accent", "accentSoft", "green", "amber", "red", "cyan",
    "scrollbar", "rowHover", "codeBg", "borderSoft", "selection",
    "editorBg", "editorLine", "cursor",
    "synKeyword", "synString", "synNumber", "synComment",
    "synFunction", "synVariable", "synType", "synOperator",
)
COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

_BASE: dict[str, str] = {
    "bg": "#0d1117", "panel": "#131a24", "panel2": "#182230", "panel3": "#1e2937",
    "line": "#263141", "text": "#dce4f0", "muted": "#8595ab", "dim": "#5f6f85",
    "accent": "#6c8cff", "accentSoft": "#24345c", "green": "#3fb950",
    "amber": "#d9a441", "red": "#f05c5c", "cyan": "#56c8d8",
    "scrollbar": "#334155", "rowHover": "#1a2432", "codeBg": "#0b1017",
    "borderSoft": "#1e2836", "selection": "#264f78",
    "editorBg": "#0d1117", "editorLine": "#161d29", "cursor": "#dce4f0",
    "synKeyword": "#c792ea", "synString": "#c3e88d", "synNumber": "#f78c6c",
    "synComment": "#5f6f85", "synFunction": "#82aaff", "synVariable": "#dce4f0",
    "synType": "#ffcb6b", "synOperator": "#89ddff",
}

PRESETS: list[dict[str, Any]] = [
    {"id": "dark", "name": "深色默认", "builtin": True, "tokens": dict(_BASE)},
    {"id": "light", "name": "浅色办公", "builtin": True, "tokens": {
        **_BASE,
        "bg": "#f5f7fa", "panel": "#ffffff", "panel2": "#eef2f7", "panel3": "#e4eaf2",
        "line": "#d5dce6", "text": "#1d2733", "muted": "#5b6a7d", "dim": "#8b98a9",
        "accent": "#3c63e0", "accentSoft": "#dce6ff", "green": "#1f9d45",
        "amber": "#b4770d", "red": "#d33a3a", "cyan": "#12879b",
        "scrollbar": "#b9c4d2", "rowHover": "#eef3fa", "codeBg": "#fbfcfe",
        "borderSoft": "#e6ebf2", "selection": "#c8d9ff",
        "editorBg": "#ffffff", "editorLine": "#f2f6fc", "cursor": "#1d2733",
        "synKeyword": "#8a2fb8", "synString": "#1c7a3c", "synNumber": "#b5501c",
        "synComment": "#8b98a9", "synFunction": "#1f4fb8", "synVariable": "#1d2733",
        "synType": "#986a00", "synOperator": "#08718b",
    }},
    {"id": "midnight", "name": "午夜高对比", "builtin": True, "tokens": {
        **_BASE,
        "bg": "#05070c", "panel": "#0b101a", "panel2": "#121a28", "panel3": "#1a2536",
        "line": "#31415a", "text": "#f2f6ff", "muted": "#a6b6cf", "dim": "#7590b5",
        "accent": "#7aa2ff", "accentSoft": "#1e3a72", "green": "#4ade80",
        "scrollbar": "#4a6080", "rowHover": "#16223a", "codeBg": "#070b12",
        "borderSoft": "#202d40", "selection": "#2b5fa8",
        "editorBg": "#05070c", "editorLine": "#101827", "cursor": "#ffffff",
    }},
    {"id": "dracula", "name": "Dracula 紫", "builtin": True, "tokens": {
        **_BASE,
        "bg": "#191a21", "panel": "#21222c", "panel2": "#282a36", "panel3": "#343746",
        "line": "#414458", "text": "#f8f8f2", "muted": "#a7a9bd", "dim": "#6e7089",
        "accent": "#bd93f9", "accentSoft": "#3a2d55", "green": "#50fa7b",
        "amber": "#f1fa8c", "red": "#ff5555", "cyan": "#8be9fd",
        "scrollbar": "#4a4d63", "rowHover": "#2f3242", "codeBg": "#16171e",
        "borderSoft": "#33354a", "selection": "#44475a",
        "editorBg": "#191a21", "editorLine": "#22232e", "cursor": "#f8f8f2",
        "synKeyword": "#ff79c6", "synString": "#f1fa8c", "synNumber": "#bd93f9",
        "synComment": "#6272a4", "synFunction": "#50fa7b", "synVariable": "#f8f8f2",
        "synType": "#8be9fd", "synOperator": "#ff79c6",
    }},
    {"id": "solarized", "name": "Solarized 暖", "builtin": True, "tokens": {
        **_BASE,
        "bg": "#fdf6e3", "panel": "#f6efdc", "panel2": "#eee8d5", "panel3": "#e4ddc8",
        "line": "#d6cfb8", "text": "#073642", "muted": "#586e75", "dim": "#93a1a1",
        "accent": "#268bd2", "accentSoft": "#d5e8f6", "green": "#859900",
        "amber": "#b58900", "red": "#dc322f", "cyan": "#2aa198",
        "scrollbar": "#c9c2a9", "rowHover": "#f0e9d4", "codeBg": "#fbf4e0",
        "borderSoft": "#e2dbc4", "selection": "#cfdff0",
        "editorBg": "#fdf6e3", "editorLine": "#f3ecd6", "cursor": "#073642",
        "synKeyword": "#859900", "synString": "#2aa198", "synNumber": "#d33682",
        "synComment": "#93a1a1", "synFunction": "#268bd2", "synVariable": "#073642",
        "synType": "#b58900", "synOperator": "#6c71c4",
    }},
]

COLOR_TOKENS = frozenset(TOKEN_KEYS)


def _normalize(tokens: Any) -> dict[str, str]:
    if not isinstance(tokens, dict):
        raise ApiError("INVALID_THEME", "tokens 必须是对象", 422)
    cleaned: dict[str, str] = {}
    for key, value in tokens.items():
        if key not in COLOR_TOKENS:
            continue
        text = str(value).strip()
        if not COLOR_RE.match(text):
            raise ApiError("INVALID_THEME", f"颜色值无效: {key}={text}（需要 #rgb / #rrggbb / #rrggbbaa）", 422)
        cleaned[key] = text
    return cleaned


def _custom() -> list[dict[str, Any]]:
    return list(config.load_settings().get("themes_custom") or [])


def _all() -> list[dict[str, Any]]:
    return PRESETS + _custom()


@router.get("/themes")
def list_themes() -> Any:
    settings = config.load_settings()
    active_id = settings.get("theme_active_id") or "dark"
    theme = next((t for t in _all() if t["id"] == active_id), PRESETS[0])
    tokens = {**theme["tokens"], **(settings.get("theme_override") or {})}
    return {"presets": PRESETS, "custom": _custom(), "active_id": active_id,
            "tokens": tokens, "token_keys": list(TOKEN_KEYS)}


@router.put("/themes/active")
def set_active_theme(payload: dict[str, Any] = Body(...)) -> Any:
    theme_id = payload.get("id")
    if not theme_id:
        raise ApiError("VALIDATION_ERROR", "需要主题 id", 422)
    if theme_id not in {t["id"] for t in _all()}:
        raise ApiError("NOT_FOUND", "主题不存在", 404, theme_id)
    override = _normalize(payload["tokens"]) if "tokens" in payload else {}
    config.save_settings({"theme_active_id": theme_id, "theme_override": override})
    return {"active_id": theme_id, "tokens": _merged_tokens(theme_id, override)}


def _merged_tokens(theme_id: str, override: dict[str, str]) -> dict[str, str]:
    theme = next((t for t in _all() if t["id"] == theme_id), PRESETS[0])
    return {**theme["tokens"], **override}


@router.put("/themes/tokens")
def set_theme_tokens(payload: dict[str, Any] = Body(...)) -> Any:
    """Live editor preview: persist raw token overrides without naming a theme."""
    override = _normalize(payload.get("tokens") or {})
    active_id = config.load_settings().get("theme_active_id") or "dark"
    config.save_settings({"theme_override": override})
    return {"active_id": active_id, "tokens": _merged_tokens(active_id, override)}


@router.post("/themes")
def save_theme(payload: dict[str, Any] = Body(...)) -> Any:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError("VALIDATION_ERROR", "主题需要 name", 422)
    tokens = _normalize(payload.get("tokens") or {})
    if not tokens:
        raise ApiError("VALIDATION_ERROR", "主题 tokens 为空", 422)
    theme_id = payload.get("id")
    customs = _custom()
    if theme_id:
        existing = next((t for t in customs if t["id"] == theme_id), None)
        if existing is None:
            raise ApiError("NOT_FOUND", "自定义主题不存在", 404, theme_id)
        existing.update({"name": name, "tokens": {**existing["tokens"], **tokens}})
        theme = existing
    else:
        theme = {"id": f"custom-{uid()[:8]}", "name": name, "builtin": False,
                 "tokens": {**PRESETS[0]["tokens"], **tokens}}
        customs.append(theme)
    config.save_settings({"themes_custom": customs,
                          "theme_active_id": theme["id"], "theme_override": {}})
    return theme


@router.delete("/themes/{id}")
def delete_theme(id: str) -> Any:
    if any(p["id"] == id for p in PRESETS):
        raise ApiError("VALIDATION_ERROR", "内置主题不可删除", 422)
    customs = [t for t in _custom() if t["id"] != id]
    if len(customs) == len(_custom()):
        raise ApiError("NOT_FOUND", "自定义主题不存在", 404, id)
    settings = {"themes_custom": customs}
    if config.load_settings().get("theme_active_id") == id:
        settings.update({"theme_active_id": "dark", "theme_override": {}})
    config.save_settings(settings)
    return {"id": id, "deleted": True}


@router.post("/themes/import")
def import_theme(payload: dict[str, Any] = Body(...)) -> Any:
    raw = payload.get("theme") if isinstance(payload.get("theme"), dict) else payload
    name = str(raw.get("name") or "导入主题").strip()
    tokens = _normalize(raw.get("tokens") or {})
    if not tokens:
        raise ApiError("INVALID_THEME", "导入的主题没有有效颜色 token", 422)
    theme = {"id": f"custom-{uid()[:8]}", "name": name, "builtin": False,
             "tokens": {**PRESETS[0]["tokens"], **tokens}}
    customs = _custom()
    customs.append(theme)
    config.save_settings({"themes_custom": customs, "theme_active_id": theme["id"],
                          "theme_override": {}})
    return theme


@router.get("/themes/{id}/export")
def export_theme(id: str) -> Any:
    theme = next((t for t in _all() if t["id"] == id), None)
    if theme is None:
        raise ApiError("NOT_FOUND", "主题不存在", 404, id)
    return JSONResponse(content={"format": "aixian-theme/1", "name": theme["name"],
                                 "tokens": theme["tokens"]},
                        headers={"Content-Disposition": f'attachment; filename="{id}.json"'})
