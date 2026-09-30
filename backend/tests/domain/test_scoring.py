"""The aggregate score as a pure function (contract section 3.8, ADR 0006).

Examples first (the contract's worked example, weights, inversion, rounding,
disagreement, archived criteria), then property-style checks over seeded random
rubrics and evaluations against a naive re-implementation.
"""

from __future__ import annotations

import random  # seeded, for reproducible property-style cases (not security)
from decimal import Decimal
from fractions import Fraction
from uuid import UUID, uuid4

import pytest

from app.domain.scoring import (
    Aggregate,
    Criterion,
    ScoredEvaluation,
    aggregate,
    round_half_up,
)
from app.models.enums import Recommendation

GO, MAYBE, NO = Recommendation.GO, Recommendation.MAYBE, Recommendation.NO


def crit(weight: str = "1", *, inverted: bool = False) -> Criterion:
    return Criterion(id=uuid4(), weight=Decimal(weight), inverted=inverted)


def ev(
    scores: dict[Criterion, int | None], recommendation: Recommendation | None = GO
) -> ScoredEvaluation:
    return ScoredEvaluation(
        scores={c.id: s for c, s in scores.items()}, recommendation=recommendation
    )


def overall(result: Aggregate | None) -> Decimal | None:
    assert result is not None
    return result.overall


# --- Examples -------------------------------------------------------------------------------
def test_contract_worked_example() -> None:
    value, effort = crit("2"), crit("1", inverted=True)

    result = aggregate(
        [value, effort],
        [
            ev({value: 4, effort: 2}, GO),
            ev({value: 5, effort: 4}, MAYBE),
            ev({value: 2, effort: 3}, GO),
        ],
    )

    assert result is not None
    assert result.overall == Decimal("3.4")  # (2 x 11/3 + 1 x 3) / 3 = 3.444...
    assert result.count == 3
    assert result.high_disagreement is True  # Value spread 3
    value_stats, effort_stats = result.criteria
    assert (value_stats.criterion_id, value_stats.mean) == (value.id, Decimal("3.7"))
    assert (value_stats.min, value_stats.max, value_stats.spread, value_stats.count) == (2, 5, 3, 3)
    # Raw scores as entered (2, 4, 3), not the adjusted 4, 2, 3.
    assert (effort_stats.mean, effort_stats.min, effort_stats.max, effort_stats.spread) == (
        Decimal("3.0"),
        2,
        4,
        2,
    )
    assert dict(result.recommendations) == {GO: 2, MAYBE: 1, NO: 0}


def test_no_evaluations_means_no_aggregate() -> None:
    assert aggregate([crit()], []) is None


def test_weights_are_relative() -> None:
    value, cost = crit("3"), crit("1")

    # (3 x 5 + 1 x 1) / 4 = 4.0
    assert overall(aggregate([value, cost], [ev({value: 5, cost: 1})])) == Decimal("4.0")
    # Scaling every weight changes nothing.
    scaled = [Criterion(c.id, c.weight * 3, c.inverted) for c in (value, cost)]
    assert overall(aggregate(scaled, [ev({value: 5, cost: 1})])) == Decimal("4.0")


def test_inverted_criteria_count_six_minus_the_score() -> None:
    value, effort = crit(), crit(inverted=True)

    # Value 4; Effort 5 = "a lot of effort" -> 1. (4 + 1) / 2 = 2.5
    result = aggregate([value, effort], [ev({value: 4, effort: 5})])

    assert overall(result) == Decimal("2.5")
    assert result is not None
    assert result.criteria[1].mean == Decimal("5.0")  # reported raw


def test_rounds_half_up_from_unrounded_means() -> None:
    a, b = crit(), crit()
    # Means 3.5 and 3.4 exactly -> overall 3.45 -> 3.5 (banker's rounding would say 3.4).
    evaluations = [ev({a: 3, b: 3})] * 5 + [ev({a: 4, b: 4})] * 5
    evaluations[0] = ev({a: 3, b: 2})  # b: 34/10 = 3.4

    assert overall(aggregate([a, b], evaluations)) == Decimal("3.5")
    # Means 1/3-ish: 10/3 -> 3.3 (not 3.4 from rounding a rounded mean twice).
    assert overall(aggregate([a], [ev({a: 3}), ev({a: 3}), ev({a: 4})])) == Decimal("3.3")
    assert overall(aggregate([a], [ev({a: 4}), ev({a: 4}), ev({a: 3})])) == Decimal("3.7")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(345, 100), "3.5"),
        (Fraction(344999, 100000), "3.4"),
        (Fraction(325, 100), "3.3"),
        (Fraction(1), "1.0"),
        (Fraction(5), "5.0"),
        (Fraction(10, 3), "3.3"),
        (Fraction(-25, 100), "-0.3"),  # away from zero
    ],
)
def test_round_half_up(value: Fraction, expected: str) -> None:
    assert round_half_up(value) == Decimal(expected)
    assert str(round_half_up(value)) == expected


