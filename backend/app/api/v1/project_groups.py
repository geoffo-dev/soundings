"""Project roles granted to groups, and everyone with access to a project.

Direct members stay in ``projects.py`` (``/projects/{slug}/members``). Business
rules: docs/api/contract-phase2.md section 3.7.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.models.enums import ProjectRole
from app.pagination import PageParamsDep
from app.schemas.base import NoNul
from app.schemas.groups import (
    ProjectAccessPage,
    ProjectGroupGrant,
    ProjectGroupGrantAdd,
    ProjectGroupGrantUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{slug}/groups",
    operation_id="list_project_group_grants",
    summary="List group grants",
    description=(
        "Anyone who can view the project (like members). Groups granted a role here, "
        "admins first, then by group name."
    ),
    responses=problems(401, 404),
)
async def list_project_group_grants(
    principal: PrincipalDep, slug: ProjectSlug
) -> list[ProjectGroupGrant]:
    raise NotImplementedProblem


@router.post(
    "/{slug}/groups",
    operation_id="add_project_group_grant",
    status_code=status.HTTP_201_CREATED,
    summary="Grant a group a role",
    description=(
        "Project admins (project.manage_members). Every member of the group gets the "
        "role (the highest of all their sources counts). 409 already_granted; 422 "
        "group_not_found."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def add_project_group_grant(
    principal: PrincipalDep, slug: ProjectSlug, body: ProjectGroupGrantAdd
) -> ProjectGroupGrant:
    raise NotImplementedProblem


@router.patch(
    "/{slug}/groups/{group_id}",
    operation_id="update_project_group_grant",
    summary="Change a group's role",
    description="Project admins (project.manage_members, c11). 404 not granted; 409 last_admin.",
    responses=problems(401, 403, 404, 409, 422),
)
async def update_project_group_grant(
    principal: PrincipalDep, slug: ProjectSlug, group_id: UUID, body: ProjectGroupGrantUpdate
) -> ProjectGroupGrant:
    raise NotImplementedProblem


@router.delete(
    "/{slug}/groups/{group_id}",
    operation_id="remove_project_group_grant",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a group grant",
    description=(
        "Project admins (project.manage_members, c11). Access through the group ends "
        "immediately. 404 not granted; 409 last_admin."
    ),
    responses=problems(401, 403, 404, 409),
)
async def remove_project_group_grant(
    principal: PrincipalDep, slug: ProjectSlug, group_id: UUID
) -> None:
    raise NotImplementedProblem


@router.get(
    "/{slug}/access",
    operation_id="list_project_access",
    summary="Everyone with access",
    description=(
        "Anyone who can view the project. Every active user with an effective role, by "
        "display name, with the sources of that role (direct, and each group). Not "
        "listed: platform admins without a role here, and (internal projects) the "
        "signed-in users who can view it without one. q matches name or email; role "
        "filters on the effective role."
    ),
    responses=problems(400, 401, 404),
)
async def list_project_access(
    principal: PrincipalDep,
    slug: ProjectSlug,
    page: PageParamsDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Part of a name or email."), NoNul
    ] = None,
    role: Annotated[ProjectRole | None, Query(description="Only this effective role.")] = None,
) -> ProjectAccessPage:
    raise NotImplementedProblem
