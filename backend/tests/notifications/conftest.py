"""Fixtures for the notification, outbox and email tests.

Every test here runs with SMTP configured (a host nobody listens on: nothing leaves
the test unless a test points the transport at :class:`FakeSmtpServer`); turn it off
with ``@pytest.mark.settings(smtp_host=None, smtp_from=None)``.

* ``team`` / ``api``: the ideas test team (tests/ideas/conftest.py).
* ``outbox``: helpers to read notifications, outbox rows and procrastinate jobs.
* ``runtime``: the worker's :class:`~app.email.delivery.Runtime` with a
  :class:`RecordingTransport` (or any transport) and a settable clock.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from procrastinate import App, PsycopgConnector
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import NotificationType
from app.models.notification import Notification, OutboundEmail
from app.worker import procrastinate_app
from tests.ideas.conftest import (  # noqa: F401 - fixtures
    API,
    Api,
    AsUser,
    Team,
    api,
    assert_problem,
    full_scores,
    ok,
    team,
)

__all__ = [
    "API",
    "SMTP",
    "Api",
    "AsUser",
    "Clock",
    "Outbox",
    "RecordingTransport",
    "Team",
    "assert_problem",
    "full_scores",
    "ok",
    "only",
]

SMTP = {
    "smtp_host": "smtp.invalid",
    "smtp_port": 2525,
    "smtp_security": "none",
    "smtp_from": "soundings@example.com",
    "smtp_timeout": 2,
}


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return dict(SMTP)


@dataclass
class RecordingTransport:
    """Records what would be sent; ``errors`` are raised first, one per send."""

    sent: list[tuple[EmailMessage, str, str]] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)

    async def send(self, message: EmailMessage, *, sender: str, recipient: str) -> None:
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append((message, sender, recipient))

    @property
    def messages(self) -> list[EmailMessage]:
        return [message for message, _, _ in self.sent]


class Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now or utcnow()


@pytest.fixture
def transport() -> RecordingTransport:
    return RecordingTransport()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def jobs(settings: Settings) -> AsyncIterator[App]:
    """procrastinate opened on the test database (the sweep's own defers)."""
    with procrastinate_app.replace_connector(
        PsycopgConnector(conninfo=settings.database_dsn, min_size=1, max_size=2)
    ) as job_app:
        async with job_app.open_async():
            yield job_app


@pytest.fixture
def runtime(
    app: FastAPI, settings: Settings, transport: RecordingTransport, clock: Clock, jobs: App
) -> Runtime:
    return Runtime(
        settings=settings,
        sessionmaker=app.state.sessionmaker,
        jobs=jobs,
        transport=transport,
        clock=clock,
    )


@dataclass
class Outbox:
    """Read what the fan-out and the worker wrote."""

    db: AsyncSession

    async def notifications(
        self, user_id: UUID | None = None, type_: NotificationType | None = None
    ) -> list[Notification]:
        statement = (
            select(Notification)
            .order_by(Notification.created_at, Notification.id)
            .execution_options(populate_existing=True)
        )
        if user_id is not None:
            statement = statement.where(Notification.user_id == user_id)
        if type_ is not None:
            statement = statement.where(Notification.type == type_)
        return list(await self.db.scalars(statement))

    async def emails(self, user_id: UUID | None = None) -> list[OutboundEmail]:
        statement = (
            select(OutboundEmail)
            .order_by(OutboundEmail.created_at, OutboundEmail.id)
            .execution_options(populate_existing=True)
        )
        if user_id is not None:
            statement = statement.where(OutboundEmail.recipient_user_id == user_id)
        return list(await self.db.scalars(statement))

    async def email(self, email_id: UUID) -> OutboundEmail:
        row = await self.db.get(OutboundEmail, email_id, populate_existing=True)
        assert row is not None
        return row

    async def jobs(self, task: str = "send_email") -> list[dict[str, Any]]:
        rows = await self.db.execute(
            text(
                "SELECT id, status, args, queueing_lock, scheduled_at FROM procrastinate_jobs"
                " WHERE task_name = :task ORDER BY id"
            ),
            {"task": task},
        )
        await self.db.commit()
        return [dict(row._mapping) for row in rows]

    async def set(self, model: type[Any], row_id: Any, **values: Any) -> None:
        row = await self.db.get(model, row_id, populate_existing=True)
        assert row is not None
        for key, value in values.items():
            setattr(row, key, value)
        await self.db.commit()


@pytest.fixture
def outbox(db_session: AsyncSession) -> Outbox:
    return Outbox(db_session)


def only[T](items: list[T]) -> T:
    assert len(items) == 1, items
    return items[0]
