"""My work (home): evaluations I owe, research to do (Phase 8b), ideas I own, recent
activity, sidebar counts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.enums import IdeaStatus
from app.schemas.activity import ActivityItem
from app.schemas.base import ResponseModel
from app.schemas.common import Page
from app.schemas.ideas import IdeaRef, IdeaSummary
from app.schemas.research import ResearchProgress
from app.schemas.users import UserRef

__all__ = [
    "EVALUATIONS_DUE_PAGE",
    "OWNED_GROUP_PREVIEW",
    "RESEARCH_TO_DO_PAGE",
    "Work",
    "WorkCounts",
    "WorkEvaluation",
    "WorkEvaluationPage",
    "WorkOwnedGroup",
    "WorkRecentIdea",
    "WorkResearch",
    "WorkResearchPage",
]

EVALUATIONS_DUE_PAGE = 50
"""``GET /me/work`` lists the first 50 evaluations due (Phase 7, C1);
``GET /me/evaluations-due?cursor=`` pages through the rest in the same order."""

RESEARCH_TO_DO_PAGE = 50
"""Phase 8b: ``GET /me/work`` lists the first 50 ideas whose research you do;
``GET /me/research-to-do?cursor=`` pages through the rest in the same order."""

OWNED_GROUP_PREVIEW = 10
"""Phase 8b (D, lead decision on the Phase 8 review): each owned group in ``GET /me/work``
holds its first 10 ideas (was 50); the SPA shows them and pages on with the group's
``next_cursor`` (``GET /me/owned-ideas``)."""


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


class WorkResearch(ResponseModel):
    """Phase 8b: an idea whose research you do (as its researcher, or as its owner while
    nobody is assigned) and that still needs it: the project's step is on, the idea is in
    Research or before it (``research_to_do``) and a required checklist item is open. Only
    for someone who may answer it (``idea.answer_research``: the researcher while the
    assignment is live; the owner while their role counts, or a platform admin)."""

    idea: IdeaRef = Field(
        description=(
            "The idea and its project. A guest researcher can't open the project: show its "
            "name as text (can_view_project)."
        )
    )
    can_view_project: bool = Field(
        default=True,
        description=(
            "project.view on the idea's project: link the project's name. False for a guest "
            "researcher (role matrix column R): show it as text, never a link (project "
            "routes are 404 for them)."
        ),
    )
    owner: UserRef | None
    as_owner: bool = Field(
        description="You do it as the idea's owner (nobody is assigned), not as its researcher."
    )
    due_at: datetime | None = Field(description="The research due date, or null.")
    overdue: bool = Field(description="due_at is in the past.")
    progress: ResearchProgress = Field(
        description='The checklist at a glance: "2 open" is progress.required_open.'
    )


class WorkResearchPage(Page[WorkResearch]):
    """Research you do, in My work's order (overdue first, then soonest due, no due date
    last; then by idea id, like evaluations due). "Show all" pages on from
    ``Work.research_to_do_next_cursor``."""


class WorkOwnedGroup(ResponseModel):
    status: IdeaStatus
    label: str = Field(description="The default status label (groups span projects).")
    count: int = Field(description="All ideas you own in this status.")
    ideas: list[IdeaSummary] = Field(
        description=(
            "Most recently active first; the first 10 (Phase 8b; was 50). count has the "
            "total; page on with next_cursor."
        )
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
    research_to_do: int = Field(
        default=0,
        description=(
            "Phase 8b: all ideas whose research you do and that still need it "
            "(Work.research_to_do lists the first 50)."
        ),
    )
    research_overdue: int = Field(
        default=0, description="Phase 8b: those of them past their research due date."
    )


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
    research_to_do: list[WorkResearch] = Field(
        default_factory=list,
        description=(
            'Phase 8b: "Research to do": overdue first, then soonest due; no due date last. '
            "The first 50 (counts.research_to_do has the total)."
        ),
    )
    research_to_do_next_cursor: str | None = Field(
        default=None,
        description=(
            "More research to do: GET /me/research-to-do?cursor=<this>; null when "
            "research_to_do holds it all."
        ),
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
