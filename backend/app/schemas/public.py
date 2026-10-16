"""Public submission: the public form, ALTCHA, tracking links, email confirmation,
moderation and erasing a submitter's details (SPEC section 10; contract-phase4
sections 3.4-3.9).

Public endpoints (``/api/v1/public/...``) need no session and never return anything
private: no people, comments, evaluations, scores or other submitters' details.
Secrets never travel in URLs the server sees: tracking and confirmation links carry
their token after ``#`` (the SPA posts it in a request body), so no access log, proxy
log or trace can record one.

Phase 11 (contract-phase11, ADR 0019): the team talks to the submitter through Soundings
(``public.message_submitter``: the idea's owner and project and platform admins, sessions
only), signed "The <project> team"; the submitter reads and answers on the tracking page
once the team has written, and gets the tracking link by email once their address is
confirmed. Messages are plain text, never rendered as Markdown or HTML; a submitter's text
is untrusted public input everywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.enums import HoldReason, IdeaStatus, MessageDirection, Resolution
from app.models.public import SUBMISSION_MESSAGE_MAX_LENGTH
from app.schemas.base import RequestModel, ResponseModel, SingleLine, VisibleText
from app.schemas.branding import EffectiveBranding
from app.schemas.common import Page
from app.schemas.email import MailAddress
from app.schemas.ideas import IdeaRef
from app.schemas.users import UserRef

__all__ = [
    "ALTCHA_PAYLOAD_MAX_LENGTH",
    "CONVERSATION_MAX_MESSAGES",
    "INTRO_MAX_LENGTH",
    "MESSAGE_DAY",
    "MESSAGE_HOUR",
    "PUBLIC_DESCRIPTION_MAX_LENGTH",
    "SUBMISSION_MESSAGE_MAX_LENGTH",
    "SUBMITTER_MESSAGES_PER_ADDRESS_PER_HOUR",
    "SUBMITTER_MESSAGES_PER_SUBMISSION_PER_DAY",
    "TEAM_MESSAGES_PER_PERSON_PER_HOUR",
    "TEAM_MESSAGES_PER_SUBMISSION_PER_DAY",
    "TRACKED_MESSAGES_SHOWN",
    "TRACKING_TOKEN_PATTERN",
    "VERIFICATION_TOKEN_PATTERN",
    "AltchaChallenge",
    "AltchaParameters",
    "EmailVerified",
    "HoldReason",
    "IdeaSubmission",
    "IdeaSubmissionPermissions",
    "MessageBody",
    "MessageDelivery",
    "MessageDirection",
    "ModerationItem",
    "ModerationPage",
    "PublicFormSettings",
    "PublicFormSettingsUpdate",
    "PublicProject",
    "PublicProjectRef",
    "PublicSubmissionCreate",
    "PublicSubmissionReceipt",
    "ReplyBlocked",
    "SendBlocked",
    "SubmissionMessage",
    "SubmissionMessageCreate",
    "SubmissionMessagePage",
    "SubmissionMessagesSummary",
    "SubmitterContact",
    "TrackedMessage",
    "TrackedStatusChange",
    "TrackedSubmission",
    "TrackingReplyRequest",
    "TrackingRequest",
    "TrackingToken",
    "TrackingUpdatesRequest",
    "VerificationRequest",
    "VerificationToken",
    "normalise_line_breaks",
]

INTRO_MAX_LENGTH: Final = 2_000
PUBLIC_DESCRIPTION_MAX_LENGTH: Final = 10_000
ALTCHA_PAYLOAD_MAX_LENGTH: Final = 4_096

TRACKING_TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"  # noqa: S105 - a pattern, not a secret
"""A tracking token: 32 random bytes, base64url without padding (43 characters)."""

VERIFICATION_TOKEN_PATTERN = r"^[A-Za-z0-9_.-]{16,512}$"  # noqa: S105 - a pattern
"""A confirmation-link token: signed (HMAC), ``base64url(payload).base64url(mac)``."""

TrackingToken = Annotated[str, StringConstraints(pattern=TRACKING_TOKEN_PATTERN)]
VerificationToken = Annotated[str, StringConstraints(pattern=VERIFICATION_TOKEN_PATTERN)]

# --- Phase 11: messages with the submitter (contract-phase11 section 5; constants) ------------
CONVERSATION_MAX_MESSAGES: Final = 200
"""Messages in one conversation, both directions; then 409 ``conversation_full``."""
TRACKED_MESSAGES_SHOWN: Final = 100
"""The latest messages the tracking page shows (oldest first)."""
MESSAGE_DAY: Final = timedelta(hours=24)
MESSAGE_HOUR: Final = timedelta(hours=1)
TEAM_MESSAGES_PER_SUBMISSION_PER_DAY: Final = 20
"""Team messages to one submission in any 24 hours, counted in the database (429)."""
TEAM_MESSAGES_PER_PERSON_PER_HOUR: Final = 30
"""Messages one person sends to public submitters in any hour, all ideas (429)."""
SUBMITTER_MESSAGES_PER_SUBMISSION_PER_DAY: Final = 10
"""Replies to one submission's conversation in any 24 hours, counted in the database (429)."""
SUBMITTER_MESSAGES_PER_ADDRESS_PER_HOUR: Final = 30
"""Replies from one client address (the trusted-proxy address, IPv6 per /64) in any hour, an
in-process throttle like the other public ones (no address is stored)."""


