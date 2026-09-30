"""People search for pickers (add member, assign owner, invite evaluators)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.pagination import PageParamsDep
from app.schemas.base import SLUG_PATTERN
from app.schemas.users import UserPage

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    operation_id="search_users",
    summary="Search users",
    description=(
        "Active, non-service-account users whose name or email contains q "
        "(case-insensitive), ordered by display name. With project, only members of "
        "that project are returned and each result carries project_role."
    ),
    responses=problems(400, 401, 404),
)
async def search_users(
    principal: PrincipalDep,
    page: PageParamsDep,
    q: Annotated[str | None, Query(max_length=100, description="Part of a name or email.")] = None,
    project: Annotated[
        str | None,
        Query(max_length=48, pattern=SLUG_PATTERN, description="Project slug: members only."),
    ] = None,
) -> UserPage:
    raise NotImplementedProblem
