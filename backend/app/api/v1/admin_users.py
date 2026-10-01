"""Admin settings -> Users (rule ``platform.manage_users``; session only).

Pre-create users with external IDs, edit and deactivate them, see where their access
comes from, unlink an SSO identity, sign them out everywhere. Business rules:
docs/api/contract-phase2.md section 3.4.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.authz import Rule, require
from app.config import Settings
from app.db import SessionDep
from app.pagination import PageParamsDep
from app.schemas.admin_users import (
    AdminUser,
    AdminUserCreate,
    AdminUserPage,
    AdminUserUpdate,
    ExternalIdsReplace,
)
from app.schemas.base import NoNul
from app.services import admin_users

router = APIRouter(prefix="/admin/users", tags=["admin"])

_ADMIN = "Platform admins (platform.manage_users). "
_RULE = Rule.PLATFORM_MANAGE_USERS


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get(
    "",
    operation_id="list_admin_users",
    summary="List users",
    description=(
        _ADMIN + "Every account (people, service accounts, the break-glass admin), by "
        "display name. q matches name or email (case-insensitive); the filters combine."
    ),
    responses=problems(400, 401, 403),
)
async def list_admin_users(
    principal: PrincipalDep,
    session: SessionDep,
    page: PageParamsDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Part of a name or email."), NoNul
    ] = None,
    active: Annotated[bool | None, Query(description="Only active (or deactivated) users.")] = None,
    platform_admin: Annotated[
        bool | None, Query(description="Only platform admins (or only non-admins).")
    ] = None,
    has_identity: Annotated[
        bool | None,
        Query(description="false: users never linked to SSO (e.g. pre-created, not signed in)."),
    ] = None,
) -> AdminUserPage:
    require(principal, _RULE)
    return await admin_users.list_users(
        session,
        q=q,
        active=active,
        platform_admin=platform_admin,
        has_identity=has_identity,
        page=page,
    )


@router.post(
    "",
    operation_id="create_admin_user",
    status_code=status.HTTP_201_CREATED,
    summary="Pre-create a user",
    description=(
        _ADMIN + "An active user without an SSO identity; their first SSO sign-in links "
        "them by external ID or verified email. 409 email_taken, external_id_taken."
    ),
    responses=problems(401, 403, 409, 422),
)
async def create_admin_user(
    request: Request, principal: PrincipalDep, session: SessionDep, body: AdminUserCreate
) -> AdminUser:
    require(principal, _RULE)
    user = await admin_users.create_user(session, principal, body)
    return await admin_users.user_detail(session, user, _settings(request))


@router.get(
    "/{user_id}",
    operation_id="get_admin_user",
    summary="Get a user",
    description=(
        _ADMIN + "Identities, external IDs, groups with provenance, and every project "
        "role with its sources (direct or group)."
    ),
    responses=problems(401, 403, 404),
)
async def get_admin_user(
    request: Request, principal: PrincipalDep, session: SessionDep, user_id: UUID
) -> AdminUser:
    require(principal, _RULE)
    user = await admin_users.get_user(session, user_id)
    return await admin_users.user_detail(session, user, _settings(request))


@router.patch(
    "/{user_id}",
    operation_id="update_admin_user",
    summary="Update a user",
    description=(
        _ADMIN + "Name, email, active, platform admin. Deactivating ends their sessions. "
        "403 cannot_change_self (your own active / platform admin flags); 409 "
        "email_taken; 409 system_account (service or break-glass account: only "
        "display_name and is_active change); 409 last_platform_admin (no other active "
        "platform admin would remain)."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_admin_user(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    user_id: UUID,
    body: AdminUserUpdate,
) -> AdminUser:
    require(principal, _RULE)
    user = await admin_users.get_user(session, user_id)
    await admin_users.update_user(session, principal, user, body)
    return await admin_users.user_detail(session, user, _settings(request))


@router.put(
    "/{user_id}/external-ids",
    operation_id="replace_user_external_ids",
    summary="Replace a user's external IDs",
    description=(
        _ADMIN + "The complete set, one per kind. 409 external_id_taken (another user "
        "has that kind and value); 409 system_account."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def replace_user_external_ids(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    user_id: UUID,
    body: ExternalIdsReplace,
) -> AdminUser:
    require(principal, _RULE)
    user = await admin_users.get_user(session, user_id)
    await admin_users.replace_external_ids(session, principal, user, body)
    return await admin_users.user_detail(session, user, _settings(request))


@router.delete(
    "/{user_id}/identities/{identity_id}",
    operation_id="unlink_user_identity",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink an SSO identity",
    description=(
        _ADMIN + "The user is matched again (external ID, verified email) at their next "
        "SSO sign-in, e.g. after their IdP account was recreated. Their SSO sessions "
        "end too."
    ),
    responses=problems(401, 403, 404),
)
async def unlink_user_identity(
    principal: PrincipalDep, session: SessionDep, user_id: UUID, identity_id: UUID
) -> None:
    require(principal, _RULE)
    user = await admin_users.get_user(session, user_id)
    await admin_users.unlink_identity(session, principal, user, identity_id)


@router.delete(
    "/{user_id}/sessions",
    operation_id="end_user_sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign a user out everywhere",
    description=(
        _ADMIN + "Ends all their sessions (yours too, if it is you); group changes then "
        "apply at their next sign-in. Idempotent."
    ),
    responses=problems(401, 403, 404),
)
async def end_user_sessions(principal: PrincipalDep, session: SessionDep, user_id: UUID) -> None:
    require(principal, _RULE)
    user = await admin_users.get_user(session, user_id)
    await admin_users.end_sessions(session, principal, user)