def test_weights_renormalise_over_scored_criteria() -> None:
    value, risk, added = crit("2"), crit("1", inverted=True), crit("5")

    # "added" joined the rubric after these submissions: no scores, no weight.
    result = aggregate([value, risk, added], [ev({value: 4, risk: 2}), ev({value: 4, risk: 2})])

    assert overall(result) == Decimal("4.0")
    assert result is not None
    assert [s.criterion_id for s in result.criteria] == [value.id, risk.id]


def test_archived_criteria_are_ignored() -> None:
    value, archived = crit(), crit()

    result = aggregate([value], [ev({value: 4, archived: 1}), ev({value: 4, archived: 5})])

    assert overall(result) == Decimal("4.0")
    assert result is not None
    assert result.high_disagreement is False  # the archived spread of 4 does not count
    assert [s.criterion_id for s in result.criteria] == [value.id]


def test_count_is_every_included_evaluation() -> None:
    value, archived = crit(), crit()

    # The second evaluation only scored a criterion that has since been archived.
    result = aggregate([value], [ev({value: 2}), ev({archived: 5}, NO)])

    assert result is not None
    assert (result.overall, result.count) == (Decimal("2.0"), 2)
    assert result.criteria[0].count == 1
    assert dict(result.recommendations) == {GO: 1, MAYBE: 0, NO: 1}


def test_nothing_scored_on_the_active_rubric_has_no_overall() -> None:
    value, archived = crit(), crit()

    result = aggregate([value], [ev({archived: 5})])

    assert result is not None
    assert (result.overall, result.count, result.high_disagreement, result.criteria) == (
        None,
        1,
        False,
        (),
    )


@pytest.mark.parametrize(
    ("scores", "flag"),
    [
        ([3, 5], True),  # spread exactly 2
        ([1, 5], True),
        ([3, 4], False),  # spread 1
        ([4, 4, 4], False),
        ([2, 3, 4], True),
        ([5], False),  # one score cannot disagree
    ],
)
def test_high_disagreement(scores: list[int], flag: bool) -> None:
    value = crit()

    result = aggregate([value], [ev({value: score}) for score in scores])

    assert result is not None
    assert result.high_disagreement is flag


def test_disagreement_needs_two_scores_on_the_same_criterion() -> None:
    a, b = crit(), crit()

    # a: 1 (one score); b: 5 (one score). The spread across criteria is not disagreement.
    result = aggregate([a, b], [ev({a: 1, b: None}), ev({a: None, b: 5})])

    assert result is not None
    assert result.high_disagreement is False


def test_inversion_does_not_change_the_spread() -> None:
    effort = crit(inverted=True)

    result = aggregate([effort], [ev({effort: 1}), ev({effort: 3})])

    assert result is not None
    assert result.high_disagreement is True
    assert result.criteria[0].spread == 2


def test_null_scores_are_skipped() -> None:
    a = crit()

    result = aggregate([a], [ev({a: None}), ev({a: 4})])

    assert result is not None
    assert (result.overall, result.criteria[0].count) == (Decimal("4.0"), 1)


def test_missing_recommendations_are_not_tallied() -> None:
    a = crit()

    result = aggregate([a], [ev({a: 4}, None)])

    assert result is not None
    assert dict(result.recommendations) == {GO: 0, MAYBE: 0, NO: 0}


@pytest.mark.parametrize("score", [0, 6, -1, True])
def test_out_of_range_scores_are_refused(score: int) -> None:
    a = crit()

    with pytest.raises(ValueError, match="scores are"):
        aggregate([a], [ev({a: score})])


@pytest.mark.parametrize("weight", ["0", "-1"])
def test_weights_must_be_positive(weight: str) -> None:
    with pytest.raises(ValueError, match="positive"):
        crit(weight)


