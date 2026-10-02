"""Public submission: the submitter behind a public idea, and ALTCHA replay protection.

An idea sent through a project's public form (``/{slug}/submit``) is an ordinary
``ideas`` row with ``submitted_by_id`` null, plus one ``public_submissions`` row with
the little the submitter chose to give (an optional name and email), their private
tracking link, and a copy of the title and summary they sent (their tracking page and
emails show what *they* wrote, never what the team edited since). Minimal personal
data (UK GDPR): no IP address, user agent or account is stored; the tracking token is
stored only as a SHA-256 hash (to look it up) and sealed with the secret key (to put
the link in later emails); admins, or the submitter with their link, can erase the
name, email, link and copy while the idea stays (``erased_at``), and the cleanup
forgets unconfirmed addresses after 3 days and contact details 180 days after a closed
idea's last activity. See docs/api/contract-phase4.md sections 3.5-3.9.

ALTCHA (proof of work, research R1 section 7) has no replay protection of its own:
``altcha_used_challenges`` remembers each solved challenge's signature until the
challenge expires, so a solution is accepted once.

``confirmation_email_sends`` counts confirmation emails per address for the limit of
3 a day, by a keyed hash of the address (never the address), so erasing, rejecting or
forgetting a submission (which delete its outbox rows) can't reset the count.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

__all__ = ["AltchaUsedChallenge", "ConfirmationEmailSend", "PublicSubmission"]

TRACKING_TOKEN_HASH_LENGTH = 64
"""Hex SHA-256 of the tracking token."""


class PublicSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The public submitter of one idea (``idea_id`` unique).

    * ``name``, ``email``: optional, as entered; never logged or audited.
    * ``email_verified_at``: the submitter opened the confirmation link. Status-update
      emails go only to a confirmed address (and only with ``wants_updates``).
    * ``tracking_token_hash`` / ``tracking_token_sealed``: the private link's token,
      hashed (lookup, unique) and sealed (AES-256-GCM, ``app/auth/sealing.py``, purpose
      ``submission-tracking-token``) so later emails can carry the link. Both null
      once erased: the link stops working.
    * ``submitted_title`` / ``submitted_summary``: what the submitter sent, shown on
      their tracking page and in their status emails. Null once erased.
    * ``project_id`` repeats the idea's project for the per-project rate limit.
    * ``reached_team_at``: when the idea stopped being held (at submission when nothing
      held it, else the confirmation or the approval that released it); the tracking
      page's "With the team" step. Null while held. Not personal data: kept on erasure.

    The per-address limit on confirmation emails counts ``confirmation_email_sends``,
    not this table.
    """

    __tablename__ = "public_submissions"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR email_verified_at IS NULL", name="verified_needs_email"
        ),
        CheckConstraint("email IS NOT NULL OR NOT wants_updates", name="updates_need_email"),
        CheckConstraint(
            "(tracking_token_hash IS NULL) = (tracking_token_sealed IS NULL)",
            name="tracking_token_pair",
        ),
        CheckConstraint(
            "erased_at IS NULL OR (name IS NULL AND email IS NULL AND tracking_token_hash IS NULL"
            " AND submitted_title IS NULL AND submitted_summary IS NULL)",
            name="erased_is_empty",
        ),
        CheckConstraint(
            "erased_at IS NOT NULL"
            " OR (submitted_title IS NOT NULL AND submitted_summary IS NOT NULL)",
            name="submitted_copy_until_erased",
        ),
        # The per-project rate limit: public submissions in the last hour.
        Index("ix_public_submissions_project_id_created_at", "project_id", "created_at"),
        # The cleanup: unconfirmed addresses are forgotten after 3 days (section 3.9).
        Index(
            "ix_public_submissions_created_at_unconfirmed",
            "created_at",
            postgresql_where=text("email IS NOT NULL AND email_verified_at IS NULL"),
        ),
    )

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), unique=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(254))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wants_updates: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    tracking_token_hash: Mapped[str | None] = mapped_column(
        String(TRACKING_TOKEN_HASH_LENGTH), unique=True
    )
    tracking_token_sealed: Mapped[str | None] = mapped_column(String(255))
    submitted_title: Mapped[str | None] = mapped_column(String(200))
    submitted_summary: Mapped[str | None] = mapped_column(String(500))
    reached_team_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The admin who erased the details; null for the automatic retention erase.
    erased_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AltchaUsedChallenge(Base):
    """A solved ALTCHA challenge, by its HMAC signature, kept until it expires (the
    hourly cleanup deletes expired rows). Inserting an existing signature fails: the
    solution was already used (422 ``challenge_failed``)."""

    __tablename__ = "altcha_used_challenges"

    signature: Mapped[str] = mapped_column(String(128), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ConfirmationEmailSend(UUIDPrimaryKeyMixin, Base):
    """One confirmation email (``submission_received``) queued to an address, first
    sends and resends alike, for the limit of 3 per address per 24 hours
    (contract-phase4 section 3.5). ``address_key`` is HMAC-SHA256 of the canonical
    address (:func:`app.public.emails.canonical_address`: lower-cased, ``+tag``
    removed, provider variants folded) with a key derived from the secret key: no
    address is stored. Nothing deletes these rows but the hourly cleanup, a day later:
    erasure, rejection and the retention rules delete outbox rows, which is why the
    limit no longer counts those."""

    __tablename__ = "confirmation_email_sends"
    __table_args__ = (
        Index("ix_confirmation_email_sends_address_key_created_at", "address_key", "created_at"),
    )

    address_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
