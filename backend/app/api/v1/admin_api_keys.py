"""Admin settings -> API keys: every user's keys, service accounts' included (SPEC
section 8; contract-phase5 sections 2 and 3.3).

Rule ``api_key.manage_any``: platform admins, session only. Admin order of checks as in
Phase 2: 401 -> 422 shape -> 403 ``forbidden`` (not a platform admin) -> 404.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.api_keys import service
from app.db import SessionDep
from app.pagination import PageParamsDep
from app.schemas.api_keys import AdminApiKeyPage, ApiKeyState
from app.schemas.base import NoNul

router = APIRouter(prefix="/admin/api-keys", tags=["admin"])

KeyId = Annotated[UUID, Path(description="An API key's id.")]

_ADMIN = "Platform admins (api_key.manage_any, session only). "


@router.get(
    "",
    operation_id="list_admin_api_keys",
    summary="List every API key",
    description=(
        _ADMIN + "Keys that aren't revoked, of every user (service accounts included), "
        "newest first, with their owner and when they were last used. q matches part of "
        "the key's name or its owner's name or email (any case), or exactly a key's prefix "
        "(sdg_ + lookup id) or lookup id, so a leaked key can be found; the filters combine."
    ),
    responses=problems(400, 401, 403),
)
async def list_admin_api_keys(
    principal: PrincipalDep,
    session: SessionDep,
    page: PageParamsDep,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description=(
                "Part of a key name, owner name or email, or a key's prefix (sdg_ + lookup "
                "id) or lookup id, matched exactly. Never send a whole key: the SPA cuts a "
                "pasted key to its prefix."
            ),
        ),
        NoNul,
    ] = None,
    user_id: Annotated[UUID | None, Query(description="Only this user's keys.")] = None,
    state: Annotated[
        ApiKeyState | None, Query(description="Only active, expired or dormant keys.")
    ] = None,
) -> AdminApiKeyPage:
    return await service.list_admin_keys(
        session, principal, q=q, user_id=user_id, state=state, page=page
    )


@router.delete(
    "/{key_id}",
    operation_id="revoke_admin_api_key",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke any API key",
    description=(
        _ADMIN + "The key stops working at once. Idempotent for a key already revoked; 404 "
        "for an unknown key. Audited as api_key.revoke (target: the key's owner)."
    ),
    responses=problems(401, 403, 404),
)
async def revoke_admin_api_key(principal: PrincipalDep, session: SessionDep, key_id: KeyId) -> None:
    await service.revoke_admin_key(session, principal, key_id)
