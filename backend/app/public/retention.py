"""The hourly cleanup's public-submission rules (contract-phase4 sections 3.9 and 3.13),
run after Phase 3's (:func:`app.notifications.schedule.run_schedule`). Idempotent,
indexed and batched; constants, not settings:

1. solved ALTCHA challenges past their expiry are forgotten (replay protection only
   needs them until then), and so are confirmation sends older than 24 hours (the
   per-address limit only needs them for that long);
2. ideas still held for email confirmation 3 days after they were sent are deleted
   (with their submission and emails: they never reached the team);
3. unconfirmed addresses are forgotten 3 days after the submission (address and
   opt-in cleared, the idea's submitter emails deleted; the tracking link and, Phase 11,
   the conversation with the team keep working: team messages then reach the tracking
   page only);
4. the details of submitters whose idea is closed and has had no activity for 180 days
   are erased (audited ``submission.erase`` without an actor, ``reason: "retention"``).
   Phase 11: the conversation's latest message counts as activity too, in the candidate
   query (so live conversations can't fill every batch: review S3) and again under the
   idea's and submission's locks (a reply takes the same locks);
5. Phase 11 (belt and braces, review S2): for submissions already erased, any
   conversation and submitter email left behind are deleted (an erasure made by 0.3.0
   during a rollback knows neither).

(Brand images nobody uses are branding's own rule.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import ColumnElement, delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SUBMITTER_EMAIL_TYPES, HoldReason, IdeaStatus
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.project import Project
from app.models.public import (
    AltchaUsedChallenge,
    ConfirmationEmailSend,
    PublicSubmission,
    SubmissionMessage,
)
from app.public import erasure
from app.public.emails import CONFIRMATION_WINDOW

__all__ = [
    "BATCH",
    "CLOSED_IDEA_RETENTION",
    "HELD_FOR_CONFIRMATION",
    "UNCONFIRMED_ADDRESS",
    "RetentionResult",
    "cleanup",
]

logger = logging.getLogger(__name__)

HELD_FOR_CONFIRMATION: Final = timedelta(days=3)
UNCONFIRMED_ADDRESS: Final = timedelta(days=3)
CLOSED_IDEA_RETENTION: Final = timedelta(days=180)
BATCH: Final = 500
"""Rows per statement (rule 4: ideas per run; the next hour takes the rest)."""

_SUBMITTER_EMAILS: Final = SUBMITTER_EMAIL_TYPES


@dataclass(frozen=True, slots=True)
class RetentionResult:
    challenges: int = 0
    unconfirmed_ideas: int = 0
    addresses: int = 0
    erased: int = 0
    sends: int = 0
    swept: int = 0
    """Phase 11 rule 5: erased submissions whose leftovers were deleted."""


async def _forget_challenges(db: AsyncSession, now: datetime) -> int:
    result = await db.execute(
        delete(AltchaUsedChallenge)
        .where(AltchaUsedChallenge.expires_at < now)
        .returning(AltchaUsedChallenge.signature)
    )
    return len(result.all())


async def _forget_sends(db: AsyncSession, now: datetime) -> int:
    """``ix_confirmation_email_sends_created_at``."""
    result = await db.execute(
        delete(ConfirmationEmailSend)
        .where(ConfirmationEmailSend.created_at <= now - CONFIRMATION_WINDOW)
        .returning(ConfirmationEmailSend.id)
    )
    return len(result.all())


async def _delete_unconfirmed_ideas(db: AsyncSession, now: datetime) -> int:
    """``ix_ideas_created_at_email_verification``; the database cascades to the
    submission, its emails and the idea's activity."""
    ids = (
        select(Idea.id)
        .where(
            Idea.held_for == HoldReason.EMAIL_VERIFICATION,
            Idea.created_at < now - HELD_FOR_CONFIRMATION,
        )
        .limit(BATCH)
    )
    result = await db.execute(delete(Idea).where(Idea.id.in_(ids)).returning(Idea.id))
    return len(result.all())


