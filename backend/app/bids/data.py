"""One call's rows, read in a handful of statements (never one per bid), and the progress
counts built from them (contract-phase10 section 8, "Progress").

:func:`load_call_data` reads the template copy (sections, questions, must-haves), the
assessors with their eligibility **now** (c28, :func:`app.authz.eligible_assessor`), the
bids and the assessments' states; on request also the submitted answers, the must-have
results and the AI assessments' scores. Everything computed from them is pure: progress
here, scores in :mod:`app.bids.scoring`.

Progress (review S10): expected = every (assessor, section, bid that isn't rejected) whose
assessor is still eligible, plus the submitted ones of assessors who no longer are (their
scores still count); submitted = those with a submitted assessment. A rejected bid's own
progress is counted the same way (so a manager sees where it stood), but it never counts
toward a section's or the call's progress.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import eligible_assessor
from app.models.bid import (
    Bid,
    BidAiAssessment,
    BidAiScore,
    BidAssessment,
    BidAssessmentAnswer,
    BidCall,
    BidCallMustHave,
    BidCallQuestion,
    BidCallSection,
    BidMustHaveResult,
    BidSectionAssessor,
)
from app.models.enums import BidQuestionType, BidStatus, EvaluationStatus, MustHaveResult
from app.models.idea import Idea
from app.models.project import Project
from app.models.user import User
from app.schemas.bid_refs import BidProgress

__all__ = ["Assignment", "CallData", "load_call_data"]

Key = tuple[UUID, UUID, UUID]
"""(bid id, section id, assessor id)."""


@dataclass(frozen=True, slots=True)
class Assignment:
    section_id: UUID
    user: User
    eligible: bool
    """c28 now: their unsubmitted assessments are expected work."""
    assigned_at: object


@dataclass(slots=True)
class CallData:
    call: BidCall
    sections: list[BidCallSection]
    questions: dict[UUID, list[BidCallQuestion]]
    """By section, in order."""
    must_haves: list[BidCallMustHave]
    assignments: list[Assignment]
    bids: list[Bid]
    """In the order received (then id)."""
    states: dict[Key, EvaluationStatus]
    """Every saved assessment's status (drafts included: callers keep them private)."""
    answers: dict[Key, dict[UUID, BidAssessmentAnswer]] = field(default_factory=dict)
    """Submitted assessments' answers by question (``answers=True``)."""
    results: dict[UUID, dict[UUID, BidMustHaveResult]] = field(default_factory=dict)
    """Bid -> must-have -> result (``results=True``)."""
    ai: dict[UUID, list[BidAiAssessment]] = field(default_factory=dict)
    """Bid -> its AI assessments (``ai=True``)."""
    ai_scores: dict[UUID, dict[UUID, BidAiScore]] = field(default_factory=dict)
    """AI assessment -> question -> score (``ai=True``)."""

    # --- The template -------------------------------------------------------------------
    @property
    def price_question(self) -> BidCallQuestion | None:
        for questions in self.questions.values():
            for question in questions:
                if question.type is BidQuestionType.PRICE:
                    return question
        return None

    def section_of(self, section_id: UUID) -> BidCallSection | None:
        return next((s for s in self.sections if s.id == section_id), None)

    # --- Assessments ----------------------------------------------------------------------
    def submitted(self, bid_id: UUID, section_id: UUID, user_id: UUID) -> bool:
        return self.states.get((bid_id, section_id, user_id)) is EvaluationStatus.SUBMITTED

    def section_users(self, section_id: UUID) -> list[Assignment]:
        return [a for a in self.assignments if a.section_id == section_id]

    @property
    def human_submitted(self) -> bool:
        """A person's assessment is submitted: the template is locked (section 4.3)."""
        return any(status is EvaluationStatus.SUBMITTED for status in self.states.values())

    def counts(
        self,
        bids: Iterable[Bid],
        assignments: Iterable[Assignment],
    ) -> BidProgress:
        """Submitted / expected over these bids and assignments (module docstring)."""
        pairs = list(assignments)
        submitted = total = 0
        for bid in bids:
            for assignment in pairs:
                done = self.submitted(bid.id, assignment.section_id, assignment.user.id)
                if assignment.eligible or done:
                    total += 1
                    submitted += int(done)
        return BidProgress(submitted=submitted, total=total)

    @property
    def live_bids(self) -> list[Bid]:
        """Bids that aren't rejected (the assessors' queue; what progress counts)."""
        return [bid for bid in self.bids if bid.status is not BidStatus.REJECTED]

    def call_progress(self) -> BidProgress:
        return self.counts(self.live_bids, self.assignments)

    def bid_progress(self, bid: Bid) -> BidProgress:
        return self.counts([bid], self.assignments)

    def bid_section_progress(self, bid: Bid, section_id: UUID) -> BidProgress:
        return self.counts([bid], self.section_users(section_id))

    def assignment_progress(self, assignment: Assignment) -> BidProgress:
        return self.counts(self.live_bids, [assignment])

    def complete(self) -> bool:
        """Every expected assessment is in (and at least one was expected)."""
        progress = self.call_progress()
        return progress.total > 0 and progress.submitted == progress.total

    # --- Must-haves -------------------------------------------------------------------------
    def results_of(self, bid_id: UUID) -> list[MustHaveResult]:
        """The bid's result for every must-have (one missing a row reads as missing)."""
        found = self.results.get(bid_id, {})
        return [
            found[m.id].result if m.id in found else MustHaveResult.MISSING for m in self.must_haves
        ]


