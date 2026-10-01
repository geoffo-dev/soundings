"""The security audit trail (``audit_log``): sign-ins and admin changes.

Entries hold ids, rule names, enum values and field names only: no names, emails,
free text, tokens or secrets (they outlive the rows they mention and may be exported).
Written in the same transaction as the change they record.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.schemas.audit import AuditAction

__all__ = ["AUDIT_ACTIONS", "record"]

AUDIT_ACTIONS: Final = frozenset(action.value for action in AuditAction)
"""The closed set of actions: exactly :class:`app.schemas.audit.AuditAction`
(contract-phase2 section 3.11). The name says what happened, ``details.rule`` which rule
allowed it. Add a member to the enum (lead-owned contract) when a new kind of change
needs auditing."""

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def _json(value: object) -> JsonValue:
    if isinstance(value, Enum):  # before str: StrEnum values are strings too
        return _json(value.value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = [_json(item) for item in value]
        return sorted(items, key=str) if isinstance(value, set | frozenset) else items
    raise TypeError(f"cannot audit a {type(value).__name__}")


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor: Principal | UUID | None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    project_id: UUID | None = None,
    details: Mapping[str, Any] | None = None,
) -> AuditLog:
    """Append an entry. ``actor`` is the principal (its session/API key id is kept),
    a user id (sign-in, sync) or ``None`` (denied sign-ins).

    Entries for a principal also record how its session started as
    ``details.auth_method`` (``sso``, ``break_glass``, ``dev_login``), so everything
    done in a break-glass session is visible as such (contract-phase2 section 3.8).
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")
    payload: dict[str, Any] = dict(details or {})
    actor_id = actor
    if isinstance(actor, Principal):
        actor_id = actor.user_id
        payload.setdefault("auth", actor.auth)
        if actor.auth_method is not None:
            payload.setdefault("auth_method", actor.auth_method)
        if actor.api_key_id is not None:
            payload.setdefault("api_key_id", actor.api_key_id)
    entry = AuditLog(
        id=uuid4(),
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        details=_json(payload),
        created_at=utcnow(),
    )
    db.add(entry)
    return entry
