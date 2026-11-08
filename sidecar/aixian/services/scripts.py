"""Versioned collection scripts (Python / SQL) with parameter injection."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .. import workspace
from ..database import project_session
from ..errors import ApiError
from ..models import DataSource, Dataset, Script
from ..util import as_dict, write_json
from . import datasets, datasources
from .common import get_or_create_dataset


def script_path(project_id: str, script: Script) -> Path:
    return workspace.resolve(project_id, script.path)


def read_content(project_id: str, script: Script) -> str:
    path = script_path(project_id, script)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def save_content(project_id: str, script: Script, content: str) -> str:
    root = workspace.ensure_workspace(project_id)
    ext = "sql" if script.type == "sql" else "py"
    target = root / "scripts" / f"{script.id}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return workspace.relative(project_id, target)


def snapshot_version(project_id: str, script: Script, content: str) -> str:
    root = workspace.ensure_workspace(project_id)
    ext = "sql" if script.type == "sql" else "py"
    target = root / "scripts" / ".versions" / script.id / f"v{script.version}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return workspace.relative(project_id, target)


def list_versions(project_id: str, script_id: str) -> list[dict[str, Any]]:
    folder = workspace.resolve(project_id, Path("scripts") / ".versions" / script_id)
    if not folder.exists():
        return []
    return [{"version": i, "name": p.name, "path": workspace.relative(project_id, p)}
            for i, p in enumerate(sorted(folder.iterdir()), 1)]


async def _exec_collect(ctx, command: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, list[str]]:
    process = await asyncio.create_subprocess_exec(
        *command, cwd=str(cwd), env={**os.environ, **env},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    captured: list[str] = []
    async for raw in process.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        captured.append(line)
        ctx.log(line)
    return await process.wait(), captured


async def run_worker(project_id: str, script_id: str, params: dict[str, Any], ctx) -> dict[str, Any]:
    with project_session(project_id) as session:
        script = session.get(Script, script_id)
        if script is None:
            raise ApiError("NOT_FOUND", "脚本不存在", 404, script_id)
        content = read_content(project_id, script)
        script_name, script_type = script.name, script.type
        code_version = __import__("hashlib").sha256(content.encode("utf-8")).hexdigest()
    root = workspace.ensure_workspace(project_id)
    job_dir = root / "tmp" / ctx.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    params_path = write_json(job_dir / "params.json", params)
    output_path = job_dir / "output.jsonl"
    env = {
        "AIXIAN_PROJECT_ID": project_id,
        "AIXIAN_JOB_ID": ctx.job_id,
        "AIXIAN_PARAMS": str(params_path),
        "AIXIAN_OUTPUT": str(output_path),
        "AIXIAN_WORKSPACE": str(root),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    ctx.log(f"[aixian] 运行收集脚本 {script_name} ({script_type}) code_version={code_version[:12]}")

    if script_type == "sql":
        datasource_id = params.get("datasource_id")
        if not datasource_id:
            raise ApiError("VALIDATION_ERROR", "SQL 脚本需要参数 datasource_id", 422)
        with project_session(project_id) as session:
            source = session.get(DataSource, datasource_id)
            if source is None:
                raise ApiError("NOT_FOUND", "数据源不存在", 404, datasource_id)
            result = datasources.query(source, params.get("sql") or content, int(params.get("limit", 1000)))
        rows = result["rows"]
    else:
        target = workspace.resolve(project_id, Path("scripts") / f"{script_id}.py")
        if not target.exists():
            raise ApiError("FILE_NOT_FOUND", "脚本文件丢失", 404, str(target))
        exit_code, captured = await _exec_collect(ctx, [sys.executable, str(target), "--params", str(params_path)], job_dir, env)
        if exit_code != 0:
            raise ApiError("SCRIPT_FAILED", f"脚本退出码 {exit_code}", 500, captured[-20:])
        if output_path.exists():
            rows = datasets.read_records(output_path, "jsonl")
        else:
            rows = []
            for line in captured:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
                except ValueError:
                    continue
            ctx.log(f"[aixian] 脚本未写 AIXIAN_OUTPUT，从 stdout 解析到 {len(rows)} 条记录")
    mapping = params.get("field_mapping")
    rows = datasets.apply_field_mapping(rows, mapping)
    name = params.get("dataset_name") or f"{script_name} 产物"
    with project_session(project_id) as session:
        dataset = get_or_create_dataset(session, project_id, name, params.get("dataset_id"), f"script:{script_type}")
        version = datasets.create_version(
            session, project_id, dataset, rows,
            changelog=f"由脚本 {script_name} (code_version={code_version[:12]}) 生成",
            created_by_job_id=ctx.job_id, source=f"script:{script_type}",
        )
        return {"dataset_id": dataset.id, "dataset_version_id": version.id,
                "record_count": version.record_count, "code_version": code_version}
