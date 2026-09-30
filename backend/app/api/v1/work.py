"""My work: the home screen, and the full list of ideas I own."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.db import SessionDep
from app.models.enums import IdeaStatus
from app.pagination import PageParamsDep
from app.schemas.ideas import IdeaPage
from app.schemas.work import Work
from app.services import work

router = APIRouter(prefix="/me", tags=["work"])


@router.get(
    "/work",
    operation_id="get_my_work",
    summary="My work",
    description="Evaluations due, ideas I own by status, recent ideas, sidebar counts.",
    responses=problems(401),
)
async def get_my_work(principal: PrincipalDep, session: SessionDep) -> Work:
    return await work.get_my_work(session, principal)


@router.get(
    "/owned-ideas",
    operation_id="list_my_owned_ideas",
    summary="Ideas I own, across projects",
    description=(
        "Ideas you own in non-archived projects, most recently active first. 'Load "
        "more' for a My work group: status=<group.status>, cursor=<group.next_cursor>."
    ),
    responses=problems(400, 401),
)
async def list_my_owned_ideas(
    principal: PrincipalDep,
    session: SessionDep,
    page: PageParamsDep,
    status_: Annotated[
        list[IdeaStatus] | None, Query(alias="status", description="Only these statuses.")
    ] = None,
) -> IdeaPage:
    return await work.list_my_owned_ideas(
        session, principal, status_ or [], cursor=page.cursor, limit=page.limit
    )
