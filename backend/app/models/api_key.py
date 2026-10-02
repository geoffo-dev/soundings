"""Personal API keys (SPEC section 8; contract-phase5 section 3.1).

A key is ``sdg_<lookup id>_<secret>`` (``app.schemas.api_keys.API_KEY_PATTERN``). Only
the public ``lookup_id`` and the SHA-256 of the whole key (``secret_hash``) are stored:
the key is shown once, at creation, and can't be recovered. Authentication finds the
row by ``lookup_id`` and compares hashes in constant time.

A key acts as its owner **live** (their current roles, platform-admin flag and active
state on every request), narrowed by ``scopes`` and, when ``project_ids`` is set, to
those projects (role matrix section 5). Revoking sets ``revoked_at``: the row stays,
so audit entries can still name the key, but it never authenticates again. Expired
keys (``expires_at`` in the past) stop working at once and stay listed until revoked.

A key also stops working, without changing its row, while the sign-in method of the
session that created it (``created_auth_method``) is unavailable (dev login turned off,
SSO no longer configured), and, for a person's key, while its owner hasn't used the app
for 30 days (``users.last_seen_at``; contract-phase5 section 3.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import AuthMethod
from app.models.types import str_enum

__all__ = ["ApiKey"]

API_KEY_SCOPES_SQL = "ARRAY['read', 'write', 'evaluate', 'mcp']::varchar[]"
"""The scope values (``ApiKeyScope``) as a SQL array, for the ``scopes`` check."""


class ApiKey(UUIDPrimaryKeyMixin, Base):
    """One API key of one user (a person, or from Phase 6 an agent's service account)."""

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("lookup_id ~ '^[A-Za-z0-9]{12}$'", name="lookup_id_format"),
        CheckConstraint("secret_hash ~ '^[0-9a-f]{64}$'", name="secret_hash_format"),
        CheckConstraint("length(name) > 0", name="name_not_empty"),
        CheckConstraint(
            f"cardinality(scopes) BETWEEN 1 AND 4 AND scopes <@ {API_KEY_SCOPES_SQL}",
            name="scopes",
        ),
        # write and evaluate include read (role matrix section 5).
        CheckConstraint(
            "'read' = ANY (scopes) OR NOT (scopes && ARRAY['write', 'evaluate']::varchar[])",
            name="scopes_include_read",
        ),
        # 1-50 ids and no NULL element: an empty or NULL-filled restriction must never
        # read as "every project".
        CheckConstraint(
            "project_ids IS NULL OR (cardinality(project_ids) BETWEEN 1 AND 50"
            " AND array_position(project_ids, NULL) IS NULL)",
            name="project_ids_not_empty",
        ),
        CheckConstraint(
            "revoked_by_id IS NULL OR revoked_at IS NOT NULL", name="revoked_by_needs_revoked"
        ),
        # A name is unique per owner (any case) among keys that aren't revoked.
        Index(
            "uq_api_keys_user_id_name_lower",
            "user_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        # Admin settings -> API keys: keys that aren't revoked, newest first.
        Index(
            "ix_api_keys_created_at_id_unrevoked",
            "created_at",
            "id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    # Public part of the key (12 base62 characters): the lookup, and how the UI shows
    # the key ("sdg_<lookup_id>..."). Unique.
    lookup_id: Mapped[str] = mapped_column(String(12), unique=True)
    # SHA-256 (hex) of the whole key string. Never logged or returned.
    secret_hash: Mapped[str] = mapped_column(String(64))
    # ApiKeyScope values, canonical order (read, write, evaluate, mcp), no duplicates.
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    # Project restriction: null = every project the owner can access; else only these
    # (ids of deleted projects simply match nothing, so the key never widens).
    project_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(Uuid()))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Updated at most once a minute (contract-phase5 section 3.1).
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who revoked it: the owner, a platform admin, or the admin who deactivated the
    # owner; null while active (or if that user no longer exists).
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Who created it: the owner, or (Phase 6) the platform admin who registered the
    # agent whose service account owns it.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # The sign-in method of the session that created it: the key works only while that
    # method is available (``app.services.sessions.method_available``), like a session.
    created_auth_method: Mapped[AuthMethod] = mapped_column(
        str_enum(AuthMethod, "created_auth_method")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
