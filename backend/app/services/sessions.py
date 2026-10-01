"""Server-side sessions (ADR 0005, contract-phase2 section 3.9): start, resolve, keep
alive, end.

The cookie holds a random token; the ``user_sessions`` row stores only its SHA-256.
A session ends after ``session_idle_timeout`` without requests (sliding) or
``session_max_age`` after sign-in (absolute), whichever comes first. ``last_seen_at``
(session and user) is written at most once per :data:`LAST_SEEN_THROTTLE`, so busy
clients don't turn every read into a write.

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

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    "end_session",
    "end_user_sessions",
    "method_available",
    "resolve_session",
    "session_limits",
    "start_session",
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
    the sign-out ``id_token_hint``, when at most :data:`ID_TOKEN_MAX_LENGTH` long.
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
    keep_id_token = (
        auth_method is AuthMethod.SSO
        and id_token is not None
        and len(id_token) <= ID_TOKEN_MAX_LENGTH
    )
    token, csrf_token = new_token(), new_token()
    row = UserSession(
        id=uuid4(),
        token_hash=hash_token(token),
        user_id=user.id,
        csrf_token=csrf_token,
        auth_method=auth_method,
        id_token=id_token if keep_id_token else None,
        created_at=now,
        last_seen_at=now,
        expires_at=now + max_age,
        user_agent=summarise_user_agent(user_agent),
    )
    db.add(row)
    user.last_seen_at = now
    await db.flush()
    return NewSession(row=row, token=token, csrf_token=csrf_token, max_age=max_age)


def _expired(row: UserSession, settings: Settings, now: datetime) -> bool:
    max_age, idle_timeout = session_limits(settings, row.auth_method)
    return (
        now >= row.expires_at
        or now >= row.created_at + max_age
        or now >= row.last_seen_at + idle_timeout
    )


async def resolve_session(
    db: AsyncSession, token: str, *, settings: Settings, now: datetime | None = None
) -> tuple[UserSession, User] | None:
    """The live session for a cookie token and its (active) user, or ``None``.

    ``None`` too when the session's sign-in method is no longer available. A live
    session is kept alive: ``last_seen_at`` moves forward (throttled).
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
    if now - row.last_seen_at >= LAST_SEEN_THROTTLE:
        row.last_seen_at = now
        user.last_seen_at = now
    return row, user


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
