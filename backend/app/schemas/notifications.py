"""Notifications: the in-app inbox, email preferences and unsubscribe links.

One fan-out feeds both channels (contract-phase3 section 3.3): every notification
lands in the recipient's inbox, and the recipient's preference for its type decides
whether it is also emailed now, in the daily digest, or not at all. Nothing here ever
carries a score (role matrix section 3, rule 8), and every notification is about one
idea the recipient can view (checked when it is created and again when it is shown or
emailed).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import Field

from app.models.enums import IdeaStatus, NotificationMode, NotificationType, Resolution
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.common import Page
from app.schemas.ideas import IdeaRef
from app.schemas.users import UserRef

__all__ = [
    "DEFAULT_MODES",
    "UNREAD_COUNT_CAP",
    "CommentExcerpt",
    "CommentNotification",
    "EvaluationReminderNotification",
    "EvaluationsCompleteNotification",
    "EvaluatorInvitedNotification",
    "MentionNotification",
    "NotificationItem",
    "NotificationMode",
    "NotificationPage",
    "NotificationPreference",
    "NotificationPreferences",
    "NotificationPreferencesUpdate",
    "NotificationSummary",
    "NotificationType",
    "OwnerAssignedNotification",
    "StatusChangedNotification",
    "UnsubscribeInfo",
    "UnsubscribeScope",
]

DEFAULT_MODES: Final[Mapping[NotificationType, NotificationMode]] = MappingProxyType(
    {
        NotificationType.OWNER_ASSIGNED: NotificationMode.IMMEDIATE,
        NotificationType.EVALUATOR_INVITED: NotificationMode.IMMEDIATE,
        NotificationType.EVALUATION_REMINDER: NotificationMode.IMMEDIATE,
        NotificationType.EVALUATIONS_COMPLETE: NotificationMode.IMMEDIATE,
        NotificationType.STATUS_CHANGED: NotificationMode.DIGEST,
        NotificationType.COMMENT: NotificationMode.DIGEST,
        NotificationType.MENTION: NotificationMode.IMMEDIATE,
    }
)
"""Email preference per type for anyone who hasn't chosen (contract-phase3 section 3.4):
what you must act on arrives now; what you follow arrives once a day."""

UNREAD_COUNT_CAP: Final = 100
"""``NotificationSummary.unread_count`` stops counting here (the bell shows "99+")."""


# --- The inbox ---------------------------------------------------------------------------
class CommentExcerpt(ResponseModel):
    """The comment a ``comment`` or ``mention`` notification is about, as it is now."""

    id: UUID
    excerpt: str = Field(
        description=(
            "Plain text (Markdown removed, mentions shown as @Name), at most 200 "
            "characters; empty when the comment was deleted."
        )
    )
    deleted: bool


class _NotificationBase(ResponseModel):
    id: UUID
    created_at: datetime
    read_at: datetime | None = Field(description="Null while unread.")
    idea: IdeaRef = Field(description="The idea it is about, with its current title and status.")
    actor: UserRef | None = Field(
        description=(
            "Who caused it; null for reminders (sent by Soundings) or if the user no longer exists."
        )
    )


class OwnerAssignedNotification(_NotificationBase):
    """Someone else made you the idea's owner (volunteering notifies nobody)."""

    type: Literal["owner_assigned"]


class EvaluatorInvitedNotification(_NotificationBase):
    """You were asked to evaluate the idea. Link: ``/ideas/{key}?evaluate=1``."""

    type: Literal["evaluator_invited"]
    due_at: datetime | None = Field(
        description=(
            "The due date set by the request that invited you (the idea page and the "
            "email show the current one)."
        )
    )


class EvaluationReminderNotification(_NotificationBase):
    """An evaluation you still owe is due soon. Show the date ("Due Fri 9 Oct"; "today"
    only while it is today), never a countdown from ``days_before``."""

    type: Literal["evaluation_reminder"]
    due_at: datetime = Field(description="The due date the reminder was sent for.")
    days_before: int = Field(
        ge=0,
        description=(
            "Which reminder this was (days before the due date, 0 = on the due date); "
            "not a countdown: phrase the reminder with due_at."
        ),
    )


class EvaluationsCompleteNotification(_NotificationBase):
    """Every evaluator of an idea you own has submitted. Never includes scores."""

    type: Literal["evaluations_complete"]
    evaluator_count: int = Field(ge=1, description="How many evaluators submitted (all).")


