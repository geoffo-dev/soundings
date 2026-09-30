"""The rubric every new project starts with (SPEC section 2).

Five criteria, equal weights. Effort and Risk are *inverted*: evaluators score how
much effort/risk there is (5 = a lot), and the aggregate counts ``6 - score`` so a
higher aggregate is always better. Guidance hints for scores 1, 3 and 5 are shown
on hover/focus in the evaluate sheet. Project admins can edit all of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Final
from uuid import UUID

from app.models.project import RubricCriterion


@dataclass(frozen=True, slots=True)
class DefaultCriterion:
    name: str
    description: str
    inverted: bool
    guidance: MappingProxyType[str, str]
    weight: Decimal = field(default=Decimal("1.00"))


def _hints(one: str, three: str, five: str) -> MappingProxyType[str, str]:
    return MappingProxyType({"1": one, "3": three, "5": five})


DEFAULT_RUBRIC: Final[tuple[DefaultCriterion, ...]] = (
    DefaultCriterion(
        name="Value",
        description="How much this would benefit customers or the organisation.",
        inverted=False,
        guidance=_hints(
            "Little or no clear benefit.",
            "A useful benefit for some users or teams.",
            "A major benefit for many customers or the whole organisation.",
        ),
    ),
    DefaultCriterion(
        name="Feasibility",
        description="How confident we are that we could build and run it.",
        inverted=False,
        guidance=_hints(
            "Unproven, with major unknowns or dependencies.",
            "Achievable, with some unknowns to resolve first.",
            "Straightforward with the skills and technology we have.",
        ),
    ),
    DefaultCriterion(
        name="Effort",
        description="How much time, money and people it would take (higher = more effort).",
        inverted=True,
        guidance=_hints(
            "A few days for a small team.",
            "A few months for one team.",
            "A major programme across several teams.",
        ),
    ),
    DefaultCriterion(
        name="Strategic fit",
        description="How well it supports our strategy and current priorities.",
        inverted=False,
        guidance=_hints(
            "Unrelated to our strategy.",
            "Supports a secondary goal.",
            "Directly advances a top priority.",
        ),
    ),
    DefaultCriterion(
        name="Risk",
        description="How much could go wrong: delivery, legal, security or reputation.",
        inverted=True,
        guidance=_hints(
            "Low risk and easy to undo.",
            "Some risks, and we know how to manage them.",
            "Serious risks that are hard to mitigate.",
        ),
    ),
)


def default_rubric_criteria(project_id: UUID) -> list[RubricCriterion]:
    """New ``RubricCriterion`` rows for a project (add them in the create transaction)."""
    return [
        RubricCriterion(
            project_id=project_id,
            position=position,
            name=criterion.name,
            description=criterion.description,
            weight=criterion.weight,
            inverted=criterion.inverted,
            guidance=dict(criterion.guidance),
        )
        for position, criterion in enumerate(DEFAULT_RUBRIC)
    ]
