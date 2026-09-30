"""Projects, members, rubric and tags."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.base import SLUG_PATTERN
from app.schemas.projects import (
    Member,
    MemberAdd,
    MemberUpdate,
    Project,
    ProjectCreate,
    ProjectSummary,
    ProjectUpdate,
    TagInfo,
)
from app.schemas.rubric import Rubric, RubricUpdate

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectSlug = Annotated[str, Path(max_length=48, pattern=SLUG_PATTERN, description="Project slug.")]


@router.get(
    "",
    operation_id="list_projects",
    summary="List projects I can see",
    description=(
        "Projects you are a member of, plus internal projects (any signed-in user can "
        "view them), plus all projects for platform admins. Ordered by name. Each "
        "carries your permissions (can_create_ideas drives the submit dialog)."
    ),
    responses=problems(401),
)
async def list_projects(
    principal: PrincipalDep,
    include_archived: Annotated[bool, Query(description="Also list archived projects.")] = False,
) -> list[ProjectSummary]:
    raise NotImplementedProblem


@router.post(
    "",
    operation_id="create_project",
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    description=(
        "project.create (platform admins). admin_user_id (default: you) becomes the "
        "project admin; the project gets the default rubric. 409 slug_taken / key_taken; "
        "422 user_not_found."
    ),
    responses=problems(401, 403, 409, 422),
)
async def create_project(principal: PrincipalDep, body: ProjectCreate) -> Project:
    raise NotImplementedProblem


@router.get(
    "/{slug}",
    operation_id="get_project",
    summary="Get a project",
    description="Settings, resolved status labels, active rubric and your permissions.",
    responses=problems(401, 404),
)
async def get_project(principal: PrincipalDep, slug: ProjectSlug) -> Project:
    raise NotImplementedProblem


@router.patch(
    "/{slug}",
    operation_id="update_project",
    summary="Update project settings",
    description="Project admins. Omitted or null fields are unchanged.",
    responses=problems(401, 403, 404, 422),
)
async def update_project(
    principal: PrincipalDep, slug: ProjectSlug, body: ProjectUpdate
) -> Project:
    raise NotImplementedProblem


# --- Members -------------------------------------------------------------------------
@router.get(
    "/{slug}/members",
    operation_id="list_project_members",
    summary="List members",
    description="Direct members, admins first, then by name. Anyone who can view the project.",
    responses=problems(401, 404),
)
async def list_project_members(principal: PrincipalDep, slug: ProjectSlug) -> list[Member]:
    raise NotImplementedProblem


@router.post(
    "/{slug}/members",
    operation_id="add_project_member",
    status_code=status.HTTP_201_CREATED,
    summary="Add a member",
    description="Project admins. 409 already_member; 422 user_not_found for unknown/inactive.",
    responses=problems(401, 403, 404, 409, 422),
)
async def add_project_member(principal: PrincipalDep, slug: ProjectSlug, body: MemberAdd) -> Member:
    raise NotImplementedProblem


@router.patch(
    "/{slug}/members/{user_id}",
    operation_id="update_project_member",
    summary="Change a member's role",
    description="Project admins. 409 last_admin when demoting the only admin.",
    responses=problems(401, 403, 404, 409, 422),
)
async def update_project_member(
    principal: PrincipalDep, slug: ProjectSlug, user_id: UUID, body: MemberUpdate
) -> Member:
    raise NotImplementedProblem


@router.delete(
    "/{slug}/members/{user_id}",
    operation_id="remove_project_member",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
    description=(
        "Project admins. 409 last_admin. Owner/evaluator assignments are kept but grant "
        "nothing while the user has no member/admin role; reassign them if needed."
    ),
    responses=problems(401, 403, 404, 409),
)
async def remove_project_member(principal: PrincipalDep, slug: ProjectSlug, user_id: UUID) -> None:
    raise NotImplementedProblem


# --- Rubric and tags (read the rubric from get_project) -------------------------------
@router.put(
    "/{slug}/rubric",
    operation_id="replace_rubric",
    summary="Replace the rubric",
    description=(
        "Project admins. 3-6 criteria in display order; see RubricUpdate for removals. "
        "Recomputes every idea's aggregate. 422 unknown_criterion for a foreign id."
    ),
    responses=problems(401, 403, 404, 422),
)
async def replace_rubric(principal: PrincipalDep, slug: ProjectSlug, body: RubricUpdate) -> Rubric:
    raise NotImplementedProblem


@router.get(
    "/{slug}/tags",
    operation_id="list_project_tags",
    summary="List tags",
    description=(
        "Tags on at least one idea you can view, by name, with how many ideas use each. "
        "Unused tags are not listed."
    ),
    responses=problems(401, 404),
)
async def list_project_tags(principal: PrincipalDep, slug: ProjectSlug) -> list[TagInfo]:
    raise NotImplementedProblem
