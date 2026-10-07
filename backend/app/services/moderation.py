"""Public ideas inside the app: the project's Public form settings, the moderation
queue, and approving or rejecting an idea held for moderation (contract-phase4 sections
3.5 and 3.6).

* **Public form settings** (``project.edit_settings``, session only): on/off, email
  confirmation, moderation and the intro. Changes apply to new submissions only (held
  ideas stay held). Turning the form on needs the instance switch and a slug that
  isn't one of the app's own paths (409 ``public_submission_unavailable``); requiring a
  confirmed address needs email (409 ``smtp_not_configured``). Audited as
  ``project.update`` with the changed column names.
* **The queue** (``project.view``, then ``idea.moderate`` at project level: project and
  platform admins): ideas held for moderation, oldest first, with the total for the
  board's "3 ideas waiting for review" link. Held ideas are in no other list.
* **Approve** (``idea.moderate``): the idea becomes visible, at the top of New
  (``last_activity_at`` now); audited ``submission.approve``. No email and no
  notification: nothing happens on a held idea, and approving is not news.
* **Reject** (``idea.moderate``): deletes the idea, with its submission, submitter
  emails and activity (spam, abuse, off-topic); the tracking link then answers 404.
  Audited ``submission.reject`` with ids and the key only. A genuine but unwanted idea
  is approved and closed as Rejected instead, so its submitter sees that.

Both answer 409 ``not_awaiting_moderation`` for an idea that isn't held for
moderation (a second click). Logs and audit entries never carry the submitter's name,
address or text.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import IdeaFacts, Resource, Rule, can, require
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.enums import HoldReason, IdeaStatus
from app.models.idea import Idea
from app.models.project import Project
from app.models.public import PublicSubmission
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.public.submissions import idea_submission, load_submission
from app.schemas.projects import RESERVED_SLUGS
from app.schemas.public import (
    IdeaSubmission,
    ModerationItem,
    ModerationPage,
    PublicFormSettings,
    PublicFormSettingsUpdate,
)
from app.services import audit
from app.services.ideas import LoadedIdea
from app.services.refs import idea_key, idea_ref

__all__ = [
    "approve",
    "awaiting_moderation",
    "form_settings",
    "may_moderate",
    "moderation_queue",
    "reject",
    "update_form_settings",
]

_FORM_FIELDS: Final = (
    ("enabled", "public_submission_enabled"),
    ("require_email_verification", "public_require_email_verification"),
    ("moderation_required", "public_moderation_required"),
    ("intro_md", "public_intro_md"),
)
"""Request field -> project column (audited by column name)."""


# --- Public form settings ---------------------------------------------------------------
def form_available(settings: Settings, project: Project) -> bool:
    """A public form is possible here (c8 apart from the project's own switch)."""
    return (
        settings.public_submission_enabled
        and project.archived_at is None
        and project.slug not in RESERVED_SLUGS
    )


async def awaiting_moderation(db: AsyncSession, project_id: UUID) -> int:
    """Ideas held for moderation in the project
    (``ix_ideas_project_id_created_at_moderation``)."""
    count = await db.scalar(
        select(func.count())
        .select_from(Idea)
        .where(Idea.project_id == project_id, Idea.held_for == HoldReason.MODERATION)
    )
    return int(count or 0)


async def form_settings(
    db: AsyncSession, settings: Settings, project: Project
) -> PublicFormSettings:
    """``GET /projects/{slug}/public-form``; the caller checked ``project.edit_settings``."""
    return PublicFormSettings(
        available=form_available(settings, project),
        email_available=settings.smtp_configured,
        enabled=project.public_submission_enabled,
        require_email_verification=project.public_require_email_verification,
        moderation_required=project.public_moderation_required,
        intro_md=project.public_intro_md,
        form_url=f"{settings.public_base_url.rstrip('/')}/{project.slug}/submit",
        awaiting_moderation=await awaiting_moderation(db, project.id),
    )


async def update_form_settings(
    db: AsyncSession,
    settings: Settings,
    principal: Principal,
    project: Project,
    body: PublicFormSettingsUpdate,
) -> PublicFormSettings:
    """``PATCH /projects/{slug}/public-form``: omitted or null fields are unchanged. The
    caller loaded the project ``for_update`` with ``project.edit_settings``."""
    if project.archived_at is not None:
        raise ProblemError(
            409,
            "project_archived",
            detail="The project is archived: unarchive it to change its settings.",
        )
    if body.enabled and not form_available(settings, project):
        raise ProblemError(
            409,
            "public_submission_unavailable",
            detail=(
                "Public forms are turned off for this instance."
                if not settings.public_submission_enabled
                else "This project's address is one of the app's own pages, so it can't "
                "have a public form."
            ),
        )
    if body.require_email_verification and not settings.smtp_configured:
        raise ProblemError(
            409,
            "smtp_not_configured",
            detail="Email isn't set up, so the form can't ask people to confirm an address.",
        )
    changed: list[str] = []
    for field, column in _FORM_FIELDS:
        value = getattr(body, field)
        if value is not None and value != getattr(project, column):
            setattr(project, column, value)
            changed.append(column)
    if changed:
        await db.flush()
        await audit.record(
            db,
            "project.update",
            actor=principal,
            target_type="project",
            target_id=project.id,
            project_id=project.id,
            details={"rule": Rule.PROJECT_EDIT_SETTINGS, "fields": changed},
        )
    return await form_settings(db, settings, project)


# --- The queue --------------------------------------------------------------------------
_HELD: Final = IdeaFacts(id=UUID(int=0), status=IdeaStatus.NEW, held_for=HoldReason.MODERATION)
"""Any idea held for moderation in the project, for deciding at project level."""


def may_moderate(principal: Principal, resource: Resource) -> bool:
    """``idea.moderate`` for the project's held ideas (project and platform admins).
    Listing and counting are reads, so the archived check (a write condition) doesn't
    apply. Also decides who sees ``ProjectSummary.pending_moderation_count``."""
    assert resource.project is not None  # noqa: S101 - load_project sets it
    probe = resource.replace(
        project=dataclasses.replace(resource.project, archived=False), idea=_HELD
    )
    return can(principal, Rule.IDEA_MODERATE, probe)


def _require_moderator(principal: Principal, resource: Resource) -> None:
    """:func:`may_moderate`, or 403 for everyone else who can see the project."""
    if not may_moderate(principal, resource):
        raise ProblemError(
            403, "forbidden", detail="Only the project's admins review public ideas."
        )


def _after(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    values = decode_cursor(cursor)
    try:
        return datetime.fromisoformat(str(values["created_at"])), UUID(str(values["id"]))
    except (KeyError, TypeError, ValueError):
        raise InvalidCursorProblem from None


async def moderation_queue(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource, page: PageParams
) -> ModerationPage:
    """``GET /projects/{slug}/moderation``: oldest first. The caller checked
    ``project.view``."""
    _require_moderator(principal, resource)
    after = _after(page.cursor)
    held = (Idea.project_id == project.id, Idea.held_for == HoldReason.MODERATION)
    statement = (
        select(Idea, PublicSubmission)
        .join(PublicSubmission, PublicSubmission.idea_id == Idea.id)
        .where(*held)
        .order_by(Idea.created_at, Idea.id)
        .limit(page.limit + 1)
    )
    if after is not None:
        statement = statement.where(tuple_(Idea.created_at, Idea.id) > after)
    rows = (await db.execute(statement)).all()
    items, next_cursor = slice_page(
        rows, page.limit, lambda row: {"created_at": row[0].created_at, "id": row[0].id}
    )
    total = await awaiting_moderation(db, project.id)
    return ModerationPage(
        items=[_item(principal, project, resource, idea, submission) for idea, submission in items],
        next_cursor=next_cursor,
        total=total,
    )


def _item(
    principal: Principal,
    project: Project,
    resource: Resource,
    idea: Idea,
    submission: PublicSubmission,
) -> ModerationItem:
    loaded = LoadedIdea(idea, project, resource.replace(idea=IdeaFacts.of(idea)))
    ref: dict[str, Any] = idea_ref(idea, project).model_dump()
    return ModerationItem(
        **ref,
        summary=idea.summary,
        description_md=idea.description_md,
        submission=idea_submission(principal, loaded, submission),
    )


# --- Approve and reject -----------------------------------------------------------------
def _not_awaiting() -> ProblemError:
    return ProblemError(
        409,
        "not_awaiting_moderation",
        detail="This idea isn't waiting for review (someone may have decided already).",
    )


async def _decide(db: AsyncSession, principal: Principal, loaded: LoadedIdea) -> PublicSubmission:
    """The checks both decisions share, in order: a public idea (404), ``idea.moderate``
    (404 for non-admins, 409 ``project_archived``), held for moderation (409)."""
    submission = await load_submission(db, loaded, for_update=True)
    require(principal, Rule.IDEA_MODERATE, loaded.resource)
    if loaded.idea.held_for is not HoldReason.MODERATION:
        raise _not_awaiting()
    return submission


async def approve(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, *, now: datetime
) -> IdeaSubmission:
    """``POST /ideas/{idea}/submission/approve``; the caller loaded the idea
    ``for_update``."""
    submission = await _decide(db, principal, loaded)
    idea = loaded.idea
    idea.held_for = None
    idea.last_activity_at = now
    submission.reached_team_at = now  # the submitter's "With the team" step
    await db.flush()
    await audit.record(
        db,
        "submission.approve",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={"rule": Rule.IDEA_MODERATE},
    )
    approved = dataclasses.replace(
        loaded, resource=loaded.resource.replace(idea=IdeaFacts.of(idea))
    )
    return idea_submission(principal, approved, submission)


async def reject(db: AsyncSession, principal: Principal, loaded: LoadedIdea) -> None:
    """``POST /ideas/{idea}/submission/reject``: delete the idea (the database cascades
    to its submission, submitter emails and activity); the caller loaded it
    ``for_update``."""
    await _decide(db, principal, loaded)
    idea = loaded.idea
    await audit.record(
        db,
        "submission.reject",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={"rule": Rule.IDEA_MODERATE, "key": idea_key(idea, loaded.project)},
    )
    await db.delete(idea)
    await db.flush()
