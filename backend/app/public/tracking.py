"""The submitter's private links (``public.track``, c9; contract-phase4 section 3.7).

* **Tracking link** (``/track#<token>``): the token's SHA-256 finds the submission;
  unknown and erased tokens are the same 404, and so is every token while public
  submission is off for the instance. It shows the project's public name, the title
  and summary **as submitted** (never the idea's current text), the status, its label
  and the status history (dates and labels only), the masked address and the
  project's branding; nothing about people, comments, evaluations, scores, tags, the
  idea key or other submissions. It also turns status emails on or off, sends the
  confirmation email again and erases the submitter's details.
* **Confirmation link** (``/verify#<token>``): a signed token (no table) that confirms
  the address while the submission still has it, and releases an idea held for
  confirmation (to moderation, or to the team).

Writes lock in the app's one order: the project row ``FOR KEY SHARE``, the idea, then
the submission, so they serialise with status changes (whose fan-out reads the
submission) and with each other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.public_form import refuse
from app.auth.submission_tokens import email_digest, read_confirmation_token, tracking_token_hash
from app.authz import Resource, Rule, not_found, require
from app.config import Settings
from app.domain.labels import status_label
from app.errors import ProblemError
from app.models.activity import ActivityEvent
from app.models.enums import HoldReason, IdeaStatus, Resolution
from app.models.idea import Idea
from app.models.project import Project
from app.models.public import PublicSubmission
from app.notifications.unsubscribe import email_hint
from app.public import erasure
from app.public.emails import (
    CONFIRMATION_WINDOW,
    CONFIRMATIONS_PER_SUBMISSION,
    confirmations_sent,
    queue_confirmation,
)
from app.schemas.public import (
    EmailVerified,
    PublicProjectRef,
    TrackedStatusChange,
    TrackedSubmission,
)
from app.services.branding import effective_branding

__all__ = [
    "Tracked",
    "erase_own_details",
    "find",
    "resend_confirmation",
    "set_updates",
    "tracked_submission",
    "verify_email",
]

Tracked = tuple[PublicSubmission, Idea, Project]

_TOO_MANY_EMAILS: Final = (
    "We've sent this confirmation email 3 times today. Check your spam folder, or try "
    "again tomorrow."
)


def _require_track(settings: Settings, valid: bool) -> None:
    """c9: a valid token for this submission and the instance switch on; else 404."""
    require(
        None,
        Rule.PUBLIC_TRACK,
        Resource(token_valid=valid, public_submission_on=settings.public_submission_enabled),
    )


async def _lock(db: AsyncSession, submission_id: UUID) -> Tracked | None:
    """The submission with its idea and project, locked project (key share) -> idea ->
    submission; ``None`` if it is gone."""
    ids = (
        await db.execute(
            select(Idea.id, Idea.project_id)
            .join(PublicSubmission, PublicSubmission.idea_id == Idea.id)
            .where(PublicSubmission.id == submission_id)
        )
    ).first()
    if ids is None:
        return None
    idea_id, project_id = ids
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
    submission = await db.scalar(
        select(PublicSubmission)
        .where(PublicSubmission.id == submission_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project = await db.get(Project, project_id)
    if idea is None or submission is None or project is None:
        return None
    return submission, idea, project


async def find(db: AsyncSession, settings: Settings, token: str, *, lock: bool = False) -> Tracked:
    """The submission a tracking token opens (c9), optionally locked for a write; 404
    for an unknown or erased token, or while public submission is off."""
    digest = tracking_token_hash(token)
    row = (
        await db.execute(
            select(PublicSubmission, Idea, Project)
            .join(Idea, Idea.id == PublicSubmission.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(PublicSubmission.tracking_token_hash == digest)
        )
    ).first()
    found: Tracked | None = None if row is None else (row[0], row[1], row[2])
    if found is not None and lock:
        found = await _lock(db, found[0].id)
    valid = (
        found is not None
        and found[0].erased_at is None
        and found[0].tracking_token_hash == digest  # still, after waiting for the lock
    )
    _require_track(settings, valid)
    assert found is not None  # noqa: S101 - c9 passed
    return found


def _label(project: Project, status: IdeaStatus, resolution: Resolution | None) -> str:
    return status_label(project.status_labels, status, resolution)


async def _history(db: AsyncSession, idea: Idea, project: Project) -> list[TrackedStatusChange]:
    events = await db.scalars(
        select(ActivityEvent)
        .where(ActivityEvent.idea_id == idea.id, ActivityEvent.type == "status_changed")
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    history = []
    for event in events:
        try:
            status = IdeaStatus(str(event.payload.get("to_status")))
            raw = event.payload.get("to_resolution")
            resolution = Resolution(str(raw)) if raw else None
        except ValueError:
            continue
        history.append(
            TrackedStatusChange(
                status=status,
                resolution=resolution,
                status_label=_label(project, status, resolution),
                at=event.created_at,
            )
        )
    return history


async def _can_resend(
    db: AsyncSession, settings: Settings, submission: PublicSubmission, *, now: datetime
) -> bool:
    if (
        not settings.smtp_configured
        or submission.email is None
        or submission.email_verified_at is not None
    ):
        return False
    sent, _ = await confirmations_sent(db, submission.idea_id, now=now)
    return sent < CONFIRMATIONS_PER_SUBMISSION


async def tracked_submission(
    db: AsyncSession, settings: Settings, found: Tracked, *, now: datetime
) -> TrackedSubmission:
    """The tracking page: the submitter's own words and the idea's public status."""
    submission, idea, project = found
    assert submission.submitted_title is not None  # noqa: S101 - not erased (c9)
    assert submission.submitted_summary is not None  # noqa: S101
    return TrackedSubmission(
        project=PublicProjectRef(slug=project.slug, name=project.name),
        title=submission.submitted_title,
        summary=submission.submitted_summary,
        submitted_at=submission.created_at,
        reached_team_at=None if idea.held_for is not None else submission.reached_team_at,
        held_for=idea.held_for,
        status=idea.status,
        resolution=idea.resolution,
        status_label=_label(project, idea.status, idea.resolution),
        history=await _history(db, idea, project),
        email_hint=email_hint(submission.email) if submission.email else None,
        email_verified=submission.email_verified_at is not None,
        wants_updates=submission.wants_updates,
        can_resend_verification=await _can_resend(db, settings, submission, now=now),
        branding=await effective_branding(db, project.id),
    )


async def set_updates(
    db: AsyncSession, settings: Settings, token: str, wants_updates: bool, *, now: datetime
) -> TrackedSubmission:
    """Status emails on (needs an address on file: 409 ``no_email``) or off (at once:
    queued status emails are cancelled when the worker reads the submission)."""
    found = await find(db, settings, token, lock=True)
    submission = found[0]
    if wants_updates and submission.email is None:
        raise ProblemError(409, "no_email", detail="There's no email address to send updates to.")
    submission.wants_updates = wants_updates
    submission.updated_at = now
    await db.flush()
    return await tracked_submission(db, settings, found, now=now)


async def resend_confirmation(
    db: AsyncSession, settings: Settings, token: str, *, now: datetime
) -> TrackedSubmission:
    """The confirmation email again: an unconfirmed address on file, email on, at most
    3 per submission per 24 hours (429 with ``Retry-After``), and within the
    per-address limit (silently)."""
    found = await find(db, settings, token, lock=True)
    submission = found[0]
    if submission.email is None:
        raise ProblemError(409, "no_email", detail="There's no email address to confirm.")
    if submission.email_verified_at is not None:
        raise ProblemError(409, "already_verified", detail="Your address is already confirmed.")
    if not settings.smtp_configured:
        raise ProblemError(409, "smtp_not_configured", detail="Email isn't available right now.")
    sent, oldest = await confirmations_sent(db, submission.idea_id, now=now)
    if sent >= CONFIRMATIONS_PER_SUBMISSION and oldest is not None:
        raise refuse((oldest + CONFIRMATION_WINDOW - now).total_seconds(), _TOO_MANY_EMAILS)
    await queue_confirmation(db, settings, submission, now=now)
    return await tracked_submission(db, settings, found, now=now)


async def erase_own_details(
    db: AsyncSession, settings: Settings, token: str, *, now: datetime
) -> None:
    """The submitter erases their details (UK GDPR): exactly an admin's erase; the
    link stops working at once (a second call is 404)."""
    submission, idea, _ = await find(db, settings, token, lock=True)
    await erasure.erase(db, submission, idea, by="submitter", now=now)


async def verify_email(
    db: AsyncSession, settings: Settings, token: str, *, now: datetime
) -> EmailVerified:
    """Confirm the address a confirmation link was sent to (idempotent). 404 when the
    token is invalid or expired, the submission is gone or erased, or its address
    changed; works while the project's form is off, not while the instance's is."""
    claim = read_confirmation_token(settings, token, now=now)
    found = None if claim is None else await _lock(db, claim.submission_id)
    valid = (
        claim is not None
        and found is not None
        and found[0].erased_at is None
        and found[0].email is not None
        and email_digest(found[0].email) == claim.email_digest
    )
    _require_track(settings, valid)
    if found is None:  # pragma: no cover - c9 passed
        raise not_found()
    submission, idea, project = found
    if submission.email_verified_at is None:
        submission.email_verified_at = now
        submission.updated_at = now
    if idea.held_for is HoldReason.EMAIL_VERIFICATION:
        idea.held_for = HoldReason.MODERATION if project.public_moderation_required else None
        idea.last_activity_at = now
        if idea.held_for is None:
            submission.reached_team_at = now
    await db.flush()
    assert submission.submitted_title is not None  # noqa: S101 - not erased
    return EmailVerified(
        project=PublicProjectRef(slug=project.slug, name=project.name),
        title=submission.submitted_title,
        held_for=idea.held_for,
        branding=await effective_branding(db, project.id),
    )
