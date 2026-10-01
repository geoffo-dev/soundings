"""Who is signed in, the development login stub and sign-out (204).

SSO, break-glass and sign-out with the IdP are in :mod:`app.api.v1.auth_sso`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.auth.sign_in import current_user, end_current_session, sign_in
from app.config import Settings
from app.db import SessionDep
from app.errors import NotFoundProblem, ProblemError
from app.models.enums import AuthMethod
from app.schemas.auth import CurrentUser, DevLoginRequest
from app.services import users

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
    description=(
        "The signed-in user and how the session was started (auth_method). 401 when "
        "not signed in: show the sign-in page."
    ),
    responses=problems(401),
)
async def get_me(principal: PrincipalDep) -> CurrentUser:
    return current_user(principal.user, principal.auth_method)


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
        "Starts a session for the user: sets the session (HttpOnly) and CSRF cookies "
        "(soundings_session and soundings_csrf; __Host- prefixed when Secure)." + _DEV_ONLY
    ),
    responses=problems(404, 422),
)
async def dev_login(
    body: DevLoginRequest, request: Request, response: Response, session: SessionDep
) -> CurrentUser:
    _require_dev_login(_settings(request))
    user = await users.active_user(session, body.user_id)
    if user is None or user.is_break_glass:
        raise ProblemError(422, "user_not_found", detail="No active user with that id.")
    await sign_in(session, request, response, user, method=AuthMethod.DEV_LOGIN)
    return current_user(user, AuthMethod.DEV_LOGIN)


@router.post(
    "/logout",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description=(
        "Ends the session (if any) and clears the session cookies. Always 204. Signs "
        "out of Soundings only; the SPA's Sign out uses POST /auth/logout/redirect."
    ),
)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    # No CSRF check: the worst a forged request can do is sign you out, and the
    # SameSite=Lax cookie is not sent on cross-site POSTs anyway.
    await end_current_session(session, request, response)
