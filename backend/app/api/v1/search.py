"""Global search for the command palette."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.db import SessionDep
from app.schemas.search import SearchResults
from app.services import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    operation_id="global_search",
    summary="Search ideas and projects",
    description=(
        "Ideas (key, title, summary) and projects (name, slug) you can view. An exact "
        "idea key such as CUST-12 comes first."
    ),
    responses=problems(401),
)
async def global_search(
    principal: PrincipalDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search text.")],
    limit: Annotated[int, Query(ge=1, le=20, description="Max results per kind.")] = 8,
) -> SearchResults:
    # Rows are filtered by project.view / idea.view in SQL (app.authz.queries).
    return await search.global_search(session, principal, q, limit=limit)
