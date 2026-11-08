"""Audit trail. Every mutation is recorded with actor/action/entity/detail."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .events import hub
from .models import AuditEvent
from .util import as_dict, now


def record(
    session: Session,
    action: str,
    entity_type: str = "",
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
    project_id: str | None = None,
    actor: str = "local",
) -> AuditEvent:
    event = AuditEvent(
        project_id=project_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail_json=detail or {},
        at=now(),
    )
    session.add(event)
    session.commit()
    hub.emit("audit.created", as_dict(event), project_id)
    return event
