"""Sign-in state and the development login stub. Phase 2 adds OIDC routes here."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.auth import CurrentUser, DevLoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])

_DEV_ONLY = (
    " Development only: 404 unless SOUNDINGS_DEV_LOGIN_ENABLED=true (always refused in production)."
)


@router.get(
    "/me",
    operation_id="get_me",
    summary="Who am I",
    description="The signed-in user. 401 when not signed in: show the sign-in page.",
    responses=problems(401),
)
async def get_me(principal: PrincipalDep) -> CurrentUser:
    raise NotImplementedProblem


@router.get(
    "/dev/users",
    operation_id="list_dev_users",
    summary="List users for the dev login picker",
    description="Active users, platform admins first, then by name." + _DEV_ONLY,
    responses=problems(404),
)
async def list_dev_users() -> list[CurrentUser]:
    raise NotImplementedProblem


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
async def dev_login(body: DevLoginRequest) -> CurrentUser:
    raise NotImplementedProblem


@router.post(
    "/logout",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description="Ends the session (if any) and clears the session cookies. Always 204.",
)
async def logout() -> None:
    raise NotImplementedProblem