# --- Properties -----------------------------------------------------------------------------
def _random_case(rng: random.Random) -> tuple[list[Criterion], list[ScoredEvaluation]]:
    criteria = [
        Criterion(
            id=uuid4(),
            weight=Decimal(rng.randint(1, 1000)) / 100,  # 0.01 .. 10.00
            inverted=rng.random() < 0.4,
        )
        for _ in range(rng.randint(3, 6))
    ]
    archived = [uuid4() for _ in range(rng.randint(0, 2))]
    evaluations = []
    for _ in range(rng.randint(1, 8)):
        scores: dict[UUID, int | None] = {
            c.id: rng.randint(1, 5) for c in criteria if rng.random() < 0.9
        }
        scores.update({a: rng.randint(1, 5) for a in archived})
        evaluations.append(
            ScoredEvaluation(scores=scores, recommendation=rng.choice([*Recommendation, None]))
        )
    return criteria, evaluations


def _naive(
    criteria: list[Criterion], evaluations: list[ScoredEvaluation]
) -> tuple[float | None, bool]:
    """Straight from the contract text, in floats."""
    numerator = denominator = 0.0
    disagreement = False
    for c in criteria:
        raw = [e.scores[c.id] for e in evaluations if e.scores.get(c.id) is not None]
        values = [s for s in raw if s is not None]
        if not values:
            continue
        adjusted = [6 - s if c.inverted else s for s in values]
        numerator += float(c.weight) * sum(adjusted) / len(adjusted)
        denominator += float(c.weight)
        disagreement = disagreement or (len(values) >= 2 and max(values) - min(values) >= 2)
    return (numerator / denominator if denominator else None), disagreement


CASES = 400


def test_property_matches_a_naive_implementation() -> None:
    rng = random.Random(20260930)  # noqa: S311
    for _ in range(CASES):
        criteria, evaluations = _random_case(rng)

        result = aggregate(criteria, evaluations)
        expected, disagreement = _naive(criteria, evaluations)

        assert result is not None
        assert result.count == len(evaluations)
        assert result.high_disagreement is disagreement
        if expected is None:
            assert result.overall is None
            continue
        assert result.overall is not None
        assert Decimal("1.0") <= result.overall <= Decimal("5.0")
        assert abs(float(result.overall) - expected) <= 0.05 + 1e-9
        if abs((expected * 10) % 1 - 0.5) > 1e-6:  # not on a rounding boundary
            assert result.overall == Decimal(str(round(expected + 1e-12, 1)))
        assert sum(result.recommendations.values()) == sum(
            e.recommendation is not None for e in evaluations
        )


def test_property_order_of_evaluations_does_not_matter() -> None:
    rng = random.Random(7)  # noqa: S311
    for _ in range(CASES):
        criteria, evaluations = _random_case(rng)
        shuffled = evaluations[:]
        rng.shuffle(shuffled)

        assert aggregate(criteria, evaluations) == aggregate(criteria, shuffled)


def test_property_weight_scale_does_not_matter() -> None:
    rng = random.Random(11)  # noqa: S311
    for _ in range(CASES):
        criteria, evaluations = _random_case(rng)
        factor = Decimal(rng.randint(2, 9)) / 7
        scaled = [Criterion(c.id, c.weight * factor, c.inverted) for c in criteria]

        assert overall(aggregate(criteria, evaluations)) == overall(aggregate(scaled, evaluations))


def test_property_inverting_and_mirroring_a_criterion_is_neutral() -> None:
    rng = random.Random(13)  # noqa: S311
    for _ in range(CASES):
        criteria, evaluations = _random_case(rng)
        flip = rng.choice(criteria)
        flipped_criteria = [
            Criterion(c.id, c.weight, not c.inverted) if c is flip else c for c in criteria
        ]
        mirrored = [
            ScoredEvaluation(
                scores={
                    key: (6 - s if key == flip.id and s is not None else s)
                    for key, s in e.scores.items()
                },
                recommendation=e.recommendation,
            )
            for e in evaluations
        ]

        before = aggregate(criteria, evaluations)
        after = aggregate(flipped_criteria, mirrored)

        assert before is not None
        assert after is not None
        assert before.overall == after.overall
        assert before.high_disagreement == after.high_disagreement  # spread is symmetric


def test_property_unanimous_scores_are_the_score() -> None:
    rng = random.Random(17)  # noqa: S311
    for _ in range(100):
        criteria, _ = _random_case(rng)
        score = rng.randint(1, 5)
        evaluations = [
            ScoredEvaluation(scores={c.id: (6 - score if c.inverted else score) for c in criteria})
            for _ in range(rng.randint(1, 5))
        ]

        result = aggregate(criteria, evaluations)

        assert result is not None
        assert result.overall == Decimal(score).quantize(Decimal("0.1"))
        assert result.high_disagreement is False
