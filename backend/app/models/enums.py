"""Domain enums shared by the ORM models and the API schemas.

Stored as ``VARCHAR`` + ``CHECK`` constraint (not native Postgres enums), so adding a
value later is a plain constraint swap in a migration. The Python values are the
wire values (snake_case).
"""

from __future__ import annotations

from enum import StrEnum


class IdeaStatus(StrEnum):
    """Fixed lifecycle (SPEC section 2). Admins may rename labels, not add stages."""

    NEW = "new"
    EVALUATING = "evaluating"
    SHORTLISTED = "shortlisted"
    PROPOSAL = "proposal"
    CLOSED = "closed"


class Resolution(StrEnum):
    """Why a closed idea was closed. Set if and only if the status is ``closed``."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARKED = "parked"


class ProjectRole(StrEnum):
    """Direct project membership role. Owner/evaluator are per-idea assignments."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectVisibility(StrEnum):
    """``private``: members only. ``internal``: any signed-in user can view."""

    PRIVATE = "private"
    INTERNAL = "internal"


class EvaluationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"


class EvaluatorState(StrEnum):
    """An assigned evaluator's progress: no evaluation yet, draft saved, or submitted."""

    INVITED = "invited"
    DRAFT = "draft"
    SUBMITTED = "submitted"


class Recommendation(StrEnum):
    GO = "go"
    MAYBE = "maybe"
    NO = "no"


class GroupSyncMode(StrEnum):
    """How sign-in sync treats a group's IdP-mapped memberships (contract-phase2 §3.6).

    ``managed``: synced memberships are exactly the groups the IdP claim matches (sync
    adds and removes). ``additive``: sync only adds. Manual memberships are never
    touched by sync in either mode.
    """

    MANAGED = "managed"
    ADDITIVE = "additive"


class AuthMethod(StrEnum):
    """How a session was started (``user_sessions.auth_method``)."""

    DEV_LOGIN = "dev_login"
    SSO = "sso"
    BREAK_GLASS = "break_glass"


class NotificationType(StrEnum):
    """What a notification is about (contract-phase3 section 3.3). Each type has its own
    email preference; the in-app inbox always gets every notification."""

    OWNER_ASSIGNED = "owner_assigned"
    """Someone else made you the owner of an idea."""
    EVALUATOR_INVITED = "evaluator_invited"
    """You were asked to evaluate an idea (with the due date and the evaluate link)."""
    EVALUATION_REMINDER = "evaluation_reminder"
    """An evaluation you owe is due soon or today."""
    EVALUATIONS_COMPLETE = "evaluations_complete"
    """Every assigned evaluator of an idea you own has submitted."""
    STATUS_CHANGED = "status_changed"
    """An idea you own, evaluate or watch changed status."""
    COMMENT = "comment"
    """A new comment on an idea you watch."""
    MENTION = "mention"
    """Someone @mentioned you in a comment."""


class NotificationMode(StrEnum):
    """How a notification type reaches you by email (per user and type)."""

    IMMEDIATE = "immediate"
    """One email per notification, as it happens."""
    DIGEST = "digest"
    """Collected into one daily digest email."""
    OFF = "off"
    """No email (the in-app inbox still shows it)."""


class EmailType(StrEnum):
    """What an outbox email is (``outbound_email.type``)."""

    OWNER_ASSIGNED = "owner_assigned"
    EVALUATOR_INVITED = "evaluator_invited"
    EVALUATION_REMINDER = "evaluation_reminder"
    EVALUATIONS_COMPLETE = "evaluations_complete"
    STATUS_CHANGED = "status_changed"
    COMMENT = "comment"
    MENTION = "mention"
    DIGEST = "digest"
    """The daily digest: every pending digest notification of one person."""
    TEST = "test"
    """Admin settings -> Email -> Send test email."""
    SUBMISSION_RECEIVED = "submission_received"
    """Phase 4: confirmation with the tracking link to a public submitter."""
    SUBMISSION_STATUS_CHANGED = "submission_status_changed"
    """Phase 4: status update to a public submitter who opted in."""


class EmailStatus(StrEnum):
    """Where an outbox email is in its life (contract-phase3 section 3.9)."""

    QUEUED = "queued"
    """Waiting for its next attempt (``next_attempt_at``)."""
    SENDING = "sending"
    """Claimed by a worker; ``next_attempt_at`` is the claim's expiry."""
    SENT = "sent"
    """The SMTP server accepted it."""
    FAILED = "failed"
    """A permanent error, out of attempts, or an internal error: an admin may retry it
    while it is recent enough to send."""
    CANCELLED = "cancelled"
    """Not sent and never will be: at send time it no longer applied (no access, not an
    evaluator any more, nothing left in a digest), was out of date, the recipient had
    turned the type off, or the address was unusable."""
