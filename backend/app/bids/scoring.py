"""A call's scores from its rows (contract-phase10 section 8; ADR 0018), with the pure
arithmetic of :mod:`app.schemas.bids` (exact fractions; only what the API returns is
rounded, half up).

* A question's counted scores: every **submitted** human assessment of its section for the
  bid, plus each **included** AI assessment's score (drafts never count).
* Price score (scored bids only): lowest scored price / this bid's price x 5.
* Section score (0-5): the weighted mean of its score and price questions; none while one
  has no score. Total (0-100): sum of section weight % x section score x 20.
* Only **scored** bids (not rejected, every must-have met, whatever the award made them:
  :func:`~app.schemas.bids.is_scored`) get a price score, section scores and a total; the
  question statistics are kept for every bid (a section's assessors read them after
  submitting).

Nothing here knows who is asking: hiding what a pending assessor may not see is the
caller's job (role matrix section 3a).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from app.bids.data import CallData
from app.models.bid import Bid, BidCallQuestion, BidCallSection
from app.models.enums import BidQuestionType, BidStatus
from app.schemas.bids import (
    RankedBid,
    bid_total,
    disagreement,
    is_scored,
    price_score,
    question_mean,
    rank_bids,
    section_score,
)

__all__ = [
    "BidScores",
    "QuestionScore",
    "SectionScore",
    "counted_scores",
    "lowest_scored_price",
    "score_bid",
    "score_call",
]


@dataclass(frozen=True, slots=True)
class QuestionScore:
    question: BidCallQuestion
    counted: tuple[int, ...]
    """The scores that count (human submitted + included AI); empty for the price question."""
    score: Fraction | None
    """The mean of ``counted`` (0-5), or the price score for the price question."""

    @property
    def disagreement(self) -> bool:
        return disagreement(self.counted)


@dataclass(frozen=True, slots=True)
class SectionScore:
    section: BidCallSection
    questions: tuple[QuestionScore, ...]
    """Score and price questions, in order (comment questions aren't scored)."""
    score: Fraction | None
    """0-5; ``None`` for a bid that isn't scored or while a question has no score."""

    @property
    def disagreement(self) -> bool:
        return any(question.disagreement for question in self.questions)


@dataclass(frozen=True, slots=True)
class BidScores:
    bid: Bid
    scored: bool
    price_score: Fraction | None
    sections: dict[UUID, SectionScore]
    total: Fraction | None
    ai_included: bool


def lowest_scored_price(data: CallData) -> Decimal | None:
    """The price formula's lowest price: among scored bids with a price."""
    prices = [bid.price for bid in data.bids if bid.price is not None and _scored(data, bid)]
    return min(prices) if prices else None


def _scored(data: CallData, bid: Bid) -> bool:
    return is_scored(rejected=bid.status is BidStatus.REJECTED, results=data.results_of(bid.id))


Counted = dict[tuple[UUID, UUID], dict[UUID, list[int]]]
"""(bid id, section id) -> question id -> the scores that count."""


def counted_scores(data: CallData, *, bid_id: UUID | None = None) -> Counted:
    """Every counted score (needs ``answers`` and ``ai``), indexed once by bid and section
    (review M2: one pass over the call's answers, never one per bid and section), for one
    bid only when ``bid_id`` is given."""
    counted: Counted = defaultdict(lambda: defaultdict(list))
    for (answer_bid, section_id, _), answers in data.answers.items():
        if bid_id is not None and answer_bid != bid_id:
            continue
        bucket = counted[(answer_bid, section_id)]
        for question_id, answer in answers.items():
            if answer.score is not None:
                bucket[question_id].append(answer.score)
    section_of = {q.id: sid for sid, questions in data.questions.items() for q in questions}
    for assessment_bid, assessments in data.ai.items():
        if bid_id is not None and assessment_bid != bid_id:
            continue
        for assessment in assessments:
            if not assessment.included:
                continue
            for question_id, ai_score in data.ai_scores.get(assessment.id, {}).items():
                ai_section = section_of.get(question_id)
                if ai_section is not None:
                    counted[(assessment_bid, ai_section)][question_id].append(ai_score.score)
    return counted


def score_bid(
    data: CallData, bid: Bid, lowest: Decimal | None, counted: Counted | None = None
) -> BidScores:
    """One bid's scores (see the module docstring); ``counted`` from
    :func:`counted_scores` (read for this bid alone when not given)."""
    if counted is None:
        counted = counted_scores(data, bid_id=bid.id)
    scored = _scored(data, bid)
    price = price_score(bid.price, lowest) if scored else None
    sections: dict[UUID, SectionScore] = {}
    for section in data.sections:
        mine = counted.get((bid.id, section.id), {})
        questions: list[QuestionScore] = []
        pairs: list[tuple[int, Fraction | None]] = []
        for question in data.questions.get(section.id, []):
            if question.type is BidQuestionType.COMMENT:
                continue
            if question.type is BidQuestionType.PRICE:
                item = QuestionScore(question, (), price)
            else:
                values = tuple(mine.get(question.id, ()))
                item = QuestionScore(question, values, question_mean(values))
            questions.append(item)
            pairs.append((question.weight, item.score))
        section_value = section_score(pairs) if scored else None
        sections[section.id] = SectionScore(section, tuple(questions), section_value)
    total = bid_total((s.section.weight, s.score) for s in sections.values()) if scored else None
    included = any(a.included for a in data.ai.get(bid.id, []))
    return BidScores(bid, scored, price, sections, total, included)


def score_call(data: CallData) -> tuple[dict[UUID, BidScores], list[RankedBid]]:
    """Every bid's scores and the ranking of scored bids with a total (best first; equal
    rounded totals share a rank)."""
    lowest = lowest_scored_price(data)
    counted = counted_scores(data)
    scores = {bid.id: score_bid(data, bid, lowest, counted) for bid in data.bids}
    ranking = rank_bids(
        (bid_id, item.total, item.bid.price, item.bid.received_at)
        for bid_id, item in scores.items()
        if item.scored and item.total is not None
    )
    return scores, ranking
