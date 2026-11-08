"""Per-project workspace layout + aixian:// URI scheme + path traversal guard."""
from __future__ import annotations

import re
from pathlib import Path

from . import config
from .errors import ApiError

SUBDIRS = (
    "datasets", "scripts", "runs", "reports", "logs", "plugins",
    "checkpoints", "exports", "annotations", "tmp",
)

_URI_RE = re.compile(r"^aixian://project/([^/]+)/([^/]+)/([^/]+)$")


def workspace_path(project_id: str) -> Path:
    return (config.PROJECTS_DIR / project_id).resolve()


def ensure_workspace(project_id: str) -> Path:
    root = workspace_path(project_id)
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def resolve(project_id: str, relative: str | Path) -> Path:
    root = workspace_path(project_id)
    target = (root / str(relative)).resolve()
    if target != root and not target.is_relative_to(root):
        raise ApiError("PATH_ESCAPE", "路径越出项目工作区", 403, str(relative))
    return target


def relative(project_id: str, absolute: str | Path) -> str:
    return Path(absolute).resolve().relative_to(workspace_path(project_id)).as_posix()


def uri(project_id: str, kind: str, ident: str) -> str:
    return f"aixian://project/{project_id}/{kind}/{ident}"


def parse_uri(value: str) -> tuple[str, str, str]:
    match = _URI_RE.match(value or "")
    if not match:
        raise ApiError("BAD_URI", f"无效的 aixian URI: {value}", 422)
    return match.group(1), match.group(2), match.group(3)


def new_asset_path(project_id: str, folder: str, name: str) -> Path:
    root = ensure_workspace(project_id)
    target = root / folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
