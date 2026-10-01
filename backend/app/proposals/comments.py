"""Margin comment threads on a proposal (docs/api/contract-phase4.md 3.3).

A thread is anchored to one section and opened with its first comment; replies are
flat. Anyone with ``proposal.comment`` (members and admins) opens, replies, resolves
and reopens (idempotent); a reply to a resolved thread reopens it. Comments are
deleted by their author (``comment.edit_own``, c2: else 403 ``not_author``) or a
project or platform admin (``comment.delete_any``): soft (``deleted_at``, text
cleared, shown as a stub); a thread whose comments are all deleted is no longer
listed (and answers 404). Caps: :data:`MAX_THREADS_PER_PROPOSAL` threads and
:data:`MAX_COMMENTS_PER_THREAD` comments per thread (409 ``too_many_comments``).

Not activity events and no notifications in Phase 4 (no ``NotificationType`` for
them: contract 3.3 and section 6).

Locks: callers load the idea with :func:`app.proposals.service.load_idea_shared`
(project ``FOR KEY SHARE``, idea ``FOR SHARE``); a new thread then locks the proposal
row and a reply, resolve or delete the thread row (``FOR UPDATE``), so the caps hold
under concurrent writes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import Exists, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, Rule, authorize, best_decision, can, idea_resource, require
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.proposal import Proposal as ProposalRow
from app.models.proposal import ProposalComment as CommentRow
from app.models.proposal import ProposalThread as ThreadRow
from app.proposals.service import SECTION_ORDER, require_proposal, user_refs
from app.schemas.proposals import (
    MAX_COMMENTS_PER_THREAD,
    MAX_THREADS_PER_PROPOSAL,
    ProposalComment,
    ProposalCommentCreate,
    ProposalThread,
    ProposalThreadCreate,
    ProposalThreadList,
)
from app.services.ideas import LoadedIdea

__all__ = [
    "create_thread",
    "delete_comment",
    "list_threads",
    "reply",
    "set_resolved",
]

_THREAD_NOT_FOUND = "This comment thread doesn't exist."


def _listed() -> Exists:
    """Threads with at least one comment that isn't deleted."""
    return exists().where(CommentRow.thread_id == ThreadRow.id, CommentRow.deleted_at.is_(None))


def _too_many(detail: str) -> ProblemError:
    return ProblemError(409, "too_many_comments", detail=detail)


def _can_delete(principal: Principal, resource: Resource, comment: CommentRow) -> bool:
    if comment.deleted_at is not None:
        return False
    return can(
        principal, Rule.COMMENT_EDIT_OWN, resource.replace(comment_author_id=comment.author_id)
    ) or can(principal, Rule.COMMENT_DELETE_ANY, resource)


async def _threads_out(
    db: AsyncSession, principal: Principal, resource: Resource, threads: Sequence[ThreadRow]
) -> list[ProposalThread]:
    ids = [thread.id for thread in threads]
    comments: dict[UUID, list[CommentRow]] = defaultdict(list)
    if ids:
        rows = await db.scalars(
            select(CommentRow)
            .where(CommentRow.thread_id.in_(ids))
            .order_by(CommentRow.created_at, CommentRow.id)
            .execution_options(populate_existing=True)
        )
        for comment in rows:
            comments[comment.thread_id].append(comment)
    users = await user_refs(
        db,
        [
            *(thread.resolved_by_id for thread in threads),
            *(comment.author_id for items in comments.values() for comment in items),
        ],
    )
    return [
        ProposalThread(
            id=thread.id,
            section_key=thread.section_key,
            created_at=thread.created_at,
            resolved_at=thread.resolved_at,
            resolved_by=users.get(thread.resolved_by_id) if thread.resolved_by_id else None,
            comments=[
                ProposalComment(
                    id=comment.id,
                    author=users.get(comment.author_id) if comment.author_id else None,
                    body_md="" if comment.deleted_at is not None else comment.body_md,
                    created_at=comment.created_at,
                    deleted=comment.deleted_at is not None,
                    can_delete=_can_delete(principal, resource, comment),
                )
                for comment in comments[thread.id]
            ],
        )
        for thread in threads
    ]


async def _thread_out(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, thread: ThreadRow
) -> ProposalThread:
    resource = await idea_resource(db, principal, loaded.idea, loaded.project)
    [out] = await _threads_out(db, principal, resource, [thread])
    return out


async def list_threads(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea
) -> ProposalThreadList:
    """Every listed thread, by section in template order, then oldest first."""
    proposal = await require_proposal(db, loaded)
    require(principal, Rule.PROPOSAL_VIEW, loaded.resource)
    threads = list(
        await db.scalars(
            select(ThreadRow)
            .where(ThreadRow.proposal_id == proposal.id, _listed())
            .order_by(ThreadRow.created_at, ThreadRow.id)
        )
    )
    threads.sort(key=lambda thread: SECTION_ORDER[thread.section_key])  # stable
    return ProposalThreadList(items=await _threads_out(db, principal, loaded.resource, threads))


