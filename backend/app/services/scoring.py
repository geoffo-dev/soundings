"""The cached aggregate score on ``ideas`` (contract section 3.8, ADR 0006).

:func:`recompute_aggregates` recomputes ``aggregate_score``, ``aggregate_count`` and
``high_disagreement`` for one idea, a few, or a whole project, in the caller's
transaction, with the pure :func:`app.domain.scoring.aggregate` (the idea page uses
the same function through :func:`idea_aggregate`, so the two always agree). Call it
after a first submission or an edit of a submitted evaluation, an
``include_in_aggregate`` change, and ``replace_rubric``. The cached values are raw;
:mod:`app.authz.queries` masks them per viewer.

It writes with one SQL ``UPDATE``: refresh ORM ``Idea`` objects you hold afterwards
(``await db.refresh(idea)``). ``last_activity_at`` and ``updated_at`` are not touched
(a recompute is not an edit), and only rows whose cached values change are written.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.scoring import Aggregate, Criterion, ScoredEvaluation, aggregate
from app.models.enums import EvaluationStatus, Recommendation
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.idea import Idea
from app.models.project import RubricCriterion
from app.services.sql import any_of

__all__ = [
    "active_criteria",
    "idea_aggregate",
    "included_evaluations",
    "recompute_aggregates",
]


async def active_criteria(
    db: AsyncSession, project_ids: Iterable[UUID]
) -> dict[UUID, list[RubricCriterion]]:
    """Active rubric criteria per project, in display order."""
    rows = await db.scalars(
        select(RubricCriterion)
        .where(
            any_of(RubricCriterion.project_id, project_ids),
            RubricCriterion.archived_at.is_(None),
        )
        .order_by(RubricCriterion.position, RubricCriterion.id)
    )
    found: dict[UUID, list[RubricCriterion]] = defaultdict(list)
    for criterion in rows:
        found[criterion.project_id].append(criterion)
    return found


async def included_evaluations(
    db: AsyncSession, idea_ids: Select[Any] | Collection[UUID]
) -> dict[UUID, list[ScoredEvaluation]]:
    """The included set per idea: submitted evaluations with ``include_in_aggregate``,
    with every stored score (the aggregate ignores archived criteria)."""
    rows = await db.execute(
        select(
            Evaluation.idea_id,
            Evaluation.id,
            Evaluation.recommendation,
            EvaluationScore.criterion_id,
            EvaluationScore.score,
        )
        .outerjoin(EvaluationScore, EvaluationScore.evaluation_id == Evaluation.id)
        .where(
            (
                Evaluation.idea_id.in_(idea_ids)
                if isinstance(idea_ids, Select)
                else any_of(Evaluation.idea_id, idea_ids)
            ),
            Evaluation.status == EvaluationStatus.SUBMITTED,
            Evaluation.include_in_aggregate,
        )
    )
    evaluations: dict[UUID, dict[UUID, tuple[Recommendation | None, dict[UUID, int | None]]]] = (
        defaultdict(dict)
    )
    for idea_id, evaluation_id, recommendation, criterion_id, score in rows:
        _, scores = evaluations[idea_id].setdefault(evaluation_id, (recommendation, {}))
        if criterion_id is not None:
            scores[criterion_id] = score
    return {
        idea_id: [
            ScoredEvaluation(scores=scores, recommendation=recommendation)
            for recommendation, scores in by_id.values()
        ]
        for idea_id, by_id in evaluations.items()
    }


def _criteria(rubric: Iterable[RubricCriterion]) -> list[Criterion]:
    return [Criterion(id=c.id, weight=c.weight, inverted=c.inverted) for c in rubric]


async def idea_aggregate(
    db: AsyncSession, idea: Idea, rubric: list[RubricCriterion]
) -> Aggregate | None:
    """The idea's aggregate with per-criterion statistics (the idea page)."""
    included = await included_evaluations(db, [idea.id])
    return aggregate(_criteria(rubric), included.get(idea.id, []))


def _cached(result: Aggregate | None) -> tuple[Decimal | None, int, bool]:
    if result is None:
        return None, 0, False
    if result.overall is None:  # nothing scored on the active rubric
        return None, result.count, False
    return result.overall, result.count, result.high_disagreement


async def recompute_aggregates(
    db: AsyncSession,
    *,
    project_id: UUID | None = None,
    idea_ids: Collection[UUID] | None = None,
) -> None:
    """Recompute the cache for every idea of ``project_id``, or for ``idea_ids``."""
    if (project_id is None) == (idea_ids is None):
        raise ValueError("pass project_id or idea_ids")
    await db.flush()  # the queries must see pending ORM changes
    target = (
        select(Idea.id).where(Idea.project_id == project_id)
        if project_id is not None
        else select(Idea.id).where(any_of(Idea.id, idea_ids or ()))
    )
    current = (
        await db.execute(
            select(
                Idea.id,
                Idea.project_id,
                Idea.aggregate_score,
                Idea.aggregate_count,
                Idea.high_disagreement,
            ).where(Idea.id.in_(target))
        )
    ).all()
    if not current:
        return
    rubrics = {
        project_id: _criteria(rubric)
        for project_id, rubric in (
            await active_criteria(db, {row.project_id for row in current})
        ).items()
    }
    included = await included_evaluations(db, target)
    ids: list[UUID] = []
    scores: list[Decimal | None] = []
    counts: list[int] = []
    flags: list[bool] = []
    for row in current:
        evaluations = included.get(row.id)
        result = aggregate(rubrics.get(row.project_id, []), evaluations) if evaluations else None
        cached = _cached(result)
        if cached != (row.aggregate_score, row.aggregate_count, row.high_disagreement):
            ids.append(row.id)
            scores.append(cached[0])
            counts.append(cached[1])
            flags.append(cached[2])
    if ids:
        # One statement for every changed idea (a rubric change touches thousands).
        await db.execute(_UPDATE, {"ids": ids, "scores": scores, "counts": counts, "flags": flags})


_UPDATE = text(
    """
    UPDATE ideas
    SET aggregate_score = changed.score,
        aggregate_count = changed.n,
        high_disagreement = changed.flag
    FROM unnest(
        CAST(:ids AS uuid[]), CAST(:scores AS numeric[]),
        CAST(:counts AS integer[]), CAST(:flags AS boolean[])
    ) AS changed(id, score, n, flag)
    WHERE ideas.id = changed.id
    """
)
