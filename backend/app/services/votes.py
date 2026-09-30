"""Votes and watching (contract section 3.12). Both are idempotent toggles with no
activity event; votes keep ``ideas.vote_count`` in step atomically (the idea row is
locked by the caller)."""

from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, require
from app.domain.principal import Principal
from app.models.idea import Idea, IdeaVote, IdeaWatcher
from app.schemas.ideas import VoteState, WatchState
from app.services.ideas import LoadedIdea

__all__ = ["set_vote", "set_watch"]


async def set_vote(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, *, voted: bool
) -> VoteState:
    """``idea.vote``: add (``voted``) or remove your vote; allowed in any status."""
    require(principal, Rule.IDEA_VOTE, loaded.resource)
    idea = loaded.idea
    if voted:
        changed = await db.scalar(
            insert(IdeaVote)
            .values(idea_id=idea.id, user_id=principal.user_id)
            .on_conflict_do_nothing()
            .returning(IdeaVote.user_id)
        )
        delta = 1
    else:
        changed = await db.scalar(
            delete(IdeaVote)
            .where(IdeaVote.idea_id == idea.id, IdeaVote.user_id == principal.user_id)
            .returning(IdeaVote.user_id)
        )
        delta = -1
    count: int | None = idea.vote_count
    if changed is not None:
        count = await db.scalar(
            update(Idea)
            .where(Idea.id == idea.id)
            .values(vote_count=Idea.vote_count + delta)
            .returning(Idea.vote_count)
            .execution_options(synchronize_session=False)
        )
    return VoteState(vote_count=int(count or 0), has_voted=voted)


async def set_watch(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, *, watching: bool
) -> WatchState:
    """``idea.watch``: anyone who can view the idea, archived projects included."""
    require(principal, Rule.IDEA_WATCH, loaded.resource)
    idea = loaded.idea
    if watching:
        await db.execute(
            insert(IdeaWatcher)
            .values(idea_id=idea.id, user_id=principal.user_id)
            .on_conflict_do_nothing()
        )
    else:
        await db.execute(
            delete(IdeaWatcher).where(
                IdeaWatcher.idea_id == idea.id, IdeaWatcher.user_id == principal.user_id
            )
        )
    return WatchState(watching=watching)
