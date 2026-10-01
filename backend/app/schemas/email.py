"""Admin settings -> Email: the effective SMTP configuration (read-only), the test email
and the outbox (failed sends and retry).

SMTP is configured through Helm values / ``SOUNDINGS_SMTP_*`` only; this view shows
what is in effect, with credentials masked (contract-phase3 section 3.10).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints

from app.config import MAIL_ADDRESS_MAX_LENGTH, MAIL_ADDRESS_PATTERN, is_mail_address
from app.models.enums import EmailStatus, EmailType
from app.schemas.admin_users import is_reserved_email
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.common import Page
from app.schemas.ideas import IdeaRef
from app.schemas.users import UserRef

__all__ = [
    "EmailConfig",
    "EmailStatus",
    "EmailTestRequest",
    "EmailType",
    "MailAddress",
    "OutboxEmail",
    "OutboxEmailPage",
    "OutboxRetryResult",
    "OutboxStats",
    "SmtpSecurity",
]

SmtpSecurity = Literal["none", "starttls", "tls"]
"""= ``app.config.SmtpSecurity``."""


def _one_usable_address(value: str) -> str:
    if not is_mail_address(value):  # also the 64-character local part
        raise ValueError("must be one plain email address such as ops@example.com")
    if is_reserved_email(value):
        raise ValueError("addresses under .invalid are reserved for system accounts")
    return value


MailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=MAIL_ADDRESS_MAX_LENGTH,
        pattern=MAIL_ADDRESS_PATTERN,
    ),
    AfterValidator(_one_usable_address),
]
"""Exactly one plain ASCII address (``app.config.MAIL_ADDRESS_PATTERN``), not under the
reserved ``.invalid`` domain: no display name, list, quoting or whitespace, so one
request can never name a second recipient (``ops@example.com,postmaster`` fails)."""


class OutboxStats(ResponseModel):
    """The outbox at a glance (the page's header and the failures callout)."""

    queued: int = Field(description="Waiting to be sent (including retries).")
    sending: int = Field(description="Claimed by a worker right now.")
    failed: int = Field(description="Failed for good (kept 90 days): retry them.")
    sent_last_24h: int
    oldest_queued_at: datetime | None = Field(
        description=(
            "Created time of the oldest queued email: long ago means the worker isn't "
            "running or the server is unreachable."
        )
    )
    last_sent_at: datetime | None


class EmailConfig(ResponseModel):
    """The email settings in effect. Credentials are never returned, only whether set."""

    configured: bool = Field(
        description="A host and sender are set. False: in-app notifications only."
    )
    host: str | None
    port: int
    security: SmtpSecurity = Field(description="none, starttls or tls (implicit TLS).")
    username_set: bool
    password_set: bool
    from_address: str | None
    from_name: str
    reply_to: str | None
    ca_bundle: str | None = Field(
        description="Path of the custom CA bundle; null: the system trust store."
    )
    timeout_seconds: float
    links_base_url: str = Field(description="Links in emails start with this (first base URL).")
    timezone: str = Field(description="IANA time zone for digests, reminders and dates.")
    digest_hour: int = Field(ge=0, le=23)
    reminder_days: list[int] = Field(
        description="Days before the due date that reminders go out (0 = due date), descending."
    )
    outbox: OutboxStats


class OutboxEmail(ResponseModel):
    """One email in the outbox. Its content isn't stored (rendered when sent)."""

    id: UUID
    type: EmailType
    status: EmailStatus
    recipient: UserRef | None = Field(description="The user it is for; null for an address.")
    address_hint: str | None = Field(
        description='Masked address when the recipient is not a user: "j•••@example.com".'
    )
    idea: IdeaRef | None = Field(
        description=(
            "The idea it is about (from its notification); null for digests, test emails "
            "and when the idea is gone or the notification was pruned."
        )
    )
    requested_by: UserRef | None = Field(description="The admin who sent a test email.")
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None = Field(
        description=(
            "Queued: when the next attempt is due; sending: when the worker's claim "
            "expires; otherwise null."
        )
    )
    last_error: str | None = Field(
        description=(
            'Why the last attempt failed, e.g. "SMTP 535: authentication failed" or '
            '"connection timed out". Never the server\'s own text.'
        )
    )
    created_at: datetime
    sent_at: datetime | None
    retryable: bool = Field(
        description=(
            "Failed and still recent enough to send (3 days after it was queued; digests "
            "2 days): show the Retry button. Older mail would be out of date."
        )
    )


class OutboxEmailPage(Page[OutboxEmail]):
    """Newest first."""


class EmailTestRequest(RequestModel):
    to: MailAddress | None = Field(
        default=None,
        description=(
            "One plain address to send it to; null or omitted: your own address. "
            "Names, lists and .invalid addresses are refused."
        ),
    )


class OutboxRetryResult(ResponseModel):
    retried: int = Field(description="Failed emails queued again (only retryable ones).")