async def _load_thread(db: AsyncSession, proposal: ProposalRow, thread_id: UUID) -> ThreadRow:
    """A listed thread of this proposal, locked for the change; else 404."""
    thread: ThreadRow | None = await db.scalar(
        select(ThreadRow)
        .where(ThreadRow.id == thread_id, ThreadRow.proposal_id == proposal.id, _listed())
        .with_for_update(of=ThreadRow)
        .execution_options(populate_existing=True)
    )
    if thread is None:
        raise ProblemError(404, "not_found", detail=_THREAD_NOT_FOUND)
    return thread


async def create_thread(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, body: ProposalThreadCreate
) -> ProposalThread:
    proposal = await require_proposal(db, loaded, for_update=True)
    require(principal, Rule.PROPOSAL_COMMENT, loaded.resource)
    count = await db.scalar(
        select(func.count()).select_from(ThreadRow).where(ThreadRow.proposal_id == proposal.id)
    )
    if (count or 0) >= MAX_THREADS_PER_PROPOSAL:
        raise _too_many(f"A proposal can have at most {MAX_THREADS_PER_PROPOSAL} threads.")
    now = utcnow()
    thread = ThreadRow(
        id=uuid4(),
        proposal_id=proposal.id,
        section_key=body.section_key,
        created_by_id=principal.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(thread)
    await db.flush()
    db.add(
        CommentRow(
            id=uuid4(),
            thread_id=thread.id,
            author_id=principal.user_id,
            body_md=body.body_md,
            created_at=now,
            updated_at=now,
        )
    )
    await db.flush()
    return await _thread_out(db, principal, loaded, thread)


async def reply(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    thread_id: UUID,
    body: ProposalCommentCreate,
) -> ProposalThread:
    """A reply; replying to a resolved thread reopens it."""
    proposal = await require_proposal(db, loaded)
    thread = await _load_thread(db, proposal, thread_id)
    require(principal, Rule.PROPOSAL_COMMENT, loaded.resource)
    count = await db.scalar(
        select(func.count()).select_from(CommentRow).where(CommentRow.thread_id == thread.id)
    )
    if (count or 0) >= MAX_COMMENTS_PER_THREAD:
        raise _too_many(f"A thread can have at most {MAX_COMMENTS_PER_THREAD} comments.")
    now = utcnow()
    db.add(
        CommentRow(
            id=uuid4(),
            thread_id=thread.id,
            author_id=principal.user_id,
            body_md=body.body_md,
            created_at=now,
            updated_at=now,
        )
    )
    thread.resolved_at = None
    thread.resolved_by_id = None
    thread.updated_at = now
    await db.flush()
    return await _thread_out(db, principal, loaded, thread)


async def set_resolved(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, thread_id: UUID, *, resolved: bool
) -> ProposalThread:
    """Resolve or reopen (idempotent: resolving a resolved thread keeps who did it)."""
    proposal = await require_proposal(db, loaded)
    thread = await _load_thread(db, proposal, thread_id)
    require(principal, Rule.PROPOSAL_COMMENT, loaded.resource)
    if resolved and thread.resolved_at is None:
        thread.resolved_at = utcnow()
        thread.resolved_by_id = principal.user_id
        await db.flush()
    elif not resolved and thread.resolved_at is not None:
        thread.resolved_at = None
        thread.resolved_by_id = None
        await db.flush()
    return await _thread_out(db, principal, loaded, thread)


async def delete_comment(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    thread_id: UUID,
    comment_id: UUID,
) -> None:
    """Soft-delete a comment: its author, or a project or platform admin. Idempotent."""
    proposal = await require_proposal(db, loaded)
    thread: ThreadRow | None = await db.scalar(
        select(ThreadRow)
        .where(ThreadRow.id == thread_id, ThreadRow.proposal_id == proposal.id)
        .with_for_update(of=ThreadRow)
    )
    comment: CommentRow | None = (
        None
        if thread is None
        else await db.scalar(
            select(CommentRow)
            .where(CommentRow.id == comment_id, CommentRow.thread_id == thread.id)
            .execution_options(populate_existing=True)
        )
    )
    if comment is None:
        raise ProblemError(404, "not_found", detail="This comment doesn't exist.")
    resource = loaded.resource.replace(comment_author_id=comment.author_id)
    decision = best_decision(
        authorize(principal, rule, resource)
        for rule in (Rule.COMMENT_EDIT_OWN, Rule.COMMENT_DELETE_ANY)
    )
    if not decision.allowed:
        if decision.code in ("forbidden", "not_author") and comment.author_id != principal.user_id:
            raise ProblemError(403, "not_author", detail="You can only delete your own comments.")
        raise decision.problem()
    if comment.deleted_at is None:
        comment.deleted_at = utcnow()
        comment.body_md = ""
        await db.flush()
