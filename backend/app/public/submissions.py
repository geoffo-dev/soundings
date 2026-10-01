"""The submission behind a public idea, inside the app (contract-phase4 sections 3.6
and 3.9): ``GET /ideas/{idea}/submission`` and an admin erasing the submitter's details.

Anyone who can view the idea sees the name the submitter gave ("Submitted by Jo via
the public form"); their address, confirmation and update preference only with
``public.erase_submitter`` (project and platform admins, session only).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, can, not_found, require
from app.domain.principal import Principal
from app.models.enums import HoldReason
from app.models.public import PublicSubmission
from app.public import erasure
from app.schemas.public import IdeaSubmission, IdeaSubmissionPermissions, SubmitterContact
from app.services.ideas import LoadedIdea

__all__ = ["erase_submitter", "idea_submission", "load_submission"]


async def load_submission(
    db: AsyncSession, loaded: LoadedIdea, *, for_update: bool = False
) -> PublicSubmission:
    """The idea's public submission; 404 when it didn't come through the form (the
    caller locked the idea first when ``for_update``)."""
    statement = select(PublicSubmission).where(PublicSubmission.idea_id == loaded.idea.id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    submission = await db.scalar(statement)
    if submission is None:
        raise not_found()
    return submission


def idea_submission(
    principal: Principal, loaded: LoadedIdea, submission: PublicSubmission
) -> IdeaSubmission:
    """``IdeaSubmission`` as ``principal`` may see it."""
    idea, resource = loaded.idea, loaded.resource
    may_erase = can(principal, Rule.PUBLIC_ERASE_SUBMITTER, resource)
    contact = None
    if may_erase:
        contact = SubmitterContact(
            email=submission.email,
            email_verified=submission.email_verified_at is not None,
            wants_updates=submission.wants_updates,
        )
    return IdeaSubmission(
        idea_id=idea.id,
        submitted_at=submission.created_at,
        held_for=idea.held_for,
        name=submission.name,
        contact=contact,
        erased_at=submission.erased_at,
        permissions=IdeaSubmissionPermissions(
            can_moderate=idea.held_for is HoldReason.MODERATION
            and can(principal, Rule.IDEA_MODERATE, resource),
            can_erase=may_erase and submission.erased_at is None,
        ),
    )


async def erase_submitter(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, *, now: datetime
) -> IdeaSubmission:
    """``public.erase_submitter``: erase the details (idempotent; audited once). The
    caller loaded the idea ``for_update``."""
    require(principal, Rule.PUBLIC_ERASE_SUBMITTER, loaded.resource)
    submission = await load_submission(db, loaded, for_update=True)
    await erasure.erase(db, submission, loaded.idea, by=principal, now=now)
    return idea_submission(principal, loaded, submission)
