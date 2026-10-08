"""People search for pickers (add member, assign owner, invite evaluators)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.authz import Rule, load_project, require, searches_co_members_only
from app.db import SessionDep
from app.errors import NotImplementedProblem
from app.pagination import PageParamsDep
from app.schemas.base import SLUG_PATTERN, NoNul
from app.schemas.users import UserPage
from app.services import users

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    operation_id="search_users",
    summary="Search users",
    description=(
        "Active, non-service-account users whose name or email contains q "
        "(case-insensitive), ordered by display name. With project, only members of "
        "that project are returned and each result carries project_role; Phase 8b: with "
        "project and include_non_members=true (the researcher picker), every active person "
        'is returned, members with their project_role and everyone else with null ("not '
        "in this project\"). An AI agent's service account finds only people who share a "
        "project with it (inside its key's projects)."
    ),
    responses=problems(400, 401, 404),
)
async def search_users(
    principal: PrincipalDep,
    page: PageParamsDep,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Part of a name or email."), NoNul
    ] = None,
    project: Annotated[
        str | None,
        Query(max_length=48, pattern=SLUG_PATTERN, description="Project slug: members only."),
    ] = None,
    include_non_members: Annotated[
        bool,
        Query(
            description=(
                "Phase 8b, with project: everyone active, not only members (project_role "
                "null for non-members). Needs project.view on the project, like project. "
                "Without project it changes nothing (the directory lists everyone)."
            )
        ),
    ] = False,
) -> UserPage:
    require(principal, Rule.USER_SEARCH)
    in_project = None
    if project is not None:
        in_project, _ = await load_project(session, principal, project)
        if include_non_members:  # Phase 8b: the researcher picker (backend builds it)
            raise NotImplementedProblem
    return await users.search_users(
        session,
        q=q,
        project=in_project,
        page=page,
        co_members_of=principal if searches_co_members_only(principal) else None,
    )
