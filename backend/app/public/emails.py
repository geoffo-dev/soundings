"""The two emails to a public submitter (contract-phase4 section 3.8), sent through the
Phase 3 outbox and worker unchanged.

* ``submission_received``: **fixed text**, nothing the submitter typed (anyone can put
  any address in the form, so it must be useless for spam): "Confirm your idea for
  <project>", the confirmation link (signed when the email is rendered, valid 3 days
  from then) and what confirming does. No tracking link: whoever opens it on the
  strength of this email would read what a stranger typed, on our domain and in our
  branding (the receipt page gives the submitter their link). On submission with an
  address and on each resend. At most 3 per address per 24 hours, first sends and
  resends together, counted in ``confirmation_email_sends`` by a keyed hash of the
  :func:`canonical_address` (lower-cased, ``+tag`` removed, Gmail's dots and Yahoo's
  ``-keyword`` folded), which nothing but the hourly cleanup deletes; beyond it
  nothing is queued, silently (the caller can't tell).
* ``submission_status_changed``: in the fan-out of each ``status_changed`` event of a
  public idea whose submitter asked for updates and confirmed their address: the new
  status label, the title *as they sent it*, the tracking link and "Stop these emails".

Rows carry ``idea_id`` (erasure deletes them by idea) and ``to_address``; ``payload``
is ``{}`` or the status change, never personal data or tokens. Content is rendered at
send time from the submission, so an erased, changed or turned-off submission cancels
its queued emails.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.submission_tokens import make_confirmation_token, unseal_tracking_token
from app.config import Settings
from app.domain.labels import status_label
from app.email import outbox
from app.email.model import Button, EmailContent, subject_title
from app.models.activity import ActivityEvent
from app.models.enums import EmailType, HoldReason, IdeaStatus, Resolution
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.project import Project
from app.models.public import ConfirmationEmailSend, PublicSubmission

if TYPE_CHECKING:
    from app.email.content import OutboxRow

__all__ = [
    "CONFIRMATIONS_PER_ADDRESS",
    "CONFIRMATIONS_PER_SUBMISSION",
    "CONFIRMATION_WINDOW",
    "address_key",
    "canonical_address",
    "confirmations_sent",
    "queue_confirmation",
    "queue_status_email",
    "submitter_email",
    "tracking_url",
]

logger = logging.getLogger(__name__)

CONFIRMATION_WINDOW: Final = timedelta(hours=24)
CONFIRMATIONS_PER_ADDRESS: Final = 3
"""``submission_received`` emails per address (:func:`canonical_address`) per 24 hours."""
CONFIRMATIONS_PER_SUBMISSION: Final = 3
"""``submission_received`` emails per submission per 24 hours (the first included)."""

_ADDRESS_INFO: Final = b"soundings/submitter-address/v1"
_GMAIL: Final = {"gmail.com": "gmail.com", "googlemail.com": "gmail.com"}
_KEYWORD_DOMAINS: Final = frozenset({"yahoo.com", "ymail.com", "rocketmail.com"})
"""Yahoo's disposable addresses: ``base-keyword@`` reaches the owner of ``base``."""
_ADDRESS_LOCK_SALT: Final = 0x5355_424D
"""First key of the advisory lock that serialises one address's confirmation emails
(the second is a hash of the address key), so concurrent submissions can't all count
the same rows before any of them commits."""


def tracking_url(settings: Settings, token: str) -> str:
    """``<base>/track#<token>``: the token stays in the fragment, which browsers never
    send to a server (no access log, proxy log, trace or ``Referer`` can hold it)."""
    return f"{settings.public_base_url.rstrip('/')}/track#{token}"


