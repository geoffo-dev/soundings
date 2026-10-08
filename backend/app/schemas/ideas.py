"""Ideas: list rows, the idea page, the board and idea commands.

Blind evaluation (docs/api/contract-phase1.md#37-blind-evaluation): anything derived
from other people's scores (``score``, ``aggregate``, ``high_disagreement``) is withheld
from an assigned evaluator until they submit their own evaluation (``score_hidden``).

Phase 8b: a **guest researcher** (role matrix column R: the idea's researcher without a
role in its private project) gets the same shapes with no score or evaluation data:
``score`` / ``aggregate`` null, ``score_hidden`` true, ``high_disagreement`` false,
``evaluators`` empty, ``evaluator_progress`` 0/0, no evaluation dates,
``evaluation_open`` false, and ``permissions.can_view_project`` false (hide the
evaluation area, the Evaluations, Proposal and AI parts, and show the project as text).
Score data follows ``score.view_aggregate`` and the evaluation area
``evaluation.view_own`` on every surface that builds these shapes (review M1: lists
included; in SQL the idea's project must be one the caller can view).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.models.enums import EvaluatorState, HoldReason, IdeaStatus, Resolution
from app.schemas.base import (
    DUE_DATE_MAX_AHEAD,
    DUE_DATE_MAX_BACK,
    DueAt,
    RequestModel,
    ResponseModel,
    SingleLine,
    TagName,
)
from app.schemas.common import Page
from app.schemas.projects import ProjectRef
from app.schemas.research import ResearchOverride, ResearchProgress
from app.schemas.users import UserRef

__all__ = [
    "DUE_DATE_MAX_AHEAD",
    "DUE_DATE_MAX_BACK",
    "MAX_TAGS_PER_IDEA",
    "AggregateScore",
    "AggregateScoreSummary",
    "Board",
    "BoardColumn",
    "CriterionAggregate",
    "DueAt",
    "EvaluationDueDate",
    "EvaluatorProgress",
    "EvaluatorsAdd",
    "IdeaCreate",
    "IdeaDetail",
    "IdeaEvaluator",
    "IdeaPage",
    "IdeaPermissions",
    "IdeaRef",
    "IdeaSort",
    "IdeaSummary",
    "IdeaSummaryPermissions",
    "IdeaUpdate",
    "OwnerAssign",
    "RecommendationCounts",
    "ResolutionCounts",
    "SimilarIdea",
    "SimilarIdeas",
    "StatusChange",
    "VoteState",
    "WatchState",
]

MAX_TAGS_PER_IDEA = 10

IdeaSort = Literal[
    "score", "-score", "updated", "-updated", "created", "-created", "votes", "-votes", "title",
    "-title",
]  # fmt: skip
"""List/board order; ``-`` prefix = descending. ``updated`` is ``last_activity_at``.
Ideas without a (visible) score sort last in both directions. Ties break on ``id``."""


# --- Building blocks -----------------------------------------------------------------
class IdeaRef(ResponseModel):
    """Enough to show and link an idea (``/ideas/{key}``) and name its project."""

    id: UUID
    key: str = Field(description='"<project key>-<number>", e.g. "CUST-12".')
    number: int
    project: ProjectRef
    title: str
    status: IdeaStatus
    resolution: Resolution | None = Field(description="Set if and only if status is closed.")
    status_label: str = Field(
        description="Project label for the status; for closed ideas, the resolution's label."
    )


class EvaluatorProgress(ResponseModel):
    """E.g. 3/4: evaluators who submitted / evaluators assigned."""

    submitted: int
    total: int


class AggregateScoreSummary(ResponseModel):
    overall: float = Field(ge=1, le=5, description="Weighted aggregate, 1 decimal place.")
    count: int = Field(ge=1, description="Submitted evaluations included in the aggregate.")


class CriterionAggregate(ResponseModel):
    """Per-criterion statistics over included submitted evaluations, as scored (raw)."""

    criterion_id: UUID
    name: str
    weight: float
    inverted: bool
    mean: float = Field(description="Mean raw score, 1 decimal place.")
    min: int
    max: int
    spread: int = Field(description="max - min; >= 2 means evaluators disagree.")
    count: int


class RecommendationCounts(ResponseModel):
    go: int
    maybe: int
    no: int


class AggregateScore(ResponseModel):
    """The idea's aggregate over submitted evaluations with include_in_aggregate."""

    overall: float = Field(ge=1, le=5, description="Weighted mean, 1 decimal place.")
    count: int
    high_disagreement: bool
    criteria: list[CriterionAggregate] = Field(description="Active criteria, rubric order.")
    recommendations: RecommendationCounts


