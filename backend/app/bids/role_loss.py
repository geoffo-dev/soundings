"""Section assessors who lose their role in a private project (review ACC-5, lead default,
to confirm): their assignments on the project's unfinished calls where they haven't
submitted anything are removed, with their drafts, audited ``bid_call.assessors_change``
with ``reason: left_project``, as Phase 8b clears a researcher. An assignment with a
submitted assessment stays (its scores count, and nothing expects more of it: c28 is checked
live). So someone added back to the project later gets no bids, documents or drafts back
until a call manager asks them again ("Asked to assess bids").

:func:`app.services.research_assignment.roles_before` and ``end_after_role_loss`` call
these, so every path that removes project roles covers both. Locks: the projects
``FOR KEY SHARE``, then the calls ``FOR UPDATE``, each by id (the idea row isn't written).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import and_, delete, exists, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.bid import BidAssessment, BidCall, BidSectionAssessor
from app.models.enums import BidCallStatus, EvaluationStatus, ProjectVisibility
from app.models.idea import Idea
from app.models.project import Project, project_effective_roles
from app.notifications import bids as bid_notifications
from app.services import audit

__all__ = ["AssessorSnapshot", "assessors_before", "end_after_role_loss"]

_roles = project_effective_roles
_FINISHED: Final = (BidCallStatus.AWARDED, BidCallStatus.CANCELLED)


@dataclass(frozen=True, slots=True)
class AssessorSnapshot:
    """Assignments on unfinished calls in private projects whose assessor held a role there
    before a change: ``(call id, idea id, project id, user id)``."""

    held: tuple[tuple[UUID, UUID, UUID, UUID], ...] = ()


async def assessors_before(
    db: AsyncSession,
    *,
    user_ids: Iterable[UUID] | None = None,
    project_ids: Iterable[UUID] | None = None,
) -> AssessorSnapshot:
    """Take before a change that may take roles away."""
    statement = (
        select(BidSectionAssessor.call_id, Idea.id, Idea.project_id, BidSectionAssessor.user_id)
        .distinct()
        .join(BidCall, BidCall.id == BidSectionAssessor.call_id)
        .join(Idea, Idea.id == BidCall.idea_id)
        .join(Project, Project.id == Idea.project_id)
        .join(
            _roles,
            and_(
                _roles.c.project_id == Idea.project_id,
                _roles.c.user_id == BidSectionAssessor.user_id,
            ),
        )
        .where(Project.visibility == ProjectVisibility.PRIVATE, BidCall.status.not_in(_FINISHED))
    )
    if user_ids is not None:
        users = list(user_ids)
        if not users:
            return AssessorSnapshot()
        statement = statement.where(BidSectionAssessor.user_id.in_(users))
    if project_ids is not None:
        projects = list(project_ids)
        if not projects:
            return AssessorSnapshot()
        statement = statement.where(Idea.project_id.in_(projects))
    rows = (await db.execute(statement)).all()
    return AssessorSnapshot(held=tuple((c, i, p, u) for c, i, p, u in rows))


async def end_after_role_loss(
    db: AsyncSession, before: AssessorSnapshot, *, actor: Principal | UUID | None
) -> int:
    """After the change (flushed by the caller): remove the unsubmitted assignments of the
    people in ``before`` who have no role in the project now. Returns how many sections'
    assignments were removed."""
    if not before.held:
        return 0
    pairs = {(project, user) for _, _, project, user in before.held}
    still = set(
        (
            await db.execute(
                select(_roles.c.project_id, _roles.c.user_id).where(
                    tuple_(_roles.c.project_id, _roles.c.user_id).in_(sorted(pairs))
                )
            )
        ).all()
    )
    lost = sorted(held for held in set(before.held) if (held[2], held[3]) not in still)
    if not lost:
        return 0
    await db.execute(
        select(Project.id)
        .where(Project.id.in_(sorted({project for _, _, project, _ in lost})))
        .order_by(Project.id)
        .with_for_update(read=True, key_share=True)
    )
    calls = {
        call.id: call
        for call in await db.scalars(
            select(BidCall)
            .where(BidCall.id.in_(sorted({call for call, _, _, _ in lost})))
            .order_by(BidCall.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    removed_total = 0
    by_call: dict[UUID, list[tuple[UUID, UUID, UUID]]] = defaultdict(list)
    for call_id, idea_id, project_id, user_id in lost:
        by_call[call_id].append((idea_id, project_id, user_id))
    for call_id, people in sorted(by_call.items()):
        call = calls.get(call_id)
        if call is None or call.status in _FINISHED:
            continue  # deleted or finished meanwhile: nothing to remove
        users = sorted({user for _, _, user in people})
        submitted = exists().where(
            BidAssessment.call_id == BidSectionAssessor.call_id,
            BidAssessment.section_id == BidSectionAssessor.section_id,
            BidAssessment.assessor_id == BidSectionAssessor.user_id,
            BidAssessment.status == EvaluationStatus.SUBMITTED,
        )
        rows = (
            await db.execute(
                select(BidSectionAssessor.section_id, BidSectionAssessor.user_id)
                .where(
                    BidSectionAssessor.call_id == call_id,
                    BidSectionAssessor.user_id.in_(users),
                    ~submitted,
                )
                .order_by(BidSectionAssessor.section_id, BidSectionAssessor.user_id)
            )
        ).all()
        if not rows:
            continue
        removed: dict[str, list[UUID]] = defaultdict(list)
        for section_id, user_id in rows:
            removed[str(section_id)].append(user_id)
        await db.execute(
            delete(BidSectionAssessor).where(
                BidSectionAssessor.call_id == call_id,
                tuple_(BidSectionAssessor.section_id, BidSectionAssessor.user_id).in_(
                    [tuple(row) for row in rows]
                ),
            )
        )
        idea_id, project_id, _ = people[0]
        await audit.record(
            db,
            "bid_call.assessors_change",
            actor=actor,
            target_type="idea",
            target_id=idea_id,
            project_id=project_id,
            details={
                "call_id": call_id,
                "added": {},
                "removed": dict(removed),
                "due_at_changed": False,
                "reason": "left_project",
            },
        )
        bid_notifications.queue_completion_check(
            db, call_id, actor.user_id if isinstance(actor, Principal) else actor
        )
        removed_total += len(rows)
    await db.flush()
    return removed_total
