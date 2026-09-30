"""An idea's activity feed and its comments."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.pagination import PageParamsDep
from app.schemas.activity import ActivityPage, CommentActivity
from app.schemas.comments import CommentCreate, CommentUpdate

router = APIRouter(tags=["activity"])


@router.get(
    "/ideas/{idea}/activity",
    operation_id="list_idea_activity",
    summary="Activity feed",
    description="Comments and events, newest first. Never contains scores.",
    responses=problems(400, 401, 404),
)
async def list_idea_activity(
    principal: PrincipalDep, idea: IdeaParam, page: PageParamsDep
) -> ActivityPage:
    raise NotImplementedProblem


@router.post(
    "/ideas/{idea}/comments",
    operation_id="create_comment",
    status_code=status.HTTP_201_CREATED,
    summary="Comment on an idea",
    description="Members and admins. Returns the new feed item; the author watches the idea.",
    responses=problems(401, 403, 404, 409, 422),
)
async def create_comment(
    principal: PrincipalDep, idea: IdeaParam, body: CommentCreate
) -> CommentActivity:
    raise NotImplementedProblem


@router.patch(
    "/comments/{comment_id}",
    operation_id="update_comment",
    summary="Edit a comment",
    description="The author only (403 not_author); sets edited_at. Deleted comments are 404.",
    responses=problems(401, 403, 404, 409, 422),
)
async def update_comment(
    principal: PrincipalDep, comment_id: UUID, body: CommentUpdate
) -> CommentActivity:
    raise NotImplementedProblem


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
async def delete_comment(principal: PrincipalDep, comment_id: UUID) -> None:
    raise NotImplementedProblem
