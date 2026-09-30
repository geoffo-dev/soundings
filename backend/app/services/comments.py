"""Comments (contract section 3.12): flat Markdown comments in the activity feed.

Creating one inserts the ``comments`` row and its ``comment`` activity event; the
author watches the idea. Editing sets ``edited_at`` and deleting sets ``deleted_at``
and clears the body (the feed keeps a placeholder); neither is an event. Deleted
comments answer 404 to further edits and deletes.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, authorize, best_decision, not_found, require
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.activity import ActivityEvent, Comment
from app.models.base import utcnow
from app.schemas.activity import CommentActivity
from app.schemas.comments import CommentCreate, CommentUpdate
from app.services import activity
from app.services.feed import activity_items
from app.services.ideas import LoadedIdea, load_idea, watch

__all__ = ["create_comment", "delete_comment", "load_comment", "update_comment"]


async def _as_item(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, comment: Comment
) -> CommentActivity:
    event = await db.scalar(select(ActivityEvent).where(ActivityEvent.comment_id == comment.id))
    assert event is not None  # noqa: S101 - every comment has its event
    [item] = await activity_items(db, principal, [event], lambda _: loaded.resource)
    assert isinstance(item, CommentActivity)  # noqa: S101
    return item


async def create_comment(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, body: CommentCreate
) -> CommentActivity:
    require(principal, Rule.COMMENT_CREATE, loaded.resource)
    idea = loaded.idea
    comment = Comment(
        id=uuid4(), idea_id=idea.id, author_id=principal.user_id, body_md=body.body_md
    )
    db.add(comment)
    await db.flush()
    await activity.emit(db, idea, "comment", actor=principal, comment_id=comment.id)
    await watch(db, idea, principal.user_id)
    await db.flush()
    return await _as_item(db, principal, loaded, comment)


async def load_comment(
    db: AsyncSession, principal: Principal, comment_id: UUID
) -> tuple[Comment, LoadedIdea]:
    """A comment that is not deleted, on an idea the principal can view; else 404."""
    comment = await db.scalar(
        select(Comment).where(Comment.id == comment_id, Comment.deleted_at.is_(None))
    )
    if comment is None:
        raise not_found()
    loaded = await load_idea(db, principal, str(comment.idea_id))
    return comment, loaded


def _require_author(
    principal: Principal, comment: Comment, loaded: LoadedIdea, rules: Iterable[Rule]
) -> None:
    """``comment.edit_own`` (c2), or for deletes also ``comment.delete_any``. Someone
    else's comment is 403 ``not_author`` whatever the principal's role."""
    resource = loaded.resource.replace(comment_author_id=comment.author_id)
    decision = best_decision(authorize(principal, rule, resource) for rule in rules)
    if decision.allowed:
        return
    if decision.code in ("forbidden", "not_author") and comment.author_id != principal.user_id:
        raise ProblemError(403, "not_author", detail="You can only change your own comments.")
    raise decision.problem()


async def update_comment(
    db: AsyncSession,
    principal: Principal,
    comment: Comment,
    loaded: LoadedIdea,
    body: CommentUpdate,
) -> CommentActivity:
    _require_author(principal, comment, loaded, [Rule.COMMENT_EDIT_OWN])
    if body.body_md != comment.body_md:
        comment.body_md = body.body_md
        comment.edited_at = utcnow()
        await db.flush()
    return await _as_item(db, principal, loaded, comment)


async def delete_comment(
    db: AsyncSession, principal: Principal, comment: Comment, loaded: LoadedIdea
) -> None:
    _require_author(principal, comment, loaded, [Rule.COMMENT_EDIT_OWN, Rule.COMMENT_DELETE_ANY])
    comment.deleted_at = utcnow()
    comment.body_md = ""
    await db.flush()
