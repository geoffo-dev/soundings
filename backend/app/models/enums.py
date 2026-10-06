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


# --- Phase 6: kagent AI assistance (contract-phase6) -------------------------------------
class AiRunKind(StrEnum):
    """What an AI run does (``ai_runs.kind``), and the purposes a registered agent serves
    (``ai_agents.purposes``). SPEC section 9's two jobs: the evaluator, and the research
    and drafting assistant."""

    EVALUATE = "evaluate"
    """"Ask AI to evaluate": the agent becomes an evaluator of the idea and submits a
    cited evaluation through MCP ``submit_evaluation`` (left out of the aggregate by
    default)."""
    RESEARCH = "research"
    """"Research this": the agent writes a cited research note into the idea's activity
    feed through MCP ``add_research_note``."""
    DRAFT_SECTION = "draft_section"
    """"Draft section": the agent suggests the text of one proposal section through MCP
    ``propose_proposal_section`` (a Phase 5 suggestion the owner accepts or discards)."""


class AiRunStatus(StrEnum):
    """Where an AI run is (``ai_runs.status``). ``queued`` and ``running`` are active; the
    other four are final (``finished_at`` set)."""

    QUEUED = "queued"
    """Waiting for the worker (at most ``SOUNDINGS_AI_MAX_CONCURRENT_RUNS`` run at once)."""
    RUNNING = "running"
    """The worker is talking to the agent over A2A."""
    SUCCEEDED = "succeeded"
    """The agent's task ended and its result (evaluation, note or suggestion) was recorded."""
    FAILED = "failed"
    """It ended without a result: see ``error_code``."""
    CANCELLED = "cancelled"
    """Someone cancelled it (``ai.cancel_run``), or the agent's task was cancelled."""
    TIMED_OUT = "timed_out"
    """It hit its deadline (``timeout_seconds`` after it started) or waited too long in the
    queue; the worker asked the agent to cancel."""


class AiAgentProtocol(StrEnum):
    """How Soundings talks to a registered agent: which kagent A2A endpoint layout and A2A
    protocol version (docs/research/kagent-a2a-claude-code-frontend.md section 1). The URL
    is always built from ``SOUNDINGS_KAGENT_URL`` + this layout + the agent's namespace
    and name, never taken from the API or the agent card."""

    KAGENT_V0_10 = "kagent_v0_10"
    """kagent 0.10.x: ``POST {kagent_url}/api/a2a/{namespace}/{name}/`` with A2A 0.3
    JSON-RPC methods (``message/stream``, ``tasks/get``, ``tasks/cancel``) and
    ``A2A-Version: 0.3``."""
    KAGENT_V1_0 = "kagent_v1_0"
    """kagent 1.0 (pre-release when written): ``POST {kagent_url}/agents/{namespace}/{name}``
    with A2A 1.0 methods (``SendStreamingMessage``, ``GetTask``, ``CancelTask``) and the
    required ``A2A-Version: 1.0`` header."""


class AiRunEventType(StrEnum):
    """One step of a run's progress (``ai_run_events.type``), streamed over SSE. Events
    carry Soundings' own fixed messages (and tool names), never the agent's text or any
    score data, so anyone who can view the idea may watch (role matrix section J)."""

    QUEUED = "queued"
    STARTED = "started"
    """The worker picked it up and is sending it to the agent."""
    RETRYING = "retrying"
    """The agent couldn't be reached before a task existed; trying again shortly."""
    AGENT_ACCEPTED = "agent_accepted"
    """The agent created its A2A task (state submitted)."""
    AGENT_WORKING = "agent_working"
    """The agent's task is working (written once per transition, not per update)."""
    TOOL_CALLED = "tool_called"
    """The agent called a Soundings MCP tool for this run (the tool's name only)."""
    RESULT_RECORDED = "result_recorded"
    """The evaluation, research note or suggestion was saved and attached to the run."""
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class AiRunError(StrEnum):
    """Why a run failed or timed out (``ai_runs.error_code``). The message shown with it is
    Soundings' own sentence for the code, never the agent's text."""

    AI_DISABLED = "ai_disabled"
    """AI assistance was turned off for the instance before the run started."""
    AGENT_UNAVAILABLE = "agent_unavailable"
    """At start the agent was no longer suitable (disabled, removed from the project, no
    usable key, purpose removed): c10 checked again."""
    AGENT_UNREACHABLE = "agent_unreachable"
    """No connection to kagent, or it answered 5xx / 404, after the retries."""
    AGENT_PROTOCOL_ERROR = "agent_protocol_error"
    """kagent answered something that isn't the A2A protocol we speak (bad JSON-RPC, a
    redirect, an oversized or malformed response, an unknown task state)."""
    AGENT_REJECTED = "agent_rejected"
    """The agent's task ended rejected."""
    AGENT_FAILED = "agent_failed"
    """The agent's task ended failed (or cancelled by someone else) without a result."""
    AGENT_NEEDS_INPUT = "agent_needs_input"
    """The agent asked for input or authorisation (input-required / auth-required), which
    a run can't give: the task was cancelled."""
    NO_RESULT = "no_result"
    """The agent's task completed but it never recorded its result through MCP."""
    TIMED_OUT = "timed_out"
    """The run reached its deadline (status ``timed_out``)."""
    QUEUE_TIMEOUT = "queue_timeout"
    """It waited in the queue for 30 minutes without starting (status ``timed_out``)."""
    WORKER_LOST = "worker_lost"
    """The worker running it stopped (no heartbeat for 2 minutes)."""
    INTERNAL_ERROR = "internal_error"
    """Anything unexpected (logged with the traceback)."""
