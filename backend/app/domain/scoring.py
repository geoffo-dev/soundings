"""The aggregate score (contract section 3.8, ADR 0006) as a pure function.

Over the **included set** *E* (submitted evaluations with ``include_in_aggregate``;
the caller selects them) and the project's **active** criteria:

1. per criterion *c*, the adjusted score is *s*, or ``6 - s`` when *c* is inverted;
   *m_c* is the mean of the adjusted scores;
2. ``overall`` = Σ w_c·m_c / Σ w_c over criteria with at least one score, rounded
   half-up to one decimal from the unrounded means;
3. ``count`` = |E|; with no evaluations there is no aggregate (``None``);
4. ``high_disagreement``: some criterion has ≥ 2 scores with raw ``max - min ≥ 2``;
5. per-criterion statistics report **raw** scores (mean to one decimal, min, max,
   spread, count); ``recommendations`` tallies go / maybe / no over *E*.

Arithmetic is exact (:class:`fractions.Fraction`), so the result does not depend on
the order of evaluations and a value such as 3.45 always rounds to 3.5. Scores for
criteria that are not passed in (archived ones) are ignored. Both the idea page and
the cached ``ideas.aggregate_*`` columns (:mod:`app.services.scoring`) use this.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Final
from uuid import UUID

from app.models.enums import Recommendation

__all__ = [
    "DISAGREEMENT_SPREAD",
    "MAX_SCORE",
    "MIN_SCORE",
    "Aggregate",
    "Criterion",
    "CriterionStats",
    "ScoredEvaluation",
    "aggregate",
    "round_half_up",
]

MIN_SCORE: Final = 1
MAX_SCORE: Final = 5
DISAGREEMENT_SPREAD: Final = 2
"""A criterion with at least two scores whose raw max - min reaches this disagrees."""

_ONE_DECIMAL: Final = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class Criterion:
    """An active rubric criterion: its weight (> 0) and whether it is inverted."""

    id: UUID
    weight: Decimal
    inverted: bool = False

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("criterion weights must be positive")


@dataclass(frozen=True, slots=True)
class ScoredEvaluation:
    """One included evaluation: raw 1-5 scores by criterion id, and its recommendation."""

    scores: Mapping[UUID, int | None]
    recommendation: Recommendation | None = None


@dataclass(frozen=True, slots=True)
class CriterionStats:
    """Raw-score statistics for one criterion with at least one score."""

    criterion_id: UUID
    mean: Decimal
    min: int
    max: int
    count: int

    @property
    def spread(self) -> int:
        return self.max - self.min


@dataclass(frozen=True, slots=True)
class Aggregate:
    """The aggregate over the included set.

    ``overall`` is ``None`` only when no active criterion has a score (every score is
    on a criterion that was archived since): there is then nothing to show.
    """

    overall: Decimal | None
    count: int
    high_disagreement: bool
    criteria: tuple[CriterionStats, ...]
    recommendations: Mapping[Recommendation, int] = field(
        default_factory=lambda: MappingProxyType(dict.fromkeys(Recommendation, 0))
    )


def round_half_up(value: Fraction) -> Decimal:
    """``value`` to one decimal place, halves away from zero (``round(numeric, 1)``)."""
    tenths = value * 10
    rounded = math.floor(abs(tenths) + Fraction(1, 2))
    return (Decimal(-rounded if tenths < 0 else rounded) / 10).quantize(_ONE_DECIMAL)


def _checked(score: int) -> int:
    if isinstance(score, bool) or not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"scores are {MIN_SCORE}-{MAX_SCORE}, not {score!r}")
    return score


def aggregate(
    criteria: Sequence[Criterion], evaluations: Iterable[ScoredEvaluation]
) -> Aggregate | None:
    """The aggregate of ``evaluations`` (the included set) over ``criteria`` (the
    active rubric, in display order), or ``None`` when there are no evaluations."""
    included = list(evaluations)
    if not included:
        return None
    recommendations = dict.fromkeys(Recommendation, 0)
    for evaluation in included:
        if evaluation.recommendation is not None:
            recommendations[evaluation.recommendation] += 1

    stats: list[CriterionStats] = []
    weighted_sum = Fraction(0)
    weight_total = Fraction(0)
    disagreement = False
    for criterion in criteria:
        raw = [
            _checked(score)
            for evaluation in included
            if (score := evaluation.scores.get(criterion.id)) is not None
        ]
        if not raw:
            continue  # nothing to average; its weight drops out (weights renormalise)
        raw_mean = Fraction(sum(raw), len(raw))
        adjusted_mean = MAX_SCORE + MIN_SCORE - raw_mean if criterion.inverted else raw_mean
        weight = Fraction(criterion.weight)
        weighted_sum += weight * adjusted_mean
        weight_total += weight
        low, high = min(raw), max(raw)
        disagreement |= len(raw) >= 2 and high - low >= DISAGREEMENT_SPREAD
        stats.append(
            CriterionStats(
                criterion_id=criterion.id,
                mean=round_half_up(raw_mean),
                min=low,
                max=high,
                count=len(raw),
            )
        )

    return Aggregate(
        overall=round_half_up(weighted_sum / weight_total) if weight_total else None,
        count=len(included),
        high_disagreement=disagreement,
        criteria=tuple(stats),
        recommendations=MappingProxyType(recommendations),
    )