def _confirmation_url(settings: Settings, token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/verify#{token}"


# --- The per-address limit --------------------------------------------------------------------
def canonical_address(address: str) -> str:
    """The inbox ``address`` reaches, as far as the limit is concerned: lower-cased,
    any ``+tag`` removed; Gmail ignores dots (and googlemail.com is gmail.com); Yahoo's
    ``base-keyword`` addresses fold to ``base``. Folding too much only makes two
    addresses share a limit."""
    local, _, domain = address.strip().lower().rpartition("@")
    local = local.split("+", 1)[0]
    domain = _GMAIL.get(domain, domain)
    if domain == "gmail.com":
        local = local.replace(".", "")
    elif domain in _KEYWORD_DOMAINS:
        local = local.split("-", 1)[0]
    return f"{local}@{domain}"


@functools.lru_cache(maxsize=4)
def _address_hmac_key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_ADDRESS_INFO).derive(
        secret.encode("utf-8")
    )


def address_key(settings: Settings, address: str) -> str:
    """HMAC-SHA256 (hex) of the :func:`canonical_address` with a key derived from the
    secret key: what ``confirmation_email_sends`` stores instead of the address."""
    key = _address_hmac_key(settings.secret_key.get_secret_value())
    return hmac.new(key, canonical_address(address).encode("utf-8"), hashlib.sha256).hexdigest()


# --- Queueing ---------------------------------------------------------------------------------
async def confirmations_sent(
    db: AsyncSession, idea_id: UUID, *, now: datetime
) -> tuple[int, datetime | None]:
    """``submission_received`` emails for the idea in the last 24 hours, and the oldest
    of them (``ix_outbound_email_idea_id``)."""
    row = (
        await db.execute(
            select(func.count(), func.min(OutboundEmail.created_at)).where(
                OutboundEmail.idea_id == idea_id,
                OutboundEmail.type == EmailType.SUBMISSION_RECEIVED,
                OutboundEmail.created_at > now - CONFIRMATION_WINDOW,
            )
        )
    ).one()
    return int(row[0] or 0), row[1]


async def _address_allows(db: AsyncSession, key: str, *, now: datetime) -> bool:
    """Fewer than :data:`CONFIRMATIONS_PER_ADDRESS` confirmation emails to the address
    with this :func:`address_key` in the last 24 hours. Takes the address's advisory
    lock first, so concurrent submissions can't all count the same rows."""
    await db.execute(select(func.pg_advisory_xact_lock(_ADDRESS_LOCK_SALT, func.hashtext(key))))
    count = await db.scalar(
        select(func.count())
        .select_from(ConfirmationEmailSend)
        .where(
            ConfirmationEmailSend.address_key == key,
            ConfirmationEmailSend.created_at > now - CONFIRMATION_WINDOW,
        )
    )
    return int(count or 0) < CONFIRMATIONS_PER_ADDRESS


async def queue_confirmation(
    db: AsyncSession, settings: Settings, submission: PublicSubmission, *, now: datetime
) -> bool:
    """Queue a ``submission_received`` email to the submission's address, unless email
    is off or the address had its 3 for the day (silently). ``True`` if queued."""
    if not settings.smtp_configured or submission.email is None:
        return False
    key = address_key(settings, submission.email)
    if not await _address_allows(db, key, now=now):
        logger.info(
            "submission email held back",
            extra={"reason": "address_limit", "idea_id": str(submission.idea_id)},
        )
        return False
    sequence = await db.scalar(
        select(func.count())
        .select_from(OutboundEmail)
        .where(
            OutboundEmail.idea_id == submission.idea_id,
            OutboundEmail.type == EmailType.SUBMISSION_RECEIVED,
        )
    )
    queued = await outbox.enqueue(
        db,
        settings,
        [
            outbox.NewEmail(
                type=EmailType.SUBMISSION_RECEIVED,
                to_address=submission.email,
                idea_id=submission.idea_id,
                idempotency_key=f"submission_received:{submission.id}:{int(sequence or 0) + 1}",
            )
        ],
        now=now,
    )
    if queued:
        db.add(ConfirmationEmailSend(address_key=key, created_at=now))
        await db.flush()
    return bool(queued)


