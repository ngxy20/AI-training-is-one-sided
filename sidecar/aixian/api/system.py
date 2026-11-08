"""Health, jobs, logs, plugins, audit, settings, workspace files, commands."""
from __future__ import annotations

from typing import Any

from fastapi import Body, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from .. import __version__, config, workspace
from ..audit import record
from ..database import project_session, registry_session
from ..errors import ApiError
from ..events import hub
from ..jobs import job_logs, jobs
from ..models import AuditEvent, Job, Plugin
from ..plugin_loader import registry
from ..plugin_sdk import EXTENSION_POINTS, HIGH_RISK_PERMISSIONS, JobContext as PluginJobContext, PERMISSIONS
from ..util import as_dict, paginate, uid
from .common import ProjectId, entity_project, get_or_404, make_router, ok

router = make_router()


@router.get("/health")
def health() -> Any:
    return {
        "name": "AI Training Studio",
        "name_zh": "AI 训练工作台",
        "version": __version__,
        "sdk_version": "0.1",
        "status": "ok",
        "running_jobs": jobs.running(),
        "app_home": str(config.APP_HOME),
    }


@router.get("/jobs")
def list_jobs(pid: str | None = None, page: int = 1, size: int = 50, status: str | None = None) -> Any:
    target = pid or config.load_settings().get("active_project_id")
    if not target:
        return {"items": [], "page": page, "size": size, "total": 0}
    with project_session(target) as session:
        query = select(Job).where(Job.project_id == target)
        if status:
            query = query.where(Job.status == status)
        return paginate(session, query.order_by(Job.created_at.desc()), page, size)


@router.get("/jobs/{id}")
def get_job(id: str) -> Any:
    pid = entity_project(Job, id)
    with project_session(pid) as session:
        return as_dict(get_or_404(session, Job, id, "任务"))


@router.get("/jobs/{id}/logs")
def get_job_logs(id: str, tail: int = Query(2000, ge=1, le=20000)) -> Any:
    pid = entity_project(Job, id)
    with project_session(pid) as session:
        data = as_dict(get_or_404(session, Job, id, "任务"))
    return {"job": data, "lines": job_logs(pid, id, tail)}


@router.post("/jobs/{id}/cancel")
def cancel_job(id: str) -> Any:
    pid = entity_project(Job, id)
    cancelled = jobs.cancel(id)
    if not cancelled:
        with project_session(pid) as session:
            job = session.get(Job, id)
            if job and job.status not in ("succeeded", "failed", "cancelled"):
                job.status = "cancelled"
                session.commit()
    with project_session(pid) as session:
        record(session, "job.cancel", "job", id, {"cancelled": cancelled}, pid)
    return {"job_id": id, "cancelled": cancelled}


@router.get("/plugins")
def list_plugins(pid: str | None = None) -> Any:
    target = pid or config.load_settings().get("active_project_id")
    enabled: dict[str, Plugin] = {}
    if target:
        with project_session(target) as session:
            enabled = {row.plugin_id: row for row in session.execute(select(Plugin)).scalars().all()}
    items = []
    for plugin in registry.discover():
        row = enabled.get(plugin.id)
        items.append({**plugin.summary(bool(row and row.enabled)),
                      "permission_confirmed": bool(row and row.permission_confirmed)})
    return {"items": items, "extension_points": list(EXTENSION_POINTS),
            "permissions": list(PERMISSIONS), "high_risk_permissions": sorted(HIGH_RISK_PERMISSIONS)}


@router.post("/plugins/scan")
def scan_plugins(pid: str | None = Query(None)) -> Any:
    target = pid or config.load_settings().get("active_project_id")
    if not target:
        raise ApiError("NO_ACTIVE_PROJECT", "请先打开一个项目", 400)
    discovered = registry.discover()
    with project_session(target) as session:
        existing = {row.plugin_id: row for row in session.execute(select(Plugin)).scalars().all()}
        for plugin in discovered:
            row = existing.get(plugin.id)
            if row is None:
                row = Plugin(id=uid(), project_id=target, plugin_id=plugin.id, name=plugin.name,
                             version=plugin.version, manifest_json=plugin.manifest,
                             permissions_json=plugin.permissions, enabled=0,
                             source_path=str(plugin.path or ""), permission_confirmed=0)
                session.add(row)
            else:
                row.name = plugin.name
                row.version = plugin.version
                row.manifest_json = plugin.manifest
                row.permissions_json = plugin.permissions
                row.source_path = str(plugin.path or "")
        session.commit()
        record(session, "plugin.scan", "plugin", "", {"count": len(discovered)}, target)
    return {"scanned": len(discovered), "items": [p.summary() for p in discovered]}


