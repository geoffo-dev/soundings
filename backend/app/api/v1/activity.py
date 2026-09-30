"""An idea's activity feed and its comments."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.db import SessionDep
from app.pagination import PageParamsDep
from app.schemas.activity import ActivityPage, CommentActivity
from app.schemas.comments import CommentCreate, CommentUpdate
from app.services import comments, feed, ideas

router = APIRouter(tags=["activity"])


@router.get(
    "/ideas/{idea}/activity",
    operation_id="list_idea_activity",
    summary="Activity feed",
    description="Comments and events, newest first. Never contains scores.",
    responses=problems(400, 401, 404),
)
async def list_idea_activity(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, page: PageParamsDep
) -> ActivityPage:
    loaded = await ideas.load_idea(session, principal, idea)
    return await feed.list_activity(
        session,
        principal,
        loaded.idea.id,
        loaded.resource,
        cursor=page.cursor,
        limit=page.limit,
    )


@router.post(
    "/ideas/{idea}/comments",
    operation_id="create_comment",
    status_code=status.HTTP_201_CREATED,
    summary="Comment on an idea",
    description="Members and admins. Returns the new feed item; the author watches the idea.",
    responses=problems(401, 403, 404, 409, 422),
)
async def create_comment(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: CommentCreate
) -> CommentActivity:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    return await comments.create_comment(session, principal, loaded, body)


@router.patch(
    "/comments/{comment_id}",
    operation_id="update_comment",
    summary="Edit a comment",
    description="The author only (403 not_author); sets edited_at. Deleted comments are 404.",
    responses=problems(401, 403, 404, 409, 422),
)
async def update_comment(
    principal: PrincipalDep, session: SessionDep, comment_id: UUID, body: CommentUpdate
) -> CommentActivity:
    comment, loaded = await comments.load_comment(session, principal, comment_id)
    return await comments.update_comment(session, principal, comment, loaded, body)


@router.delete(
    "/comments/{comment_id}",
    operation_id="delete_comment",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a comment",
    description=(
        "The author (403 not_author) or a project admin. Leaves a 'comment deleted' "
        "placeholder in the feed."
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_comment(principal: PrincipalDep, session: SessionDep, comment_id: UUID) -> None:
    comment, loaded = await comments.load_comment(session, principal, comment_id)
    await comments.delete_comment(session, principal, comment, loaded)
