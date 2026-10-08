"""The idea activity feed: comments and events, as a discriminated union on ``type``.

Stored in ``activity_events`` (``type`` + JSON ``payload`` holding ids and from/to
values); the API resolves ids to ``UserRef``. Payloads never contain scores, so
the feed is safe to show to anyone who can view the idea, blind evaluation or not.
New types are added per phase; clients should skip types they do not know.

Phase 8b (review M2): the evaluation events (:data:`EVALUATION_ACTIVITY_TYPES`) rebuild the
evaluation area a guest researcher must not see, so a principal without
``evaluation.view_own`` gets only :data:`RESEARCH_GUEST_ACTIVITY_TYPES` (an allow-list).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.models.enums import IdeaStatus, Resolution
from app.schemas.ai import ResearchNote
from app.schemas.base import ResponseModel
from app.schemas.common import Page
from app.schemas.users import UserRef

__all__ = [
    "ACTIVITY_TYPES",
    "AI_RESEARCH_NOTE",
    "EVALUATION_ACTIVITY_TYPES",
    "PHASE8B_ACTIVITY_TYPES",
    "RESEARCH_GUEST_ACTIVITY_TYPES",
    "ActivityItem",
    "ActivityPage",
    "AiResearchNoteActivity",
    "CommentActivity",
    "CommentBody",
    "DueDateChangedActivity",
    "EvaluationClosedActivity",
    "EvaluationReopenedActivity",
    "EvaluationSubmittedActivity",
    "EvaluatorAddedActivity",
    "EvaluatorRemovedActivity",
    "IdeaCreatedActivity",
    "IdeaEditedActivity",
    "IdeaEditedField",
    "OwnerChangedActivity",
    "ResearchDueDateChangedActivity",
    "ResearcherChangedActivity",
    "StatusChangedActivity",
]

IdeaEditedField = Literal["title", "summary", "description_md", "tags"]


class _ActivityBase(ResponseModel):
    id: UUID
    idea_id: UUID
    created_at: datetime
    actor: UserRef | None = Field(description="Who did it; null if the user no longer exists.")


class CommentBody(ResponseModel):
    id: UUID
    body_md: str = Field(description="Empty when deleted.")
    edited_at: datetime | None
    deleted: bool = Field(description='Show a "comment deleted" placeholder.')
    can_edit: bool = Field(description="You wrote it (and may still comment).")
    can_delete: bool = Field(description="You wrote it, or you are a project admin.")


class CommentActivity(_ActivityBase):
    type: Literal["comment"]
    comment: CommentBody


class IdeaCreatedActivity(_ActivityBase):
    type: Literal["idea_created"]


class IdeaEditedActivity(_ActivityBase):
    type: Literal["idea_edited"]
    fields: list[IdeaEditedField] = Field(description="What changed (values are not kept).")


class StatusChangedActivity(_ActivityBase):
    type: Literal["status_changed"]
    from_status: IdeaStatus
    from_resolution: Resolution | None
    to_status: IdeaStatus
    to_resolution: Resolution | None
    research_overridden: bool = Field(
        default=False,
        description=(
            'Phase 8: an admin moved it past an unfinished research checklist ("Move '
            'anyway"): say "without finishing research". Stored in the payload as '
            "research_overridden: true (absent = false)."
        ),
    )
    from_label: str | None = Field(
        default=None,
        description=(
            "Phase 8b: the project's label for from_status / from_resolution when the feed "
            "is read (not stored), so the sentence needs no project read (a guest researcher "
            "can't read the project); null: use the default label."
        ),
    )
    to_label: str | None = Field(
        default=None,
        description="Phase 8b: the project's label for to_status / to_resolution, like from_label.",
    )


class OwnerChangedActivity(_ActivityBase):
    type: Literal["owner_changed"]
    from_owner: UserRef | None
    to_owner: UserRef | None
    volunteered: bool = Field(description='The new owner chose "I\'ll own this".')


class EvaluatorAddedActivity(_ActivityBase):
    type: Literal["evaluator_added"]
    evaluator: UserRef | None


class EvaluatorRemovedActivity(_ActivityBase):
    type: Literal["evaluator_removed"]
    evaluator: UserRef | None


class EvaluationSubmittedActivity(_ActivityBase):
    """First submission only (later edits are not events). Never includes scores."""

    type: Literal["evaluation_submitted"]
    evaluator: UserRef | None


class EvaluationClosedActivity(_ActivityBase):
    type: Literal["evaluation_closed"]


class EvaluationReopenedActivity(_ActivityBase):
    type: Literal["evaluation_reopened"]


class DueDateChangedActivity(_ActivityBase):
    type: Literal["due_date_changed"]
    from_due_at: datetime | None
    to_due_at: datetime | None


class AiResearchNoteActivity(_ActivityBase):
    """Phase 6: a research note an AI agent wrote for an "Ask AI to research" run (actor: the
    agent's service account; the SPA's ``describeActivity`` says "wrote a research note",
    or "deleted a research note" once ``note.deleted``). Stored as an ``activity_events``
    row of type :data:`AI_RESEARCH_NOTE` whose payload is ``{run_id, agent_id, body_md,
    sources: [{title, url}]}`` (a deleted note keeps ``run_id`` and ``agent_id`` and gets
    ``deleted: true``, ``body_md: ""``, ``sources: []``). Never holds score data
    (contract-phase6 sections 3.8 and 5)."""

    type: Literal["ai_research_note"]
    note: ResearchNote


AI_RESEARCH_NOTE = "ai_research_note"
"""``activity_events.type`` of a research note (Phase 6)."""


class ResearcherChangedActivity(_ActivityBase):
    """Phase 8b: the idea's researcher changed (assigned, changed, removed, or handed back
    by the researcher: ``handed_back``). Stored as ``researcher_changed`` with payload
    ``{from_researcher_id, to_researcher_id, handed_back}``. "Asked to research" notifies
    the new researcher from it. Deactivating a researcher clears the assignment without
    an event."""

    type: Literal["researcher_changed"]
    from_researcher: UserRef | None = Field(description="Null: nobody was assigned (the owner).")
    to_researcher: UserRef | None = Field(description="Null: nobody now (the owner does it).")
    handed_back: bool = Field(description='The researcher removed themselves ("Hand back").')


class ResearchDueDateChangedActivity(_ActivityBase):
    """Phase 8b: the research due date changed (``research_due_date_changed``, payload
    ``{from_due_at, to_due_at}``). No notification: reminders follow the current date."""

    type: Literal["research_due_date_changed"]
    from_due_at: datetime | None
    to_due_at: datetime | None


ActivityItem = Annotated[
    CommentActivity
    | IdeaCreatedActivity
    | IdeaEditedActivity
    | StatusChangedActivity
    | OwnerChangedActivity
    | EvaluatorAddedActivity
    | EvaluatorRemovedActivity
    | EvaluationSubmittedActivity
    | EvaluationClosedActivity
    | EvaluationReopenedActivity
    | DueDateChangedActivity
    | AiResearchNoteActivity
    | ResearcherChangedActivity
    | ResearchDueDateChangedActivity,
    Field(discriminator="type"),
]
"""One feed entry; branch on ``type``."""

ACTIVITY_TYPES: tuple[str, ...] = (
    "comment",
    "idea_created",
    "idea_edited",
    "status_changed",
    "owner_changed",
    "evaluator_added",
    "evaluator_removed",
    "evaluation_submitted",
    "evaluation_closed",
    "evaluation_reopened",
    "due_date_changed",
    AI_RESEARCH_NOTE,
)
"""Every ``activity_events.type`` value (Phase 1, plus Phase 6's research notes).

Phase 8b: backend adds :data:`PHASE8B_ACTIVITY_TYPES` here together with their
``app.services.activity.PAYLOAD_KEYS`` (an import-time guard ties the two), when it
emits them; the union above already has their items (contract-phase8b section 8)."""

PHASE8B_ACTIVITY_TYPES: tuple[str, ...] = ("researcher_changed", "research_due_date_changed")
"""Phase 8b's two feed events (the research assignment), until they join
:data:`ACTIVITY_TYPES`."""

EVALUATION_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        "evaluator_added",
        "evaluator_removed",
        "evaluation_submitted",
        "evaluation_closed",
        "evaluation_reopened",
        "due_date_changed",
    }
)
"""The feed events that rebuild the evaluation area (who evaluates, who submitted, AI
evaluations included, the window and its due date). Phase 8b review M2: a principal
without ``evaluation.view_own`` on the idea (a guest researcher, role matrix column R)
never gets them; see :data:`RESEARCH_GUEST_ACTIVITY_TYPES`."""

RESEARCH_GUEST_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        "comment",
        "idea_created",
        "idea_edited",
        "status_changed",
        "owner_changed",
        AI_RESEARCH_NOTE,
        "researcher_changed",
        "research_due_date_changed",
    }
)
"""Phase 8b review M2: **the allow-list** of feed events for a principal without
``evaluation.view_own`` on the idea (a guest researcher, role matrix column R, table L):
``list_idea_activity`` returns only these types to them (deny by default: a type added
later stays hidden from guests until it is added here). Every other caller gets the whole
feed. ``tests/test_schemas_phase8b.py`` checks that this set and
:data:`EVALUATION_ACTIVITY_TYPES` split every feed type."""


class ActivityPage(Page[ActivityItem]):
    """Newest first. Reverse client-side to show oldest-to-newest."""
