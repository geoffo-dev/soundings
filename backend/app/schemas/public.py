"""Public submission: the public form, ALTCHA, tracking links, email confirmation,
moderation and erasing a submitter's details (SPEC section 10; contract-phase4
sections 3.4-3.9).

Public endpoints (``/api/v1/public/...``) need no session and never return anything
private: no people, comments, evaluations, scores or other submitters' details.
Secrets never travel in URLs the server sees: tracking and confirmation links carry
their token after ``#`` (the SPA posts it in a request body), so no access log, proxy
log or trace can record one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.models.enums import HoldReason, IdeaStatus, Resolution
from app.schemas.base import RequestModel, ResponseModel, SingleLine
from app.schemas.branding import EffectiveBranding
from app.schemas.common import Page
from app.schemas.email import MailAddress
from app.schemas.ideas import IdeaRef

__all__ = [
    "ALTCHA_PAYLOAD_MAX_LENGTH",
    "INTRO_MAX_LENGTH",
    "PUBLIC_DESCRIPTION_MAX_LENGTH",
    "TRACKING_TOKEN_PATTERN",
    "VERIFICATION_TOKEN_PATTERN",
    "AltchaChallenge",
    "AltchaParameters",
    "EmailVerified",
    "HoldReason",
    "IdeaSubmission",
    "IdeaSubmissionPermissions",
    "ModerationItem",
    "ModerationPage",
    "PublicFormSettings",
    "PublicFormSettingsUpdate",
    "PublicProject",
    "PublicProjectRef",
    "PublicSubmissionCreate",
    "PublicSubmissionReceipt",
    "SubmitterContact",
    "TrackedStatusChange",
    "TrackedSubmission",
    "TrackingRequest",
    "TrackingToken",
    "TrackingUpdatesRequest",
    "VerificationRequest",
    "VerificationToken",
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
    """The confirmation page. The tracking link is shown once here (and emailed when
    there is an address): only its hash is kept to look it up."""

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
            "An address was given and email is set up: say \"We'll also email you the "
            'link." True even when the per-address limit held that email back (the limit '
            "is silent, so this can't reveal how often an address was used)."
        )
    )


# --- Tracking and confirmation links -------------------------------------------------
class TrackingRequest(RequestModel):
    """The tracking page posts the token from its URL's fragment (``/track#<token>``)."""

    token: TrackingToken


class TrackingUpdatesRequest(RequestModel):
    token: TrackingToken
    wants_updates: bool = Field(description="Email me when the status changes.")


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


class TrackedSubmission(ResponseModel):
    """The private tracking page: what the submitter sent and its status, nothing
    else (no people, comments, evaluations, scores, or anything the team wrote: the
    title and summary are the submitter's own, as sent, even if the team edited the
    idea since)."""

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
    intro_md: str
    form_url: str = Field(description="<base URL>/<slug>/submit, to copy and share.")
    awaiting_moderation: int = Field(description="Ideas in the moderation queue now.")


class PublicFormSettingsUpdate(RequestModel):
    """Partial update; omitted or null fields are unchanged."""

    enabled: bool | None = None
    require_email_verification: bool | None = None
    moderation_required: bool | None = None
    intro_md: str | None = Field(default=None, max_length=INTRO_MAX_LENGTH)


# --- The submission behind an idea, and moderation -----------------------------------
class SubmitterContact(ResponseModel):
    """Only for project and platform admins (``public.erase_submitter``)."""

    email: str | None = Field(description="Null when none was given or it was erased.")
    email_verified: bool
    wants_updates: bool


class IdeaSubmissionPermissions(ResponseModel):
    can_moderate: bool = Field(description="idea.moderate and the idea is held for moderation.")
    can_erase: bool = Field(description="public.erase_submitter and not erased yet.")


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


class ModerationItem(IdeaRef):
    """A public idea waiting for approval: everything needed to decide."""

    summary: str
    description_md: str
    submission: IdeaSubmission


class ModerationPage(Page[ModerationItem]):
    """Oldest first (a queue)."""

    total: int = Field(description="Ideas waiting, all pages (the board's badge).")
