"""Admin settings -> Email (rule ``platform.configure_email``; sessions only).

SMTP is configured through Helm values / ``SOUNDINGS_SMTP_*``; this page shows the
effective settings (credentials masked), sends a test email through the outbox, and
lists the outbox with retry for failed emails. Business rules:
docs/api/contract-phase3.md sections 3.9-3.10.
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
from app.email import admin
from app.models.enums import EmailStatus, EmailType
from app.pagination import PageParamsDep
from app.schemas.email import (
    EmailConfig,
    EmailTestRequest,
    OutboxEmail,
    OutboxEmailPage,
    OutboxRetryResult,
)

router = APIRouter(prefix="/admin/email", tags=["admin"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get(
    "",
    operation_id="get_email_config",
    summary="Effective email configuration",
    description=(
        "Platform admins (platform.configure_email). The SMTP settings in effect with "
        "credentials masked, the notification schedule, and outbox counts."
    ),
    responses=problems(401, 403),
)
async def get_email_config(
    request: Request, principal: PrincipalDep, session: SessionDep
) -> EmailConfig:
    require(principal, Rule.PLATFORM_CONFIGURE_EMAIL)
    return await admin.email_config(session, _settings(request))


@router.post(
    "/test",
    operation_id="send_test_email",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a test email",
    description=(
        "Platform admins. Queues one test email (one attempt, no retries) to you or to "
        "the given address and returns it; poll get_outbox_email for sent or the error. "
        "At most 5 per admin per 10 minutes (429 too_many_attempts with Retry-After). "
        "409 smtp_not_configured when email is off. Audited."
    ),
    responses=problems(401, 403, 409, 422, 429),
)
async def send_test_email(
    request: Request, principal: PrincipalDep, session: SessionDep, body: EmailTestRequest
) -> OutboxEmail:
    require(principal, Rule.PLATFORM_CONFIGURE_EMAIL)
    return await admin.send_test_email(session, _settings(request), principal, body.to)


@router.get(
    "/outbox",
    operation_id="list_outbox_emails",
    summary="The email outbox",
    description=(
        "Platform admins. Emails newest first, optionally only some statuses and types "
        "(repeat a parameter for several). Kept 30 days after sending or cancelling "
        "(failed: 90)."
    ),
    responses=problems(400, 401, 403),
)
async def list_outbox_emails(
    principal: PrincipalDep,
    session: SessionDep,
    page: PageParamsDep,
    status_filter: Annotated[
        list[EmailStatus] | None, Query(alias="status", description="Only these statuses.")
    ] = None,
    type_filter: Annotated[
        list[EmailType] | None, Query(alias="type", description="Only these types.")
    ] = None,
) -> OutboxEmailPage:
    require(principal, Rule.PLATFORM_CONFIGURE_EMAIL)
    return await admin.list_outbox(
        session, statuses=status_filter, types=type_filter, cursor=page.cursor, limit=page.limit
    )


@router.post(
    "/outbox/retry-failed",
    operation_id="retry_failed_outbox_emails",
    summary="Retry every failed email",
    description=(
        "Platform admins. Queues every retryable failed email again with fresh attempts "
        "(after an outage longer than the retries); failed mail older than 3 days "
        "(digests 2) is left as it is. 409 smtp_not_configured when email is off. "
        "Audited."
    ),
    responses=problems(401, 403, 409),
)
async def retry_failed_outbox_emails(
    request: Request, principal: PrincipalDep, session: SessionDep
) -> OutboxRetryResult:
    require(principal, Rule.PLATFORM_CONFIGURE_EMAIL)
    return OutboxRetryResult(
        retried=await admin.retry_all_failed(session, _settings(request), principal)
    )


@router.get(
    "/outbox/{email_id}",
    operation_id="get_outbox_email",
    summary="One outbox email",
    description="Platform admins. Its status, attempts and last error (no content).",
    responses=problems(401, 403, 404),
)
async def get_outbox_email(
    principal: PrincipalDep, session: SessionDep, email_id: UUID
) -> OutboxEmail:
    require(principal, Rule.PLATFORM_CONFIGURE_EMAIL)
    return await admin.get_outbox_email(session, email_id)


@router.post(
    "/outbox/{email_id}/retry",
    operation_id="retry_outbox_email",
    summary="Retry a failed email",
    description=(
        "Platform admins. A failed email is queued again with fresh attempts. 409 "
        "email_not_retryable unless it is failed and recent enough to send (retryable); "
        "409 smtp_not_configured when email is off. Audited."
    ),
    responses=problems(401, 403, 404, 409),
)
async def retry_outbox_email(
    request: Request, principal: PrincipalDep, session: SessionDep, email_id: UUID
) -> OutboxEmail:
    require(principal, Rule.PLATFORM_CONFIGURE_EMAIL)
    return await admin.retry_email(session, _settings(request), principal, email_id)
