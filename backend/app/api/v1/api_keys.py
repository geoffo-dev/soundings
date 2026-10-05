"""Your API keys: Settings -> API keys (SPEC section 8; contract-phase5 sections 2 and
3.1-3.2).

Rule ``api_key.manage_own``: every signed-in person, **session only** (a request
authenticated by an API key gets 403 ``insufficient_scope``), not the break-glass
account (c20). Creating returns the full key once; afterwards only its prefix is shown.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.api_keys import service
from app.db import SessionDep
from app.schemas.api_keys import ApiKeyCreate, ApiKeyList, CreatedApiKey

router = APIRouter(prefix="/me/api-keys", tags=["api-keys"])

KeyId = Annotated[UUID, Path(description="An API key's id.")]

_RULE = "api_key.manage_own (session only; an API key gets 403 insufficient_scope). "


@router.get(
    "",
    operation_id="list_my_api_keys",
    summary="List my API keys",
    description=(
        _RULE + "Your keys that aren't revoked (active and expired), newest first, with "
        "whether you may create another. Never returns a secret."
    ),
    responses=problems(401, 403),
)
async def list_my_api_keys(principal: PrincipalDep, session: SessionDep) -> ApiKeyList:
    return await service.list_my_keys(session, principal)


@router.post(
    "",
    operation_id="create_my_api_key",
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description=(
        _RULE + "Returns the full key once, in secret (Cache-Control: no-store); only its "
        "hash is stored. write and evaluate include read (added). 403 break_glass_account "
        "(c20); 409 too_many_api_keys (25 that aren't revoked), api_key_name_taken; 422 "
        "invalid_project (a project you can't view, or unknown). Audited as api_key.create."
    ),
    responses=problems(401, 403, 409, 422),
)
async def create_my_api_key(
    principal: PrincipalDep, session: SessionDep, body: ApiKeyCreate, response: Response
) -> CreatedApiKey:
    response.headers["Cache-Control"] = "no-store"
    return await service.create_my_key(session, principal, body)


@router.delete(
    "/{key_id}",
    operation_id="revoke_my_api_key",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description=(
        _RULE + "The key stops working at once: the next request with it is 401, on REST "
        "and /mcp alike. Idempotent for a key already revoked; 404 for someone else's or "
        "an unknown key. Audited as api_key.revoke."
    ),
    responses=problems(401, 403, 404),
)
async def revoke_my_api_key(principal: PrincipalDep, session: SessionDep, key_id: KeyId) -> None:
    await service.revoke_my_key(session, principal, key_id)
