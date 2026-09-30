"""The idea activity feed: comments and events, as a discriminated union on ``type``.

Stored in ``activity_events`` (``type`` + JSON ``payload`` holding ids and from/to
values); the API resolves ids to ``UserRef``. Payloads never contain scores, so
the feed is safe to show to anyone who can view the idea, blind evaluation or not.
New types are added per phase; clients should skip types they do not know.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.models.enums import IdeaStatus, Resolution
from app.schemas.base import ResponseModel
from app.schemas.common import Page
from app.schemas.users import UserRef

__all__ = [
    "ACTIVITY_TYPES",
    "ActivityItem",
    "ActivityPage",
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
    | DueDateChangedActivity,
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
)
"""Every ``activity_events.type`` value in Phase 1."""


class ActivityPage(Page[ActivityItem]):
    """Newest first. Reverse client-side to show oldest-to-newest."""
