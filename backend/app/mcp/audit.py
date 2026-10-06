"""``mcp.call`` audit entries (contract-phase5 section 3.6).

One entry per ``tools/call``, whatever the outcome, written by the dispatcher
(:mod:`app.mcp.dispatcher`): in the tool's own transaction when the call commits,
otherwise in a short transaction of its own after the rollback, so denials and failures
are kept. Requests the guard refuses before the SDK, whatever their JSON-RPC method
(c15: a key without the ``mcp`` scope; the key's request budget), get an entry without
a tool, at most one per key and refusal a minute (:mod:`app.mcp.guard`). Entries carry
the tool, its rule, the decision and the error code, plus ``auth`` and ``api_key_id``
(added by :func:`app.services.audit.record`); never the arguments (queries, idea text
and comments may hold personal data).

The hourly cleanup deletes entries older than :data:`MCP_AUDIT_RETENTION`
(:func:`delete_expired_calls`); what a call changed keeps its own entries for good.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.domain.idea_keys import IdeaKey, parse_idea_ref
from app.domain.principal import Principal
from app.models.activity import AuditLog
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.audit import AuditAction
from app.schemas.mcp import MCP_AUDIT_RETENTION
from app.services import audit

__all__ = [
    "MCP_CALL",
    "AuditTarget",
    "Decision",
    "delete_expired_calls",
    "record_call",
    "record_call_separately",
    "record_door_refusal",
]

logger = logging.getLogger(__name__)

MCP_CALL: Final = AuditAction.MCP_CALL.value
Decision = Literal["allow", "deny"]


@dataclass(slots=True)
class AuditTarget:
    """What a call was about: an idea (with its project) or a project; nothing for lists.

    Tools fill it as soon as they have found the thing. When a call fails before that
    (an idea the key may not see, say), :meth:`resolve` finds it from the arguments,
    without any permission check: the entry is for platform admins, and names the idea
    "when it exists (also for denials)"."""

    target_type: Literal["idea", "project"] | None = None
    target_id: UUID | None = None
    project_id: UUID | None = None

    def idea(self, idea_id: UUID, project_id: UUID) -> None:
        self.target_type, self.target_id, self.project_id = "idea", idea_id, project_id

    def project(self, project_id: UUID) -> None:
        self.target_type, self.target_id, self.project_id = "project", project_id, project_id

    async def resolve(self, db: AsyncSession, arguments: object) -> None:
        if self.target_type is not None or not isinstance(arguments, dict):
            return
        ref, slug = arguments.get("idea"), arguments.get("project")
        if isinstance(ref, str) and len(ref) <= 36:
            try:
                parsed = parse_idea_ref(ref)
            except ValueError:
                parsed = None
            if parsed is not None:
                statement = select(Idea.id, Idea.project_id)
                if isinstance(parsed, IdeaKey):
                    statement = statement.join(Project, Project.id == Idea.project_id).where(
                        Project.key == parsed.project_key, Idea.number == parsed.number
                    )
                else:
                    statement = statement.where(Idea.id == parsed)
                row = (await db.execute(statement)).first()
                if row is not None:
                    self.idea(row[0], row[1])
                    return
        if isinstance(slug, str) and len(slug) <= 48:
            project_id = await db.scalar(select(Project.id).where(Project.slug == slug))
            if project_id is not None:
                self.project(project_id)


async def record_call(
    db: AsyncSession,
    principal: Principal,
    *,
    tool: str | None,
    rule: str | None,
    decision: Decision,
    code: str | None,
    target: AuditTarget | None = None,
) -> None:
    """Add the ``mcp.call`` entry to ``db``'s unit of work."""
    target = target or AuditTarget()
    await audit.record(
        db,
        MCP_CALL,
        actor=principal,
        target_type=target.target_type,
        target_id=target.target_id,
        project_id=target.project_id,
        details={"tool": tool, "rule": rule, "decision": decision, "code": code},
    )


async def record_call_separately(
    app: Any,
    principal: Principal,
    *,
    tool: str | None,
    rule: str | None,
    decision: Decision,
    code: str | None,
    target: AuditTarget | None = None,
    arguments: object = None,
) -> None:
    """Write the entry in a short transaction of its own (after the call's rollback, or
    for a call the dispatcher never ran). A failure here is logged, never raised: the
    client still gets its answer."""
    target = target or AuditTarget()
    try:
        async with session_scope(app.state.sessionmaker) as db:
            await target.resolve(db, arguments)
            await record_call(
                db, principal, tool=tool, rule=rule, decision=decision, code=code, target=target
            )
    except Exception:
        logger.exception("mcp call audit failed", extra={"tool": tool, "code": code})


async def record_door_refusal(
    app: Any, principal: Principal, *, rule: str | None, code: str
) -> None:
    """A request the guard refused before the SDK, whatever its JSON-RPC method: c15 (a
    key without the ``mcp`` scope: ``rule`` ``mcp.connect``, ``insufficient_scope``) or
    the key's request budget (no rule, ``too_many_attempts``). One entry, no tool; the
    guard calls this at most once per key and code a minute."""
    await record_call_separately(app, principal, tool=None, rule=rule, decision="deny", code=code)


async def delete_expired_calls(db: AsyncSession, now: datetime) -> None:
    """The hourly cleanup: ``mcp.call`` entries older than 90 days (on
    ``ix_audit_log_action_created_at``). Every other entry is kept."""
    await db.execute(
        delete(AuditLog).where(
            AuditLog.action == MCP_CALL, AuditLog.created_at < now - MCP_AUDIT_RETENTION
        )
    )