async def load_call_data(
    db: AsyncSession,
    call: BidCall,
    *,
    answers: bool = False,
    results: bool = False,
    ai: bool = False,
) -> CallData:
    """The call's rows (see the module docstring): six statements, plus one for each of
    ``answers``, ``results`` and ``ai`` (two for ``ai``)."""
    sections = list(
        await db.scalars(
            select(BidCallSection)
            .where(BidCallSection.call_id == call.id)
            .order_by(BidCallSection.position, BidCallSection.id)
            .execution_options(populate_existing=True)
        )
    )
    questions: dict[UUID, list[BidCallQuestion]] = defaultdict(list)
    for question in await db.scalars(
        select(BidCallQuestion)
        .where(BidCallQuestion.call_id == call.id)
        .order_by(BidCallQuestion.position, BidCallQuestion.id)
        .execution_options(populate_existing=True)
    ):
        questions[question.section_id].append(question)
    must_haves = list(
        await db.scalars(
            select(BidCallMustHave)
            .where(BidCallMustHave.call_id == call.id)
            .order_by(BidCallMustHave.position, BidCallMustHave.id)
            .execution_options(populate_existing=True)
        )
    )
    rows = await db.execute(
        select(
            BidSectionAssessor,
            User,
            eligible_assessor(BidSectionAssessor.user_id, Project.id).label("eligible"),
        )
        .join(User, User.id == BidSectionAssessor.user_id)
        .join(BidCall, BidCall.id == BidSectionAssessor.call_id)
        .join(Idea, Idea.id == BidCall.idea_id)
        .join(Project, Project.id == Idea.project_id)
        .where(BidSectionAssessor.call_id == call.id)
        .execution_options(populate_existing=True)
    )
    order = {section.id: index for index, section in enumerate(sections)}
    assignments = sorted(
        (
            Assignment(row[0].section_id, row[1], bool(row[2]), row[0].assigned_at)
            for row in rows.all()
        ),
        key=lambda a: (order.get(a.section_id, 0), a.user.display_name.casefold(), a.user.id),
    )
    bids = list(
        await db.scalars(
            select(Bid)
            .where(Bid.call_id == call.id)
            .order_by(Bid.received_at, Bid.id)
            .execution_options(populate_existing=True)
        )
    )
    states: dict[Key, EvaluationStatus] = {
        (bid_id, section_id, assessor_id): status
        for bid_id, section_id, assessor_id, status in await db.execute(
            select(
                BidAssessment.bid_id,
                BidAssessment.section_id,
                BidAssessment.assessor_id,
                BidAssessment.status,
            ).where(BidAssessment.call_id == call.id)
        )
    }
    data = CallData(
        call=call,
        sections=sections,
        questions=dict(questions),
        must_haves=must_haves,
        assignments=assignments,
        bids=bids,
        states=states,
    )
    if answers:
        found: dict[Key, dict[UUID, BidAssessmentAnswer]] = defaultdict(dict)
        for row, answer in await db.execute(
            select(BidAssessment, BidAssessmentAnswer)
            .join(BidAssessmentAnswer, BidAssessmentAnswer.assessment_id == BidAssessment.id)
            .where(
                BidAssessment.call_id == call.id,
                BidAssessment.status == EvaluationStatus.SUBMITTED,
            )
        ):
            key = (row.bid_id, row.section_id, row.assessor_id)
            found[key][answer.question_id] = answer
        data.answers = dict(found)
    if results:
        by_bid: dict[UUID, dict[UUID, BidMustHaveResult]] = defaultdict(dict)
        for result in await db.scalars(
            select(BidMustHaveResult)
            .where(BidMustHaveResult.call_id == call.id)
            .execution_options(populate_existing=True)
        ):
            by_bid[result.bid_id][result.must_have_id] = result
        data.results = dict(by_bid)
    if ai:
        bid_ids = [bid.id for bid in bids]
        assessments: dict[UUID, list[BidAiAssessment]] = defaultdict(list)
        if bid_ids:
            for assessment in await db.scalars(
                select(BidAiAssessment)
                .where(BidAiAssessment.bid_id.in_(bid_ids))
                .order_by(BidAiAssessment.submitted_at, BidAiAssessment.id)
                .execution_options(populate_existing=True)
            ):
                assessments[assessment.bid_id].append(assessment)
        data.ai = dict(assessments)
        ids = [a.id for items in assessments.values() for a in items]
        scores: dict[UUID, dict[UUID, BidAiScore]] = defaultdict(dict)
        if ids:
            for score in await db.scalars(
                select(BidAiScore).where(BidAiScore.ai_assessment_id.in_(ids))
            ):
                scores[score.ai_assessment_id][score.question_id] = score
        data.ai_scores = dict(scores)
    return data
