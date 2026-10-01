"""In-app notifications (the bell) and my email preferences.

Every notification is about one idea and is listed only while you can view it. Your
email preferences decide which types are also emailed now, in the daily digest, or
not at all. Business rules: docs/api/contract-phase3.md sections 3.2-3.4.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import not_activity
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.authz import Rule, require
from app.config import Settings
from app.db import SessionDep
from app.notifications import inbox, preferences
from app.pagination import PageParamsDep
from app.schemas.notifications import (
    NotificationPage,
    NotificationPreferences,
    NotificationPreferencesUpdate,
    NotificationSummary,
)
from app.services.ideas import load_idea

router = APIRouter(prefix="/me", tags=["notifications"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


IdeaQuery = Annotated[
    str | None,
    Query(
        max_length=36,
        pattern=r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        r"|[A-Za-z][A-Za-z0-9]{1,5}-[1-9][0-9]{0,8})$",
        description='Only this idea: its id or key such as "CUST-12" (any case).',
    ),
]


@router.get(
    "/notifications",
    operation_id="list_notifications",
    summary="My notifications",
    description=(
        "Your inbox, newest first: notifications about ideas you can view now (others "
        "are skipped, not shown as gaps). unread=true: unread ones only."
    ),
    responses=problems(400, 401),
)
async def list_notifications(
    principal: PrincipalDep,
    session: SessionDep,
    page: PageParamsDep,
    unread: Annotated[bool, Query(description="Only unread notifications.")] = False,
) -> NotificationPage:
    return await inbox.list_notifications(
        session, principal, unread=unread, cursor=page.cursor, limit=page.limit
    )


@router.get(
    "/notifications/summary",
    operation_id="get_notification_summary",
    summary="Unread count and email status",
    description=(
        "For the app shell, polled about once a minute and on focus: the bell's unread "
        "count (up to 100), whether email is configured, and for platform admins whether "
        "email is failing (the banners). Polling isn't activity: this request doesn't "
        "keep the session alive (idle timeouts still apply)."
    ),
    responses=problems(401),
    # Polling isn't activity: resolve the session without sliding its idle timer
    # (contract-phase3 section 3.2). Runs before the principal is resolved.
    dependencies=[Depends(not_activity)],
)
async def get_notification_summary(
    request: Request, principal: PrincipalDep, session: SessionDep
) -> NotificationSummary:
    return await inbox.summary(session, _settings(request), principal)


@router.post(
    "/notifications/{notification_id}/read",
    operation_id="mark_notification_read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a notification read",
    description="Idempotent. 404 unless it is your notification about an idea you can view.",
    responses=problems(401, 404),
)
async def mark_notification_read(
    principal: PrincipalDep, session: SessionDep, notification_id: UUID
) -> None:
    await inbox.mark_read(session, principal, notification_id)


@router.post(
    "/notifications/read-all",
    operation_id="mark_all_notifications_read",
    summary="Mark all notifications read",
    description=(
        "Every unread notification of yours, or with idea only those about that idea "
        "(the idea page calls this when it opens). Returns the new summary."
    ),
    responses=problems(401, 404),
)
async def mark_all_notifications_read(
    request: Request, principal: PrincipalDep, session: SessionDep, idea: IdeaQuery = None
) -> NotificationSummary:
    idea_id = (await load_idea(session, principal, idea)).idea.id if idea else None
    return await inbox.mark_all_read(session, _settings(request), principal, idea_id)


@router.get(
    "/notification-preferences",
    operation_id="get_notification_preferences",
    summary="My email preferences",
    description=(
        "Per notification type: immediate, daily digest or off, with the defaults "
        "resolved (self.manage_profile; sessions only). The inbox always shows everything."
    ),
    responses=problems(401, 403),
)
async def get_notification_preferences(
    request: Request, principal: PrincipalDep, session: SessionDep
) -> NotificationPreferences:
    require(principal, Rule.SELF_MANAGE_PROFILE)
    return await preferences.view(session, _settings(request), principal.user_id)


@router.patch(
    "/notification-preferences",
    operation_id="update_notification_preferences",
    summary="Change my email preferences",
    description=(
        "Omitted or null types are unchanged; choosing a type's default clears your "
        "choice (self.manage_profile; sessions only)."
    ),
    responses=problems(401, 403),
)
async def update_notification_preferences(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    body: NotificationPreferencesUpdate,
) -> NotificationPreferences:
    require(principal, Rule.SELF_MANAGE_PROFILE)
    await preferences.update_from_request(session, principal.user_id, body)
    return await preferences.view(session, _settings(request), principal.user_id)
