"""Server-side sessions (ADR 0005, contract-phase2 section 3.9): start, resolve, keep
alive, end.

The cookie holds a random token; the ``user_sessions`` row stores only its SHA-256.
A session ends after ``session_idle_timeout`` without requests (sliding) or
``session_max_age`` after sign-in (absolute), whichever comes first. ``last_seen_at``
(session and user) is written at most once per :data:`LAST_SEEN_THROTTLE`, so busy
clients don't turn every read into a write, and by :func:`touch_session` in a short
transaction of its own after the response (``app.middleware.SessionTouchMiddleware``;
performance review B8): inside the request's transaction, a screen's parallel requests
queued on the user's row lock until each of them committed.

Every sign-in method (SSO, break-glass, dev login) calls :func:`start_session`, which
records the method. A session works only while its method is available
(:func:`method_available`): SSO sessions need SSO configured, break-glass sessions
need break-glass available (so configuring SSO ends them), dev-login sessions need the
dev login on. Break-glass sessions are also short: at most :data:`BREAK_GLASS_MAX_AGE`,
and :data:`BREAK_GLASS_IDLE_TIMEOUT` without a request (the shorter of these and the
settings applies).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.sealing import seal, unseal
from app.auth.tokens import hash_token, new_token
from app.auth.user_agent import summarise_user_agent
from app.config import Settings
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.models.user import User, UserSession

__all__ = [
    "BREAK_GLASS_IDLE_TIMEOUT",
    "BREAK_GLASS_MAX_AGE",
    "ID_TOKEN_MAX_LENGTH",
    "LAST_SEEN_THROTTLE",
    "NewSession",
    "delete_expired_sessions",
    "end_session",
    "end_user_sessions",
    "id_token_hint",
    "method_available",
    "needs_touch",
    "resolve_session",
    "session_limits",
    "start_session",
    "touch_session",
]

LAST_SEEN_THROTTLE: Final = timedelta(minutes=1)

BREAK_GLASS_MAX_AGE: Final = timedelta(hours=8)
BREAK_GLASS_IDLE_TIMEOUT: Final = timedelta(hours=1)

ID_TOKEN_MAX_LENGTH: Final = 3072
"""A larger ID token isn't stored: as ``id_token_hint`` in the sign-out redirect it
would push the ``Location`` header past common proxy limits (section 3.9)."""


@dataclass(frozen=True, slots=True)
class NewSession:
    """A started session: the token and CSRF token go into cookies, never the logs."""

    row: UserSession
    token: str
    csrf_token: str
    max_age: timedelta
    """How long the cookies should live (the session's absolute limit)."""


def method_available(settings: Settings, method: AuthMethod | str) -> bool:
    """The sign-in method is configured now (its sessions work only while it is)."""
    match AuthMethod(method):
        case AuthMethod.SSO:
            return settings.sso_configured
        case AuthMethod.BREAK_GLASS:
            return settings.break_glass_available
        case AuthMethod.DEV_LOGIN:
            return settings.dev_login_enabled


def session_limits(settings: Settings, method: AuthMethod | str) -> tuple[timedelta, timedelta]:
    """``(max_age, idle_timeout)`` for a session of ``method``."""
    if AuthMethod(method) is AuthMethod.BREAK_GLASS:
        return (
            min(settings.session_max_age, BREAK_GLASS_MAX_AGE),
            min(settings.session_idle_timeout, BREAK_GLASS_IDLE_TIMEOUT),
        )
    return settings.session_max_age, settings.session_idle_timeout


async def start_session(
    db: AsyncSession,
    user: User,
    *,
    settings: Settings,
    auth_method: AuthMethod,
    id_token: str | None = None,
    user_agent: str | None = None,
    replacing_token: str | None = None,
) -> NewSession:
    """Sign ``user`` in with a fresh session started by ``auth_method``.

    The session id always rotates at sign-in: ``replacing_token`` (the cookie the
    browser already had, whoever it belonged to) is ended first. The user's expired
    sessions are removed while we're here. ``id_token`` (SSO only) is kept, solely as
    the sign-out ``id_token_hint``, when at most :data:`ID_TOKEN_MAX_LENGTH` long, and
    sealed with the secret key: the database alone doesn't reveal its claims.
    """
    now = utcnow()
    if replacing_token:
        await end_session(db, replacing_token)
    await db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id,
            or_(
                UserSession.expires_at <= now,
                UserSession.last_seen_at <= now - settings.session_idle_timeout,
            ),
        )
    )
    max_age, _ = session_limits(settings, auth_method)
    sealed_id_token = None
    if auth_method is AuthMethod.SSO and id_token and len(id_token) <= ID_TOKEN_MAX_LENGTH:
        sealed_id_token = seal(settings, "session-id-token", id_token.encode("utf-8"))
    token, csrf_token = new_token(), new_token()
    row = UserSession(
        id=uuid4(),
        token_hash=hash_token(token),
        user_id=user.id,
        csrf_token=csrf_token,
        auth_method=auth_method,
        id_token=sealed_id_token,
        created_at=now,
        last_seen_at=now,
        expires_at=now + max_age,
        user_agent=summarise_user_agent(user_agent),
    )
    db.add(row)
    user.last_seen_at = now
    await db.flush()
    return NewSession(row=row, token=token, csrf_token=csrf_token, max_age=max_age)


