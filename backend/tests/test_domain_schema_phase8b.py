"""Phase 8b columns and types (migration 0015): an idea's researcher and research due
date, the two research notification types, what the upgrade does for people who had
unsubscribed from everything and what the downgrade removes. tests/test_domain_schema.py
runs the full up/down/up and compares the migrated schema with the models."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import MIGRATIONS_DIR, alembic_config
from app.models.enums import EmailType, NotificationType
from app.schemas.activity import PHASE8B_ACTIVITY_TYPES
from app.schemas.notifications import DEFAULT_MODES, NotificationMode
from tests.conftest import make_settings
from tests.test_domain_schema import (  # noqa: F401 - scratch_database_url is a fixture
    _dsn,
    _idea_and_user,
    _insert_user,
    scratch_database_url,
)

NEW_TYPES = ("researcher_assigned", "research_reminder")
EARLIER_TYPES = tuple(t.value for t in NotificationType if t.value not in NEW_TYPES)


def _migration() -> Any:
    path = MIGRATIONS_DIR / "versions" / "20261008_0015_research_assignment.py"
    spec = importlib.util.spec_from_file_location("migration_0015", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_enum_values_are_the_migrations() -> None:
    """The migration spells the values out, in the enums' order (the CHECKs list them so)."""
    migration = _migration()

    assert tuple(NotificationType) == migration.NOTIFICATION_TYPES
    assert migration.NOTIFICATION_TYPES_BEFORE == EARLIER_TYPES
    assert migration.NEW_TYPES == NEW_TYPES
    assert tuple(EmailType) == migration.EMAIL_TYPES
    assert tuple(t for t in EmailType if t.value not in NEW_TYPES) == migration.EMAIL_TYPES_BEFORE
    assert migration.NEW_ACTIVITY_TYPES == PHASE8B_ACTIVITY_TYPES


def test_the_research_types_are_emailed_at_once_by_default() -> None:
    assert DEFAULT_MODES[NotificationType.RESEARCHER_ASSIGNED] is NotificationMode.IMMEDIATE
    assert DEFAULT_MODES[NotificationType.RESEARCH_REMINDER] is NotificationMode.IMMEDIATE
    assert set(DEFAULT_MODES) == set(NotificationType)


async def test_an_idea_has_one_optional_researcher_and_research_due_date(
    db_session: AsyncSession,
) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    due = datetime.now(UTC) + timedelta(days=3)
    await db_session.execute(
        text(
            "UPDATE ideas SET researcher_id = :u, research_assigned_at = now(),"
            " research_due_at = :due WHERE id = :i"
        ),
        {"u": user_id, "due": due, "i": idea_id},
    )
    row = (
        await db_session.execute(
            text("SELECT researcher_id, research_due_at FROM ideas WHERE id = :i"), {"i": idea_id}
        )
    ).one()
    assert row == (user_id, due)

    with pytest.raises(IntegrityError, match="fk_ideas_researcher_id_users"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE ideas SET researcher_id = :u WHERE id = :i"),
                {"u": uuid.uuid4(), "i": idea_id},
            )

    # A researcher always has the time they were asked (review C5); one way only.
    with pytest.raises(IntegrityError, match="ck_ideas_researcher_assigned_at"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE ideas SET research_assigned_at = NULL WHERE id = :i"),
                {"i": idea_id},
            )

    # Users are deactivated, not deleted; a deleted row would leave nobody assigned.
    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    researcher = await db_session.scalar(
        text("SELECT researcher_id FROM ideas WHERE id = :i"), {"i": idea_id}
    )
    assert researcher is None
    await db_session.rollback()


async def test_the_research_notification_types_are_stored(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    for new_type in NEW_TYPES:
        email_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO outbound_email (id, type, recipient_user_id, message_id)"
                " VALUES (:id, :type, :u, :m)"
            ),
            {"id": email_id, "type": new_type, "u": user_id, "m": f"{email_id}@x"},
        )
        await db_session.execute(
            text(
                "INSERT INTO notifications (id, user_id, type, idea_id, dedupe_key, email_mode,"
                " email_id) VALUES (:id, :u, :type, :i, :key, 'immediate', :e)"
            ),
            {
                "id": uuid.uuid4(),
                "u": user_id,
                "type": new_type,
                "i": idea_id,
                "key": f"{new_type}:x",
                "e": email_id,
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO notification_preferences (user_id, type, mode)"
                " VALUES (:u, :type, 'digest')"
            ),
            {"u": user_id, "type": new_type},
        )

    with pytest.raises(IntegrityError, match="ck_notifications_type"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO notifications (id, user_id, type, idea_id, dedupe_key,"
                    " email_mode) VALUES (:id, :u, 'research_assigned', :i, 'k', 'off')"
                ),
                {"id": uuid.uuid4(), "u": user_id, "i": idea_id},
            )
    await db_session.rollback()


