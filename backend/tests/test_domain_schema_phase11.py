"""Phase 11 tables and constraints (migration 0017): the conversation with a public
submitter (``submission_messages``), the two submitter email types and "The submitter
replied", what the upgrade does for people who had unsubscribed from everything and what the
downgrade removes. tests/test_domain_schema.py runs the full up/down/up and compares the
migrated schema with the models."""

from __future__ import annotations

import importlib.util
import uuid
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import MIGRATIONS_DIR, alembic_config
from app.models.enums import SUBMITTER_EMAIL_TYPES, EmailType, MessageDirection, NotificationType
from app.models.public import SUBMISSION_MESSAGE_MAX_LENGTH
from tests.conftest import make_settings
from tests.test_domain_schema import (  # noqa: F401 - scratch_database_url is a fixture
    _dsn,
    _idea_and_user,
    scratch_database_url,
)

NEW_TYPES = ("submitter_replied",)
NEW_EMAILS = ("submission_link", "submission_message")
EARLIER_TYPES = tuple(t.value for t in NotificationType if t.value not in NEW_TYPES)

INSERT_MESSAGE = text(
    "INSERT INTO submission_messages (id, submission_id, direction, author_id, body, emailed)"
    " VALUES (:id, :s, :d, :a, :b, :e)"
)


def _migration() -> Any:
    path = MIGRATIONS_DIR / "versions" / "20261016_0017_submitter_messages.py"
    spec = importlib.util.spec_from_file_location("migration_0017", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_enum_values_are_the_migrations() -> None:
    """The migration spells the values out, in the enums' order (the CHECKs list them so)."""
    m = _migration()

    assert tuple(NotificationType) == m.NOTIFICATION_TYPES
    assert m.NOTIFICATION_TYPES_BEFORE == EARLIER_TYPES
    assert m.NEW_TYPES == NEW_TYPES
    assert tuple(EmailType) == m.EMAIL_TYPES
    later = (*NEW_TYPES, *NEW_EMAILS)
    assert tuple(t for t in EmailType if t.value not in later) == m.EMAIL_TYPES_BEFORE
    assert tuple(SUBMITTER_EMAIL_TYPES) == m.SUBMITTER_EMAILS
    assert m.NEW_SUBMITTER_EMAILS == NEW_EMAILS
    assert tuple(MessageDirection) == m.DIRECTIONS
    assert m.BODY_MAX == SUBMISSION_MESSAGE_MAX_LENGTH


async def _submission(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    idea_id, user_id = await _idea_and_user(db)
    project_id = await db.scalar(text("SELECT project_id FROM ideas WHERE id = :i"), {"i": idea_id})
    submission_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO public_submissions (id, idea_id, project_id, email, submitted_title,"
            " submitted_summary) VALUES (:s, :i, :p, 'jo@example.org', 'Title', 'Summary')"
        ),
        {"s": submission_id, "i": idea_id, "p": project_id},
    )
    return submission_id, idea_id, user_id


def _message(submission: uuid.UUID, **values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(), "s": submission, "d": "submitter", "a": None,
        "b": "All of them.", "e": False,
    }  # fmt: skip
    row.update(values)
    return row


async def test_messages_belong_to_a_submission(db_session: AsyncSession) -> None:
    """One submission per idea, so the submission names the idea (review C2: no idea_id)."""
    submission, _, user = await _submission(db_session)
    await db_session.execute(INSERT_MESSAGE, _message(submission, d="team", a=user, e=True))
    await db_session.execute(INSERT_MESSAGE, _message(submission))

    cases: list[tuple[dict[str, object], str]] = [
        ({"s": uuid.uuid4()}, "fk_submission_messages_submission_id_public_submissions"),
        # Replies have no author and are never emailed; directions are fixed.
        ({"a": user}, "ck_submission_messages_author_only_for_team"),
        ({"e": True}, "ck_submission_messages_emailed_only_for_team"),
        ({"d": "admin"}, "ck_submission_messages_direction"),
        ({"b": ""}, "ck_submission_messages_body_length"),
    ]
    for values, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(INSERT_MESSAGE, _message(submission, **values))
    with pytest.raises(DataError):  # 4,001 characters don't fit the column
        async with db_session.begin_nested():
            await db_session.execute(
                INSERT_MESSAGE,
                _message(submission, b="x" * (SUBMISSION_MESSAGE_MAX_LENGTH + 1)),
            )

    # People are deactivated, not deleted; a deleted author leaves the message unsigned.
    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})
    authors = await db_session.scalars(
        text("SELECT author_id FROM submission_messages WHERE submission_id = :s"),
        {"s": submission},
    )
    assert list(authors) == [None, None]
    await db_session.rollback()


@pytest.mark.parametrize("deleted", ["ideas", "public_submissions"])
async def test_deleting_the_idea_or_submission_deletes_the_conversation(
    db_session: AsyncSession, deleted: str
) -> None:
    submission, idea, user = await _submission(db_session)
    await db_session.execute(INSERT_MESSAGE, _message(submission, d="team", a=user))
    target = idea if deleted == "ideas" else submission

    await db_session.execute(text(f"DELETE FROM {deleted} WHERE id = :t"), {"t": target})  # noqa: S608

    left = await db_session.scalar(
        text("SELECT count(*) FROM submission_messages WHERE submission_id = :s"),
        {"s": submission},
    )
    assert left == 0
    await db_session.rollback()


