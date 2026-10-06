"""Evaluators, the evaluation window (contract section 3.5), your own evaluation (3.6)
and the blind-filtered list of submitted evaluations (3.7).

"Evaluation is open" = ``evaluation_closed_at IS NULL`` and the idea is not closed
(condition c6). Every first submission and every save of a submitted evaluation
recomputes the idea's cached aggregate in the same transaction (3.8).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, authorize, require
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import EvaluationStatus, EvaluatorState
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.idea import IdeaEvaluator
from app.models.project import RubricCriterion
from app.models.user import User
from app.schemas.common import FieldError
from app.schemas.evaluations import (
    Evaluation as EvaluationOut,
)
from app.schemas.evaluations import (
    EvaluationList,
    MyEvaluation,
    MyEvaluationIn,
    MyScore,
)
from app.schemas.evaluations import (
    EvaluationScore as EvaluationScoreOut,
)
from app.schemas.ideas import EvaluatorsAdd
from app.schemas.users import UserRef
from app.services import activity, audit
from app.services.ideas import LoadedIdea, assignee_roles, watch
from app.services.scoring import active_criteria, recompute_aggregates
from app.services.sql import any_of

__all__ = [
    "add_evaluators",
    "list_evaluations",
    "my_evaluation",
    "remove_evaluator",
    "save_my_evaluation",
    "set_due_date",
    "set_evaluation_closed",
]

_MISSING_SCORE: Final = "Score this criterion."
_MISSING_RECOMMENDATION: Final = "Choose a recommendation."


async def _rubric(db: AsyncSession, loaded: LoadedIdea) -> list[RubricCriterion]:
    return (await active_criteria(db, [loaded.project.id])).get(loaded.project.id, [])


async def _refresh_aggregate(db: AsyncSession, loaded: LoadedIdea) -> None:
    await recompute_aggregates(db, idea_ids=[loaded.idea.id])
    await db.refresh(loaded.idea)


async def _set_due(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, due_at: datetime | None
) -> None:
    idea = loaded.idea
    previous = idea.evaluation_due_at
    if due_at is not None:
        due_at = due_at.astimezone(UTC)  # stored and reported in UTC
    if previous == due_at:
        return
    idea.evaluation_due_at = due_at
    await activity.emit(
        db,
        idea,
        "due_date_changed",
        actor=principal,
        payload={"from_due_at": previous, "to_due_at": due_at},
    )


# --- Evaluators ------------------------------------------------------------------------------
async def add_evaluators(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, body: EvaluatorsAdd
) -> None:
    """Invite: every new evaluator needs member/admin (c4, all or nothing); users already
    assigned are skipped. Only the first invite sets the default due date."""
    idea = loaded.idea
    assigned = set(
        await db.scalars(select(IdeaEvaluator.user_id).where(IdeaEvaluator.idea_id == idea.id))
    )
    new = [user_id for user_id in dict.fromkeys(body.user_ids) if user_id not in assigned]
    roles = await assignee_roles(db, loaded.project.id, new)
    require(
        principal,
        Rule.EVALUATOR_MANAGE,
        loaded.resource.replace(assignee_roles=tuple(roles[user_id] for user_id in new)),
    )
    now = utcnow()
    for offset, user_id in enumerate(new):
        # Distinct microseconds keep the request's order as the invitation order.
        invited_at = now + timedelta(microseconds=offset)
        db.add(
            IdeaEvaluator(
                idea_id=idea.id,
                user_id=user_id,
                invited_by_id=principal.user_id,
                invited_at=invited_at,
            )
        )
        await db.flush()
        await watch(db, idea, user_id)
        await activity.emit(
            db, idea, "evaluator_added", actor=principal, payload={"evaluator_id": user_id}
        )
        await audit.record(
            db,
            "evaluator.add",
            actor=principal,
            target_type="user",
            target_id=user_id,
            project_id=idea.project_id,
            details={"rule": Rule.EVALUATOR_MANAGE, "idea_id": idea.id},
        )
    if body.due_at is not None:
        await _set_due(db, principal, loaded, body.due_at)
    elif not assigned and new and idea.evaluation_due_at is None:
        # The first invite: evaluators are never overdue on arrival (no event).
        idea.evaluation_due_at = now + timedelta(days=loaded.project.default_evaluation_days)
    await db.flush()


async def remove_evaluator(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, user_id: UUID
) -> None:
    """Whatever the evaluation state: never yourself (c16), 404 if not assigned, 409
    once they submitted. Their draft goes with the assignment."""
    require(principal, Rule.EVALUATOR_MANAGE, loaded.resource.replace(evaluator_to_remove=user_id))
    idea = loaded.idea
    assignment = await db.get(IdeaEvaluator, (idea.id, user_id))
    if assignment is None:
        raise NotFoundProblem("That person is not an evaluator of this idea.")
    status = await db.scalar(
        select(Evaluation.status).where(
            Evaluation.idea_id == idea.id, Evaluation.evaluator_id == user_id
        )
    )
    if status is EvaluationStatus.SUBMITTED:
        raise ConflictProblem(
            "They have submitted; submitted evaluations are kept.", code="evaluator_has_submitted"
        )
    await db.delete(assignment)  # the database cascades to the draft and its scores
    await activity.emit(
        db, idea, "evaluator_removed", actor=principal, payload={"evaluator_id": user_id}
    )
    await audit.record(
        db,
        "evaluator.remove",
        actor=principal,
        target_type="user",
        target_id=user_id,
        project_id=idea.project_id,
        details={"rule": Rule.EVALUATOR_MANAGE, "idea_id": idea.id},
    )
    await db.flush()
    # Only unsubmitted evaluations can go, so the aggregate cannot change; recompute
    # anyway so the cache is right by construction.
    await _refresh_aggregate(db, loaded)


async def set_due_date(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, due_at: datetime | None
) -> None:
    """``idea.set_due_date`` (c6): set it, or clear it with ``None``."""
    require(principal, Rule.IDEA_SET_DUE_DATE, loaded.resource)
    await _set_due(db, principal, loaded, due_at)
    await db.flush()


async def set_evaluation_closed(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, *, closed: bool
) -> None:
    """Close or reopen evaluation (``evaluation.close``, c5); idempotent."""
    require(principal, Rule.EVALUATION_CLOSE, loaded.resource)
    idea = loaded.idea
    if (idea.evaluation_closed_at is not None) == closed:
        return
    idea.evaluation_closed_at = utcnow() if closed else None
    event = "evaluation_closed" if closed else "evaluation_reopened"
    await activity.emit(db, idea, event, actor=principal)
    await audit.record(
        db,
        "evaluation.close" if closed else "evaluation.reopen",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={"rule": Rule.EVALUATION_CLOSE},
    )
    await db.flush()


# --- My evaluation ---------------------------------------------------------------------------
async def _mine(db: AsyncSession, loaded: LoadedIdea, user_id: UUID) -> Evaluation | None:
    evaluation: Evaluation | None = await db.scalar(
        select(Evaluation).where(
            Evaluation.idea_id == loaded.idea.id, Evaluation.evaluator_id == user_id
        )
    )
    return evaluation


async def _scores(
    db: AsyncSession, evaluation_ids: list[UUID], rubric: list[RubricCriterion]
) -> dict[UUID, list[EvaluationScore]]:
    """Saved scores per evaluation, active criteria only, in rubric order."""
    order = {criterion.id: position for position, criterion in enumerate(rubric)}
    rows = await db.scalars(
        select(EvaluationScore).where(
            any_of(EvaluationScore.evaluation_id, evaluation_ids),
            any_of(EvaluationScore.criterion_id, order),
        )
    )
    found: dict[UUID, list[EvaluationScore]] = defaultdict(list)
    for score in rows:
        found[score.evaluation_id].append(score)
    for scores in found.values():
        scores.sort(key=lambda score: order[score.criterion_id])
    return found


async def my_evaluation(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea
) -> MyEvaluation | None:
    """``evaluation.view_own``: your evaluation, or ``None`` if you are not assigned."""
    require(principal, Rule.EVALUATION_VIEW_OWN, loaded.resource)
    idea = loaded.idea
    if await db.get(IdeaEvaluator, (idea.id, principal.user_id)) is None:
        return None
    evaluation = await _mine(db, loaded, principal.user_id)
    # Editable = you could save now: assigned with member/admin, evaluation open, and
    # the project not archived (the same rule the save checks).
    editable = authorize(principal, Rule.EVALUATION_SUBMIT_OWN, loaded.resource).allowed
    if evaluation is None:
        return MyEvaluation(
            idea_id=idea.id,
            state=EvaluatorState.INVITED,
            editable=editable,
            due_at=idea.evaluation_due_at,
            recommendation=None,
            comment="",
            scores=[],
            submitted_at=None,
            updated_at=None,
        )
    scores = (await _scores(db, [evaluation.id], await _rubric(db, loaded))).get(evaluation.id, [])
    return MyEvaluation(
        idea_id=idea.id,
        state=EvaluatorState(evaluation.status.value),
        editable=editable,
        due_at=idea.evaluation_due_at,
        recommendation=evaluation.recommendation,
        comment=evaluation.comment,
        scores=[
            MyScore(criterion_id=s.criterion_id, score=s.score, comment=s.comment) for s in scores
        ],
        submitted_at=evaluation.submitted_at,
        updated_at=evaluation.updated_at,
    )


class EvaluationIncompleteProblem(ProblemError):
    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__(
            422,
            "evaluation_incomplete",
            detail="Score every criterion and choose a recommendation to submit.",
            errors=errors,
        )


async def save_my_evaluation(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, body: MyEvaluationIn
) -> MyEvaluation:
    """Replace your saved evaluation; ``submit`` submits it (contract section 3.6).

    Check order (contract): a denial's 403 comes first, its 409
    (evaluation closed, project archived) only after the body's own 422s.
    """
    decision = authorize(principal, Rule.EVALUATION_SUBMIT_OWN, loaded.resource)
    if not decision.allowed and decision.status != 409:
        raise decision.problem()
    idea = loaded.idea
    rubric = await _rubric(db, loaded)
    active = {criterion.id for criterion in rubric}
    if any(score.criterion_id not in active for score in body.scores):
        raise ProblemError(
            422, "unknown_criterion", detail="A criterion is not in this project's rubric."
        )
    given = {score.criterion_id: score for score in body.scores}
    evaluation = await _mine(db, loaded, principal.user_id)
    already_submitted = evaluation is not None and evaluation.status is EvaluationStatus.SUBMITTED
    if body.submit:
        errors = [
            FieldError(
                loc=["body", "scores", str(criterion.id)], msg=_MISSING_SCORE, type="missing"
            )
            for criterion in rubric
            if criterion.id not in given or given[criterion.id].score is None
        ]
        if body.recommendation is None:
            errors.append(
                FieldError(
                    loc=["body", "recommendation"], msg=_MISSING_RECOMMENDATION, type="missing"
                )
            )
        if errors:
            raise EvaluationIncompleteProblem(errors)
    if not decision.allowed:
        raise decision.problem()
    if not body.submit and already_submitted:
        raise ConflictProblem(
            "A submitted evaluation can be edited, not turned back into a draft.",
            code="evaluation_already_submitted",
        )

    now = utcnow()
    if evaluation is None:
        evaluation = Evaluation(
            id=uuid4(),
            idea_id=idea.id,
            evaluator_id=principal.user_id,
            status=EvaluationStatus.DRAFT,
            include_in_aggregate=True,
        )
        db.add(evaluation)
    evaluation.recommendation = body.recommendation
    evaluation.comment = body.comment
    evaluation.updated_at = now  # "last save", even when only scores changed
    first_submission = body.submit and not already_submitted
    if first_submission:
        evaluation.status = EvaluationStatus.SUBMITTED
        evaluation.submitted_at = now
        if principal.user.is_service_account:
            # An AI agent's evaluation is left out of the aggregate by default (role
            # matrix section 3 rule 10); ``evaluation.include_ai`` changes it later.
            evaluation.include_in_aggregate = False
    elif already_submitted:
        evaluation.edited_at = now
    await db.flush()
    # Replace the scores of active criteria; archived criteria keep theirs.
    await db.execute(
        delete(EvaluationScore).where(
            EvaluationScore.evaluation_id == evaluation.id,
            EvaluationScore.criterion_id.in_(list(active)),
        )
    )
    if body.scores:
        await db.execute(
            insert(EvaluationScore).values(
                [
                    {
                        "evaluation_id": evaluation.id,
                        "criterion_id": score.criterion_id,
                        "score": score.score,
                        "comment": score.comment,
                    }
                    for score in body.scores
                ]
            )
        )
    if first_submission:
        await activity.emit(
            db,
            idea,
            "evaluation_submitted",
            actor=principal,
            payload={"evaluator_id": principal.user_id},
        )
        await audit.record(
            db,
            "evaluation.submit",
            actor=principal,
            target_type="idea",
            target_id=idea.id,
            project_id=idea.project_id,
            details={"rule": Rule.EVALUATION_SUBMIT_OWN, "evaluation_id": evaluation.id},
        )
    if body.submit:
        await _refresh_aggregate(db, loaded)
    await db.flush()
    result = await my_evaluation(db, principal, loaded)
    assert result is not None  # noqa: S101 - we just saved it
    return result


# --- Everyone's (blind-filtered) -------------------------------------------------------------
async def list_evaluations(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea
) -> EvaluationList:
    """Every submitted evaluation, oldest first; nothing while you owe your own."""
    decision = authorize(principal, Rule.EVALUATION_VIEW_OTHERS, loaded.resource)
    if not decision.allowed:
        if decision.hidden:
            return EvaluationList(items=[], score_hidden=True)
        raise decision.problem()
    rows = (
        await db.execute(
            select(Evaluation, User)
            .join(User, User.id == Evaluation.evaluator_id)
            .where(
                Evaluation.idea_id == loaded.idea.id,
                Evaluation.status == EvaluationStatus.SUBMITTED,
            )
            .order_by(Evaluation.submitted_at, Evaluation.id)
        )
    ).all()
    scores = await _scores(db, [evaluation.id for evaluation, _ in rows], await _rubric(db, loaded))
    items = []
    for evaluation, user in rows:
        assert evaluation.recommendation is not None  # noqa: S101 - ck_evaluations_submitted_complete
        assert evaluation.submitted_at is not None  # noqa: S101
        items.append(
            EvaluationOut(
                id=evaluation.id,
                evaluator=UserRef.model_validate(user),
                recommendation=evaluation.recommendation,
                comment=evaluation.comment,
                scores=[
                    EvaluationScoreOut(
                        criterion_id=s.criterion_id, score=s.score, comment=s.comment
                    )
                    for s in scores.get(evaluation.id, [])
                    if s.score is not None
                ],
                submitted_at=evaluation.submitted_at,
                edited_at=evaluation.edited_at,
                is_ai=user.is_service_account,
                include_in_aggregate=evaluation.include_in_aggregate,
            )
        )
    return EvaluationList(items=items, score_hidden=False)