def normalise_line_breaks(value: str) -> str:
    r"""``\r\n`` and a lone ``\r`` become ``\n``: one kind of line break is stored."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


MessageBody = Annotated[
    str,
    Field(min_length=1, max_length=SUBMISSION_MESSAGE_MAX_LENGTH),
    VisibleText,
    AfterValidator(normalise_line_breaks),
]
"""A message between the team and a public submitter: **plain text** (never Markdown or
HTML), 1-4,000 characters with at least one visible one; NUL and Unicode tag characters are
a 422, other invisible characters are removed, the ends trimmed and line breaks kept (as
``\n``). Shown with its line breaks as plain text everywhere; escaped in emails."""


# --- The public form -----------------------------------------------------------------
class PublicProjectRef(ResponseModel):
    """The project as the public sees it: its name, nothing else."""

    slug: str
    name: str


class PublicProject(PublicProjectRef):
    """What the public form at ``/{slug}/submit`` shows and asks for."""

    intro_md: str = Field(description="Markdown above the form (render without raw HTML).")
    asks_for_email: bool = Field(
        description=(
            "Email is set up for this instance: show the optional email field and the "
            '"Email me when the status changes" box. False: ask for neither.'
        )
    )
    email_required: bool = Field(
        description=(
            "The project requires a confirmed address: the email field is required, and "
            "the idea waits until the submitter opens the link we email them."
        )
    )
    moderated: bool = Field(
        description="New ideas wait for the team's review before anyone else sees them."
    )
    branding: EffectiveBranding = Field(description="The project's effective branding.")


class AltchaParameters(ResponseModel):
    """ALTCHA v2 challenge parameters, in the widget's own (camelCase) format. The
    signature covers all of them, ``data`` included."""

    model_config = ConfigDict(
        serialize_by_alias=True, validate_by_alias=True, validate_by_name=True
    )

    algorithm: str = Field(description='"PBKDF2/SHA-256".')
    cost: int
    key_length: int = Field(alias="keyLength")
    key_prefix: str = Field(alias="keyPrefix")
    nonce: str
    salt: str
    expires_at: int = Field(alias="expiresAt", description="Unix time (seconds).")
    data: dict[str, str] = Field(
        description=(
            '{"project": "<slug>"}: binds the challenge to this form (a solution for '
            "another project's form is refused). Pass it back unchanged."
        )
    )


class AltchaChallenge(ResponseModel):
    """A proof-of-work challenge for the ALTCHA widget (Python ``altcha`` 2.x with the
    ``altcha@3`` widget, research R1 section 7). Pass the endpoint's URL (or this JSON)
    to the widget unchanged; it solves it in the browser and puts the result in the
    form's ``altcha`` field. The one place the API isn't snake_case: the format is the
    widget's."""

    parameters: AltchaParameters
    signature: str = Field(description="HMAC of the parameters (they can't be changed).")


