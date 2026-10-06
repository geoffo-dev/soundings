"""Checking a presented API key (contract-phase5 section 3.2, steps 2-4 and 6) and the
throttled ``last_used_at`` update (step 8).

:func:`check_api_key` is pure authentication: format (no query for a malformed
token), one lookup by ``lookup_id`` with the owner, a constant-time hash compare, then
whether the key is usable now. It reads the row on every call (no cache), so a revoke
or an expiry applies to the very next request. Throttles, logging and the HTTP answer
are the caller's (:mod:`app.auth.key_auth`).

:func:`verify_api_key` runs that check and the ``last_used_at`` update in one short
transaction of its own, committed and closed before it returns, so a request never
holds two database connections at once (one of its unit of work and one for the key):
under parallel use that exhausted the pool. :func:`reload_api_key` then rebuilds the
principal from the key's id inside the caller's unit of work (the request's session,
or an MCP tool's transaction), so what runs uses the key and its owner as they are in
that transaction: a key revoked or an owner deactivated since the check is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select

from app.api_keys.state import RefusalReason, refusal_reason
from app.api_keys.tokens import hash_key, hashes_match, lookup_id_of
from app.config import Settings
from app.domain.principal import ApiKeyScope, Principal
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.user import User
from app.schemas.api_keys import LAST_USED_THROTTLE

__all__ = [
    "KeyCheck",
    "check_api_key",
    "key_principal",
    "reload_api_key",
    "touch_last_used",
    "verify_api_key",
]


@dataclass(frozen=True, slots=True)
class KeyCheck:
    """The outcome: a ``principal`` (accepted) or a ``refusal`` (``key_id`` when the
    lookup id matched a key, for the log)."""

    principal: Principal | None = None
    refusal: RefusalReason | None = None
    key_id: UUID | None = None
    last_used_at: datetime | None = None


def key_principal(key: ApiKey, owner: User) -> Principal:
    """The key's owner, live, narrowed by the key (section 3.2 step 6). An empty
    restriction stays "no project" (never ``or None``)."""
    return Principal(
        user=owner,
        auth="api_key",
        scopes=frozenset(cast(ApiKeyScope, scope) for scope in key.scopes),
        project_ids=None if key.project_ids is None else frozenset(key.project_ids),
        api_key_id=key.id,
        auth_method=None,
    )


def _with_owner() -> Select[ApiKey, User]:
    return select(ApiKey, User).join(User, User.id == ApiKey.user_id)


def _decide(key: ApiKey, owner: User, *, settings: Settings, now: datetime) -> KeyCheck:
    reason = refusal_reason(key, owner, settings=settings, now=now)
    if reason is not None:
        return KeyCheck(refusal=reason, key_id=key.id)
    return KeyCheck(
        principal=key_principal(key, owner), key_id=key.id, last_used_at=key.last_used_at
    )


async def check_api_key(
    db: AsyncSession, token: str, *, settings: Settings, now: datetime | None = None
) -> KeyCheck:
    """Authenticate ``token`` (the bearer value): see the module docstring."""
    lookup_id = lookup_id_of(token)
    if lookup_id is None:
        return KeyCheck(refusal="malformed")
    found = (await db.execute(_with_owner().where(ApiKey.lookup_id == lookup_id))).first()
    if found is None:
        return KeyCheck(refusal="unknown")
    key, owner = found
    if not hashes_match(hash_key(token), key.secret_hash):
        return KeyCheck(refusal="mismatch", key_id=key.id)
    return _decide(key, owner, settings=settings, now=now or utcnow())


async def reload_api_key(
    db: AsyncSession, key_id: UUID, *, settings: Settings, now: datetime | None = None
) -> KeyCheck:
    """The key (already authenticated by its secret) and its owner read again in
    ``db``: the principal for work done in ``db``, or the refusal (revoked, expired,
    owner deactivated... since the check). One query by primary key."""
    found = (await db.execute(_with_owner().where(ApiKey.id == key_id))).first()
    if found is None:
        return KeyCheck(refusal="unknown", key_id=key_id)
    key, owner = found
    return _decide(key, owner, settings=settings, now=now or utcnow())


def _touch_due(check: KeyCheck, now: datetime) -> bool:
    if check.key_id is None or check.principal is None:
        return False
    return check.last_used_at is None or now - check.last_used_at >= LAST_USED_THROTTLE


async def touch_last_used(
    db: AsyncSession, check: KeyCheck, *, now: datetime | None = None
) -> None:
    """Move ``last_used_at`` of an accepted key when it is null or at least
    :data:`LAST_USED_THROTTLE` old, in ``db`` (the caller commits at once: the key row
    must never stay locked for a whole request, or a revoke would wait behind a slow
    one). Conditional, so concurrent requests write it once; a revoked key isn't
    touched."""
    now = now or utcnow()
    if not _touch_due(check, now):
        return
    await db.execute(
        update(ApiKey)
        .where(
            ApiKey.id == check.key_id,
            ApiKey.revoked_at.is_(None),
            or_(
                ApiKey.last_used_at.is_(None),
                ApiKey.last_used_at <= now - LAST_USED_THROTTLE,
            ),
        )
        .values(last_used_at=now)
        .execution_options(synchronize_session=False)
    )


async def verify_api_key(
    sessionmaker: async_sessionmaker[AsyncSession],
    token: str,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> KeyCheck:
    """:func:`check_api_key` and, for an accepted key, :func:`touch_last_used`, in one
    short transaction of its own on one connection, committed and returned to the pool
    before this returns. Call it while holding no other connection (a request's session
    that hasn't run a query yet holds none)."""
    if lookup_id_of(token) is None:
        return KeyCheck(refusal="malformed")  # no session, no query
    now = now or utcnow()
    async with sessionmaker() as db:
        check = await check_api_key(db, token, settings=settings, now=now)
        await touch_last_used(db, check, now=now)
        await db.commit()
    return check
