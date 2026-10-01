"""Comments, the activity feed and the audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A flat comment on an idea. Deleting sets ``deleted_at`` (the feed shows a stub).

    Every comment also has an ``activity_events`` row (``type = 'comment'``) that
    places it in the idea's feed.
    """

    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_idea_id_created_at", "idea_id", "created_at"),)

    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body_md: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityEvent(UUIDPrimaryKeyMixin, Base):
    """An entry in an idea's activity feed; Phase 3 notifications are derived from these.

    ``type`` is one of the ``ActivityItem`` discriminators in ``app/schemas/activity.py``
    (validated in the application, not the database, since the set grows by phase).
    ``payload`` holds the type-specific data (user ids, from/to values) and must never
    contain evaluation scores. ``idea_id`` is nullable for future project-level events.
    """

    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_events_idea_id_created_at", "idea_id", "created_at", "id"),
        Index("ix_activity_events_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    idea_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(40))
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only security audit trail (sign-ins, assignments, evaluations, status
    and admin changes; contract-phase2 §3.11).

    No foreign keys on purpose: entries must outlive the users, projects and ideas
    they mention. Never store secrets, tokens, emails or claims in ``details``.
    The viewer (``GET /admin/audit``) pages newest first by ``(created_at, id)``;
    each filter has an index leading with its column.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created_at_id", "created_at", "id"),
        Index("ix_audit_log_actor_id_created_at", "actor_id", "created_at"),
        Index("ix_audit_log_action_created_at", "action", "created_at"),
        Index("ix_audit_log_project_id_created_at", "project_id", "created_at"),
        Index("ix_audit_log_target_type_target_id", "target_type", "target_id"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    project_id: Mapped[uuid.UUID | None] = mapped_column()
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