async def queue_status_email(
    db: AsyncSession, settings: Settings | None, event: ActivityEvent, idea: Idea
) -> None:
    """The fan-out hook for a ``status_changed`` event (also the move inside
    ``create_proposal``): a ``submission_status_changed`` email to an opted-in,
    confirmed submitter whose details aren't erased. Idempotent per event (the
    deferred fan-out may run it again)."""
    if settings is None or not settings.smtp_configured or idea.held_for is not None:
        return
    submission = await db.scalar(
        select(PublicSubmission).where(PublicSubmission.idea_id == idea.id)
    )
    if (
        submission is None
        or submission.erased_at is not None
        or submission.email is None
        or submission.email_verified_at is None
        or not submission.wants_updates
    ):
        return
    payload = {
        key: event.payload.get(key)
        for key in ("from_status", "from_resolution", "to_status", "to_resolution")
    }
    await outbox.enqueue(
        db,
        settings,
        [
            outbox.NewEmail(
                type=EmailType.SUBMISSION_STATUS_CHANGED,
                to_address=submission.email,
                idea_id=idea.id,
                payload=payload,
                idempotency_key=f"submission_status:{event.id}",
            )
        ],
    )


# --- Content at send time --------------------------------------------------------------------
async def _load(db: AsyncSession, idea_id: UUID) -> tuple[PublicSubmission, Idea, Project] | None:
    row = (
        await db.execute(
            select(PublicSubmission, Idea, Project)
            .join(Idea, Idea.id == PublicSubmission.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(PublicSubmission.idea_id == idea_id)
        )
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def _status_label(project: Project, payload: Mapping[str, Any]) -> str | None:
    try:
        status = IdeaStatus(str(payload.get("to_status")))
        raw = payload.get("to_resolution")
        resolution = Resolution(str(raw)) if raw else None
    except ValueError:
        return None
    return status_label(project.status_labels, status, resolution)


async def submitter_email(
    db: AsyncSession, settings: Settings, email: OutboxRow, *, now: datetime
) -> EmailContent | str:
    """The content of a submitter email now, or why it must not be sent (one of
    :mod:`app.email.content`'s cancellation reasons)."""
    from app.email.content import NO_LONGER_APPLIES, TURNED_OFF

    found = None if email.idea_id is None else await _load(db, email.idea_id)
    if found is None:
        return NO_LONGER_APPLIES
    submission, idea, project = found
    if (
        submission.erased_at is not None
        or submission.email is None
        or submission.email != email.to_address
    ):
        return NO_LONGER_APPLIES
    project_name = project.name

    if email.type is EmailType.SUBMISSION_RECEIVED:
        if submission.email_verified_at is not None:
            return NO_LONGER_APPLIES  # confirmed with an earlier link meanwhile
        confirm = _confirmation_url(
            settings, make_confirmation_token(settings, submission.id, submission.email, now=now)
        )
        return EmailContent(
            template="submission_received",
            subject=f"Confirm your idea for {project_name}",
            preheader=f"Someone sent an idea to {project_name} and gave this email address.",
            context={
                "project": project_name,
                "confirm_url": confirm,
                "held_until_confirmed": idea.held_for is HoldReason.EMAIL_VERIFICATION,
                "wants_updates": submission.wants_updates,
            },
            button=Button("Confirm my email address", confirm),
            reason=f"Someone gave this address on the public idea form of {project_name}.",
        )

    if not submission.wants_updates or submission.email_verified_at is None:
        return TURNED_OFF
    if idea.held_for is not None:
        return NO_LONGER_APPLIES
    label = _status_label(project, email.payload)
    if label is None or submission.submitted_title is None:
        return NO_LONGER_APPLIES
    title = submission.submitted_title
    sealed = submission.tracking_token_sealed
    token = None if sealed is None else unseal_tracking_token(settings, sealed)
    tracking = None if token is None else tracking_url(settings, token)
    return EmailContent(
        template="submission_status_changed",
        subject=f'Your idea "{subject_title(title)}" is now {label}',
        preheader=f"Your idea for {project_name} is now {label}.",
        context={
            "title": title,
            "project": project_name,
            "status": label,
            "tracking_url": tracking,
        },
        button=Button("See where your idea stands", tracking) if tracking else None,
        reason=f"You asked for updates on an idea you sent to {project_name}.",
    )
