"""The demo seed fills the inbox (in-app only, backdated, partly read) and sets a few
email preferences; it never queues email."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import NotificationMode, NotificationType
from app.models.notification import Notification, NotificationPreference, OutboundEmail
from app.models.user import User
from app.seed import run_seed
from tests.conftest import Login


async def test_the_demo_inbox_is_lived_in(
    settings: Settings, db_session: AsyncSession, login: Login
) -> None:
    await run_seed(settings)

    alice = await db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    notes = list(
        await db_session.scalars(select(Notification).where(Notification.user_id == alice.id))
    )
    types = Counter(note.type for note in notes)
    assert types[NotificationType.STATUS_CHANGED] > 0
    assert types[NotificationType.COMMENT] > 0
    assert any(note.read_at is None for note in notes)
    assert any(note.read_at is not None for note in notes)
    every = list(await db_session.scalars(select(Notification)))
    assert {note.email_mode for note in every} == {NotificationMode.OFF}
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 0
    assert await db_session.scalar(select(func.count()).select_from(NotificationPreference)) == 3

    http = await login(alice)
    summary = (await http.get("/api/v1/me/notifications/summary")).json()
    assert 0 < summary["unread_count"] <= 100
    page = (await http.get("/api/v1/me/notifications", params={"limit": 5})).json()
    assert len(page["items"]) == 5
