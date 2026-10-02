"""Personal API keys: Settings -> API keys and Admin settings -> API keys (SPEC section 8;
contract-phase5 sections 2 and 3.1-3.3).

A key is ``sdg_`` + a 12-character lookup id + ``_`` + a 40-character secret (base62).
It is shown **once**, in the response that creates it; afterwards only its ``prefix``
(``sdg_`` + the lookup id) identifies it. It acts as its owner, live, narrowed by its
scopes and optional project restriction, and never does more than its owner could at
that moment (role matrix section 5). Keys are created, listed and revoked in a signed-in
session only (``api_key.manage_own`` / ``api_key.manage_any`` are session-only rules).
A key works only while the sign-in method that created it is available and, for a
person, while they have used the app within :data:`API_KEY_OWNER_IDLE_LIMIT`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, Field, field_validator

from app.models.enums import ApiKeyScope
from app.schemas.base import RequestModel, ResponseModel, SingleLine
from app.schemas.common import Page
from app.schemas.projects import ProjectRef
from app.schemas.users import UserRef

__all__ = [
    "API_KEY_FAILURES_PER_MINUTE",
    "API_KEY_LOOKUP_LENGTH",
    "API_KEY_MAX_LIFETIME",
    "API_KEY_MIN_LIFETIME",
    "API_KEY_NAME_MAX_LENGTH",
    "API_KEY_OWNER_IDLE_LIMIT",
    "API_KEY_PATTERN",
    "API_KEY_PREFIX",
    "API_KEY_REQUESTS_PER_MINUTE",
    "API_KEY_SECRET_LENGTH",
    "API_KEY_WRITES_PER_MINUTE",
    "LAST_USED_THROTTLE",
    "MAX_API_KEYS_PER_USER",
    "MAX_KEY_PROJECTS",
    "SCOPES_IMPLYING_READ",
    "AdminApiKey",
    "AdminApiKeyPage",
    "ApiKey",
    "ApiKeyCreate",
    "ApiKeyExpiry",
    "ApiKeyList",
    "ApiKeyScope",
    "ApiKeyState",
    "CreatedApiKey",
    "canonical_scopes",
]

API_KEY_PREFIX: Final = "sdg_"
"""Every key starts with it, so people and secret scanners recognise a Soundings key."""
API_KEY_LOOKUP_LENGTH: Final = 12
"""Base62 characters of the public lookup id (stored in clear, unique)."""
API_KEY_SECRET_LENGTH: Final = 40
"""Base62 characters of the secret part (about 238 bits; only the hash is stored)."""
API_KEY_PATTERN: Final = (
    rf"^{API_KEY_PREFIX}[A-Za-z0-9]{{{API_KEY_LOOKUP_LENGTH}}}"
    rf"_[A-Za-z0-9]{{{API_KEY_SECRET_LENGTH}}}$"
)
"""The whole key. Anything else after ``Authorization: Bearer`` is a 401 without a
database lookup."""

MAX_API_KEYS_PER_USER: Final = 25
"""Keys one user may hold that aren't revoked (expired ones count until revoked);
more: 409 ``too_many_api_keys``."""
MAX_KEY_PROJECTS: Final = 50
"""Projects one key may be restricted to."""
API_KEY_NAME_MAX_LENGTH: Final = 80
API_KEY_MIN_LIFETIME: Final = timedelta(hours=1)
API_KEY_MAX_LIFETIME: Final = timedelta(days=366)
"""``expires_at`` is at least an hour and at most a year (366 days) ahead; no expiry
(null) is allowed too."""
LAST_USED_THROTTLE: Final = timedelta(minutes=1)
"""``last_used_at`` moves at most once a minute per key."""
API_KEY_FAILURES_PER_MINUTE: Final = 30
"""Failed key authentications per client address (IPv6: per /64) per minute, per API
process. Beyond it, for the rest of the minute, a key from that address that fails is
answered 429 ``too_many_attempts`` (with ``Retry-After``) instead of 401, while a valid
key still works: one script retrying a revoked key behind a shared NAT doesn't lock
out its neighbours. Malformed tokens never reach the database either way."""
API_KEY_REQUESTS_PER_MINUTE: Final = 300
"""Requests one key may make per minute (REST and ``/mcp`` together), per API
process; beyond it 429 ``too_many_attempts`` with ``Retry-After``."""
API_KEY_WRITES_PER_MINUTE: Final = 30
"""Writes one key may make per minute, per API process: REST requests with an unsafe
method (``POST``, ``PUT``, ``PATCH``, ``DELETE``) and MCP calls of tools that aren't
read-only, together. Beyond it 429 ``too_many_attempts`` with ``Retry-After`` (REST) or
the tool error ``too_many_attempts`` (MCP). Bounds a runaway or prompt-injected agent
(comments, @mentions, notifications)."""
API_KEY_OWNER_IDLE_LIMIT: Final = timedelta(days=30)
"""A **person's** key works only while its owner has used Soundings in a session within
this time (``users.last_seen_at``; null counts as never). Group sync and access changes
happen at sign-in, so someone removed from the identity provider stops signing in and
their keys stop within 30 days, like their sessions within ``maxAge``. Signing in again
reactivates the keys. Service accounts never sign in and are exempt."""


class ApiKeyState(StrEnum):
    """A listed key's state. Revoked keys are never listed."""

    ACTIVE = "active"
    EXPIRED = "expired"
    """``expires_at`` has passed: the key no longer works; revoke it to free its name and
    its place in the 25-key limit. Takes precedence over ``dormant``."""
    DORMANT = "dormant"
    """A person's key whose owner hasn't used Soundings for 30 days
    (:data:`API_KEY_OWNER_IDLE_LIMIT`): it doesn't work until they sign in again. In
    practice only admins see it (the owner's own list is read in a session)."""


