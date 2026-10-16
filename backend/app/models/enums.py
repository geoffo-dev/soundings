"""Domain enums shared by the ORM models and the API schemas.

Stored as ``VARCHAR`` + ``CHECK`` constraint (not native Postgres enums), so adding a
value later is a plain constraint swap in a migration. The Python values are the
wire values (snake_case).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class IdeaStatus(StrEnum):
    """The lifecycle (SPEC section 2), in the **canonical order** used across projects (My
    work's groups, search, MCP). Admins may rename labels, not add stages.

    Phase 8 (product owner, 2026-10-07): ``research`` exists only in projects whose
    research step is on (``projects.research_step``), at the step's position: New ->
    Research -> Evaluating -> ... (``before_evaluation``) or ... -> Shortlisted ->
    Research -> Proposal -> Closed (``before_proposal``). A project's own order is
    :func:`app.schemas.research.lifecycle`; the canonical order puts Research after New.
    """

    NEW = "new"
    RESEARCH = "research"
    """Phase 8: checking the idea isn't being done elsewhere and the right teams were
    consulted (the project's research checklist). Only while the project's step is on."""
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
    RESEARCHER_ASSIGNED = "researcher_assigned"
    """Phase 8b: someone else asked you to do an idea's research ("Asked to research",
    with the research due date and a link to the idea's Research panel)."""
    RESEARCH_REMINDER = "research_reminder"
    """Phase 8b: research you do (as the idea's researcher, or as its owner when nobody is
    assigned) is due soon or today and a required checklist item is still open."""
    ASSESSOR_ASSIGNED = "assessor_assigned"
    """Phase 10, "Asked to assess bids": someone else made you an assessor of one or more
    sections of an idea's call for bids (the call, your sections, the due date)."""
    ASSESSMENT_REMINDER = "assessment_reminder"
    """Phase 10: bid assessments you owe (a section you assess, for a bid that isn't
    rejected) are due soon or today, while the call is being assessed."""
    ASSESSMENTS_COMPLETE = "assessments_complete"
    """Phase 10: every assigned assessor has submitted every section they assess for every
    bid that isn't rejected (to the idea's owner and the call's creator). Never scores."""
    SUBMITTER_REPLIED = "submitter_replied"
    """Phase 11, "The submitter replied": the person who sent the idea through the public
    form replied on their tracking page (to the idea's owner and everyone who has written to
    them, while they hold ``public.message_submitter``). Never the reply's text (untrusted
    public input)."""


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
    RESEARCHER_ASSIGNED = "researcher_assigned"
    """Phase 8b: "Asked to research"."""
    RESEARCH_REMINDER = "research_reminder"
    """Phase 8b: research due soon or today."""
    ASSESSOR_ASSIGNED = "assessor_assigned"
    """Phase 10: "Asked to assess bids"."""
    ASSESSMENT_REMINDER = "assessment_reminder"
    """Phase 10: bid assessments due soon or today."""
    ASSESSMENTS_COMPLETE = "assessments_complete"
    """Phase 10: every bid assessment of a call is in."""
    SUBMITTER_REPLIED = "submitter_replied"
    """Phase 11: "The submitter replied" (to the team; never the reply's text)."""
    DIGEST = "digest"
    """The daily digest: every pending digest notification of one person."""
    TEST = "test"
    """Admin settings -> Email -> Send test email."""
    SUBMISSION_RECEIVED = "submission_received"
    """Phase 4: confirmation with the tracking link to a public submitter."""
    SUBMISSION_STATUS_CHANGED = "submission_status_changed"
    """Phase 4: status update to a public submitter who opted in."""
    SUBMISSION_LINK = "submission_link"
    """Phase 11: the private tracking link, once, to a public submitter's address when it is
    confirmed for the first time (the confirmation email itself never carries it)."""
    SUBMISSION_MESSAGE = "submission_message"
    """Phase 11: a message from the team to a public submitter with a confirmed address."""


SUBMITTER_EMAIL_TYPES: Final = (
    EmailType.SUBMISSION_RECEIVED,
    EmailType.SUBMISSION_STATUS_CHANGED,
    EmailType.SUBMISSION_LINK,
    EmailType.SUBMISSION_MESSAGE,
)
"""Phase 11: the emails to a public submitter, the one list used everywhere (the outbox's
``ck_outbound_email_idea_iff_submission_type``, erasure, retention rule 3, branding, the
send-time renderer, Admin -> Email). Each names its idea (``outbound_email.idea_id``) and goes
to an address (``to_address``), never to a user; erasure deletes every one of them."""


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
    """The keys of the **built-in default** proposal template (SPEC section 2), in
    document order; titles and hints in ``app.schemas.proposals.DEFAULT_PROPOSAL_TEMPLATE``.

    Phase 8: templates are per project (``proposal_template_sections``). Every project
    starts with these eight and they keep these keys, but they are no longer the set of
    valid keys: a project's sections are its template rows, and a section added later
    gets a key of its own (``app.schemas.proposals.SECTION_KEY_PATTERN``). Use this enum
    only to name the defaults."""

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


class ResearchStep(StrEnum):
    """Phase 8: whether a project has a research step, and where (``projects.research_step``,
    project settings -> Research). Off for every project until a project admin turns it
    on; while on, the lifecycle gains the Research status at this position and the
    research checklist gates the statuses after it (contract-phase8 section 3)."""

    OFF = "off"
    """No Research status, column or checklist anywhere in the project (the default)."""
    BEFORE_EVALUATION = "before_evaluation"
    """New -> Research -> Evaluating -> Shortlisted -> Proposal -> Closed."""
    BEFORE_PROPOSAL = "before_proposal"
    """New -> Evaluating -> Shortlisted -> Research -> Proposal -> Closed."""


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


class MessageDirection(StrEnum):
    """Phase 11: who wrote a message in the conversation with a public submitter
    (``submission_messages.direction``; contract-phase11 section 3)."""

    TEAM = "team"
    """A person of the team (``author_id``, holding ``public.message_submitter``) wrote it."""
    SUBMITTER = "submitter"
    """The submitter replied on their tracking page (no author: public input, untrusted)."""


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
    """"Ask AI to research" (Phase 6's "Research this"): the agent writes a cited research
    note into the idea's activity feed through MCP ``add_research_note``."""
    DRAFT_SECTION = "draft_section"
    """"Draft section": the agent suggests the text of one proposal section through MCP
    ``propose_proposal_section`` (a Phase 5 suggestion the owner accepts or discards)."""
    ASSESS_BID = "assess_bid"
    """Phase 10, "Ask AI to assess": the AI assessor reads one bid of the idea's call for
    bids (the call's questions and must-haves, the bid's documents' extracted text) and
    records a score with evidence for every score question and a finding for every
    must-have through MCP ``submit_bid_assessment``. Its scores are left out of the totals
    until a call manager includes them; its findings are only suggestions. One run per
    bid (``ai_runs.bid_id``). Also the purpose an agent needs for it."""


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


# --- Phase 10: bid evaluation (contract-phase10) ------------------------------------------
class BidCallStatus(StrEnum):
    """Where an idea's call for bids is (``bid_calls.status``; contract-phase10 section 3).
    ``awarded`` and ``cancelled`` are final: the call is read-only."""

    DRAFT = "draft"
    """Being set up: its evaluation template, deadline and assessors; no bids yet."""
    OPEN = "open"
    """Bids are entered (one after the deadline is marked late, not refused)."""
    ASSESSING = "assessing"
    """No new bids; the section assessors (and the AI assessor) score the bids. Back to open
    only while no assessment is submitted."""
    AWARDED = "awarded"
    """One qualified bid was awarded; every other bid that isn't rejected is unsuccessful."""
    CANCELLED = "cancelled"
    """Stopped without an award (a reason is optional)."""


class BidStatus(StrEnum):
    """Where one bid is (``bids.status``), kept by the service from the bid's must-have
    results, its rejection and the award."""

    RECEIVED = "received"
    """Entered, and a must-have is missing, unchecked or not met (not qualified yet)."""
    QUALIFIED = "qualified"
    """Every must-have of the call is met."""
    REJECTED = "rejected"
    """A call manager rejected it with a reason (one click; "Reinstate" undoes it until the
    award). Out of assessors' queues, the totals, the price formula and the ranking."""
    AWARDED = "awarded"
    UNSUCCESSFUL = "unsuccessful"
    """Not awarded when another bid was (rejected bids stay rejected)."""


class BidQuestionType(StrEnum):
    """What a question of a bid evaluation template asks for."""

    SCORE = "score"
    """Each assessor of its section scores it 0-5 against the template's scale anchors."""
    PRICE = "price"
    """At most one per call: the team enters each bid's price; scored automatically as
    lowest qualified price / this bid's price x 5. Assessors don't score it."""
    COMMENT = "comment"
    """Free text from each assessor of its section; not scored (weight 0)."""


class MustHaveKind(StrEnum):
    """What a must-have of a call is (``bid_call_must_haves.kind``)."""

    DOCUMENT = "document"
    """A required document: missing (flagged automatically) until a file is linked to it."""
    CONFIRMATION = "confirmation"
    """A statement a person confirms (e.g. "Accepts our standard terms"); the AI assessor
    pre-checks it."""


class MustHaveResult(StrEnum):
    """A bid's result for one must-have (``bid_must_have_results.result``)."""

    MISSING = "missing"
    """A required document with no file linked to it (automatic)."""
    UNCHECKED = "unchecked"
    """A confirmation nobody has decided yet."""
    MET = "met"
    """Confirmed by a person, or (a document) a file is linked and nobody decided otherwise."""
    NOT_MET = "not_met"
    """A person decided it isn't met (with an optional note)."""


class AiMustHaveFinding(StrEnum):
    """The AI assessor's pre-check of one must-have: only a suggestion, stored apart from
    the result, which it never changes."""

    MET = "met"
    NOT_MET = "not_met"
    UNCLEAR = "unclear"


class BidDocumentType(StrEnum):
    """What an uploaded bid document **is**, decided from its bytes (magic numbers and,
    for ZIP-based formats, the archive's entry names and content types), never from the
    request's ``Content-Type`` (contract-phase10 section 6.1). Anything else is refused (415).
    The name only labels plain text: ``csv`` when it ends in ``.csv``, else ``txt``."""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    ODT = "odt"
    ODS = "ods"
    TXT = "txt"
    CSV = "csv"
    PNG = "png"
    JPEG = "jpeg"


class ExtractionState(StrEnum):
    """Where a bid document's text extraction is (``bid_documents.extraction_state``).
    Extraction runs in the worker, in a child process with time, memory and output caps."""

    PENDING = "pending"
    """Queued (the worker extracts it shortly after the upload)."""
    DONE = "done"
    """Text extracted (``text_truncated`` when it hit the 2,000,000-character cap)."""
    NO_TEXT = "no_text"
    """Nothing to extract: an image (no OCR), or a document without text."""
    FAILED = "failed"
    """It couldn't be read in time or within the limits (``extraction_error``)."""


class ExtractionError(StrEnum):
    """Why a bid document's text extraction failed (``bid_documents.extraction_error``);
    the SPA words each one, never the parser's own message."""

    TIMEOUT = "timeout"
    """The child process didn't finish in 30 seconds and was killed."""
    MEMORY = "memory"
    """The child process hit its memory cap."""
    DAMAGED = "damaged"
    """The file couldn't be parsed (truncated, corrupt, not what its bytes first said)."""
    ENCRYPTED = "encrypted"
    """Password-protected or encrypted: Soundings has no password to open it with."""
    ARCHIVE_LIMITS = "archive_limits"
    """An Office or OpenDocument file whose archive is over the caps (total uncompressed
    size, one entry's size or compression ratio, number of entries): a zip bomb, or simply
    too big to read."""
    INTERNAL_ERROR = "internal_error"
    """Anything unexpected (logged with the document id, never its text)."""
