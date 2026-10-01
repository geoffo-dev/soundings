"""Admin settings -> Groups (rule ``platform.manage_groups``; session only).

Internal groups, their IdP mapping (managed or additive), manual members, and the
"test mapping" box. Business rules: docs/api/contract-phase2.md sections 3.5-3.7.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.pagination import PageParamsDep
from app.schemas.base import NoNul
from app.schemas.groups import (
    Group,
    GroupCreate,
    GroupMappingUpdate,
    GroupMember,
    GroupMemberAdd,
    GroupMemberPage,
    GroupPage,
    GroupUpdate,
    MappingTestRequest,
    MappingTestResult,
)

router = APIRouter(prefix="/admin/groups", tags=["admin"])

_ADMIN = "Platform admins (platform.manage_groups). "


@router.get(
    "",
    operation_id="list_admin_groups",
    summary="List groups",
    description=(
        _ADMIN + "Every group by name (case-insensitive), with mapping and counts. q "
        "matches the name."
    ),
    responses=problems(400, 401, 403),
)
async def list_admin_groups(
    principal: PrincipalDep,
    page: PageParamsDep,
    q: Annotated[str | None, Query(max_length=80, description="Part of a name."), NoNul] = None,
) -> GroupPage:
    raise NotImplementedProblem


@router.post(
    "",
    operation_id="create_group",
    status_code=status.HTTP_201_CREATED,
    summary="Create a group",
    description=_ADMIN + "Optionally mapped to IdP values right away. 409 group_name_taken.",
    responses=problems(401, 403, 409, 422),
)
async def create_group(principal: PrincipalDep, body: GroupCreate) -> Group:
    raise NotImplementedProblem


@router.post(
    "/test-mapping",
    operation_id="test_group_mapping",
    summary="Test the group mapping",
    description=(
        _ADMIN + "What a sign-in with these claims would do: the values extracted from "
        "the configured groups claim, the groups they match, the effect on each (for "
        "user_id's memberships, or a user with none) and the resulting project roles. "
        "Changes nothing; the claims are not stored or logged. 422 user_not_found."
    ),
    responses=problems(401, 403, 422),
)
async def test_group_mapping(
    principal: PrincipalDep, body: MappingTestRequest
) -> MappingTestResult:
    raise NotImplementedProblem


@router.get(
    "/{group_id}",
    operation_id="get_group",
    summary="Get a group",
    description=_ADMIN + "Mapping, counts by provenance and project grants (members: paged).",
    responses=problems(401, 403, 404),
)
async def get_group(principal: PrincipalDep, group_id: UUID) -> Group:
    raise NotImplementedProblem


@router.patch(
    "/{group_id}",
    operation_id="update_group",
    summary="Rename or describe a group",
    description=_ADMIN + "Omitted or null fields are unchanged. 409 group_name_taken.",
    responses=problems(401, 403, 404, 409, 422),
)
async def update_group(principal: PrincipalDep, group_id: UUID, body: GroupUpdate) -> Group:
    raise NotImplementedProblem


@router.delete(
    "/{group_id}",
    operation_id="delete_group",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a group",
    description=(
        _ADMIN + "Removes its memberships, mapping and project grants: access through it "
        "ends immediately. The SPA confirms first (no undo)."
    ),
    responses=problems(401, 403, 404),
)
async def delete_group(principal: PrincipalDep, group_id: UUID) -> None:
    raise NotImplementedProblem


@router.put(
    "/{group_id}/mapping",
    operation_id="replace_group_mapping",
    summary="Replace the IdP mapping",
    description=(
        _ADMIN + "sync_mode and the complete list of IdP values (normalised). Applies to "
        "each user at their next sign-in; memberships don't change now."
    ),
    responses=problems(401, 403, 404, 422),
)
async def replace_group_mapping(
    principal: PrincipalDep, group_id: UUID, body: GroupMappingUpdate
) -> Group:
    raise NotImplementedProblem


@router.get(
    "/{group_id}/members",
    operation_id="list_group_members",
    summary="List group members",
    description=(
        _ADMIN + "By display name, with provenance (manual, synced or both); deactivated "
        "members are listed too (is_active false)."
    ),
    responses=problems(400, 401, 403, 404),
)
async def list_group_members(
    principal: PrincipalDep,
    group_id: UUID,
    page: PageParamsDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Part of a name or email."), NoNul
    ] = None,
) -> GroupMemberPage:
    raise NotImplementedProblem


@router.post(
    "/{group_id}/members",
    operation_id="add_group_member",
    status_code=status.HTTP_201_CREATED,
    summary="Add a manual member",
    description=(
        _ADMIN + "Sign-in sync never removes a manual membership. A synced member "
        "becomes manual too. 409 already_member (already manual); 422 user_not_found "
        "(unknown, inactive, service or break-glass account)."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def add_group_member(
    principal: PrincipalDep, group_id: UUID, body: GroupMemberAdd
) -> GroupMember:
    raise NotImplementedProblem


@router.delete(
    "/{group_id}/members/{user_id}",
    operation_id="remove_group_member",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
    description=(
        _ADMIN + "Removes the membership whatever its provenance (manual and synced). A "
        "synced member comes back at their next sign-in while the IdP still sends a "
        "mapped value. 404 not a member."
    ),
    responses=problems(401, 403, 404),
)
async def remove_group_member(principal: PrincipalDep, group_id: UUID, user_id: UUID) -> None:
    raise NotImplementedProblem