class ResolutionCounts(ResponseModel):
    """Closed ideas by resolution (the expanded Closed column)."""

    accepted: int
    rejected: int
    parked: int


class IdeaEvaluator(ResponseModel):
    """An assigned evaluator and their progress. Never carries scores."""

    user: UserRef
    state: EvaluatorState = Field(
        description=(
            "Drafts are private: other people's rows are only invited or submitted; "
            "draft appears only on your own row."
        )
    )
    is_ai: bool = Field(description="An AI agent (Phase 6); shown with an AI badge.")
    invited_at: datetime
    submitted_at: datetime | None


class IdeaSummaryPermissions(ResponseModel):
    """Per-card permissions for lists and the board (the API enforces the same rules)."""

    can_change_status: bool = Field(
        description="idea.change_status: show the board drag handle and status menu."
    )


class IdeaPermissions(IdeaSummaryPermissions):
    """What the current user may do with this idea (the API enforces the same rules).

    In an archived project every flag is false (idea writes answer 409
    project_archived), except the view flag ``can_view_project`` (Phase 8b), which says
    what the caller may read, not do.
    """

    can_edit: bool = Field(description="idea.edit_own / idea.edit_any: title, summary, tags.")
    can_assign_owner: bool = Field(description="idea.assign_owner: pick any eligible owner.")
    can_release_owner: bool = Field(description='idea.release_owner: "Step down" as owner.')
    can_volunteer: bool = Field(description='idea.volunteer_owner: "I\'ll own this".')
    can_invite_evaluators: bool = Field(
        description=(
            "evaluator.manage while evaluation is open (c6): invite evaluators. Also "
            "idea.set_due_date, which has the same conditions: edit the due date."
        )
    )
    can_remove_evaluators: bool = Field(
        description=(
            "evaluator.manage without c6: remove evaluators, open or closed. Offer it only "
            "on rows of others who have not submitted (403 cannot_remove_self, 409 "
            "evaluator_has_submitted)."
        )
    )
    can_evaluate: bool = Field(description="evaluation.submit_own: open the evaluate sheet.")
    can_close_evaluation: bool = Field(description="evaluation.close: close or reopen.")
    can_comment: bool = Field(description="comment.create")
    can_vote: bool = Field(description="idea.vote")
    can_delete: bool = Field(description="idea.delete")
    can_answer_research: bool = Field(
        default=False,
        description=(
            "Phase 8: idea.answer_research: answer, edit and clear research checklist items "
            "(the owner, the researcher (Phase 8b) and admins; false while the project's step "
            "is off)."
        ),
    )
    invite_blocked_by_research: bool = Field(
        default=False,
        description=(
            "Phase 8: inviting evaluators now would be refused (409 research_incomplete): "
            "the research step is before evaluation, the idea (New or Research) has no "
            'evaluator yet and required checklist items are open. Say so next to "Invite '
            'evaluators" (and "Ask AI to evaluate"); admins may invite anyway '
            "(IdeaResearch.permissions.can_override)."
        ),
    )
    can_assign_researcher: bool = Field(
        default=False,
        description=(
            "Phase 8b: idea.assign_researcher: assign, change or remove the researcher and "
            "set the research due date (the owner, project admins and platform admins; false "
            "while the research step is off or the idea is closed, and through an API key: "
            "assigning is session only)."
        ),
    )
    can_hand_back_research: bool = Field(
        default=False,
        description=(
            'Phase 8b: idea.release_researcher: you are the researcher: offer "Hand back".'
        ),
    )
    can_view_project: bool = Field(
        default=True,
        description=(
            "Phase 8b: project.view. False only for a guest researcher (role matrix column R): "
            "show the project's name as text (no link), and hide the evaluation area "
            "(evaluators, progress, due date), the Evaluations and Proposal tabs, the AI "
            "menu and anything else that reads the project (board, members, rubric, tags)."
        ),
    )


