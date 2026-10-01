"""The last step of every sign-in method (SSO, break-glass, dev login) and sign-out:
start (rotate) the server-side session, audit it, set or clear the cookies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import (
    SESSION_COOKIE,
    clear_session_cookies,
    read_cookie,
    set_session_cookies,
)
from app.config import Settings
from app.models.enums import AuthMethod
from app.models.user import User, UserSession
from app.schemas.auth import CurrentUser
from app.services import audit, sessions

__all__ = ["current_user", "end_current_session", "sign_in"]


def current_user(user: User, auth_method: AuthMethod | None) -> CurrentUser:
    """``CurrentUser`` for a session of ``auth_method``."""
    return CurrentUser.model_validate(user).model_copy(update={"auth_method": auth_method})


async def sign_in(
    db: AsyncSession,
    request: Request,
    response: Response,
    user: User,
    *,
    method: AuthMethod,
    id_token: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> sessions.NewSession:
    """Start a session for ``user`` (rotating whatever session cookie the browser had),
    audit ``session.sign_in {method, session_id, auth_method, **details}`` and set the
    session cookies on ``response``."""
    settings: Settings = request.app.state.settings
    started = await sessions.start_session(
        db,
        user,
        settings=settings,
        auth_method=method,
        id_token=id_token,
        user_agent=request.headers.get("user-agent"),
        replacing_token=read_cookie(request, settings, SESSION_COOKIE),
    )
    await audit.record(
        db,
        "session.sign_in",
        actor=user.id,
        target_type="user",
        target_id=user.id,
        details={
            "method": method,
            "session_id": started.row.id,
            **(details or {}),
            "auth_method": method,
        },
    )
    set_session_cookies(
        response,
        request,
        settings,
        token=started.token,
        csrf_token=started.csrf_token,
        max_age=started.max_age,
    )
    return started


async def end_current_session(
    db: AsyncSession, request: Request, response: Response
) -> UserSession | None:
    """End the request's session, if any (audit ``session.sign_out``), and clear the
    cookies either way. Returns the ended session row."""
    settings: Settings = request.app.state.settings
    token = read_cookie(request, settings, SESSION_COOKIE)
    ended = await sessions.end_session(db, token) if token else None
    if ended is not None:
        await audit.record(
            db,
            "session.sign_out",
            actor=ended.user_id,
            target_type="user",
            target_id=ended.user_id,
            details={
                "session_id": ended.id,
                "method": ended.auth_method,
                "auth_method": ended.auth_method,
            },
        )
    clear_session_cookies(response, request, settings)
    return ended