class StatusChangedNotification(_NotificationBase):
    """The idea moved; labels are the project's (for closed: the resolution's)."""

    type: Literal["status_changed"]
    from_status: IdeaStatus
    from_resolution: Resolution | None
    from_label: str
    to_status: IdeaStatus
    to_resolution: Resolution | None
    to_label: str


class CommentNotification(_NotificationBase):
    """A new comment on an idea you watch."""

    type: Literal["comment"]
    comment: CommentExcerpt


class MentionNotification(_NotificationBase):
    """You were @mentioned in a comment."""

    type: Literal["mention"]
    comment: CommentExcerpt


NotificationItem = Annotated[
    OwnerAssignedNotification
    | EvaluatorInvitedNotification
    | EvaluationReminderNotification
    | EvaluationsCompleteNotification
    | StatusChangedNotification
    | CommentNotification
    | MentionNotification,
    Field(discriminator="type"),
]
"""One inbox entry; branch on ``type`` (skip types you don't know)."""


class NotificationPage(Page[NotificationItem]):
    """Newest first. Only notifications about ideas you can view now."""


class NotificationSummary(ResponseModel):
    """What the app shell needs: the bell's badge and the email banners."""

    unread_count: int = Field(
        ge=0,
        le=UNREAD_COUNT_CAP,
        description=f"Unread notifications you can see, counted up to {UNREAD_COUNT_CAP}.",
    )
    email_available: bool = Field(
        description=(
            "Email is configured on this instance. False: notifications are in-app only "
            "(platform admins see a banner)."
        )
    )
    email_trouble: bool = Field(
        description=(
            "Platform admins only (always false for everyone else, and while email isn't "
            "configured): an email failed in the last 24 hours, or one has been queued "
            "for more than 15 minutes. Show admins a banner linking to Settings -> Email."
        )
    )


# --- Email preferences ---------------------------------------------------------------------
class NotificationPreference(ResponseModel):
    type: NotificationType
    mode: NotificationMode = Field(description="Your choice, or the default.")
    default_mode: NotificationMode


class NotificationPreferences(ResponseModel):
    """Your email preference for every type, in a fixed order."""

    email_available: bool = Field(
        description="Email is configured; when false, say that nothing is emailed for now."
    )
    digest_hour: int = Field(ge=0, le=23, description="When the daily digest goes out.")
    timezone: str = Field(description="IANA time zone of digest_hour, e.g. Europe/London.")
    items: list[NotificationPreference] = Field(
        description="One per type, in NotificationType order."
    )


class NotificationPreferencesUpdate(RequestModel):
    """Change some types; omitted or null types are unchanged. Choosing the default
    clears your choice (later default changes then apply to you)."""

    owner_assigned: NotificationMode | None = None
    evaluator_invited: NotificationMode | None = None
    evaluation_reminder: NotificationMode | None = None
    evaluations_complete: NotificationMode | None = None
    status_changed: NotificationMode | None = None
    comment: NotificationMode | None = None
    mention: NotificationMode | None = None


# --- Unsubscribe links ------------------------------------------------------------------
class UnsubscribeScope(StrEnum):
    """What an email's unsubscribe link turns off: its notification type, every type
    currently sent in the digest (the digest's link), or every type."""

    OWNER_ASSIGNED = "owner_assigned"
    EVALUATOR_INVITED = "evaluator_invited"
    EVALUATION_REMINDER = "evaluation_reminder"
    EVALUATIONS_COMPLETE = "evaluations_complete"
    STATUS_CHANGED = "status_changed"
    COMMENT = "comment"
    MENTION = "mention"
    DIGEST = "digest"
    ALL = "all"


class UnsubscribeInfo(ResponseModel):
    """The unsubscribe page (no sign-in). Says whose emails stop without naming them."""

    scope: UnsubscribeScope = Field(description="What the link (or all=true) turns off.")
    types: list[NotificationType] = Field(
        description=(
            "The types it turns off: the link's type; for digest, the types sent in the "
            "digest (before confirming) or just switched off (after); for all, every type."
        )
    )
    unsubscribed: bool = Field(description="Every type in types is off now.")
    email_hint: str = Field(description='The address, masked: "a•••@example.com".')
