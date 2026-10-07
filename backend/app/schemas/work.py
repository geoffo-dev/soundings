"""My work (home): evaluations I owe, ideas I own, recent activity, sidebar counts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.enums import IdeaStatus
from app.schemas.activity import ActivityItem
from app.schemas.base import ResponseModel
from app.schemas.common import Page
from app.schemas.ideas import IdeaRef, IdeaSummary
from app.schemas.users import UserRef

__all__ = [
    "EVALUATIONS_DUE_PAGE",
    "Work",
    "WorkCounts",
    "WorkEvaluation",
    "WorkEvaluationPage",
    "WorkOwnedGroup",
    "WorkRecentIdea",
]

EVALUATIONS_DUE_PAGE = 50
"""``GET /me/work`` lists the first 50 evaluations due (Phase 7, C1);
``GET /me/evaluations-due?cursor=`` pages through the rest in the same order."""


class WorkEvaluation(ResponseModel):
    """An evaluation you still owe (evaluation open, not yet submitted)."""

    idea: IdeaRef = Field(description="The idea and its project.")
    owner: UserRef | None
    due_at: datetime | None
    overdue: bool = Field(description="due_at is in the past.")
    state: Literal["invited", "draft"]


class WorkEvaluationPage(Page[WorkEvaluation]):
    """Evaluations you owe, in My work's order (overdue first, then soonest due, no due
    date last). Phase 7 (C1): "Show all" pages on from ``Work.evaluations_due_next_cursor``."""


class WorkOwnedGroup(ResponseModel):
    status: IdeaStatus
    label: str = Field(description="The default status label (groups span projects).")
    count: int = Field(description="All ideas you own in this status.")
    ideas: list[IdeaSummary] = Field(
        description="Most recently active first; the first 50 (count has the total)."
    )
    next_cursor: str | None = Field(
        description=(
            "More in this group: GET /me/owned-ideas?status=<status>&cursor=<next_cursor>."
        )
    )


class WorkRecentIdea(ResponseModel):
    """A recently active idea and the latest thing that happened to it."""

    idea: IdeaSummary
    latest_activity: ActivityItem | None


class WorkCounts(ResponseModel):
    """Sidebar badges (also ``GET /me/work/counts``, which runs only the counts)."""

    evaluations_due: int = Field(
        description=("All evaluations you owe (Work.evaluations_due lists the first 50 of them).")
    )
    evaluations_overdue: int
    owned_open: int = Field(description="Ideas you own that are not closed.")


class Work(ResponseModel):
    counts: WorkCounts
    evaluations_due: list[WorkEvaluation] = Field(
        description=(
            "Overdue first, then soonest due; no due date last. The first 50 "
            "(counts.evaluations_due has the total)."
        )
    )
    evaluations_due_next_cursor: str | None = Field(
        description=(
            "More evaluations due: GET /me/evaluations-due?cursor=<this>; null when "
            "evaluations_due holds them all."
        )
    )
    owned: list[WorkOwnedGroup] = Field(
        description=(
            "Ideas you own, grouped by status in lifecycle order (closed last, for the "
            "collapsed 'Show closed' row); empty groups are omitted."
        )
    )
    recent: list[WorkRecentIdea] = Field(
        description=(
            "The 20 most recently active ideas in projects you are a member of, one entry per idea."
        )
    )
