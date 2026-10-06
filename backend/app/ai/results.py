"""Matching an agent's MCP writes to its run (contract-phase6 section 3.4), and the
``tool_called`` / ``result_recorded`` progress events of its calls.

Results are attached by the server, never by parsing agent text: in the write tool's
transaction, after it locked the project and the idea and :func:`app.ai.scope.lock_run`
locked the run the call names (lock order project, idea, run), the evaluation, suggestion or note
id goes on the run. The events are written by :func:`record_call` **after** the tool's
transaction has ended (committed or rolled back), in a short transaction of their own:
writing them while the tool's transaction holds the run row would deadlock the call on
itself, and this way "Saved its evaluation" comes before "Evaluation submitted". The
dispatcher awaits them before answering the agent, so they also come before the run's
final event.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import scope
from app.ai.transitions import RESULT_MESSAGES, add_event
from app.db import session_scope
from app.domain.principal import Principal
from app.models.ai import AiRun
from app.models.enums import AiRunEventType, AiRunKind, AiRunStatus
from app.schemas.ai import tool_event_message

__all__ = ["NO_RUN_EVENT_TOOLS", "attach", "record_call"]

logger = logging.getLogger("soundings.ai")

NO_RUN_EVENT_TOOLS: Final = frozenset({"list_projects", "search_ideas"})
"""Tools that name no single idea: they add no ``tool_called`` event."""


async def attach(
    db: AsyncSession,
    run: AiRun,
    *,
    evaluation_id: UUID | None = None,
    suggestion_id: UUID | None = None,
) -> bool:
    """Put the result on ``run`` (locked by :func:`~app.ai.scope.lock_run`) while it is
    still open: ``running`` and not cancel-requested. ``False`` when it isn't."""
    values: dict[str, Any] = {}
    if evaluation_id is not None:
        values["evaluation_id"] = evaluation_id
    if suggestion_id is not None:
        values["suggestion_id"] = suggestion_id
    if not values:
        raise ValueError("attach a result")
    attached = await db.scalar(
        update(AiRun)
        .where(
            AiRun.id == run.id,
            AiRun.status == AiRunStatus.RUNNING,
            AiRun.cancel_requested_at.is_(None),
        )
        .values(**values)
        .returning(AiRun.id)
        .execution_options(synchronize_session=False)
    )
    return attached is not None


async def record_call(
    app: Any,
    principal: Principal,
    *,
    tool: str,
    run_id: UUID | None,
    error_code: str | None,
    recorded: Sequence[tuple[UUID, AiRunKind]] = (),
) -> None:
    """After an agent's tool call: ``tool_called`` (Soundings' sentence for the tool, with
    the error code when it failed) on the run the call named, when the call was about that
    run's idea (``run_id``, from :attr:`app.mcp.tools.ToolContext.event_run`), then
    ``result_recorded`` on each run the call attached a result to. Nothing for people,
    unknown tools, ``list_projects`` / ``search_ideas``, or a call about anything else.
    Never fails the call (logged)."""
    if not scope.is_agent(principal) or tool in NO_RUN_EVENT_TOOLS:
        return
    try:
        message = tool_event_message(tool, error_code)
    except ValueError:
        message = tool_event_message(tool)
    if run_id is None:
        message = None
    if message is None and not recorded:
        return
    try:
        async with session_scope(app.state.sessionmaker) as db:
            if message is not None and run_id is not None:
                await add_event(db, run_id, AiRunEventType.TOOL_CALLED, message)
            for recorded_id, kind in recorded:
                await add_event(
                    db, recorded_id, AiRunEventType.RESULT_RECORDED, RESULT_MESSAGES[kind]
                )
    except Exception:  # pragma: no cover - progress events must never fail a tool call
        logger.exception("ai run events failed", extra={"tool": tool})
