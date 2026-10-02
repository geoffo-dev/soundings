"""``POST /public/projects/{slug}/submissions``: an idea through the public form
(contract-phase4 section 3.5).

Checks, in order, each failure being the response (415, the body's shape and the
per-IP throttle on form requests come first, in the router): the form is available
(c8, 404) -> the per-IP limit (429,
every attempt counted) -> email required (422 ``email_required``) -> ALTCHA, spent in
this transaction (422 ``challenge_failed``) -> the per-project limit (429) -> the
honeypot (a normal-looking receipt, nothing kept but the spent challenge) -> create.

Created in one transaction: the idea (New, no submitter account, the project's next
number, held for email confirmation or moderation as the project says), its
``idea_created`` event with no actor, the ``public_submissions`` row (what the
submitter chose to give, the hashed and sealed tracking token, a copy of the title and
summary they sent) and, with an address, the confirmation email. No watchers and no
notifications. Logs and audit carry ids and outcome codes only.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.auth import altcha
from app.auth.public_form import check_throttle, honeypot_filled, refuse
from app.auth.submission_tokens import (
    new_tracking_token,
    seal_tracking_token,
    tracking_token_hash,
)
from app.auth.throttle import public_submission_throttle
from app.authz import Rule, not_found, require
from app.config import Settings
from app.errors import ProblemError
from app.models.enums import HoldReason, IdeaStatus
from app.models.idea import Idea
from app.models.project import Project
from app.models.public import PublicSubmission
from app.public.emails import queue_confirmation, tracking_url
from app.public.forms import asks_for_email, email_required, form_resource, initial_hold, load_form
from app.schemas.public import PublicSubmissionCreate, PublicSubmissionReceipt
from app.services import activity

__all__ = ["PROJECT_WINDOW", "submit"]

logger = logging.getLogger(__name__)

PROJECT_WINDOW: Final = timedelta(hours=1)
_REFUSED: Final = "public submission refused"
_TOO_MANY_FROM_YOU: Final = "You've sent several ideas in a short time. Try again in a few minutes."
_TOO_MANY_FOR_PROJECT: Final = (
    "This form is receiving a lot of ideas right now. Try again in a little while."
)


def _challenge_failed() -> ProblemError:
    return ProblemError(
        422,
        "challenge_failed",
        detail="We couldn't verify this browser. Reload the form and try again.",
    )


async def _lock_project(db: AsyncSession, settings: Settings, project: Project) -> Project:
    """Lock the project row (``FOR NO KEY UPDATE``: idea writes, which take ``FOR KEY
    SHARE``, carry on) so the per-project count and the new idea's number are
    decided one submission at a time, and check c8 again under the lock."""
    locked = await db.scalar(
        select(Project)
        .where(Project.id == project.id)
        .with_for_update(key_share=True)  # FOR NO KEY UPDATE
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise not_found()
    require(None, Rule.PUBLIC_SUBMIT, form_resource(settings, locked))
    return locked


async def _project_retry_after(
    settings: Settings, db: AsyncSession, project: Project, now: datetime
) -> float | None:
    """Seconds until the project accepts another submission, when it has had
    ``SOUNDINGS_PUBLIC_SUBMISSIONS_PER_PROJECT`` in the last hour (counted in the
    database, so across replicas; ``ix_public_submissions_project_id_created_at``)."""
    limit = settings.public_submissions_per_project
    recent = (
        select(PublicSubmission.created_at)
        .where(
            PublicSubmission.project_id == project.id,
            PublicSubmission.created_at > now - PROJECT_WINDOW,
        )
        .order_by(PublicSubmission.created_at.desc())
        .limit(limit)
        .subquery()
    )
    row = (await db.execute(select(func.count(), func.min(recent.c.created_at)))).one()
    count, oldest = int(row[0] or 0), row[1]
    if count < limit or oldest is None:
        return None
    return max(float((oldest + PROJECT_WINDOW - now).total_seconds()), 1.0)


def _receipt(
    settings: Settings, token: str, held_for: HoldReason | None, email_sent: bool
) -> PublicSubmissionReceipt:
    return PublicSubmissionReceipt(
        tracking_token=token,
        tracking_url=tracking_url(settings, token),
        held_for=held_for,
        email_sent=email_sent,
    )


async def submit(
    db: AsyncSession,
    settings: Settings,
    request: Request,
    slug: str,
    body: PublicSubmissionCreate,
    *,
    now: datetime,
) -> PublicSubmissionReceipt:
    project = await load_form(db, settings, slug)  # c8: 404
    log = {"project_id": str(project.id)}
    check_throttle(
        request,
        public_submission_throttle(settings.public_submissions_per_ip),
        detail=_TOO_MANY_FROM_YOU,
        event=_REFUSED,
        log_fields=log,
    )

    # Without email the form asks for no address: drop both, so a form loaded before
    # email was turned off still goes through (and nothing half-kept breaks a check).
    email = body.email if asks_for_email(settings) else None
    wants_updates = body.wants_updates and email is not None
    if email_required(settings, project) and email is None:
        logger.info(_REFUSED, extra={"reason": "email_required", **log})
        raise ProblemError(
            422,
            "email_required",
            detail="Give your email address: we'll send a link to confirm it.",
        )

    # PBKDF2 at the configured cost (up to about 235 ms at the highest): off the loop.
    challenge = await asyncio.to_thread(altcha.verify, settings, body.altcha, project.slug, now=now)
    if challenge is None or not await altcha.spend(db, challenge):
        logger.info(_REFUSED, extra={"reason": "challenge_failed", **log})
        raise _challenge_failed()

    project = await _lock_project(db, settings, project)
    retry_after = await _project_retry_after(settings, db, project, now)
    if retry_after is not None:
        logger.info(_REFUSED, extra={"reason": "rate_limited", "limit": "project", **log})
        await db.commit()  # the challenge stays spent: a solution is accepted once
        raise refuse(retry_after, _TOO_MANY_FOR_PROJECT)

    held_for = initial_hold(settings, project)
    email_sent = email is not None and settings.smtp_configured
    if honeypot_filled(body.website):
        # Exactly a real submission's answer, nothing kept but the spent challenge.
        logger.info("public submission dropped (honeypot)", extra=log)
        return _receipt(settings, new_tracking_token(), held_for, email_sent)

    number = await db.scalar(
        update(Project)
        .where(Project.id == project.id)
        .values(next_idea_number=Project.next_idea_number + 1)
        .returning(Project.next_idea_number - 1)
        .execution_options(synchronize_session=False)
    )
    assert number is not None  # noqa: S101 - the row is locked
    idea = Idea(
        id=uuid4(),
        project_id=project.id,
        number=number,
        title=body.title,
        summary=body.summary,
        description_md=body.description_md,
        status=IdeaStatus.NEW,
        submitted_by_id=None,
        held_for=held_for,
    )
    db.add(idea)
    await db.flush()
    await activity.emit(db, idea, "idea_created", actor=None, at=now)
    token = new_tracking_token()
    submission = PublicSubmission(
        id=uuid4(),
        idea_id=idea.id,
        project_id=project.id,
        name=body.name,
        email=email,
        wants_updates=wants_updates,
        tracking_token_hash=tracking_token_hash(token),
        tracking_token_sealed=seal_tracking_token(settings, token),
        submitted_title=body.title,
        submitted_summary=body.summary,
        reached_team_at=now if held_for is None else None,
        created_at=now,
        updated_at=now,
    )
    db.add(submission)
    await db.flush()
    if email is not None:
        await queue_confirmation(db, settings, submission, now=now)
    logger.info(
        "public submission received",
        extra={**log, "idea_id": str(idea.id), "held_for": held_for.value if held_for else None},
    )
    return _receipt(settings, token, held_for, email_sent)
