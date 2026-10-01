"""Users, their sign-in identities and external IDs, sessions and OIDC login attempts."""

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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import AuthMethod
from app.models.types import str_enum

EXTERNAL_ID_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
"""External-ID kinds: ``employee_no``, ``gitlab``, ... (lower-case, digits, underscores)."""

BREAK_GLASS_EMAIL = "break-glass@soundings.invalid"
"""The break-glass account's address. ``.invalid`` addresses are reserved for system
accounts: admins can't set one and SSO never uses one (contract-phase2 section 3.8)."""


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person, the break-glass admin, or (from Phase 6) an AI agent's service account.

    Users are deactivated (``is_active = false``), not deleted. A pre-created user is
    an ordinary row without an identity yet; the first SSO sign-in that matches it
    (external ID or verified email) links one (``user_identities``).
    """

    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness; look users up with lower(email) = lower(:email).
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
        # At most one break-glass account.
        Index(
            "uq_users_is_break_glass",
            "is_break_glass",
            unique=True,
            postgresql_where=text("is_break_glass"),
        ),
    )

    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Reserved for Phase 5/6: API-key-only accounts used by kagent agents (never sign in).
    is_service_account: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # The local admin whose credentials come from a K8s Secret (SOUNDINGS_BREAK_GLASS_*).
    # Created at its first sign-in; never matched by SSO login matching.
    is_break_glass: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserIdentity(UUIDPrimaryKeyMixin, Base):
    """An OIDC account linked to a user: the ID token's ``(iss, sub)``.

    One identity per issuer per user, and each ``(issuer, subject)`` belongs to one
    user. Linked at the first sign-in that matches the user (contract-phase2 §3.3).
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        UniqueConstraint("user_id", "issuer"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The ``iss`` claim exactly as received (equals the discovered issuer).
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserExternalId(Base):
    """An admin-managed external ID (``employee_no = E1001``) used to link a pre-created
    user at first sign-in. One value per kind per user; ``(kind, value)`` unique,
    case-insensitively."""

    __tablename__ = "user_external_ids"
    __table_args__ = (
        CheckConstraint(f"kind ~ '{EXTERNAL_ID_KIND_PATTERN}'", name="kind"),
        CheckConstraint("length(value) > 0", name="value_not_empty"),
        Index(
            "uq_user_external_ids_kind_value_lower",
            "kind",
            func.lower(text("value")),
            unique=True,
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class UserSession(UUIDPrimaryKeyMixin, Base):
    """Server-side session. The cookie holds a random token; only its SHA-256 is stored."""

    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Double-submit CSRF token, mirrored in the non-HttpOnly ``soundings_csrf`` cookie.
    csrf_token: Mapped[str] = mapped_column(String(64))
    # How the session started. Sign-in code passes it explicitly; the Python default
    # only keeps Phase 1 callers of start_session working (no server default).
    auth_method: Mapped[AuthMethod] = mapped_column(
        str_enum(AuthMethod, "auth_method"), default=AuthMethod.DEV_LOGIN
    )
    # SSO sessions only: the ID token, kept server-side solely as ``id_token_hint`` for
    # RP-initiated logout. Never logged, never returned by the API.
    id_token: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Short summary such as "Firefox on macOS" for a future "your sessions" list.
    user_agent: Mapped[str | None] = mapped_column(String(200))


class OidcLoginAttempt(UUIDPrimaryKeyMixin, Base):
    """One SSO sign-in in progress (``GET /auth/login`` -> ``GET /auth/callback``).

    Server-side so the browser never holds the PKCE verifier or nonce. Looked up by
    the SHA-256 of ``state``; the same ``state`` is also in the HttpOnly
    ``soundings_oidc`` cookie, which binds the attempt to the browser that started it.
    Single use (deleted at the callback) and short-lived (``expires_at``, 10 minutes).
    """

    __tablename__ = "oidc_login_attempts"

    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nonce: Mapped[str] = mapped_column(String(128))
    code_verifier: Mapped[str] = mapped_column(String(128))
    # The exact redirect_uri sent to the IdP (repeated in the token request).
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    # Where to go after sign-in: an already validated same-origin path.
    next_path: Mapped[str] = mapped_column(String(2048), default="/", server_default="/")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
