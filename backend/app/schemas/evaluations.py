"""Evaluations: other people's (blind-filtered) and your own."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.models.enums import EvaluatorState, Recommendation
from app.schemas.base import RequestModel, ResponseModel, Score
from app.schemas.rubric import MAX_CRITERIA
from app.schemas.users import UserRef

__all__ = [
    "Evaluation",
    "EvaluationList",
    "EvaluationScore",
    "MyEvaluation",
    "MyEvaluationIn",
    "MyScore",
    "MyScoreIn",
]


class EvaluationScore(ResponseModel):
    criterion_id: UUID
    score: Score
    comment: str


class Evaluation(ResponseModel):
    """A submitted evaluation as others see it (drafts are never shown to anyone else)."""

    id: UUID
    evaluator: UserRef
    recommendation: Recommendation
    comment: str
    scores: list[EvaluationScore] = Field(description="Active criteria only, rubric order.")
    submitted_at: datetime = Field(description="First submission.")
    edited_at: datetime | None = Field(
        description='Last change after the first submission; show "edited after submission".'
    )
    is_ai: bool = Field(description="The evaluator is an AI agent's service account (Phase 6).")
    include_in_aggregate: bool = Field(
        description="False for AI evaluations unless the owner includes them (Phase 6)."
    )


class EvaluationList(ResponseModel):
    """Submitted evaluations of an idea, or nothing while you owe your own."""

    items: list[Evaluation] = Field(
        description="Oldest submission first; empty while score_hidden."
    )
    score_hidden: bool = Field(
        description="You are an assigned evaluator who has not submitted (blind evaluation)."
    )


class MyScore(ResponseModel):
    criterion_id: UUID
    score: Score | None = Field(description="Null only in a draft.")
    comment: str


class MyEvaluation(ResponseModel):
    """Your evaluation of an idea you were asked to evaluate (the evaluate sheet)."""

    idea_id: UUID
    state: EvaluatorState = Field(description="invited = nothing saved yet.")
    editable: bool = Field(description="Evaluation is open, so you can still save changes.")
    due_at: datetime | None
    recommendation: Recommendation | None
    comment: str
    scores: list[MyScore] = Field(description="Saved scores for active criteria, rubric order.")
    submitted_at: datetime | None
    updated_at: datetime | None = Field(description="Last save; null until first saved.")


class MyScoreIn(RequestModel):
    criterion_id: UUID
    score: Score | None = None
    comment: str = Field(default="", max_length=1000)


class MyEvaluationIn(RequestModel):
    """Save your evaluation (replaces what was saved before).

    ``submit: false`` saves a draft (any subset of scores). ``submit: true`` submits:
    every active criterion needs a score and ``recommendation`` is required, else
    422 ``evaluation_incomplete``. A submitted evaluation stays submitted; later
    saves must also use ``submit: true`` (409 ``evaluation_already_submitted``).
    """

    scores: list[MyScoreIn] = Field(default_factory=list, max_length=MAX_CRITERIA)
    recommendation: Recommendation | None = None
    comment: str = Field(default="", max_length=4000)
    submit: bool = False

    @field_validator("scores")
    @classmethod
    def _unique_criteria(cls, scores: list[MyScoreIn]) -> list[MyScoreIn]:
        ids = [score.criterion_id for score in scores]
        if len(set(ids)) != len(ids):
            raise ValueError("each criterion may appear only once")
        return scores
