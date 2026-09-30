"""My work (home): evaluations I owe, ideas I own, recent activity, sidebar counts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.enums import IdeaStatus
from app.schemas.activity import ActivityItem
from app.schemas.base import ResponseModel
from app.schemas.ideas import IdeaRef, IdeaSummary
from app.schemas.users import UserRef

__all__ = ["Work", "WorkCounts", "WorkEvaluation", "WorkOwnedGroup", "WorkRecentIdea"]


class WorkEvaluation(ResponseModel):
    """An evaluation you still owe (evaluation open, not yet submitted)."""

    idea: IdeaRef = Field(description="The idea and its project.")
    owner: UserRef | None
    due_at: datetime | None
    overdue: bool = Field(description="due_at is in the past.")
    state: Literal["invited", "draft"]


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
    """Sidebar badges."""

    evaluations_due: int = Field(description="Evaluations you owe (length of evaluations_due).")
    evaluations_overdue: int
    owned_open: int = Field(description="Ideas you own that are not closed.")


class Work(ResponseModel):
    counts: WorkCounts
    evaluations_due: list[WorkEvaluation] = Field(
        description="Overdue first, then soonest due; no due date last."
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