async def test_the_new_submitter_emails_name_their_idea(db_session: AsyncSession) -> None:
    _, idea, user = await _submission(db_session)
    insert = text(
        "INSERT INTO outbound_email (id, type, recipient_user_id, to_address, idea_id,"
        " message_id) VALUES (:id, :type, :u, :address, :i, :m)"
    )
    for type_ in NEW_EMAILS:
        row = {"id": uuid.uuid4(), "type": type_, "u": None, "address": "jo@example.org"}
        await db_session.execute(insert, row | {"i": idea, "m": f"{row['id']}@x"})
        with pytest.raises(IntegrityError, match="ck_outbound_email_idea_iff_submission_type"):
            async with db_session.begin_nested():
                await db_session.execute(insert, row | {"id": uuid.uuid4(), "i": None, "m": "a@x"})
    # "The submitter replied" is a team notification: a user, never an idea row of its own.
    email = uuid.uuid4()
    await db_session.execute(
        insert,
        {"id": email, "type": "submitter_replied", "u": user, "address": None, "i": None,
         "m": f"{email}@x"},
    )  # fmt: skip
    await db_session.execute(
        text(
            "INSERT INTO notifications (id, user_id, type, idea_id, dedupe_key, email_mode,"
            " email_id) VALUES (:id, :u, 'submitter_replied', :i, :k, 'immediate', :e)"
        ),
        {"id": uuid.uuid4(), "u": user, "i": idea, "k": f"submitter_replied:{email}", "e": email},
    )
    with pytest.raises(IntegrityError, match="ck_outbound_email_idea_iff_submission_type"):
        async with db_session.begin_nested():
            await db_session.execute(
                insert,
                {"id": uuid.uuid4(), "type": "submitter_replied", "u": None,
                 "address": "jo@example.org", "i": idea, "m": "b@x"},
            )  # fmt: skip
    await db_session.rollback()


# --- The migration on data -------------------------------------------------------------------
def _people(connection: psycopg.Connection[Any]) -> dict[str, uuid.UUID]:
    people = {name: uuid.uuid4() for name in ("all_off", "some_off")}
    for name, user_id in people.items():
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, %s, %s)",
            (user_id, f"{name}@example.com", name),
        )
    for type_ in EARLIER_TYPES:  # "Unsubscribe from all email" turned every type off
        connection.execute(
            "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, %s, 'off')",
            (people["all_off"], type_),
        )
    for type_ in EARLIER_TYPES[:-1]:
        connection.execute(
            "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, %s, 'off')",
            (people["some_off"], type_),
        )
    return people


def test_0017_keeps_unsubscribe_from_all_meaning_all(scratch_database_url: str) -> None:  # noqa: F811
    """Someone with every earlier type off gets "The submitter replied" off too; everyone
    else gets the default (immediate: no row). Nothing is backfilled (no link emails)."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0016")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        people = _people(connection)

    command.upgrade(config, "head")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        rows = connection.execute(
            "SELECT user_id, type, mode FROM notification_preferences WHERE type = ANY(%s)",
            (list(NEW_TYPES),),
        ).fetchall()
        emails = connection.execute("SELECT count(*) FROM outbound_email").fetchone()

    assert rows == [(people["all_off"], "submitter_replied", "off")]
    assert emails == (0,)


def test_0017_downgrade_removes_the_conversations(scratch_database_url: str) -> None:  # noqa: F811
    """Below 0017: no message, no submission_link / submission_message email, no "submitter
    replied" notification or preference; everything else stays, and upgrading again
    matches the models."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "head")
    project, idea, user, submission = (uuid.uuid4() for _ in range(4))
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, 'bob@example.com', 'Bob')",
            (user,),
        )
        connection.execute(
            "INSERT INTO projects (id, slug, key, name) VALUES (%s, 'cust', 'CUST', 'Cust')",
            (project,),
        )
        connection.execute(
            "INSERT INTO ideas (id, project_id, number, title) VALUES (%s, %s, 21, 'Idea')",
            (idea, project),
        )
        connection.execute(
            "INSERT INTO public_submissions (id, idea_id, project_id, email, submitted_title,"
            " submitted_summary) VALUES (%s, %s, %s, 'jo@example.org', 'Title', 'Summary')",
            (submission, idea, project),
        )
        connection.execute(
            "INSERT INTO submission_messages (id, submission_id, direction, author_id, body)"
            " VALUES (%s, %s, 'team', %s, 'Which stores?')",
            (uuid.uuid4(), submission, user),
        )
        for type_ in (*NEW_EMAILS, "submission_status_changed"):
            email = uuid.uuid4()
            connection.execute(
                "INSERT INTO outbound_email (id, type, to_address, idea_id, message_id)"
                " VALUES (%s, %s, 'jo@example.org', %s, %s)",
                (email, type_, idea, f"{email}@x"),
            )
        for type_ in (*NEW_TYPES, "owner_assigned"):
            email = uuid.uuid4()
            connection.execute(
                "INSERT INTO outbound_email (id, type, recipient_user_id, message_id)"
                " VALUES (%s, %s, %s, %s)",
                (email, type_, user, f"{email}@x"),
            )
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

    command.downgrade(config, "0016")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        table = connection.execute("SELECT to_regclass('submission_messages')").fetchone()
        emails = connection.execute("SELECT type FROM outbound_email ORDER BY type").fetchall()
        notifications = connection.execute("SELECT type FROM notifications").fetchall()
        preferences = connection.execute("SELECT type FROM notification_preferences").fetchall()
        submissions = connection.execute("SELECT count(*) FROM public_submissions").fetchone()

    assert table == (None,)
    assert emails == [("owner_assigned",), ("submission_status_changed",)]
    assert notifications == [("owner_assigned",)]
    assert preferences == [("owner_assigned",)]
    assert submissions == (1,)
    command.upgrade(config, "head")
