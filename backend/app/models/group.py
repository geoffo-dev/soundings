"""Groups, their IdP mappings and memberships, and project roles granted to groups."""

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
from app.models.enums import GroupSyncMode, ProjectRole
from app.models.types import str_enum


class Group(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An internal group. Names are unique case-insensitively.

    A group may be mapped to IdP group values (``group_idp_values``); ``sync_mode``
    says what sign-in sync does with them (``managed`` adds and removes, ``additive``
    only adds). A managed group with no values matches nothing, so sync removes its
    synced memberships; manual memberships are never touched by sync.
    """

    __tablename__ = "groups"
    __table_args__ = (Index("uq_groups_name_lower", func.lower(text("name")), unique=True),)

    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    sync_mode: Mapped[GroupSyncMode] = mapped_column(
        str_enum(GroupSyncMode, "sync_mode"),
        default=GroupSyncMode.MANAGED,
        server_default=GroupSyncMode.MANAGED.value,
    )


class GroupIdpValue(Base):
    """One IdP group value mapped to a group, stored **normalised** (contract-phase2
    §3.5: trimmed, slashes stripped at both ends, lower-case). A value may map to
    several groups; it is unique per group. Indexed by value for the sign-in lookup."""

    __tablename__ = "group_idp_values"
    __table_args__ = (CheckConstraint("length(value) > 0", name="value_not_empty"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class GroupMembership(TimestampMixin, Base):
    """A user's membership of a group, with its provenance.

    ``manual``: added by an admin; sync never changes it. ``synced``: added by
    sign-in sync from the IdP claim; sync sets it and (managed groups) clears it. A
    user can be both; the row exists while at least one is true.
    """

    __tablename__ = "group_memberships"
    __table_args__ = (CheckConstraint("manual OR synced", name="has_source"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    synced: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class ProjectGroupGrant(TimestampMixin, Base):
    """A project role granted to every member of a group.

    A user's effective project role is the highest of their direct membership
    (``project_members``) and the grants of every group they belong to; read it from
    the ``project_effective_roles`` view, never from this table.
    """

    __tablename__ = "project_group_grants"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole, "role"))
