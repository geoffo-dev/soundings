"""Admin settings -> Users: pre-created users, external IDs, identities, groups and
project roles (contract-phase2 section 3.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.common import Page
from app.schemas.groups import GroupRef, UserProjectRole
from app.schemas.users import UserRef

__all__ = [
    "EXTERNAL_ID_KIND_PATTERN",
    "MAX_EXTERNAL_IDS",
    "RESERVED_EMAIL_DOMAIN",
    "AdminUser",
    "AdminUserCreate",
    "AdminUserPage",
    "AdminUserSummary",
    "AdminUserUpdate",
    "EmailAddress",
    "ExternalId",
    "ExternalIdIn",
    "ExternalIdsReplace",
    "LinkedIdentity",
    "UserGroup",
    "is_reserved_email",
]

EXTERNAL_ID_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
"""``employee_no``, ``gitlab``: lower-case letters, digits and underscores."""

MAX_EXTERNAL_IDS = 20

RESERVED_EMAIL_DOMAIN = ".invalid"
"""Addresses under the ``.invalid`` top-level domain (RFC 2606) are reserved for system
accounts (``break-glass@soundings.invalid``): admins can't give one to a user."""


def is_reserved_email(address: str) -> bool:
    """Under ``.invalid``, also written with a trailing dot (``x@host.invalid.``)."""
    return address.lower().rstrip(".").endswith(RESERVED_EMAIL_DOMAIN)


def _not_reserved(email: str) -> str:
    if is_reserved_email(email):
        raise ValueError("addresses under .invalid are reserved for system accounts")
    return email


EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$"
    ),
    AfterValidator(_not_reserved),
]
"""An email address (only the shape is checked: something@something), not under the
reserved ``.invalid`` domain."""

DisplayName = Annotated[str, Field(min_length=1, max_length=100)]


class ExternalIdIn(RequestModel):
    kind: str = Field(pattern=EXTERNAL_ID_KIND_PATTERN, description="e.g. employee_no, gitlab.")
    value: str = Field(min_length=1, max_length=200, description="Matched case-insensitively.")


def _one_per_kind(values: list[ExternalIdIn]) -> list[ExternalIdIn]:
    kinds = [value.kind for value in values]
    if len(kinds) != len(set(kinds)):
        raise ValueError("at most one external ID per kind")
    return values


ExternalIds = Annotated[
    list[ExternalIdIn], Field(max_length=MAX_EXTERNAL_IDS), AfterValidator(_one_per_kind)
]


class ExternalId(ResponseModel):
    kind: str
    value: str


class LinkedIdentity(ResponseModel):
    """An SSO account linked to the user (the ID token's ``iss`` and ``sub``)."""

    id: UUID
    issuer: str
    subject: str
    linked_at: datetime
    last_login_at: datetime | None


class UserGroup(ResponseModel):
    """A group the user belongs to, with provenance (both flags can be true)."""

    group: GroupRef
    manual: bool
    synced: bool


class AdminUserSummary(UserRef):
    """A row in Admin settings -> Users."""

    email: str
    is_platform_admin: bool
    is_active: bool
    is_service_account: bool = Field(description="An agent account (Phase 6); never signs in.")
    is_break_glass: bool = Field(description="The break-glass admin (K8s Secret credentials).")
    has_identity: bool = Field(
        description="Linked to an SSO account. False for pre-created users until they sign in."
    )
    last_seen_at: datetime | None
    created_at: datetime


class AdminUser(AdminUserSummary):
    """One user, everything an admin needs to see where their access comes from."""

    identities: list[LinkedIdentity]
    external_ids: list[ExternalId] = Field(description="By kind.")
    groups: list[UserGroup] = Field(description="By group name.")
    project_roles: list[UserProjectRole] = Field(description="By project name.")
    active_session_count: int = Field(description="Live sessions (signed in on N browsers).")


class AdminUserPage(Page[AdminUserSummary]):
    """Users by display name."""


class AdminUserCreate(RequestModel):
    """Pre-create a user: they are linked at their first SSO sign-in by an external ID
    or their verified email (section 3.3)."""

    email: EmailAddress
    display_name: DisplayName
    is_platform_admin: bool = False
    external_ids: ExternalIds = Field(default_factory=list)


class AdminUserUpdate(RequestModel):
    """Omitted or null fields are unchanged. You cannot change your own ``is_active``
    or ``is_platform_admin`` (403 ``cannot_change_self``), and the last active platform
    admin stays one (409 ``last_platform_admin``)."""

    display_name: DisplayName | None = None
    email: EmailAddress | None = None
    is_active: bool | None = Field(
        default=None, description="false deactivates: ends their sessions, blocks sign-in."
    )
    is_platform_admin: bool | None = None


class ExternalIdsReplace(RequestModel):
    """The user's complete set of external IDs (one per kind)."""

    external_ids: ExternalIds
