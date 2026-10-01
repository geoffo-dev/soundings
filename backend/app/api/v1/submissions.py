"""Public submissions, inside the app: the project's Public form settings, the
moderation queue, the submission behind an idea, and erasing a submitter's details.

Rules: ``project.edit_settings`` (form settings), ``idea.moderate`` (queue, approve,
reject), ``public.erase_submitter`` (contact details, erase). Business rules:
docs/api/contract-phase4.md sections 3.4, 3.6 and 3.9.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.pagination import PageParamsDep
from app.schemas.public import (
    IdeaSubmission,
    ModerationPage,
    PublicFormSettings,
    PublicFormSettingsUpdate,
)

router = APIRouter(tags=["submissions"])


@router.get(
    "/projects/{slug}/public-form",
    operation_id="get_public_form_settings",
    summary="Project settings: public form",
    description="project.edit_settings (session only).",
    responses=problems(401, 403, 404),
)
async def get_public_form_settings(
    principal: PrincipalDep, slug: ProjectSlug
) -> PublicFormSettings:
    raise NotImplementedProblem


@router.patch(
    "/projects/{slug}/public-form",
    operation_id="update_public_form_settings",
    summary="Change the public form",
    description=(
        "project.edit_settings (session only); audited as project.update. Changes apply to "
        "new submissions only (held ideas stay held). 409 public_submission_unavailable "
        "(turning the form on while the instance switch is off, or for an older project "
        "whose slug is one of the app's own paths), smtp_not_configured (requiring email "
        "verification without email), project_archived."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_public_form_settings(
    principal: PrincipalDep, slug: ProjectSlug, body: PublicFormSettingsUpdate
) -> PublicFormSettings:
    raise NotImplementedProblem


@router.get(
    "/projects/{slug}/moderation",
    operation_id="list_moderation_queue",
    summary="Ideas waiting for moderation",
    description=(
        "idea.moderate (project and platform admins; others 403 after project.view): "
        "public ideas held for moderation, oldest first, with total."
    ),
    responses=problems(400, 401, 403, 404),
)
async def list_moderation_queue(
    principal: PrincipalDep, slug: ProjectSlug, page: PageParamsDep
) -> ModerationPage:
    raise NotImplementedProblem


@router.get(
    "/ideas/{idea}/submission",
    operation_id="get_idea_submission",
    summary="How a public idea came in",
    description=(
        "idea.view: the submitter's name; contact details only with public.erase_submitter. "
        "404 when the idea didn't come through the public form."
    ),
    responses=problems(401, 404),
)
async def get_idea_submission(principal: PrincipalDep, idea: IdeaParam) -> IdeaSubmission:
    raise NotImplementedProblem


@router.post(
    "/ideas/{idea}/submission/approve",
    operation_id="approve_submission",
    summary="Approve a public idea",
    description=(
        "idea.moderate. The idea appears in New for everyone with access. 409 "
        "not_awaiting_moderation when it isn't held for moderation. Audited."
    ),
    responses=problems(401, 404, 409),
)
async def approve_submission(principal: PrincipalDep, idea: IdeaParam) -> IdeaSubmission:
    raise NotImplementedProblem


@router.post(
    "/ideas/{idea}/submission/reject",
    operation_id="reject_submission",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject a public idea",
    description=(
        "idea.moderate. Deletes the idea with its submitter's details and emails (spam, "
        "abuse, off-topic); its tracking link stops working. No email is sent. 409 "
        "not_awaiting_moderation when it isn't held for moderation. Audited (ids only)."
    ),
    responses=problems(401, 404, 409),
)
async def reject_submission(principal: PrincipalDep, idea: IdeaParam) -> None:
    raise NotImplementedProblem


@router.post(
    "/ideas/{idea}/submission/erase",
    operation_id="erase_submitter",
    summary="Erase the submitter's details",
    description=(
        "public.erase_submitter (project and platform admins, session only). Removes the "
        "name, address, confirmation and update preference, ends the tracking link and "
        "deletes the idea's submitter emails; the idea stays. Idempotent. Audited without "
        "personal data. 404 when the idea didn't come through the public form."
    ),
    responses=problems(401, 403, 404),
)
async def erase_submitter(principal: PrincipalDep, idea: IdeaParam) -> IdeaSubmission:
    raise NotImplementedProblem
