"""Sign-in state and the development login stub. Phase 2 adds OIDC routes here."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.auth.cookies import SESSION_COOKIE, clear_session_cookies, set_session_cookies
from app.config import Settings
from app.db import SessionDep
from app.errors import NotFoundProblem, ProblemError
from app.schemas.auth import CurrentUser, DevLoginRequest
from app.services import audit, sessions, users

router = APIRouter(prefix="/auth", tags=["auth"])

_DEV_ONLY = (
    " Development only: 404 unless SOUNDINGS_DEV_LOGIN_ENABLED=true (always refused in production)."
)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _require_dev_login(settings: Settings) -> None:
    if not settings.dev_login_enabled:
        raise NotFoundProblem


@router.get(
    "/me",
    operation_id="get_me",
    summary="Who am I",
    description="The signed-in user. 401 when not signed in: show the sign-in page.",
    responses=problems(401),
)
async def get_me(principal: PrincipalDep) -> CurrentUser:
    return CurrentUser.model_validate(principal.user)


@router.get(
    "/dev/users",
    operation_id="list_dev_users",
    summary="List users for the dev login picker",
    description="Active users, platform admins first, then by name." + _DEV_ONLY,
    responses=problems(404),
)
async def list_dev_users(request: Request, session: SessionDep) -> list[CurrentUser]:
    _require_dev_login(_settings(request))
    return await users.list_dev_users(session)


@router.post(
    "/dev/login",
    operation_id="dev_login",
    summary="Sign in as a user without a password",
    description=(
        "Starts a session for the user: sets the soundings_session (HttpOnly) and "
        "soundings_csrf cookies." + _DEV_ONLY
    ),
    responses=problems(404, 422),
)
async def dev_login(
    body: DevLoginRequest, request: Request, response: Response, session: SessionDep
) -> CurrentUser:
    settings = _settings(request)
    _require_dev_login(settings)
    user = await users.active_user(session, body.user_id)
    if user is None:
        raise ProblemError(422, "user_not_found", detail="No active user with that id.")
    started = await sessions.start_session(
        session,
        user,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
        replacing_token=request.cookies.get(SESSION_COOKIE),
    )
    await audit.record(
        session,
        "session.sign_in",
        actor=user.id,
        target_type="user",
        target_id=user.id,
        details={"method": "dev_login", "session_id": started.row.id},
    )
    set_session_cookies(
        response, request, settings, token=started.token, csrf_token=started.csrf_token
    )
    return CurrentUser.model_validate(user)


@router.post(
    "/logout",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description="Ends the session (if any) and clears the session cookies. Always 204.",
)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    # No CSRF check: the worst a forged request can do is sign you out, and the
    # SameSite=Lax cookie is not sent on cross-site POSTs anyway.
    token = request.cookies.get(SESSION_COOKIE)
    ended = await sessions.end_session(session, token) if token else None
    if ended is not None:
        await audit.record(
            session,
            "session.sign_out",
            actor=ended.user_id,
            target_type="user",
            target_id=ended.user_id,
            details={"session_id": ended.id},
        )
    clear_session_cookies(response, request, _settings(request))