SCOPES_IMPLYING_READ: Final = frozenset({ApiKeyScope.WRITE, ApiKeyScope.EVALUATE})
"""Scopes whose responses return readable data (the changed idea, the saved evaluation),
so a key with one of them always has ``read`` too (role matrix section 5)."""


def canonical_scopes(scopes: list[ApiKeyScope]) -> list[ApiKeyScope]:
    """Distinct scopes in the canonical order ``read, write, evaluate, mcp``, with ``read``
    added when ``write`` or ``evaluate`` is there (they include it)."""
    wanted = set(scopes)
    if wanted & SCOPES_IMPLYING_READ:
        wanted.add(ApiKeyScope.READ)
    return [scope for scope in ApiKeyScope if scope in wanted]


def _expiry_in_range(value: datetime) -> datetime:
    try:
        utc = value.astimezone(UTC)
    except OverflowError:  # e.g. 0001-01-01T00:00+05:00
        raise ValueError("the expiry date is out of range") from None
    now = datetime.now(UTC)
    if not now + API_KEY_MIN_LIFETIME <= utc <= now + API_KEY_MAX_LIFETIME:
        raise ValueError("the expiry must be at least an hour and at most a year ahead")
    return value


ApiKeyExpiry = Annotated[AwareDatetime, AfterValidator(_expiry_in_range)]
"""A new key's expiry: with an offset, at least an hour and at most 366 days ahead."""

ApiKeyName = Annotated[str, Field(min_length=1, max_length=API_KEY_NAME_MAX_LENGTH), SingleLine]


# --- Responses -----------------------------------------------------------------------
class ApiKey(ResponseModel):
    """One of your keys (Settings -> API keys). Never carries the secret."""

    id: UUID
    name: str
    prefix: str = Field(
        description=(
            'The start of the key, "sdg_" and its 12-character lookup id, so you can '
            "recognise it; the rest is never shown again."
        )
    )
    scopes: list[ApiKeyScope] = Field(
        description="Canonical order: read, write, evaluate, mcp (write and evaluate include read)."
    )
    restricted: bool = Field(
        description="Only the projects below (true), or every project you can access."
    )
    projects: list[ProjectRef] = Field(
        description=(
            "The projects it is restricted to that still exist and you can still view, by "
            "name. Empty when not restricted (or when you can view none of them: then the "
            "key reaches nothing)."
        )
    )
    expires_at: datetime | None = Field(description="Null: never expires.")
    state: ApiKeyState
    created_at: datetime
    last_used_at: datetime | None = Field(
        description="Last successful authentication (updated at most once a minute)."
    )


class ApiKeyList(ResponseModel):
    """Your keys that aren't revoked, newest first (at most ``max_keys``: no paging)."""

    items: list[ApiKey]
    max_keys: int = Field(description="How many keys you may hold (25).")
    can_create: bool = Field(
        description=(
            "api_key.manage_own allows a new key now: you hold fewer than max_keys and are "
            "not the break-glass account (c20)."
        )
    )


class CreatedApiKey(ResponseModel):
    """The new key. ``secret`` is the only time the full key is ever returned
    (``Cache-Control: no-store``)."""

    key: ApiKey
    secret: str = Field(
        description=(
            "The full key (sdg_<lookup id>_<secret>). Copy it now: it can't be shown again. "
            "Send it as Authorization: Bearer <key>."
        )
    )


class AdminApiKey(ApiKey):
    """A key in Admin settings -> API keys, with its owner. ``projects`` lists every
    restricted project that still exists."""

    owner: UserRef
    owner_email: str
    owner_is_service_account: bool = Field(
        description="An AI agent's service account (Phase 6): show the AI badge."
    )
    created_by: UserRef | None = Field(
        description=(
            "Who created it: the owner, or the platform admin who registered the agent "
            "(Phase 6); null if that user no longer exists."
        )
    )


class AdminApiKeyPage(Page[AdminApiKey]):
    """Keys that aren't revoked, of every user, newest first."""

    total: int = Field(description="Keys matching the filters, all pages.")


# --- Requests ------------------------------------------------------------------------
class ApiKeyCreate(RequestModel):
    """Create a key for yourself (session only). Scopes and the project restriction
    can't be changed later: create another key and revoke this one."""

    name: ApiKeyName = Field(
        description=(
            'What it is for, e.g. "Claude Desktop" or "Weekly report script": unique among '
            "your keys (any case) that aren't revoked."
        )
    )
    scopes: list[ApiKeyScope] = Field(
        min_length=1,
        max_length=4,
        description=(
            "read: view projects, ideas, evaluations, scores and proposals (as you can). "
            "write: create and change ideas, comments, votes, owners, evaluators, statuses, "
            "proposals (deleting and moderating ideas need a session); includes read. "
            "evaluate: save and submit your own evaluations; includes read. mcp: connect an "
            "MCP client to /mcp (its tools also need read, write or evaluate). Duplicates "
            "are merged and read is added to write and evaluate."
        ),
    )
    expires_at: ApiKeyExpiry | None = Field(
        default=None,
        description="When it stops working: 1 hour to 366 days ahead, or null for never.",
    )
    project_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_KEY_PROJECTS,
        description=(
            "Restrict the key to these projects (1-50, each one you can view: else 422 "
            "invalid_project); null for every project you can access, now and later."
        ),
    )

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, scopes: list[ApiKeyScope]) -> list[ApiKeyScope]:
        return canonical_scopes(scopes)

    @field_validator("project_ids")
    @classmethod
    def _projects(cls, project_ids: list[UUID] | None) -> list[UUID] | None:
        return None if project_ids is None else list(dict.fromkeys(project_ids))
