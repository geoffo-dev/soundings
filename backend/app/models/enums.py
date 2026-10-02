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


# --- Phase 4: proposals, public submission, branding (contract-phase4) ------------------
class ProposalSectionKey(StrEnum):
    """The fixed proposal template (SPEC section 2), in document order. Titles and
    prompts are in ``app.schemas.proposals.PROPOSAL_TEMPLATE``."""

    SUMMARY = "summary"
    PROBLEM = "problem"
    SOLUTION = "solution"
    MARKET = "market"
    """Market & users."""
    COST = "cost"
    """Cost & effort."""
    BENEFITS = "benefits"
    """Benefits / revenue."""
    RISKS = "risks"
    NEXT_STEPS = "next_steps"
    """Next steps / the ask."""


class HoldReason(StrEnum):
    """Why a public submission is not visible yet (``ideas.held_for``; null = visible).

    Held ideas are in no list, board, search, count, My work or notification for anyone
    (contract-phase4 section 3.6)."""

    EMAIL_VERIFICATION = "email_verification"
    """The project requires a confirmed address and the submitter hasn't confirmed it
    yet. Invisible to everyone, admins included; deleted after 3 days."""
    MODERATION = "moderation"
    """Waiting for a project admin to approve it (c12): only project and platform
    admins can see it, in the moderation queue and on its own page."""


class BrandFont(StrEnum):
    """Bundled fonts (open licences) a branding profile may choose. Nothing is fetched:
    the SPA bundles them (@fontsource) and the image ships the files for PDFs."""

    INTER = "inter"
    """Inter: neutral sans-serif (the default)."""
    IBM_PLEX_SANS = "ibm_plex_sans"
    """IBM Plex Sans: technical, corporate sans-serif."""
    SOURCE_SERIF_4 = "source_serif_4"
    """Source Serif 4: editorial serif."""
    ATKINSON_HYPERLEGIBLE = "atkinson_hyperlegible"
    """Atkinson Hyperlegible: designed for low-vision readability."""


class BrandAssetKind(StrEnum):
    """What an uploaded branding image is for."""

    LOGO = "logo"
    FAVICON = "favicon"


# --- Phase 5: API keys and MCP (contract-phase5) ---------------------------------------
class ApiKeyScope(StrEnum):
    """What an API key may be used for (role matrix section 5). A key acts as its owner,
    live, narrowed to the rules its scopes grant; ``mcp`` only opens ``/mcp``, where each
    tool also needs the scope of its own rule. Same values as
    :data:`app.domain.principal.ApiKeyScope`, in this canonical order."""

    READ = "read"
    WRITE = "write"
    EVALUATE = "evaluate"
    MCP = "mcp"


class SuggestionStatus(StrEnum):
    """Where a proposal suggestion is (``proposal_suggestions.status``)."""

    PENDING = "pending"
    """Waiting for the owner (or an admin) to accept or discard it."""
    ACCEPTED = "accepted"
    """Its text became the section's text (a normal, versioned section save)."""
    DISCARDED = "discarded"
    """Dismissed by the owner or an admin, or replaced by a newer suggestion from the same
    author for the same section (then ``decided_by`` is the author)."""


class SuggestionSource(StrEnum):
    """Who or what wrote a proposal suggestion (``proposal_suggestions.source``). It
    follows the **author**: ``ai`` for a service account whatever the channel, else the
    channel a person used."""

    API = "api"
    """A person through REST (``create_proposal_suggestion``): the SPA or an API client."""
    MCP = "mcp"
    """A person through the MCP tool ``propose_proposal_section`` (their key)."""
    AI = "ai"
    """An AI agent's service account, through MCP or REST (shown with an AI badge;
    Phase 6's "Draft section" arrives this way)."""