# --- Responses -----------------------------------------------------------------------
class IdeaSummary(IdeaRef):
    """A row in the list, a card on the board, an entry in My work."""

    summary: str
    owner: UserRef | None
    tags: list[str] = Field(description="Tag names, alphabetical.")
    evaluator_progress: EvaluatorProgress
    score: AggregateScoreSummary | None = Field(
        description="Null when there are no included submitted evaluations, or when hidden."
    )
    score_hidden: bool = Field(
        description=(
            "True while you owe this idea an evaluation (blind evaluation): show "
            '"Hidden until you submit".'
        )
    )
    high_disagreement: bool = Field(description="Always false while score_hidden.")
    vote_count: int
    has_voted: bool
    comment_count: int = Field(description="Comments that are not deleted.")
    created_at: datetime
    last_activity_at: datetime = Field(
        description='The latest activity event ("updated"); sort=updated uses it.'
    )
    research: ResearchProgress | None = Field(
        default=None,
        description=(
            'Phase 8: the research checklist at a glance ("2/3" on cards), only for an idea '
            "in Research or in the status right before it (New when Research comes before "
            "evaluation, Shortlisted when it comes before the proposal) while the project's "
            "research step is on; null otherwise (step off, past Research, closed). Holds "
            "no score data."
        ),
    )
    researcher: UserRef | None = Field(
        default=None,
        description=(
            "Phase 8b: the person asked to do the idea's research (cards in the Research "
            "column show their avatar); null when nobody is assigned (the owner does it) or "
            "the project's research step is off."
        ),
    )
    permissions: IdeaSummaryPermissions


class IdeaDetail(IdeaSummary):
    """The idea page."""

    description_md: str
    submitted_by: UserRef | None = Field(description="Null for anonymous/public submissions.")
    evaluators: list[IdeaEvaluator] = Field(description="In invitation order.")
    evaluation_due_at: datetime | None
    evaluation_closed_at: datetime | None
    evaluation_open: bool = Field(
        description="Evaluations can be saved: evaluation not closed and the idea not closed."
    )
    research_due_at: datetime | None = Field(
        default=None,
        description=(
            'Phase 8b: the research due date ("Research: <name> · due <date>" in the '
            "sidebar; the instance time zone), or null; null while the step is off."
        ),
    )
    aggregate: AggregateScore | None = Field(
        description="Null when there is nothing to aggregate yet, or when score_hidden."
    )
    watching: bool
    permissions: IdeaPermissions
    held_for: HoldReason | None = Field(
        description=(
            "Phase 4: moderation = a public submission waiting for review (only project "
            "and platform admins can open it; every permission but can_delete is false: "
            "show Approve / Reject from GET /ideas/{idea}/submission). Otherwise null."
        )
    )
    via_public_form: bool = Field(
        description=(
            "Phase 4: sent through the project's public form (submitted_by is null): "
            'show "via the public form" and the submission panel (GET '
            "/ideas/{idea}/submission). False for every internal idea."
        )
    )


class IdeaPage(Page[IdeaSummary]):
    """A page of ideas in the requested order."""

    total: int = Field(description='Ideas matching the filters, all pages ("42 ideas").')


class BoardColumn(ResponseModel):
    status: IdeaStatus = Field(
        description="research only in projects whose research step is on (Phase 8)."
    )
    label: str
    count: int = Field(description="All ideas in this column matching the filters.")
    resolution_counts: ResolutionCounts | None = Field(
        description=(
            "Closed column only (null elsewhere): count split by resolution. Expand it "
            "with GET /projects/{slug}/ideas?status=closed&resolution=<resolution>."
        )
    )
    items: list[IdeaSummary]
    next_cursor: str | None = Field(
        description=(
            "Load more with GET /projects/{slug}/ideas?status=<status>, the same filters "
            "and sort, and cursor=<next_cursor>."
        )
    )


