"""Server-side sessions (ADR 0005): start, resolve, keep alive, end.

The cookie holds a random token; the ``user_sessions`` row stores only its SHA-256.
A session ends after ``session_idle_timeout`` without requests (sliding) or
``session_max_age`` after sign-in (absolute), whichever comes first. ``last_seen_at``
(session and user) is written at most once per :data:`LAST_SEEN_THROTTLE`, so busy
clients don't turn every read into a write.

Sign-in methods (dev login now, OIDC in Phase 2, break-glass) all call
:func:`start_session`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_token, new_token
from app.auth.user_agent import summarise_user_agent
from app.config import Settings
from app.models.base import utcnow
from app.models.user import User, UserSession

__all__ = [
    "LAST_SEEN_THROTTLE",
    "NewSession",
    "end_session",
    "end_user_sessions",
    "resolve_session",
    "start_session",
]

LAST_SEEN_THROTTLE = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class NewSession:
    """A started session: the token and CSRF token go into cookies, never the logs."""

    row: UserSession
    token: str
    csrf_token: str


async def start_session(
    db: AsyncSession,
    user: User,
    *,
    settings: Settings,
    user_agent: str | None = None,
    replacing_token: str | None = None,
) -> NewSession:
    """Sign ``user`` in with a fresh session.

    The session id always rotates at sign-in: ``replacing_token`` (the cookie the
    browser already had, whoever it belonged to) is ended first. The user's expired
    sessions are removed while we're here.
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
    token, csrf_token = new_token(), new_token()
    row = UserSession(
        id=uuid4(),
        token_hash=hash_token(token),
        user_id=user.id,
        csrf_token=csrf_token,
        created_at=now,
        last_seen_at=now,
        expires_at=now + settings.session_max_age,
        user_agent=summarise_user_agent(user_agent),
    )
    db.add(row)
    user.last_seen_at = now
    await db.flush()
    return NewSession(row=row, token=token, csrf_token=csrf_token)


def _expired(row: UserSession, settings: Settings, now: datetime) -> bool:
    return now >= row.expires_at or now >= row.last_seen_at + settings.session_idle_timeout


async def resolve_session(
    db: AsyncSession, token: str, *, settings: Settings, now: datetime | None = None
) -> tuple[UserSession, User] | None:
    """The live session for a cookie token and its (active) user, or ``None``.

    A live session is kept alive: ``last_seen_at`` moves forward (throttled).
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
    if _expired(row, settings, now) or not user.is_active or user.is_service_account:
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


async def end_user_sessions(db: AsyncSession, user_id: UUID) -> int:
    """Sign a user out everywhere (deactivation, Phase 2 admin action)."""
    result = await db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    return int(getattr(result, "rowcount", 0) or 0)
