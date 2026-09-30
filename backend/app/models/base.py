"""Declarative base and mixins shared by all ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names, so Alembic autogenerate can diff and drop them.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Timezone-aware 'now' in UTC."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all models. Import models in ``app/models/__init__.py``."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        # Every datetime column is timezone-aware (timestamptz).
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKeyMixin:
    """``id`` UUID primary key generated in Python (known before flush)."""

    # sort_order: ``id`` first and timestamps last in CREATE TABLE, for readable schemas.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, sort_order=-10)


class TimestampMixin:
    """``created_at`` / ``updated_at`` (UTC, timezone-aware).

    Values are set in Python so they are available right after flush without an
    extra round trip (async sessions cannot lazy-load expired attributes); the
    server defaults cover rows inserted with plain SQL.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), sort_order=10
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
        sort_order=10,
    )