@router.post("/plugins/{id}/enable")
def enable_plugin(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    target = payload.get("pid") or config.load_settings().get("active_project_id")
    if not target:
        raise ApiError("NO_ACTIVE_PROJECT", "请先打开一个项目", 400)
    enabled = bool(payload.get("enabled", True))
    plugin = next((p for p in registry.discover() if p.id == id), None)
    if plugin is None:
        raise ApiError("PLUGIN_NOT_FOUND", f"插件未发现: {id}", 404)
    if plugin.problems:
        raise ApiError("PLUGIN_INCOMPATIBLE", "插件不兼容，无法启用", 400, plugin.problems)
    high_risk = sorted(HIGH_RISK_PERMISSIONS.intersection(plugin.permissions))
    if enabled and high_risk and config.load_settings().get("plugin_confirm_high_risk") and not payload.get("confirm"):
        raise ApiError("PERMISSION_CONFIRMATION_REQUIRED", "启用高风险权限需要二次确认", 428,
                       {"permissions": high_risk, "plugin_id": id})
    with project_session(target) as session:
        row = session.execute(select(Plugin).where(Plugin.plugin_id == id)).scalars().first()
        if row is None:
            row = Plugin(id=uid(), project_id=target, plugin_id=id, name=plugin.name,
                         version=plugin.version, manifest_json=plugin.manifest,
                         permissions_json=plugin.permissions, source_path=str(plugin.path or ""))
            session.add(row)
        row.enabled = 1 if enabled else 0
        row.permission_confirmed = 1 if payload.get("confirm") else row.permission_confirmed
        session.commit()
        record(session, "plugin.enable" if enabled else "plugin.disable", "plugin", row.id,
               {"plugin_id": id, "permissions": plugin.permissions, "confirmed": bool(payload.get("confirm"))}, target)
        return {**plugin.summary(enabled), "permission_confirmed": bool(row.permission_confirmed)}


@router.get("/projects/{pid}/plugins")
def project_plugins(pid: str = ProjectId) -> Any:
    with project_session(pid) as session:
        return [as_dict(row) for row in session.execute(select(Plugin)).scalars().all()]


@router.get("/audit-events")
def list_audit_events(pid: str | None = None, page: int = 1, size: int = 50,
                      action: str | None = None, entity_type: str | None = None) -> Any:
    target = pid or config.load_settings().get("active_project_id")
    if not target:
        return {"items": [], "page": page, "size": size, "total": 0}
    with project_session(target) as session:
        query = select(AuditEvent)
        if action:
            query = query.where(AuditEvent.action.like(f"%{action}%"))
        if entity_type:
            query = query.where(AuditEvent.entity_type == entity_type)
        return paginate(session, query.order_by(AuditEvent.at.desc()), page, size)


@router.get("/settings")
def get_settings() -> Any:
    return config.load_settings()


@router.patch("/settings")
def update_settings(payload: dict[str, Any] = Body(...)) -> Any:
    return config.save_settings(payload)


@router.get("/files")
def workspace_file(pid: str, path: str, download: bool = False) -> Any:
    target = workspace.resolve(pid, path)
    if not target.exists() or not target.is_file():
        raise ApiError("FILE_NOT_FOUND", "工作区文件不存在", 404, path)
    return FileResponse(str(target), filename=target.name if download else None)


@router.post("/terminal/exec")
def terminal_exec(payload: dict[str, Any] = Body(...)) -> Any:
    """Local IDE terminal. CWD is always confined to the active project's workspace."""
    import subprocess

    if not config.load_settings().get("enable_local_terminal"):
        raise ApiError(
            "TERMINAL_DISABLED",
            "本地终端默认关闭（可执行任意命令）。如需使用，请在「设置 → 全局设置」把 "
            "enable_local_terminal 设为 true，并仅在可信单机上运行。",
            403,
        )
    pid = payload.get("pid") or config.load_settings().get("active_project_id")
    if not pid:
        raise ApiError("NO_ACTIVE_PROJECT", "请先打开一个项目", 400)
    command = str(payload.get("command") or "").strip()
    if not command or len(command) > 2000:
        raise ApiError("VALIDATION_ERROR", "命令为空或过长", 422)
    root = workspace.ensure_workspace(pid)
    sub = str(payload.get("cwd") or "").strip()
    cwd = workspace.resolve(pid, sub) if sub else root
    if not cwd.is_dir():
        cwd = root
    try:
        completed = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=45)
        output = (completed.stdout or "") + (completed.stderr or "")
        return {"command": command, "cwd": str(cwd), "exit_code": completed.returncode,
                "output": output[-20000:], "truncated": len(output) > 20000}
    except subprocess.TimeoutExpired as exc:
        raise ApiError("TERMINAL_TIMEOUT", "命令执行超时（45s）", 408, str(exc)) from exc


@router.get("/events/recent")
def recent_events() -> Any:
    return list(hub.recent)


@router.get("/commands")
def plugin_commands() -> Any:
    return {"items": [
        {"name": ext.get("label") or plugin.id, "plugin_id": plugin.id, "extension": ext}
        for plugin, ext, _ in registry.implementations("command")
    ]}


@router.post("/commands/{name}")
def run_plugin_command(name: str, payload: dict[str, Any] = Body(default={})) -> Any:
    for plugin, _, impl in registry.implementations("command"):
        if plugin.id == name or name.endswith(plugin.id):
            context = PluginJobContext(job_id=uid(), project_id=payload.get("pid", ""),
                                       workdir=str(config.APP_HOME), params=payload, log=lambda _: None)
            return impl.run(payload, context)
    raise ApiError("COMMAND_NOT_FOUND", f"未找到插件命令: {name}", 404)
