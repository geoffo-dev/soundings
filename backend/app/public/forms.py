"""The public form of a project: is it available (c8), and what it asks for
(contract-phase4 section 3.5).

c8 = the instance switch (``SOUNDINGS_PUBLIC_SUBMISSION_ENABLED``) and the project's
``public_submission_enabled`` are on, the project isn't archived and its slug isn't
reserved. Every failure, an unknown slug included, is the same 404: nothing tells
whether a project exists. The form shows only the project's name, intro and branding,
even for a private project.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import ProjectFacts, Resource, Rule, not_found, require
from app.config import Settings
from app.models.enums import HoldReason
from app.models.project import Project
from app.schemas.public import PublicProject
from app.services.branding import effective_branding

__all__ = [
    "asks_for_email",
    "email_required",
    "form_resource",
    "initial_hold",
    "load_form",
    "public_project",
]


def form_resource(settings: Settings, project: Project) -> Resource:
    """The facts for ``public.submit`` (c8)."""
    return Resource(
        project=ProjectFacts.of(project), public_submission_on=settings.public_submission_enabled
    )


async def load_form(db: AsyncSession, settings: Settings, slug: str) -> Project:
    """The project whose public form is available (c8); else 404."""
    project = await db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise not_found()
    require(None, Rule.PUBLIC_SUBMIT, form_resource(settings, project))
    return project


def asks_for_email(settings: Settings) -> bool:
    """Email is set up: the form offers an address field and status emails. Without
    it the form asks for no address at all (minimal data)."""
    return settings.smtp_configured


def email_required(settings: Settings, project: Project) -> bool:
    """The project holds new ideas until the submitter confirms their address."""
    return project.public_require_email_verification and settings.smtp_configured


def initial_hold(settings: Settings, project: Project) -> HoldReason | None:
    """Where a new public idea waits: for its address to be confirmed, for moderation,
    or nowhere (the team sees it at once)."""
    if email_required(settings, project):
        return HoldReason.EMAIL_VERIFICATION
    if project.public_moderation_required:
        return HoldReason.MODERATION
    return None


async def public_project(db: AsyncSession, settings: Settings, project: Project) -> PublicProject:
    return PublicProject(
        slug=project.slug,
        name=project.name,
        intro_md=project.public_intro_md,
        asks_for_email=asks_for_email(settings),
        email_required=email_required(settings, project),
        moderated=project.public_moderation_required,
        branding=await effective_branding(db, project.id),
    )
