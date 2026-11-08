"""Local users, role switching and per-project sharing (P2-b)."""
from __future__ import annotations

from typing import Any

from fastapi import Body
from sqlalchemy import select

from .. import config
from ..audit import record
from ..database import project_session, registry_session
from ..errors import ApiError
from ..models import Project, ProjectMember, User
from ..services import identity
from ..util import as_dict, require, uid
from .common import ProjectId, make_router

router = make_router()


@router.get("/roles")
def roles() -> Any:
    return {"items": [{"role": role, "label": label} for role, label in identity.ROLE_LABELS.items()]}


@router.get("/users")
def list_users() -> Any:
    return {"items": identity.list_users()}


@router.post("/users")
def create_user(payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "username", "display_name")
    with registry_session() as session:
        exists = session.scalar(select(User).where(User.username == data["username"]))
        if exists:
            raise ApiError("CONFLICT", "用户名已存在", 409, data["username"])
        role = data.get("global_role", "viewer")
        if role not in identity.ROLES:
            raise ApiError("VALIDATION_ERROR", f"角色必须是 {identity.ROLES}", 422)
        row = User(id=uid(), username=data["username"], display_name=data["display_name"],
                   color=data.get("color") or "#6c8cff", global_role=role, active=1)
        session.add(row)
        session.commit()
        return as_dict(row)


@router.patch("/users/{id}")
def update_user(id: str, payload: dict[str, Any] = Body(...)) -> Any:
    with registry_session() as session:
        row = session.get(User, id)
        if row is None:
            raise ApiError("NOT_FOUND", "用户不存在", 404, id)
        if payload.get("global_role") and payload["global_role"] not in identity.ROLES:
            raise ApiError("VALIDATION_ERROR", f"角色必须是 {identity.ROLES}", 422)
        for key in ("display_name", "color", "global_role", "active"):
            if key in payload:
                setattr(row, key, payload[key])
        session.commit()
        return as_dict(row)


@router.delete("/users/{id}")
def deactivate_user(id: str) -> Any:
    with registry_session() as session:
        row = session.get(User, id)
        if row is None:
            raise ApiError("NOT_FOUND", "用户不存在", 404, id)
        if row.username == "local":
            raise ApiError("VALIDATION_ERROR", "内置本地账户不可停用", 422)
        row.active = 0
        session.commit()
        return {"id": id, "active": 0}


@router.get("/me")
def me() -> Any:
    with registry_session() as session:
        user = identity.current_user(session)
        projects = session.execute(select(Project)).scalars().all()
        return {
            "user": as_dict(user),
            "projects": [{"id": p.id, "name": p.name,
                          "role": identity.effective_role(session, p.id, user)} for p in projects],
        }


@router.post("/me")
def switch_me(payload: dict[str, Any] = Body(...)) -> Any:
    user_id = payload.get("user_id")
    if not user_id:
        raise ApiError("VALIDATION_ERROR", "需要 user_id", 422)
    with registry_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError("NOT_FOUND", "用户不存在", 404, user_id)
        if not user.active:
            raise ApiError("VALIDATION_ERROR", "该用户已停用", 422)
        config.save_settings({"active_user_id": user_id})
        return {"user": as_dict(user), "active": True}


@router.get("/projects/{pid}/members")
def list_members(pid: str = ProjectId) -> Any:
    return {"items": identity.list_members(pid)}


@router.post("/projects/{pid}/members")
def add_member(pid: str = ProjectId, payload: dict[str, Any] = Body(...)) -> Any:
    data = require(payload, "user_id", "role")
    result = identity.set_member(pid, data["user_id"], data["role"], identity.actor_name())
    with project_session(pid) as session:
        record(session, "member.upsert", "project_member", data["user_id"],
               {"role": data["role"]}, pid, actor=identity.actor_name())
    return result


@router.delete("/projects/{pid}/members/{user_id}")
def delete_member(pid: str = ProjectId, user_id: str = "") -> Any:
    removed = identity.remove_member(pid, user_id)
    if not removed:
        raise ApiError("NOT_FOUND", "成员不存在", 404, user_id)
    with project_session(pid) as session:
        record(session, "member.remove", "project_member", user_id, {}, pid,
               actor=identity.actor_name())
    return {"id": user_id, "removed": True}
