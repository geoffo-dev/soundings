"""Phase 8b schemas (contract-phase8b): the research assignment, its request, the
"Research to do" rule, the two notification types and the My work and MCP additions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.enums import IdeaStatus, NotificationType, ResearchStep
from app.schemas.activity import (
    ACTIVITY_TYPES,
    EVALUATION_ACTIVITY_TYPES,
    PHASE8B_ACTIVITY_TYPES,
    RESEARCH_GUEST_ACTIVITY_TYPES,
    StatusChangedActivity,
)
from app.schemas.ideas import IdeaPermissions
from app.schemas.mcp import McpIdeaDetail, McpResearch
from app.schemas.notifications import (
    RESEARCH_GUEST_NOTIFICATION_TYPES,
    NotificationPreferencesUpdate,
    UnsubscribeScope,
)
from app.schemas.proposals import RemovedTemplateSection
from app.schemas.research import (
    IdeaResearch,
    RemovedResearchItem,
    ResearchAssignment,
    ResearchAssignmentUpdate,
    awaits_research,
    research_to_do,
)
from app.schemas.work import OWNED_GROUP_PREVIEW, RESEARCH_TO_DO_PAGE, WorkCounts, WorkResearch

OFF, BEFORE_EVALUATION, BEFORE_PROPOSAL = (
    ResearchStep.OFF,
    ResearchStep.BEFORE_EVALUATION,
    ResearchStep.BEFORE_PROPOSAL,
)
NEW, RESEARCH, EVALUATING, SHORTLISTED, PROPOSAL, CLOSED = tuple(IdeaStatus)


def _in(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


# --- The assignment request ------------------------------------------------------------------
def test_an_assignment_is_the_complete_new_state() -> None:
    researcher = uuid.uuid4()

    update = ResearchAssignmentUpdate.model_validate(
        {"researcher_id": str(researcher), "due_at": _in(3)}
    )
    nobody = ResearchAssignmentUpdate.model_validate({"researcher_id": None, "due_at": None})

    assert update.researcher_id == researcher
    assert update.due_at is not None
    assert (nobody.researcher_id, nobody.due_at) == (None, None)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"researcher_id": None},
        {"due_at": None},
        {"researcher_id": "bob", "due_at": None},
        {"researcher_id": None, "due_at": "2026-10-11"},  # no time
        {"researcher_id": None, "due_at": "2026-10-11T17:00:00"},  # no offset
        {"researcher_id": None, "due_at": _in(-400)},  # more than a year ago
        {"researcher_id": None, "due_at": _in(5 * 366 + 2)},  # beyond five years
        {"researcher_id": None, "due_at": None, "notify": False},  # unknown field
    ],
)
def test_assignment_requests_are_validated(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ResearchAssignmentUpdate.model_validate(body)


# --- What is still to do -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("step", "status", "expected"),
    [
        (OFF, NEW, False),
        (OFF, EVALUATING, False),
        (BEFORE_EVALUATION, NEW, True),
        (BEFORE_EVALUATION, RESEARCH, True),
        (BEFORE_EVALUATION, EVALUATING, False),
        (BEFORE_EVALUATION, PROPOSAL, False),
        (BEFORE_EVALUATION, CLOSED, False),
        (BEFORE_PROPOSAL, NEW, True),
        (BEFORE_PROPOSAL, EVALUATING, True),
        (BEFORE_PROPOSAL, SHORTLISTED, True),
        (BEFORE_PROPOSAL, RESEARCH, True),
        (BEFORE_PROPOSAL, PROPOSAL, False),
        (BEFORE_PROPOSAL, CLOSED, False),
    ],
)
def test_research_awaits_while_the_idea_is_open_and_not_past_research(
    step: ResearchStep, status: IdeaStatus, expected: bool
) -> None:
    assert awaits_research(step, status) is expected


# step, status, required_open, assigned, has_due_date -> listed in "Research to do"
TO_DO_CASES: list[tuple[ResearchStep, IdeaStatus, int, bool, bool, bool]] = [
    # The researcher: every status that awaits research, while a required item is open.
    (BEFORE_EVALUATION, NEW, 2, True, False, True),
    (BEFORE_EVALUATION, RESEARCH, 1, True, False, True),
    (BEFORE_PROPOSAL, NEW, 2, True, False, True),
    (BEFORE_PROPOSAL, EVALUATING, 2, True, True, True),
    (BEFORE_EVALUATION, RESEARCH, 0, True, True, False),  # nothing required is open
    (BEFORE_EVALUATION, EVALUATING, 2, True, True, False),  # past Research
    (BEFORE_EVALUATION, CLOSED, 2, True, True, False),
    (OFF, NEW, 2, True, True, False),
    # The owner, nobody assigned: in Research or the status right before it...
    (BEFORE_EVALUATION, NEW, 2, False, False, True),
    (BEFORE_EVALUATION, RESEARCH, 2, False, False, True),
    (BEFORE_PROPOSAL, SHORTLISTED, 2, False, False, True),
    (BEFORE_PROPOSAL, RESEARCH, 2, False, False, True),
    # ...not their whole pipeline before a "Before proposal" step...
    (BEFORE_PROPOSAL, NEW, 2, False, False, False),
    (BEFORE_PROPOSAL, EVALUATING, 2, False, False, False),
    # ...unless someone set a research due date.
    (BEFORE_PROPOSAL, EVALUATING, 2, False, True, True),
    (BEFORE_PROPOSAL, PROPOSAL, 2, False, True, False),
    (BEFORE_PROPOSAL, RESEARCH, 0, False, True, False),
]


@pytest.mark.parametrize(
    ("step", "status", "required_open", "assigned", "has_due_date", "expected"), TO_DO_CASES
)
def test_research_to_do(
    step: ResearchStep,
    status: IdeaStatus,
    required_open: int,
    assigned: bool,
    has_due_date: bool,
    expected: bool,
) -> None:
    listed = research_to_do(
        step, status, required_open=required_open, assigned=assigned, has_due_date=has_due_date
    )

    assert listed is expected


# --- Responses -------------------------------------------------------------------------------
def test_new_response_fields_default_to_nobody_and_nothing() -> None:
    """Builders keep building the old shapes until they fill these in; the OpenAPI document
    still marks them required (contract-phase1 section 1)."""
    assignment = ResearchAssignment()

    assert (assignment.researcher, assignment.due_at, assignment.overdue) == (None, None, False)
    assert assignment.researcher_in_project is False
    assert IdeaResearch.model_fields["assignment"].default_factory is ResearchAssignment
    assert IdeaPermissions.model_fields["can_view_project"].default is True
    assert IdeaPermissions.model_fields["can_assign_researcher"].default is False
    assert IdeaPermissions.model_fields["can_hand_back_research"].default is False
    assert WorkCounts(evaluations_due=0, evaluations_overdue=0, owned_open=0).research_to_do == 0
    assert McpIdeaDetail.model_fields["research_guest"].default is False
    assert {"researcher", "due_at"} <= set(McpResearch.model_fields)
    assert {"position"} <= set(RemovedTemplateSection.model_fields)
    assert {"position"} <= set(RemovedResearchItem.model_fields)
    assert WorkResearch.model_fields["can_view_project"].default is True  # review S7
    assert StatusChangedActivity.model_fields["from_label"].default is None  # review C6
    assert StatusChangedActivity.model_fields["to_label"].default is None


def test_my_work_page_sizes() -> None:
    assert OWNED_GROUP_PREVIEW == 10  # D: was 50
    assert RESEARCH_TO_DO_PAGE == 50


# --- Notifications -------------------------------------------------------------------------
def test_each_research_type_has_a_preference_and_an_unsubscribe_scope() -> None:
    types = {t.value for t in NotificationType}

    assert {"researcher_assigned", "research_reminder"} <= types
    assert set(NotificationPreferencesUpdate.model_fields) == types
    assert {s.value for s in UnsubscribeScope} == types | {"digest", "all"}


def test_a_guest_researcher_holds_only_the_types_about_their_job_and_the_discussion() -> None:
    """Review S5: the inbox shows a guest researcher only these types about the idea."""
    assert {t.value for t in RESEARCH_GUEST_NOTIFICATION_TYPES} == {
        "status_changed",
        "comment",
        "mention",
        "researcher_assigned",
        "research_reminder",
    }


# --- The feed for a guest researcher (review M2) ------------------------------------------
def test_the_guest_feed_is_an_allow_list_that_leaves_out_the_evaluation_area() -> None:
    every_type = {*ACTIVITY_TYPES, *PHASE8B_ACTIVITY_TYPES}

    assert {
        "evaluator_added",
        "evaluator_removed",
        "evaluation_submitted",
        "evaluation_closed",
        "evaluation_reopened",
        "due_date_changed",
    } == EVALUATION_ACTIVITY_TYPES
    # Every feed type is decided: shown to a guest or part of the evaluation area. A new
    # type fails here until someone adds it to one of the two (deny by default for guests).
    assert every_type == RESEARCH_GUEST_ACTIVITY_TYPES | EVALUATION_ACTIVITY_TYPES
    assert not RESEARCH_GUEST_ACTIVITY_TYPES & EVALUATION_ACTIVITY_TYPES
