"""Global configuration. All application state lives under AIXIAN_HOME (local-first)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import __version__

APP_NAME = "AI Training Studio"
APP_NAME_ZH = "AI 训练工作台"
SDK_VERSION = "0.1"

APP_HOME = Path(os.environ.get("AIXIAN_HOME", str(Path.home() / ".aixian"))).resolve()
PROJECTS_DIR = APP_HOME / "projects"
REGISTRY_DB = APP_HOME / "registry.db"
SETTINGS_FILE = APP_HOME / "settings.json"
EXTERNAL_PLUGINS_DIR = APP_HOME / "plugins"
REPO_ROOT = Path(__file__).resolve().parents[2]
# A frozen (PyInstaller) sidecar cannot derive the layout from __file__, so the
# Electron main process passes the unpacked plugin directory explicitly.
BUNDLED_PLUGINS_DIR = Path(os.environ.get(
    "AIXIAN_BUNDLED_PLUGINS", str(REPO_ROOT / "plugins" / "examples")))
WEB_DIST = Path(os.environ.get("AIXIAN_WEB_DIST", str(REPO_ROOT / "desktop" / "dist")))
# Optional legacy TrainFlow data location for `aixian.migration`. The legacy
# prototype is NOT part of this repository; point AIXIAN_LEGACY_ROOT at a
# directory containing data/DS-*.json when you actually need to import it.
_FALLBACK_LEGACY = REPO_ROOT / "原型"
LEGACY_ROOT = Path(os.environ.get("AIXIAN_LEGACY_ROOT", str(
    _FALLBACK_LEGACY if (_FALLBACK_LEGACY / "data").is_dir() else REPO_ROOT)))

HOST = "127.0.0.1"
PORT = int(os.environ.get("AIXIAN_PORT", "8756"))
API_PREFIX = "/api/v1"

DEFAULT_SETTINGS: dict[str, Any] = {
    "active_project_id": None,
    "theme": "dark",
    "locale": "zh-CN",
    "log_follow": True,
    "max_query_rows": 500,
    "plugin_confirm_high_risk": True,
    "telemetry": False,
    # Local terminal can execute arbitrary shell commands; disabled by default
    # for invited trial builds. Enable explicitly in Settings -> global settings.
    "enable_local_terminal": False,
}


def bootstrap() -> None:
    for path in (APP_HOME, PROJECTS_DIR, EXTERNAL_PLUGINS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_FILE.exists():
        save_settings(dict(DEFAULT_SETTINGS))


def load_settings() -> dict[str, Any]:
    bootstrap()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**DEFAULT_SETTINGS, **data}


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    merged = {**load_settings_cold(), **data}
    SETTINGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def load_settings_cold() -> dict[str, Any]:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def app_version() -> str:
    return __version__