class Board(ResponseModel):
    """One column per status of the project's lifecycle, in its order: five, or six with
    Research at the project's research step (Phase 8; ``Project.lifecycle``)."""

    columns: list[BoardColumn]


class VoteState(ResponseModel):
    vote_count: int
    has_voted: bool


class WatchState(ResponseModel):
    watching: bool


# --- Requests ------------------------------------------------------------------------
def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for tag in tags:
        seen.setdefault(tag.casefold(), tag)
    return list(seen.values())


class IdeaCreate(RequestModel):
    title: Annotated[str, Field(min_length=1, max_length=200), SingleLine]
    summary: str = Field(min_length=1, max_length=500, description="One or two sentences.")
    description_md: str = Field(default="", max_length=50_000, description="Markdown.")
    tags: list[TagName] = Field(
        default_factory=list,
        max_length=MAX_TAGS_PER_IDEA,
        description="Tag names; unknown tags are created. Duplicates (any case) are merged.",
    )

    @field_validator("tags")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        return _dedupe_tags(tags)


class IdeaUpdate(RequestModel):
    """Partial update: omitted or null fields are unchanged; ``tags`` replaces the set."""

    title: Annotated[str, Field(min_length=1, max_length=200), SingleLine] | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    description_md: str | None = Field(default=None, max_length=50_000)
    tags: list[TagName] | None = Field(default=None, max_length=MAX_TAGS_PER_IDEA)

    @field_validator("tags")
    @classmethod
    def _tags(cls, tags: list[str] | None) -> list[str] | None:
        return None if tags is None else _dedupe_tags(tags)


class StatusChange(ResearchOverride):
    """Move an idea. ``resolution`` is required for ``closed`` and forbidden otherwise.

    Phase 8: ``research`` only while the project's research step is on (else 409
    ``research_step_off``); a move into a status after Research from one before it (or
    reopening a closed idea into one, when it was closed from New, Research or a status
    before it) while required checklist items are open is 409 ``research_incomplete``
    unless an admin sends ``override_research``."""

    status: IdeaStatus
    resolution: Resolution | None = None

    @model_validator(mode="after")
    def _resolution_iff_closed(self) -> StatusChange:
        if self.status is IdeaStatus.CLOSED and self.resolution is None:
            raise ValueError("resolution is required when closing an idea")
        if self.status is not IdeaStatus.CLOSED and self.resolution is not None:
            raise ValueError("resolution is only allowed when closing an idea")
        return self


class OwnerAssign(RequestModel):
    user_id: UUID | None = Field(
        description="New owner (effective role member or admin), or null to leave it unowned."
    )


class EvaluatorsAdd(ResearchOverride):
    """Invite evaluators. Users already assigned are ignored.

    Phase 8: with a research step before evaluation, the first invite of an idea in New or
    Research while required checklist items are open is 409 ``research_incomplete`` unless
    an admin sends ``override_research``."""

    user_ids: list[UUID] = Field(min_length=1, max_length=20)
    due_at: DueAt | None = Field(
        default=None,
        description=(
            "Also set the evaluation due date. If omitted on the first invite (the idea "
            "has no evaluators yet) and the idea has no due date, it becomes now + the "
            "project's default_evaluation_days; later invites leave it alone."
        ),
    )


class EvaluationDueDate(RequestModel):
    """``PUT`` body: the complete new value (``null`` clears the due date)."""

    due_at: DueAt | None = Field(description="New due date, or null for none.")


# --- Phase 8: "Similar ideas" on the Research panel (contract-phase8 section 3.7) ------
class SimilarIdea(IdeaRef):
    """An idea whose title or summary is like this one's, in any project you can view.
    No score data (blind rules are unaffected)."""

    summary: str
    owner: UserRef | None = Field(description="Whom to ask about it.")
    last_activity_at: datetime
    similarity: float = Field(
        ge=0,
        le=1,
        description="pg_trgm similarity, 2 decimal places (the higher of title and summary).",
    )


class SimilarIdeas(ResponseModel):
    items: list[SimilarIdea] = Field(
        description=(
            "At most 5, most similar first (similarity >= 0.3), never the idea itself or a "
            "held idea; ideas you can view in every project you can view, archived ones "
            "included."
        )
    )
