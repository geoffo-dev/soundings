"""A project's rubric: 3-6 weighted criteria scored 1-5."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import RequestModel, ResponseModel, ScoreKey

__all__ = [
    "MAX_CRITERIA",
    "MIN_CRITERIA",
    "Rubric",
    "RubricCriterion",
    "RubricCriterionIn",
    "RubricUpdate",
]

MIN_CRITERIA = 3
MAX_CRITERIA = 6

Weight = Annotated[
    float,
    Field(
        ge=0.01,
        le=10,
        multiple_of=0.01,
        description="Relative weight (default 1): 0.01 to 10, at most 2 decimal places.",
    ),
]
"""Matches ``rubric_criteria.weight`` (``numeric(4,2)``, > 0), so no value rounds to 0."""
Guidance = Annotated[
    dict[ScoreKey, Annotated[str, Field(max_length=200)]],
    Field(
        description=(
            'Hover hints keyed by score ("1".."5"); any subset, e.g. only 1, 3 and 5. '
            "Shown on hover/focus in the evaluate sheet."
        )
    ),
]


class RubricCriterion(ResponseModel):
    """An active criterion (``Project.rubric``)."""

    id: UUID
    position: int = Field(description="0-based display order.")
    name: str
    description: str
    weight: float
    inverted: bool = Field(
        description=(
            "A high score is bad (Effort, Risk). Scores are shown as entered; the "
            "aggregate uses 6 - score."
        )
    )
    guidance: Guidance


class Rubric(ResponseModel):
    """The rubric after ``replace_rubric``: active criteria in display order."""

    criteria: list[RubricCriterion]


class RubricCriterionIn(RequestModel):
    id: UUID | None = Field(
        default=None, description="Existing criterion to update; omit to add a new one."
    )
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    weight: Weight = 1.0
    inverted: bool = False
    guidance: Guidance = Field(default_factory=dict)


class RubricUpdate(RequestModel):
    """The complete new rubric, in display order.

    Criteria left out are removed: archived if already scored (old evaluations keep
    them), deleted otherwise. Changing the rubric recomputes every aggregate.
    """

    criteria: list[RubricCriterionIn] = Field(min_length=MIN_CRITERIA, max_length=MAX_CRITERIA)

    @field_validator("criteria")
    @classmethod
    def _unique(cls, criteria: list[RubricCriterionIn]) -> list[RubricCriterionIn]:
        names = [criterion.name.casefold() for criterion in criteria]
        if len(set(names)) != len(names):
            raise ValueError("criterion names must be unique")
        ids = [criterion.id for criterion in criteria if criterion.id is not None]
        if len(set(ids)) != len(ids):
            raise ValueError("a criterion id appears more than once")
        return criteria
