"""Admin settings -> Audit log (rule ``platform.view_audit_log``; session only).
Business rules: docs/api/contract-phase2.md section 3.11."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.pagination import PageParamsDep
from app.schemas.audit import AuditAction, AuditPage, AuditTargetType

router = APIRouter(prefix="/admin/audit", tags=["admin"])


@router.get(
    "",
    operation_id="list_audit_entries",
    summary="Read the audit log",
    description=(
        "Platform admins (platform.view_audit_log). Newest first; filters combine with "
        "AND, several action values with OR. since is inclusive, until exclusive."
    ),
    responses=problems(400, 401, 403),
)
async def list_audit_entries(
    principal: PrincipalDep,
    page: PageParamsDep,
    actor_id: Annotated[UUID | None, Query(description="Entries by this user.")] = None,
    action: Annotated[
        list[AuditAction] | None, Query(max_length=40, description="Any of these actions.")
    ] = None,
    target_type: Annotated[
        AuditTargetType | None, Query(description="Entries about this kind of thing.")
    ] = None,
    target_id: Annotated[UUID | None, Query(description="Entries about this id.")] = None,
    project_id: Annotated[UUID | None, Query(description="Entries in this project.")] = None,
    since: Annotated[
        AwareDatetime | None, Query(description="From this time (with a UTC offset).")
    ] = None,
    until: Annotated[
        AwareDatetime | None, Query(description="Before this time (with a UTC offset).")
    ] = None,
) -> AuditPage:
    raise NotImplementedProblem
