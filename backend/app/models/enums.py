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
