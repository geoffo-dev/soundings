"""Email preferences per user and notification type (contract-phase3 section 3.4).

Only choices that differ from :data:`app.schemas.notifications.DEFAULT_MODES` are
stored; resolution is "row if present, else the default". Preferences govern email
only: the inbox always gets every notification.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.base import utcnow
from app.models.enums import NotificationMode, NotificationType
from app.models.notification import NotificationPreference
from app.schemas.notifications import (
    DEFAULT_MODES,
    NotificationPreferences,
    NotificationPreferencesUpdate,
)
from app.schemas.notifications import (
    NotificationPreference as NotificationPreferenceOut,
)
from app.services.sql import any_of

__all__ = ["all_modes", "mode_of", "modes_for", "update", "update_from_request", "view"]


async def modes_for(
    db: AsyncSession, user_ids: Iterable[UUID], type_: NotificationType
) -> dict[UUID, NotificationMode]:
    """Each user's mode for one type (one query)."""
    wanted = list(dict.fromkeys(user_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(NotificationPreference.user_id, NotificationPreference.mode).where(
            any_of(NotificationPreference.user_id, wanted), NotificationPreference.type == type_
        )
    )
    chosen: dict[UUID, NotificationMode] = dict(rows.all())
    return {user_id: chosen.get(user_id, DEFAULT_MODES[type_]) for user_id in wanted}


async def mode_of(db: AsyncSession, user_id: UUID, type_: NotificationType) -> NotificationMode:
    return (await modes_for(db, [user_id], type_))[user_id]


async def all_modes(db: AsyncSession, user_id: UUID) -> dict[NotificationType, NotificationMode]:
    """The user's mode for every type, in ``NotificationType`` order."""
    rows = await db.execute(
        select(NotificationPreference.type, NotificationPreference.mode).where(
            NotificationPreference.user_id == user_id
        )
    )
    chosen: dict[NotificationType, NotificationMode] = dict(rows.all())
    return {type_: chosen.get(type_, DEFAULT_MODES[type_]) for type_ in NotificationType}


async def update(
    db: AsyncSession, user_id: UUID, changes: Mapping[NotificationType, NotificationMode]
) -> None:
    """Apply ``changes``: a type's default deletes its row, any other mode upserts it."""
    resets = [type_ for type_, mode in changes.items() if mode is DEFAULT_MODES[type_]]
    chosen = {type_: mode for type_, mode in changes.items() if mode is not DEFAULT_MODES[type_]}
    if resets:
        await db.execute(
            delete(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type.in_(resets),
            )
        )
    if chosen:
        now = utcnow()
        statement = insert(NotificationPreference).values(
            [
                {"user_id": user_id, "type": type_, "mode": mode, "updated_at": now}
                for type_, mode in chosen.items()
            ]
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "type"],
                set_={"mode": statement.excluded.mode, "updated_at": now},
            )
        )


async def update_from_request(
    db: AsyncSession, user_id: UUID, body: NotificationPreferencesUpdate
) -> None:
    changes = {
        NotificationType(name): mode
        for name, mode in body.model_dump(exclude_none=True).items()
        if mode is not None
    }
    await update(db, user_id, changes)


async def view(db: AsyncSession, settings: Settings, user_id: UUID) -> NotificationPreferences:
    modes = await all_modes(db, user_id)
    return NotificationPreferences(
        email_available=settings.smtp_configured,
        digest_hour=settings.digest_hour,
        timezone=settings.timezone,
        items=[
            NotificationPreferenceOut(type=type_, mode=mode, default_mode=DEFAULT_MODES[type_])
            for type_, mode in modes.items()
        ],
    )
