"""Group search for pickers (granting a group a project role)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.base import NoNul
from app.schemas.groups import GroupSearchResult

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get(
    "",
    operation_id="search_groups",
    summary="Search groups",
    description=(
        "Signed-in users (user.search: people and group pickers). Groups whose name "
        "contains q (case-insensitive), by name; at most limit."
    ),
    responses=problems(401),
)
async def search_groups(
    principal: PrincipalDep,
    q: Annotated[str | None, Query(max_length=80, description="Part of a name."), NoNul] = None,
    limit: Annotated[int, Query(ge=1, le=50, description="Most results to return.")] = 20,
) -> list[GroupSearchResult]:
    raise NotImplementedProblem
