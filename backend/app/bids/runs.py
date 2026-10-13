"""Cancelling a call's AI assess runs when what they assess changes (contract-phase10
section 9.1, review S8): rejecting a bid, marking one of its documents pricing, changing
the call's template copy, the award and cancelling the call. Queued runs end
``cancelled`` at once; running ones get a cancel request (the worker sends
``tasks/cancel``). The caller holds project -> idea -> call (-> bid) already, so the run
comes last in the lock order."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.transitions import cancel
from app.domain.principal import Principal
from app.models.ai import AiRun
from app.models.bid import BidCall
from app.models.enums import AiRunKind, AiRunStatus

__all__ = ["cancel_assess_runs"]

_ACTIVE = (AiRunStatus.QUEUED, AiRunStatus.RUNNING)


async def cancel_assess_runs(
    db: AsyncSession, principal: Principal | None, call: BidCall, *, bid_id: UUID | None = None
) -> int:
    """Cancel the call's (or one bid's) active assess runs; how many were active."""
    statement = (
        select(AiRun.id)
        .where(
            AiRun.bid_call_id == call.id,
            AiRun.kind == AiRunKind.ASSESS_BID,
            AiRun.status.in_(_ACTIVE),
        )
        .order_by(AiRun.created_at, AiRun.id)
    )
    if bid_id is not None:
        statement = statement.where(AiRun.bid_id == bid_id)
    cancelled = 0
    for run_id in list(await db.scalars(statement)):
        status = await cancel(
            db, run_id, by_id=principal.user_id if principal is not None else None
        )
        cancelled += int(status is not None)
    return cancelled
