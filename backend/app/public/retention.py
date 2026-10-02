"""The hourly cleanup's public-submission rules (contract-phase4 sections 3.9 and 3.13),
run after Phase 3's (:func:`app.notifications.schedule.run_schedule`). Idempotent,
indexed and batched; constants, not settings:

1. solved ALTCHA challenges past their expiry are forgotten (replay protection only
   needs them until then), and so are confirmation sends older than 24 hours (the
   per-address limit only needs them for that long);
2. ideas still held for email confirmation 3 days after they were sent are deleted
   (with their submission and emails: they never reached the team);
3. unconfirmed addresses are forgotten 3 days after the submission (address and
   opt-in cleared, the idea's submitter emails deleted; the tracking link keeps
   working);
4. the details of submitters whose idea is closed and has had no activity for 180 days
   are erased (audited ``submission.erase`` without an actor, ``reason: "retention"``).

(Brand images nobody uses are branding's own rule.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EmailType, HoldReason, IdeaStatus
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.project import Project
from app.models.public import AltchaUsedChallenge, ConfirmationEmailSend, PublicSubmission
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

_SUBMITTER_EMAILS: Final = (EmailType.SUBMISSION_RECEIVED, EmailType.SUBMISSION_STATUS_CHANGED)


@dataclass(frozen=True, slots=True)
class RetentionResult:
    challenges: int = 0
    unconfirmed_ideas: int = 0
    addresses: int = 0
    erased: int = 0
    sends: int = 0


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


async def _erase_closed(db: AsyncSession, now: datetime) -> int:
    """Rule 4, one idea at a time under its lock (project ``FOR KEY SHARE``, then the
    idea), like any idea write; an idea reopened meanwhile is skipped."""
    candidates = (
        await db.execute(
            select(Idea.id, Idea.project_id)
            .join(PublicSubmission, PublicSubmission.idea_id == Idea.id)
            .where(
                PublicSubmission.erased_at.is_(None),
                Idea.status == IdeaStatus.CLOSED,
                Idea.last_activity_at < now - CLOSED_IDEA_RETENTION,
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
        if submission is not None and await erasure.erase(
            db, submission, idea, by="retention", now=now
        ):
            erased += 1
    return erased


async def cleanup(db: AsyncSession, now: datetime) -> RetentionResult:
    """Run the four rules (in the caller's transaction)."""
    result = RetentionResult(
        challenges=await _forget_challenges(db, now),
        unconfirmed_ideas=await _delete_unconfirmed_ideas(db, now),
        addresses=await _forget_unconfirmed_addresses(db, now),
        erased=await _erase_closed(db, now),
        sends=await _forget_sends(db, now),
    )
    if result.unconfirmed_ideas or result.addresses or result.erased:
        logger.info(
            "public submission retention",
            extra={
                "unconfirmed_ideas": result.unconfirmed_ideas,
                "addresses": result.addresses,
                "erased": result.erased,
            },
        )
    return result
