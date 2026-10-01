"""Who may be told about an idea, and whether a notification still applies.

Used three times with the same rules (contract-phase3 sections 3.3, 3.7, 3.9): by the
fan-out when a notification is created, by the reminder scan, and by the worker just
before an email goes out. Permissions go through the policy (ADR 0010):
``idea.view`` for everyone, ``evaluation.submit_own`` for the evaluator types; facts
about the idea (its owner, due date, a comment's state) are plain data checks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import IdeaFacts, ProjectFacts, Resource, Rule, can, effective_roles_of
from app.domain.principal import Principal
from app.models.activity import Comment
from app.models.enums import EvaluationStatus, EvaluatorState, NotificationType
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project
from app.models.user import User
from app.schemas.comments import mentioned_user_ids
from app.services.sql import any_of

__all__ = [
    "Recipient",
    "applies",
    "evaluator_ids",
    "notifiable_users",
    "parse_time",
    "parse_uuid",
    "recipients",
    "submitted_count",
]


@dataclass(frozen=True, slots=True)
class Recipient:
    """A user who may be notified about one idea: their principal and the policy
    facts (effective role, evaluator state) for decisions about it."""

    user: User
    principal: Principal
    resource: Resource

    @property
    def id(self) -> UUID:
        return self.user.id


def notifiable_users() -> Any:
    """``WHERE`` over ``users``: people who can ever be notified (active, a person, not
    the break-glass account)."""
    return (
        User.is_active.is_(True)
        & User.is_service_account.is_(False)
        & User.is_break_glass.is_(False)
    )


async def _evaluator_states(
    db: AsyncSession, idea_id: UUID, user_ids: list[UUID]
) -> dict[UUID, EvaluatorState]:
    rows = await db.execute(
        select(IdeaEvaluator.user_id, Evaluation.status)
        .outerjoin(
            Evaluation,
            (Evaluation.idea_id == IdeaEvaluator.idea_id)
            & (Evaluation.evaluator_id == IdeaEvaluator.user_id),
        )
        .where(IdeaEvaluator.idea_id == idea_id, any_of(IdeaEvaluator.user_id, user_ids))
    )
    states: dict[UUID, EvaluatorState] = {}
    for user_id, status in rows:
        states[user_id] = EvaluatorState.INVITED if status is None else EvaluatorState(status.value)
    return states


async def recipients(
    db: AsyncSession, idea: Idea, project: Project, user_ids: Iterable[UUID]
) -> dict[UUID, Recipient]:
    """Of ``user_ids``, those who may be notified about ``idea`` now: active people
    (not service accounts or the break-glass account) who pass ``idea.view``. Three
    queries for the whole set, in the given order."""
    wanted = list(dict.fromkeys(user_ids))
    if not wanted:
        return {}
    users = {
        user.id: user
        for user in await db.scalars(
            select(User).where(any_of(User.id, wanted), notifiable_users())
        )
    }
    if not users:
        return {}
    ids = [user_id for user_id in wanted if user_id in users]
    roles = await effective_roles_of(db, project.id, ids)
    states = await _evaluator_states(db, idea.id, ids)
    project_facts = ProjectFacts.of(project)
    found: dict[UUID, Recipient] = {}
    for user_id in ids:
        principal = Principal(user=users[user_id])
        resource = Resource(
            project=project_facts,
            role=roles.get(user_id),
            idea=IdeaFacts.of(idea, states.get(user_id)),
        )
        if can(principal, Rule.IDEA_VIEW, resource):
            found[user_id] = Recipient(users[user_id], principal, resource)
    return found


def parse_time(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def parse_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value else None


def _owes_evaluation(recipient: Recipient) -> bool:
    """An assigned evaluator who may submit now (``evaluation.submit_own``: member or
    admin, evaluation open, project not archived) and hasn't submitted."""
    facts = recipient.resource.idea
    return (
        facts is not None
        and facts.my_evaluation is not EvaluatorState.SUBMITTED
        and can(recipient.principal, Rule.EVALUATION_SUBMIT_OWN, recipient.resource)
    )


def applies(
    type_: NotificationType,
    recipient: Recipient,
    idea: Idea,
    *,
    payload: Mapping[str, Any],
    comment: Comment | None = None,
    now: datetime,
) -> bool:
    """The type's own condition (contract-phase3 section 3.3 table), for a recipient
    who already passed ``idea.view`` (:func:`recipients`)."""
    match type_:
        case NotificationType.OWNER_ASSIGNED | NotificationType.EVALUATIONS_COMPLETE:
            return idea.owner_id == recipient.id
        case NotificationType.EVALUATOR_INVITED:
            return _owes_evaluation(recipient)
        case NotificationType.EVALUATION_REMINDER:
            due_at = parse_time(payload.get("due_at"))
            return (
                _owes_evaluation(recipient)
                and due_at is not None
                and idea.evaluation_due_at == due_at
                and now < due_at
            )
        case NotificationType.STATUS_CHANGED:
            return True
        case NotificationType.COMMENT:
            return comment is not None and comment.deleted_at is None
        case NotificationType.MENTION:
            # People with a role in the project (not every viewer of an internal one).
            return (
                comment is not None
                and comment.deleted_at is None
                and recipient.resource.role is not None
                and recipient.id in mentioned_user_ids(comment.body_md)
            )


async def evaluator_ids(db: AsyncSession, idea_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(IdeaEvaluator.user_id)
            .where(IdeaEvaluator.idea_id == idea_id)
            .order_by(IdeaEvaluator.invited_at, IdeaEvaluator.user_id)
        )
    )


async def submitted_count(db: AsyncSession, idea_id: UUID) -> tuple[int, int]:
    """``(assigned, submitted)`` evaluators of the idea (AI evaluators included)."""
    rows = await db.execute(
        select(IdeaEvaluator.user_id, Evaluation.status)
        .outerjoin(
            Evaluation,
            (Evaluation.idea_id == IdeaEvaluator.idea_id)
            & (Evaluation.evaluator_id == IdeaEvaluator.user_id),
        )
        .where(IdeaEvaluator.idea_id == idea_id)
    )
    statuses = [status for _, status in rows]
    return len(statuses), sum(1 for status in statuses if status is EvaluationStatus.SUBMITTED)
