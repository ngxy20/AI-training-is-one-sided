"""Local users, project membership and role-based write guards (P2-b).

Backward compatible: a project with no members keeps the original local-only
owner semantics. As soon as members are configured, writes are enforced.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from .. import config
from ..database import registry_session
from ..errors import ApiError
from ..models import ProjectMember, User
from ..util import as_dict, uid

ROLES = ("owner", "admin", "reviewer", "annotator", "viewer")
ROLE_LABELS = {
    "owner": "项目负责人（全部权限）",
    "admin": "管理员（全部权限）",
    "reviewer": "审核者（标注 + 审核）",
    "annotator": "标注员（仅提交标注）",
    "viewer": "只读（查看）",
}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
WRITE_ROLES = ("owner", "admin")
ANNOTATION_SUBMIT = re.compile(r"/annotation-tasks/[^/]+/annotations/?$")
ANNOTATION_REVIEW = re.compile(r"/annotation-tasks/[^/]+/review/?$")


def local_user(session) -> User:
    row = session.scalar(select(User).where(User.username == "local"))
    if row is None:
        row = User(id=uid(), username="local", display_name="本地负责人",
                   color="#6c8cff", global_role="owner", active=1)
        session.add(row)
        session.commit()
    return row


def current_user(session) -> User:
    user_id = config.load_settings().get("active_user_id")
    row = session.get(User, user_id) if user_id else None
    return row or local_user(session)


def actor_name() -> str:
    with registry_session() as session:
        return current_user(session).display_name


def effective_role(session, project_id: str, user: User | None = None) -> str:
    user = user or current_user(session)
    members = session.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id)).scalars().all()
    if not members:
        return "owner"  # legacy project: no access control configured yet
    membership = next((m for m in members if m.user_id == user.id), None)
    if membership:
        return membership.role
    return user.global_role if user.global_role in WRITE_ROLES else "viewer"


def enforce(pid: str | None, method: str, path: str) -> None:
    """Deny mutations that the current identity is not allowed to perform."""
    if method not in MUTATING:
        return
    if not pid:
        # Creating a project is a global capability, not a project one.
        if path.rstrip("/").endswith("/projects"):
            with registry_session() as session:
                user = current_user(session)
                if user.global_role not in WRITE_ROLES:
                    raise ApiError("FORBIDDEN",
                                   f"当前身份「{user.display_name}」无权创建项目", 403)
        return
    if path.rstrip("/").endswith("/open"):
        return  # opening a project is a read-like action
    with registry_session() as session:
        user = current_user(session)
        role = effective_role(session, pid, user)
        actor = user.display_name
    if role in WRITE_ROLES:
        return
    allowed = False
    if role == "annotator" and method == "POST" and ANNOTATION_SUBMIT.search(path):
        allowed = True
    elif role == "reviewer" and (ANNOTATION_SUBMIT.search(path) or ANNOTATION_REVIEW.search(path)):
        allowed = True
    if not allowed:
        raise ApiError("FORBIDDEN",
                       f"当前身份「{actor}」的角色为 {role}（{ROLE_LABELS.get(role, role)}），无权执行该操作",
                       403, {"role": role, "method": method, "path": path})


def list_users() -> list[dict[str, Any]]:
    with registry_session() as session:
        local_user(session)
        rows = session.execute(select(User).order_by(User.created_at)).scalars().all()
        return [as_dict(row) for row in rows]


def list_members(project_id: str) -> list[dict[str, Any]]:
    with registry_session() as session:
        local_user(session)
        members = session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project_id)).scalars().all()
        result = []
        for member in members:
            user = session.get(User, member.user_id)
            result.append({**as_dict(member),
                           "username": user.username if user else member.user_id,
                           "display_name": user.display_name if user else member.user_id,
                           "color": user.color if user else "#6c8cff"})
        return result


def set_member(project_id: str, user_id: str, role: str, invited_by: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ApiError("VALIDATION_ERROR", f"角色必须是 {ROLES}", 422)
    with registry_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError("NOT_FOUND", "用户不存在", 404, user_id)
        member = session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
        if member is None:
            member = ProjectMember(id=uid(), project_id=project_id, user_id=user_id,
                                   role=role, invited_by=invited_by)
            session.add(member)
        else:
            member.role = role
        session.commit()
        return {**as_dict(member), "username": user.username, "display_name": user.display_name}


def remove_member(project_id: str, user_id: str) -> bool:
    with registry_session() as session:
        member = session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
        if member is None:
            return False
        session.delete(member)
        session.commit()
        return True
