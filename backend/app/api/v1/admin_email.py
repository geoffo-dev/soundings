"""Admin settings -> Email (rule ``platform.configure_email``; sessions only).

SMTP is configured through Helm values / ``SOUNDINGS_SMTP_*``; this page shows the
effective settings (credentials masked), sends a test email through the outbox, and
lists the outbox with retry for failed emails. Business rules:
docs/api/contract-phase3.md sections 3.9-3.10.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
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
async def get_email_config(principal: PrincipalDep) -> EmailConfig:
    raise NotImplementedProblem


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
async def send_test_email(principal: PrincipalDep, body: EmailTestRequest) -> OutboxEmail:
    raise NotImplementedProblem


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
    page: PageParamsDep,
    status_filter: Annotated[
        list[EmailStatus] | None, Query(alias="status", description="Only these statuses.")
    ] = None,
    type_filter: Annotated[
        list[EmailType] | None, Query(alias="type", description="Only these types.")
    ] = None,
) -> OutboxEmailPage:
    raise NotImplementedProblem


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
async def retry_failed_outbox_emails(principal: PrincipalDep) -> OutboxRetryResult:
    raise NotImplementedProblem


@router.get(
    "/outbox/{email_id}",
    operation_id="get_outbox_email",
    summary="One outbox email",
    description="Platform admins. Its status, attempts and last error (no content).",
    responses=problems(401, 403, 404),
)
async def get_outbox_email(principal: PrincipalDep, email_id: UUID) -> OutboxEmail:
    raise NotImplementedProblem


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
async def retry_outbox_email(principal: PrincipalDep, email_id: UUID) -> OutboxEmail:
    raise NotImplementedProblem
