"""Users and server-side sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person (or, from Phase 6, an AI agent's service account).

    Users are deactivated (``is_active = false``), not deleted. Phase 2 adds OIDC
    identities (issuer, subject) and external IDs in their own tables.
    """

    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness; look users up with lower(email) = lower(:email).
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
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
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(UUIDPrimaryKeyMixin, Base):
    """Server-side session. The cookie holds a random token; only its SHA-256 is stored."""

    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Double-submit CSRF token, mirrored in the non-HttpOnly ``soundings_csrf`` cookie.
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Short summary such as "Firefox on macOS" for a future "your sessions" list.
    user_agent: Mapped[str | None] = mapped_column(String(200))