def id_token_hint(settings: Settings, row: UserSession) -> str | None:
    """The ID token a session keeps for sign-out, or ``None`` (none kept, or sealed
    under another secret key)."""
    if not row.id_token:
        return None
    raw = unseal(settings, "session-id-token", row.id_token)
    return raw.decode("utf-8") if raw is not None else None


def _expired(row: UserSession, settings: Settings, now: datetime) -> bool:
    max_age, idle_timeout = session_limits(settings, row.auth_method)
    return (
        now >= row.expires_at
        or now >= row.created_at + max_age
        or now >= row.last_seen_at + idle_timeout
    )


async def resolve_session(
    db: AsyncSession,
    token: str,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[UserSession, User] | None:
    """The live session for a cookie token and its (active) user, or ``None``.

    ``None`` too when the session's sign-in method is no longer available. Reads only:
    keeping a live session alive is :func:`touch_session`'s, after the response, when
    :func:`needs_touch` (and the request counts as activity: the bell's poll doesn't,
    contract-phase3 section 3.2).
    """
    now = now or utcnow()
    found = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token))
        )
    ).first()
    if found is None:
        return None
    row, user = found
    if (
        _expired(row, settings, now)
        or not method_available(settings, row.auth_method)
        or not user.is_active
        or user.is_service_account
    ):
        return None
    return row, user


def needs_touch(row: UserSession, now: datetime) -> bool:
    """The session was last seen :data:`LAST_SEEN_THROTTLE` ago or more."""
    return now - row.last_seen_at >= LAST_SEEN_THROTTLE


async def touch_session(
    sessionmaker: async_sessionmaker[AsyncSession],
    session_id: UUID,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> bool:
    """Keep a session alive: ``last_seen_at`` of the session and its user moves to
    ``now`` in one short transaction of its own, guarded by the throttle in SQL, so of a
    screen's parallel requests one writes and the rest find nothing to do. Returns
    whether the session moved. Call it holding no other connection (after the request's
    session is closed: :class:`app.middleware.SessionTouchMiddleware`)."""
    now = now or utcnow()
    async with sessionmaker() as db:
        moved = await db.execute(
            update(UserSession)
            .where(
                UserSession.id == session_id, UserSession.last_seen_at <= now - LAST_SEEN_THROTTLE
            )
            .values(last_seen_at=now)
        )
        if not getattr(moved, "rowcount", 0):
            await db.rollback()
            return False
        await db.execute(
            update(User)
            .where(
                User.id == user_id,
                or_(User.last_seen_at.is_(None), User.last_seen_at < now),  # never back
            )
            .values(last_seen_at=now)
        )
        await db.commit()
    return True


async def delete_expired_sessions(db: AsyncSession, settings: Settings, now: datetime) -> int:
    """Delete sessions past their absolute limit or idle timeout (security review P7
    L5: until then a leaver's rows, with their user-agent summary, stayed until that
    person signed in again). The hourly schedule calls it; returns how many."""
    result = await db.execute(
        delete(UserSession).where(
            or_(
                UserSession.expires_at <= now,
                UserSession.last_seen_at <= now - settings.session_idle_timeout,
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def end_session(db: AsyncSession, token: str) -> UserSession | None:
    """Delete the session for this token; returns the deleted row (``None`` if none)."""
    row = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is not None:
        await db.delete(row)
        await db.flush()
    return row


async def end_user_sessions(
    db: AsyncSession, user_id: UUID, *, auth_method: AuthMethod | None = None
) -> int:
    """Sign a user out everywhere (deactivation, ``end_user_sessions``), or only their
    sessions of one method (``auth_method=SSO`` when an identity is unlinked).
    Returns how many sessions ended."""
    statement = delete(UserSession).where(UserSession.user_id == user_id)
    if auth_method is not None:
        statement = statement.where(UserSession.auth_method == auth_method)
    result = await db.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)
