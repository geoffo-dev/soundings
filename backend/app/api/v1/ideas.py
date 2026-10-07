"""Ideas: list/board, the idea page, status, owner, evaluators, votes and watching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.authz import Rule, load_project
from app.db import SessionDep
from app.models.enums import IdeaStatus, Resolution
from app.pagination import MAX_LIMIT, PageParamsDep
from app.schemas.base import NoNul, TagName
from app.schemas.ideas import (
    Board,
    EvaluationDueDate,
    EvaluatorsAdd,
    IdeaCreate,
    IdeaDetail,
    IdeaPage,
    IdeaSort,
    IdeaUpdate,
    OwnerAssign,
    StatusChange,
    VoteState,
    WatchState,
)
from app.services import board, evaluations, ideas, votes

router = APIRouter(tags=["ideas"])

IdeaParam = Annotated[
    str,
    Path(
        max_length=36,
        pattern=r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        r"|[A-Za-z][A-Za-z0-9]{1,5}-[1-9][0-9]{0,8})$",
        description='The idea: its id (UUID) or its key such as "CUST-12" (any case).',
    ),
]
"""``{idea}`` in every ``/ideas/{idea}...`` path: one parameter name, UUID or key."""

OwnerFilter = UUID | Literal["me", "none"]

StatusFilter = Annotated[
    list[IdeaStatus] | None, Query(alias="status", description="Only these statuses.")
]
ResolutionFilter = Annotated[
    list[Resolution] | None,
    Query(description="Only closed ideas with these resolutions (the expanded Closed column)."),
]


@dataclass(frozen=True, slots=True)
class IdeaFilters:
    """Filters shared by the list and the board (the filter chips)."""

    owner: OwnerFilter | None
    tag: list[str]
    needs_evaluators: bool
    high_disagreement: bool
    q: str | None
    sort: IdeaSort


def idea_filters(
    owner: Annotated[
        OwnerFilter | None,
        Query(description='A user id, "me", or "none" (unowned).'),
    ] = None,
    tag: Annotated[
        list[TagName] | None,
        Query(max_length=10, description="Tag names (case-insensitive); ideas with any of them."),
    ] = None,
    needs_evaluators: Annotated[
        bool, Query(description="Only ideas that are not closed and have no evaluators.")
    ] = False,
    high_disagreement: Annotated[
        bool,
        Query(description="Only ideas flagged high disagreement (and not hidden from you)."),
    ] = False,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Text in the title or summary (case-insensitive), or an idea key.",
        ),
        NoNul,
    ] = None,
    sort: Annotated[IdeaSort, Query(description="Order; '-' prefix = descending.")] = "-updated",
) -> IdeaFilters:
    return IdeaFilters(
        owner=owner,
        tag=tag or [],
        needs_evaluators=needs_evaluators,
        high_disagreement=high_disagreement,
        q=q,
        sort=sort,
    )


IdeaFiltersDep = Annotated[IdeaFilters, Depends(idea_filters)]


def _filter(
    filters: IdeaFilters,
    statuses: list[IdeaStatus] | None = None,
    resolutions: list[Resolution] | None = None,
) -> board.IdeaFilter:
    return board.IdeaFilter(
        statuses=statuses or (),
        resolutions=resolutions or (),
        owner=filters.owner,
        tags=filters.tag,
        needs_evaluators=filters.needs_evaluators,
        high_disagreement=filters.high_disagreement,
        q=filters.q,
    )


# --- Lists ---------------------------------------------------------------------------
@router.get(
    "/projects/{slug}/ideas",
    operation_id="list_ideas",
    summary="List ideas",
    description=(
        "The List view, and 'load more' for a board column. Filters combine with AND; "
        "status, resolution and tag values combine with OR."
    ),
    responses=problems(400, 401, 404),
)
async def list_ideas(
    principal: PrincipalDep,
    session: SessionDep,
    slug: ProjectSlug,
    filters: IdeaFiltersDep,
    page: PageParamsDep,
    status_: StatusFilter = None,
    resolution: ResolutionFilter = None,
) -> IdeaPage:
    project, resource = await load_project(session, principal, slug)
    return await board.list_ideas(
        session,
        principal,
        project,
        resource.role,
        _filter(filters, status_, resolution),
        board.Sort(filters.sort),
        cursor=page.cursor,
        limit=page.limit,
    )


@router.get(
    "/projects/{slug}/board",
    operation_id="get_board",
    summary="Board: ideas by status",
    description=(
        "All five status columns with their counts and first page of ideas, using the "
        "same filters and sort as the list. Load more of a column with list_ideas "
        "(status=<column>, same filters, cursor=<column.next_cursor>)."
    ),
    responses=problems(401, 404),
)
async def get_board(
    principal: PrincipalDep,
    session: SessionDep,
    slug: ProjectSlug,
    filters: IdeaFiltersDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Ideas per column.")] = 50,
) -> Board:
    project, resource = await load_project(session, principal, slug)
    return await board.get_board(
        session,
        principal,
        project,
        resource.role,
        _filter(filters),
        board.Sort(filters.sort),
        limit=limit,
    )


# --- Create / read / update / delete -------------------------------------------------
@router.post(
    "/projects/{slug}/ideas",
    operation_id="create_idea",
    status_code=status.HTTP_201_CREATED,
    summary="Submit an idea",
    description="Members and admins. Starts in New, unowned; the submitter watches it.",
    responses=problems(401, 403, 404, 409, 422),
)
async def create_idea(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug, body: IdeaCreate
) -> IdeaDetail:
    project, resource = await load_project(session, principal, slug, Rule.IDEA_CREATE)
    idea = await ideas.create_idea(session, principal, project, body)
    return await ideas.idea_detail(session, principal, ideas.LoadedIdea(idea, project, resource))


@router.get(
    "/ideas/{idea}",
    operation_id="get_idea",
    summary="Get an idea (the idea page)",
    responses=problems(401, 404),
)
async def get_idea(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea)
    return await ideas.idea_detail(session, principal, loaded, reread=False)


@router.patch(
    "/ideas/{idea}",
    operation_id="update_idea",
    summary="Edit an idea",
    description=(
        "Submitter while the idea is new (else 409 idea_not_new), owner while it is not "
        "closed (409 idea_closed), project admins always. Omitted or null fields are "
        "unchanged."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_idea(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: IdeaUpdate
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await ideas.update_idea(session, principal, loaded, body)
    return await ideas.idea_detail(session, principal, loaded)


@router.delete(
    "/ideas/{idea}",
    operation_id="delete_idea",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an idea",
    description=(
        "Project admins. Permanent, with its evaluations and comments (the SPA confirms "
        "first; there is no undo)."
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_idea(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> None:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await ideas.delete_idea(session, principal, loaded)


# --- Status and owner ----------------------------------------------------------------
@router.post(
    "/ideas/{idea}/status",
    operation_id="change_idea_status",
    summary="Move an idea to a status",
    description=(
        "Owner or project admin; any status to any status. Closing requires a "
        "resolution; leaving closed clears it. Same status and resolution is a no-op. "
        "No side effects (moving to evaluating does not set a due date), so the "
        "inverse call undoes a move."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def change_idea_status(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: StatusChange
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await ideas.change_status(session, principal, loaded, body)
    return await ideas.idea_detail(session, principal, loaded)


@router.put(
    "/ideas/{idea}/owner",
    operation_id="set_idea_owner",
    summary="Assign or unassign the owner",
    description=(
        "Project admins assign anyone eligible or clear it (idea.assign_owner); the "
        "owner may only send null to step down (idea.release_owner). 422 "
        "assignee_not_eligible unless the new owner's role is member or admin."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def set_idea_owner(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: OwnerAssign
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await ideas.set_owner(session, principal, loaded, body.user_id)
    return await ideas.idea_detail(session, principal, loaded)


@router.post(
    "/ideas/{idea}/volunteer",
    operation_id="volunteer_as_owner",
    summary="I'll own this",
    description=(
        "Members (if the project allows volunteers, else 403 volunteering_disabled) and "
        "project admins. 422 assignee_not_eligible for a platform admin without a "
        "project role; 409 idea_has_owner; 409 idea_closed."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def volunteer_as_owner(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await ideas.volunteer(session, principal, loaded)
    return await ideas.idea_detail(session, principal, loaded)


# --- Evaluators and the evaluation window --------------------------------------------
@router.post(
    "/ideas/{idea}/evaluators",
    operation_id="add_evaluators",
    summary="Invite evaluators",
    description=(
        "Owner or project admin. Evaluators need effective role member or admin (422 "
        "assignee_not_eligible). 409 evaluation_closed unless evaluation is open. The "
        "first invite sets the default due date when the idea has none."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def add_evaluators(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: EvaluatorsAdd
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await evaluations.add_evaluators(session, principal, loaded, body)
    return await ideas.idea_detail(session, principal, loaded)


@router.delete(
    "/ideas/{idea}/evaluators/{user_id}",
    operation_id="remove_evaluator",
    summary="Remove an evaluator",
    description=(
        "Owner or project admin, whether evaluation is open or closed; deletes their "
        "draft. 403 cannot_remove_self (never yourself); 404 if not assigned; 409 "
        "evaluator_has_submitted once they have submitted."
    ),
    responses=problems(401, 403, 404, 409),
)
async def remove_evaluator(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, user_id: UUID
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await evaluations.remove_evaluator(session, principal, loaded, user_id)
    return await ideas.idea_detail(session, principal, loaded)


@router.put(
    "/ideas/{idea}/evaluation/due-date",
    operation_id="set_evaluation_due_date",
    summary="Set or clear the evaluation due date",
    description=(
        "Owner or project admin. The body is the complete new value: due_at null means "
        "no due date. 409 evaluation_closed unless evaluation is open."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def set_evaluation_due_date(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: EvaluationDueDate
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await evaluations.set_due_date(session, principal, loaded, body.due_at)
    return await ideas.idea_detail(session, principal, loaded)


@router.post(
    "/ideas/{idea}/evaluation/close",
    operation_id="close_evaluation",
    summary="Close evaluation",
    description=(
        "Owner or project admin. Evaluations can no longer be saved; drafts stay out of "
        "the aggregate and their authors stay blind. Idempotent. 409 idea_closed."
    ),
    responses=problems(401, 403, 404, 409),
)
async def close_evaluation(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await evaluations.set_evaluation_closed(session, principal, loaded, closed=True)
    return await ideas.idea_detail(session, principal, loaded)


@router.post(
    "/ideas/{idea}/evaluation/reopen",
    operation_id="reopen_evaluation",
    summary="Reopen evaluation",
    description="Owner or project admin. Idempotent. 409 idea_closed.",
    responses=problems(401, 403, 404, 409),
)
async def reopen_evaluation(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> IdeaDetail:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await evaluations.set_evaluation_closed(session, principal, loaded, closed=False)
    return await ideas.idea_detail(session, principal, loaded)


# --- Votes and watching --------------------------------------------------------------
@router.put(
    "/ideas/{idea}/vote",
    operation_id="vote_idea",
    summary="Upvote",
    description="Members and admins. Idempotent.",
    responses=problems(401, 403, 404, 409),
)
async def vote_idea(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> VoteState:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    return await votes.set_vote(session, principal, loaded, voted=True)


@router.delete(
    "/ideas/{idea}/vote",
    operation_id="unvote_idea",
    summary="Remove my upvote",
    description="Idempotent.",
    responses=problems(401, 403, 404, 409),
)
async def unvote_idea(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> VoteState:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    return await votes.set_vote(session, principal, loaded, voted=False)


@router.put(
    "/ideas/{idea}/watch",
    operation_id="watch_idea",
    summary="Watch",
    description="Anyone who can view the idea. Idempotent.",
    responses=problems(401, 404),
)
async def watch_idea(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> WatchState:
    loaded = await ideas.load_idea(session, principal, idea)
    return await votes.set_watch(session, principal, loaded, watching=True)


@router.delete(
    "/ideas/{idea}/watch",
    operation_id="unwatch_idea",
    summary="Stop watching",
    description="Idempotent.",
    responses=problems(401, 404),
)
async def unwatch_idea(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> WatchState:
    loaded = await ideas.load_idea(session, principal, idea)
    return await votes.set_watch(session, principal, loaded, watching=False)
