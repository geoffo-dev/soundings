"""My work: the home screen, its counts, every evaluation due, the research I do (Phase
8b) and every idea I own."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.db import SessionDep
from app.errors import NotImplementedProblem
from app.models.enums import IdeaStatus
from app.pagination import PageParamsDep
from app.schemas.ideas import IdeaPage
from app.schemas.work import Work, WorkCounts, WorkEvaluationPage, WorkResearchPage
from app.services import work

router = APIRouter(prefix="/me", tags=["work"])


@router.get(
    "/work",
    operation_id="get_my_work",
    summary="My work",
    description=(
        "Evaluations due, research to do (Phase 8b), ideas I own by status (the first 10 of "
        "each group), recent ideas, sidebar counts."
    ),
    responses=problems(401),
)
async def get_my_work(principal: PrincipalDep, session: SessionDep) -> Work:
    return await work.get_my_work(session, principal)


@router.get(
    "/work/counts",
    operation_id="get_my_work_counts",
    summary="My work counts (sidebar badges)",
    description=(
        "The sidebar's badges alone: evaluations you owe (and how many are overdue), the "
        "research you do that is still to do (and how many are overdue; Phase 8b) and the "
        "ideas you own that are not closed. The same numbers as GET /me/work's counts."
    ),
    responses=problems(401),
)
async def get_my_work_counts(principal: PrincipalDep, session: SessionDep) -> WorkCounts:
    return await work.get_work_counts(session, principal)


@router.get(
    "/evaluations-due",
    operation_id="list_my_evaluations_due",
    summary="Evaluations I owe",
    description=(
        "Every evaluation you owe, in My work's order (overdue first, then soonest due, no "
        "due date last). 'Show all' in My work: cursor=<work.evaluations_due_next_cursor>."
    ),
    responses=problems(400, 401),
)
async def list_my_evaluations_due(
    principal: PrincipalDep, session: SessionDep, page: PageParamsDep
) -> WorkEvaluationPage:
    return await work.list_evaluations_due(session, principal, cursor=page.cursor, limit=page.limit)


@router.get(
    "/research-to-do",
    operation_id="list_my_research_to_do",
    summary="Research I do",
    description=(
        "Phase 8b: every idea whose research you do (as its researcher, or as its owner "
        "while nobody is assigned) and that still needs it (the step on, the idea in "
        "Research or before it with a required item open; for an owner: in Research or the "
        "status right before it, or with a research due date; only ideas you may answer), "
        "in My work's order (overdue first, then soonest due, no due date last; then by "
        "idea id). 'Show all' in My work: "
        "cursor=<work.research_to_do_next_cursor>. Includes ideas you see only as a guest "
        "researcher; never held ideas or archived projects."
    ),
    responses=problems(400, 401),
)
async def list_my_research_to_do(
    principal: PrincipalDep, session: SessionDep, page: PageParamsDep
) -> WorkResearchPage:
    raise NotImplementedProblem


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