async def _forget_unconfirmed_addresses(db: AsyncSession, now: datetime) -> int:
    """``ix_public_submissions_created_at_unconfirmed``. A confirmation committed
    meanwhile wins: the ``UPDATE`` re-checks ``email_verified_at`` on the row it waited
    for."""
    stale = (
        select(PublicSubmission.id)
        .where(
            PublicSubmission.email.is_not(None),
            PublicSubmission.email_verified_at.is_(None),
            PublicSubmission.created_at < now - UNCONFIRMED_ADDRESS,
        )
        .limit(BATCH)
    )
    forgotten = (
        (
            await db.execute(
                update(PublicSubmission)
                .where(
                    PublicSubmission.id.in_(stale),
                    PublicSubmission.email.is_not(None),
                    PublicSubmission.email_verified_at.is_(None),
                )
                .values(email=None, wants_updates=False, updated_at=now)
                .returning(PublicSubmission.idea_id)
                .execution_options(synchronize_session=False)
            )
        )
        .scalars()
        .all()
    )
    if forgotten:
        await db.execute(
            delete(OutboundEmail)
            .where(OutboundEmail.idea_id.in_(forgotten), OutboundEmail.type.in_(_SUBMITTER_EMAILS))
            .execution_options(synchronize_session=False)
        )
    return len(forgotten)


def _quiet_conversation(submission_id: Any, now: datetime) -> ColumnElement[bool]:
    """Phase 11: no message in the conversation in the last 180 days
    (``ix_submission_messages_submission_id_created_at``)."""
    return ~exists().where(
        SubmissionMessage.submission_id == submission_id,
        SubmissionMessage.created_at >= now - CLOSED_IDEA_RETENTION,
    )


async def _erase_closed(db: AsyncSession, now: datetime) -> int:
    """Rule 4, one idea at a time under its lock (project ``FOR KEY SHARE``, then the
    idea, then the submission), like any idea write; an idea reopened, or a conversation
    with a reply committed meanwhile, is skipped."""
    candidates = (
        await db.execute(
            select(Idea.id, Idea.project_id)
            .join(PublicSubmission, PublicSubmission.idea_id == Idea.id)
            .where(
                PublicSubmission.erased_at.is_(None),
                Idea.status == IdeaStatus.CLOSED,
                Idea.last_activity_at < now - CLOSED_IDEA_RETENTION,
                _quiet_conversation(PublicSubmission.id, now),
            )
            .order_by(Idea.last_activity_at)
            .limit(BATCH)
        )
    ).all()
    erased = 0
    for idea_id, project_id in candidates:
        await db.execute(
            select(Project.id)
            .where(Project.id == project_id)
            .with_for_update(read=True, key_share=True)
        )
        idea = await db.scalar(
            select(Idea)
            .where(Idea.id == idea_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            idea is None
            or idea.status is not IdeaStatus.CLOSED
            or idea.last_activity_at >= now - CLOSED_IDEA_RETENTION
        ):
            continue
        submission = await db.scalar(
            select(PublicSubmission)
            .where(PublicSubmission.idea_id == idea_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if submission is None or not await db.scalar(
            select(_quiet_conversation(submission.id, now))
        ):
            continue  # a reply came in meanwhile (it takes the same locks)
        if await erasure.erase(db, submission, idea, by="retention", now=now):
            erased += 1
    return erased


async def _sweep_erased(db: AsyncSession) -> int:
    """Rule 5: messages and submitter emails left on erased submissions (batched)."""
    leftovers = or_(
        exists().where(SubmissionMessage.submission_id == PublicSubmission.id),
        exists().where(
            OutboundEmail.idea_id == PublicSubmission.idea_id,
            OutboundEmail.type.in_(_SUBMITTER_EMAILS),
        ),
    )
    rows = (
        await db.execute(
            select(PublicSubmission.id, PublicSubmission.idea_id)
            .where(PublicSubmission.erased_at.is_not(None), leftovers)
            .limit(BATCH)
        )
    ).all()
    if not rows:
        return 0
    await db.execute(
        delete(SubmissionMessage)
        .where(SubmissionMessage.submission_id.in_([row[0] for row in rows]))
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(OutboundEmail)
        .where(
            OutboundEmail.idea_id.in_([row[1] for row in rows]),
            OutboundEmail.type.in_(_SUBMITTER_EMAILS),
        )
        .execution_options(synchronize_session=False)
    )
    return len(rows)


async def cleanup(db: AsyncSession, now: datetime) -> RetentionResult:
    """Run the five rules (in the caller's transaction)."""
    result = RetentionResult(
        challenges=await _forget_challenges(db, now),
        unconfirmed_ideas=await _delete_unconfirmed_ideas(db, now),
        addresses=await _forget_unconfirmed_addresses(db, now),
        erased=await _erase_closed(db, now),
        sends=await _forget_sends(db, now),
        swept=await _sweep_erased(db),
    )
    if result.unconfirmed_ideas or result.addresses or result.erased or result.swept:
        logger.info(
            "public submission retention",
            extra={
                "unconfirmed_ideas": result.unconfirmed_ideas,
                "addresses": result.addresses,
                "erased": result.erased,
                "swept": result.swept,
            },
        )
    return result