def _blank_is_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class PublicSubmissionCreate(RequestModel):
    """The public form. Only ``title`` and ``summary`` are required. Send it as
    ``Content-Type: application/json`` (anything else is 415)."""

    title: Annotated[str, Field(min_length=1, max_length=200), SingleLine]
    summary: str = Field(min_length=1, max_length=500, description="One or two sentences.")
    description_md: str = Field(
        default="", max_length=PUBLIC_DESCRIPTION_MAX_LENGTH, description="Markdown, optional."
    )
    name: Annotated[str, Field(min_length=1, max_length=80), SingleLine] | None = Field(
        default=None, description="Optional; a blank value means none."
    )
    email: MailAddress | None = Field(
        default=None,
        description=(
            "Optional (required when PublicProject.email_required). One plain address. "
            "When PublicProject.asks_for_email is false it is ignored and not stored, and "
            "so is wants_updates."
        ),
    )
    wants_updates: bool = Field(
        default=False, description="Email me when the status changes (needs email)."
    )
    altcha: str = Field(
        min_length=1,
        max_length=ALTCHA_PAYLOAD_MAX_LENGTH,
        pattern=r"^[A-Za-z0-9+/=_-]+$",
        description="The ALTCHA widget's payload (base64).",
    )
    website: str = Field(default="", description="Leave empty.")
    # The honeypot (contract-phase4 section 3.5): any value, of any length, makes the
    # server answer exactly as for a real submission without keeping anything. Its
    # description stays neutral on purpose (the OpenAPI document is public).

    @field_validator("name", "email", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_is_none(value)

    @model_validator(mode="after")
    def _updates_need_an_address(self) -> PublicSubmissionCreate:
        if self.wants_updates and self.email is None:
            raise ValueError("wants_updates needs an email address")
        return self


class PublicSubmissionReceipt(ResponseModel):
    """The confirmation page. The tracking link is shown once here (and, Phase 11, emailed
    once the address is confirmed): only its hash and a sealed copy are kept."""

    tracking_token: str = Field(description="43 characters; keep it private.")
    tracking_url: str = Field(
        description="<base URL>/track#<token>: the private link to show and copy."
    )
    held_for: HoldReason | None = Field(
        description=(
            "email_verification: ask them to open the link we emailed; moderation: the "
            "team reviews new ideas first; null: the team can see it now."
        )
    )
    email_sent: bool = Field(
        description=(
            "An address was given and email is set up: we emailed them a link to confirm "
            "it, and (Phase 11) once they confirm we email them this tracking link, so say "
            '"Once you confirm your address, we\'ll email you this link too." The '
            "confirmation email itself never carries the tracking link. True even when the "
            "per-address limit held the confirmation email back (the limit is silent, so "
            "this can't reveal how often an address was used)."
        )
    )


# --- Tracking and confirmation links -------------------------------------------------
class TrackingRequest(RequestModel):
    """The tracking page posts the token from its URL's fragment (``/track#<token>``)."""

    token: TrackingToken


class TrackingUpdatesRequest(RequestModel):
    token: TrackingToken
    wants_updates: bool = Field(description="Email me when the status changes.")


class TrackingReplyRequest(RequestModel):
    """Phase 11: the submitter's reply to the team, from their tracking page (the token from
    its URL's fragment, as for every tracking write)."""

    token: TrackingToken
    body: MessageBody


class VerificationRequest(RequestModel):
    """The confirmation page posts the token from its URL's fragment (``/verify#<token>``)."""

    token: VerificationToken


class TrackedStatusChange(ResponseModel):
    """A change of the status the submitter sees. Phase 8: never ``research``: an idea in
    Research is reported as the status before Research in its project's lifecycle (``new``
    before evaluation, ``shortlisted`` before the proposal;
    ``app.schemas.research.public_status``), so a move that doesn't change the reported
    status or resolution (New -> Research, Shortlisted -> Research and back) is left out."""

    status: IdeaStatus = Field(
        description=(
            "Never research (Phase 8: reported as the status before it, new or shortlisted)."
        )
    )
    resolution: Resolution | None
    status_label: str = Field(description="The project's label (closed: the resolution's).")
    at: datetime


class ReplyBlocked(StrEnum):
    """Phase 11: why the submitter can't reply on their tracking page now."""

    AWAITING_TEAM = "awaiting_team"
    """The team hasn't written yet: the public never starts a conversation (no reply box;
    the Messages section isn't shown)."""
    CONVERSATION_FULL = "conversation_full"
    """200 messages in the conversation: "This conversation is full." (reading stays)."""
    PROJECT_ARCHIVED = "project_archived"
    """The project is archived: "The team isn't taking messages about this idea any more."
    (reading stays)."""
    DAILY_LIMIT = "daily_limit"
    """10 replies in the last 24 hours: "You can reply again tomorrow." (sending anyway is 429
    ``too_many_attempts``)."""


class TrackedMessage(ResponseModel):
    """Phase 11: a message on the tracking page. The team's are shown as "The <project
    name> team" (never a person: public pages show no people), the submitter's as "You";
    plain text with its line breaks (never Markdown or HTML)."""

    id: UUID
    direction: MessageDirection = Field(
        description='team: show "The <project> team"; submitter: show "You".'
    )
    body: str = Field(description="Plain text; render with line breaks, never as Markdown.")
    created_at: datetime


class TrackedSubmission(ResponseModel):
    """The private tracking page: what the submitter sent and its status, nothing
    else (no people, comments, evaluations, scores, or anything the team wrote: the
    title and summary are the submitter's own, as sent, even if the team edited the
    idea since). Phase 11: plus the conversation with the team (the one thing the team
    writes that the submitter sees, signed "The <project> team")."""

    project: PublicProjectRef
    title: str = Field(description="As submitted.")
    summary: str = Field(description="As submitted.")
    submitted_at: datetime
    reached_team_at: datetime | None = Field(
        description=(
            'When it reached the team (the "With the team" step): at submission when '
            "nothing held it, else when the confirmation or the approval released it. "
            "Null while held. Added after the contract (2026-10-02)."
        )
    )
    held_for: HoldReason | None = Field(
        description=(
            'email_verification: "Confirm your address to send it"; moderation: '
            '"Waiting for review"; null: with the team.'
        )
    )
    status: IdeaStatus = Field(
        description=(
            "Never research: Phase 8 reports an idea in Research as the status before it in "
            "the project's lifecycle (new before evaluation, shortlisted before the "
            "proposal), with that status's label."
        )
    )
    resolution: Resolution | None
    status_label: str
    history: list[TrackedStatusChange] = Field(
        description=(
            "Changes of the status shown here since it reached the team, oldest first "
            "(Research counts as the status before it; moves that change nothing shown "
            "are left out)."
        )
    )
    email_hint: str | None = Field(
        description='The address on file, masked ("j•••@example.org"); null if none.'
    )
    email_verified: bool
    wants_updates: bool
    can_resend_verification: bool = Field(
        description=(
            "An unconfirmed address is on file and another confirmation email may be "
            "sent now (at most 3 a day)."
        )
    )
    branding: EffectiveBranding
    messages: list[TrackedMessage] = Field(
        default_factory=list,
        description=(
            "Phase 11: the conversation with the team, oldest first: the latest "
            f"{TRACKED_MESSAGES_SHOWN} at most (message_count says how many there are). Empty "
            "until the team writes: then show a Messages section."
        ),
    )
    message_count: int = Field(
        default=0, ge=0, description="Phase 11: messages in the conversation, both directions."
    )
    team_messages_emailed: bool = Field(
        default=False,
        description=(
            "Phase 11: the team's messages are also emailed to the address on file (it is "
            'confirmed and email is set up): "We\'ll also email you when the team writes." '
            "False: they appear only here."
        ),
    )
    can_reply: bool = Field(
        default=False, description="Phase 11: show the reply box (reply_blocked is null)."
    )
    reply_blocked: ReplyBlocked | None = Field(
        default=ReplyBlocked.AWAITING_TEAM,
        description="Phase 11: why there is no reply box now; null when can_reply.",
    )


class EmailVerified(ResponseModel):
    """The confirmation page after the person clicked "Confirm" (the page posts the
    token only on that click, never on load: link scanners must not confirm).
    Idempotent."""

    project: PublicProjectRef
    title: str = Field(description="The idea's title as submitted.")
    held_for: HoldReason | None = Field(
        description="moderation: confirmed, now waiting for review; null: with the team."
    )
    branding: EffectiveBranding
    tracking_link_emailed: bool = Field(
        default=False,
        description=(
            "Phase 11: this confirmation was the address's first and queued the email with "
            "the private tracking link (email is set up): say \"We've emailed you a private "
            'link to follow your idea." False on a repeated confirmation and without email.'
        ),
    )


# --- Project settings -> Public form -------------------------------------------------
class PublicFormSettings(ResponseModel):
    """Project settings -> Public form (``project.edit_settings``)."""

    available: bool = Field(
        description=(
            "Public forms are allowed on this instance (SOUNDINGS_PUBLIC_SUBMISSION_ENABLED, "
            "the chart's features.publicSubmission), the project isn't archived and its "
            "slug isn't one of the app's own paths (RESERVED_SLUGS, older projects only). "
            "False: explain why and disable the switch."
        )
    )
    email_available: bool = Field(
        description=(
            "Email is set up (SMTP): without it the form can't ask for an address, so "
            "require_email_verification can't be turned on."
        )
    )
    enabled: bool
    require_email_verification: bool = Field(
        description="New ideas wait until the submitter confirms their address."
    )
    moderation_required: bool = Field(
        description="New ideas wait until a project admin approves them (default on)."
    )
    intro_md: str = Field(
        description=(
            "The text shown at the top of the public form, above the fields (Markdown: "
            "headings, lists, links; no raw HTML). Phase 11 (D3): label it so in Project "
            "settings -> Public form."
        )
    )
    form_url: str = Field(description="<base URL>/<slug>/submit, to copy and share.")
    awaiting_moderation: int = Field(description="Ideas in the moderation queue now.")


class PublicFormSettingsUpdate(RequestModel):
    """Partial update; omitted or null fields are unchanged."""

    enabled: bool | None = None
    require_email_verification: bool | None = None
    moderation_required: bool | None = None
    intro_md: str | None = Field(
        default=None,
        max_length=INTRO_MAX_LENGTH,
        description="The text at the top of the public form (Markdown, at most 2,000 characters).",
    )


# --- The submission behind an idea, and moderation -----------------------------------
class SubmitterContact(ResponseModel):
    """Only for project and platform admins (``public.erase_submitter``)."""

    email: str | None = Field(description="Null when none was given or it was erased.")
    email_verified: bool
    wants_updates: bool


class IdeaSubmissionPermissions(ResponseModel):
    can_moderate: bool = Field(description="idea.moderate and the idea is held for moderation.")
    can_erase: bool = Field(description="public.erase_submitter and not erased yet.")
    can_message: bool = Field(
        default=False,
        description=(
            "Phase 11: public.message_submitter (the idea's owner, project and platform "
            "admins, in a session) and a message can be sent now (messages.blocked is null): "
            "show the composer."
        ),
    )


class MessageDelivery(StrEnum):
    """Phase 11: where a new team message reaches the submitter."""

    EMAIL = "email"
    """Their tracking page and an email to their confirmed address."""
    TRACKING_PAGE = "tracking_page"
    """Only their tracking page (no address, not confirmed, or email isn't set up; the
    reason isn't given: contact details are for public.erase_submitter only)."""


class SendBlocked(StrEnum):
    """Phase 11: why the team can't send a message now (``SubmissionMessagesSummary``)."""

    SUBMITTER_ERASED = "submitter_erased"
    """Their details were erased: no link, no address, no conversation (409
    ``submitter_erased``)."""
    CONVERSATION_FULL = "conversation_full"
    """200 messages (409 ``conversation_full``)."""
    PROJECT_ARCHIVED = "project_archived"
    """The project is archived: the conversation is read-only (409 ``project_archived``)."""
    DAILY_LIMIT = "daily_limit"
    """The team sent 20 messages to this submitter in the last 24 hours (429
    ``too_many_attempts``). Your own hourly limit (30, every idea) isn't shown here: sending
    over it is 429 too."""


class SubmissionMessagesSummary(ResponseModel):
    """Phase 11: what the submission panel needs to show the Messages section; only for
    whoever holds public.message_submitter (``IdeaSubmission.messages`` is null for everyone
    else, who must not learn that a conversation exists)."""

    count: int = Field(ge=0, description="Messages in the conversation, both directions.")
    last_message_at: datetime | None = Field(description="The latest message's time; null if none.")
    last_direction: MessageDirection | None = Field(
        description='Who wrote the latest message (submitter: "They replied"); null if none.'
    )
    delivery: MessageDelivery = Field(
        description=(
            "Where a message sent now reaches them; tracking_page: say before sending "
            '"They\'ll see it only on their tracking page."'
        )
    )
    blocked: SendBlocked | None = Field(
        description="Why a message can't be sent now (say so instead of the composer); null: can."
    )


class SubmissionMessage(ResponseModel):
    """Phase 11: a message in the conversation, as the team sees it."""

    id: UUID
    direction: MessageDirection
    body: str = Field(
        description=(
            "Plain text; render with line breaks, never as Markdown or HTML. A submitter's "
            "text is untrusted public input (don't make its links clickable)."
        )
    )
    created_at: datetime
    author: UserRef | None = Field(
        description=(
            'Who on the team wrote it (submitters see only "The <project> team"); null for '
            "the submitter's replies and if the user no longer exists."
        )
    )
    emailed: bool = Field(
        description=(
            "A team message that was also emailed to their confirmed address (queued when "
            "sent); false: tracking page only. Always false for replies."
        )
    )


class SubmissionMessagePage(Page[SubmissionMessage]):
    """Newest first (load earlier messages with ``next_cursor``; show them oldest at the
    top). At most 200 in all."""


class SubmissionMessageCreate(RequestModel):
    """Phase 11: a message from the team to the submitter (plain text)."""

    body: MessageBody


class IdeaSubmission(ResponseModel):
    """How an idea came in through the public form (``GET /ideas/{idea}/submission``)."""

    idea_id: UUID
    submitted_at: datetime
    held_for: HoldReason | None = Field(
        description="moderation: show Approve / Reject; never email_verification here."
    )
    name: str | None = Field(
        description="The name they gave (anyone who can view the idea sees it); null if none."
    )
    contact: SubmitterContact | None = Field(
        description="Null unless you may erase the submitter's details (project admins)."
    )
    erased_at: datetime | None = Field(
        description="Their details were erased: no name, address or tracking link left."
    )
    permissions: IdeaSubmissionPermissions
    messages: SubmissionMessagesSummary | None = Field(
        default=None,
        description=(
            "Phase 11: the conversation with the submitter, in short; null unless you hold "
            "public.message_submitter (the idea's owner, project and platform admins, in a "
            "session): nobody else learns that one exists."
        ),
    )


class ModerationItem(IdeaRef):
    """A public idea waiting for approval: everything needed to decide."""

    summary: str
    description_md: str
    submission: IdeaSubmission


class ModerationPage(Page[ModerationItem]):
    """Oldest first (a queue)."""

    total: int = Field(description="Ideas waiting, all pages (the board's badge).")