def _insert_people(connection: psycopg.Connection[Any]) -> dict[str, uuid.UUID]:
    people = {name: uuid.uuid4() for name in ("all_off", "some_off", "defaults")}
    for name, user_id in people.items():
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, %s, %s)",
            (user_id, f"{name}@example.com", name),
        )
    for type_ in EARLIER_TYPES:  # "Unsubscribe from all email" set every type off
        connection.execute(
            "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, %s, 'off')",
            (people["all_off"], type_),
        )
    for type_ in EARLIER_TYPES[:-1]:  # everything but mentions off
        connection.execute(
            "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, %s, 'off')",
            (people["some_off"], type_),
        )
    connection.execute(
        "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, 'mention',"
        " 'digest')",
        (people["some_off"],),
    )
    return people


def test_0015_keeps_unsubscribe_from_all_meaning_all(scratch_database_url: str) -> None:  # noqa: F811
    """Someone with every earlier type off gets the two research types off too; everyone
    else gets the defaults (immediate: no rows)."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0014")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        people = _insert_people(connection)

    command.upgrade(config, "head")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        rows = connection.execute(
            "SELECT user_id, type, mode FROM notification_preferences WHERE type = ANY(%s)"
            " ORDER BY type",
            (list(NEW_TYPES),),
        ).fetchall()
        researchers = connection.execute(
            "SELECT count(*) FROM ideas WHERE researcher_id IS NOT NULL"
            " OR research_due_at IS NOT NULL"
        ).fetchone()

    assert rows == [
        (people["all_off"], "research_reminder", "off"),
        (people["all_off"], "researcher_assigned", "off"),
    ]
    assert researchers == (0,)


def test_0015_downgrade_drops_assignments_and_research_notifications(
    scratch_database_url: str,  # noqa: F811
) -> None:
    """Below 0015: no researcher or research due date, no notification, outbox row or
    preference of the two research types, no researcher_changed or
    research_due_date_changed events; everything else is kept."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "head")
    project, idea, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, 'bob@example.com', 'Bob')",
            (user,),
        )
        connection.execute(
            "INSERT INTO projects (id, slug, key, name) VALUES (%s, 'tools', 'TOOLS', 'Tools')",
            (project,),
        )
        connection.execute(
            "INSERT INTO ideas (id, project_id, number, title, researcher_id,"
            " research_assigned_at, research_due_at) VALUES (%s, %s, 12, 'Idea', %s, now(),"
            " now() + interval '3 days')",
            (idea, project, user),
        )
        for type_ in (*NEW_TYPES, "comment", "owner_assigned"):
            email = uuid.uuid4()
            connection.execute(
                "INSERT INTO outbound_email (id, type, recipient_user_id, message_id)"
                " VALUES (%s, %s, %s, %s)",
                (email, type_, user, f"{email}@x"),
            )
            if type_ != "comment":  # a comment notification needs a comment
                connection.execute(
                    "INSERT INTO notifications (id, user_id, type, idea_id, dedupe_key,"
                    " email_mode, email_id) VALUES (%s, %s, %s, %s, %s, 'immediate', %s)",
                    (uuid.uuid4(), user, type_, idea, f"{type_}:1", email),
                )
            connection.execute(
                "INSERT INTO notification_preferences (user_id, type, mode)"
                " VALUES (%s, %s, 'digest')",
                (user, type_),
            )
        for type_ in (*PHASE8B_ACTIVITY_TYPES, "owner_changed"):
            connection.execute(
                "INSERT INTO activity_events (id, project_id, idea_id, type) VALUES"
                " (%s, %s, %s, %s)",
                (uuid.uuid4(), project, idea, type_),
            )

    command.downgrade(config, "0014")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'ideas'"
            " AND column_name LIKE 'research%%'"
        ).fetchall()
        kept = {
            table: connection.execute(f"SELECT type FROM {table} ORDER BY type").fetchall()  # noqa: S608
            for table in (
                "outbound_email",
                "notifications",
                "notification_preferences",
                "activity_events",
            )
        }

    assert columns == []
    assert kept == {
        "outbound_email": [("comment",), ("owner_assigned",)],
        "notifications": [("owner_assigned",)],
        "notification_preferences": [("comment",), ("owner_assigned",)],
        "activity_events": [("owner_changed",)],
    }
    command.upgrade(config, "head")
    command.check(config)
