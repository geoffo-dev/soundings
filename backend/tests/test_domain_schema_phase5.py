"""Phase 5 tables (migration 0010): the constraints API keys and proposal suggestions
rely on, and the downgrade. tests/test_domain_schema.py runs the full up/down/up and
compares the migrated schema with the models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import alembic_config
from tests.conftest import make_settings
from tests.test_domain_schema import (  # noqa: F401 - scratch_database_url is a fixture
    _dsn,
    _idea_and_user,
    _insert_user,
    scratch_database_url,
)

INSERT_KEY = text(
    "INSERT INTO api_keys (id, user_id, name, lookup_id, secret_hash, scopes, project_ids,"
    " revoked_at, revoked_by_id, created_auth_method)"
    " VALUES (:id, :user, :name, :lookup, :hash, CAST(:scopes AS varchar[]),"
    " CAST(:projects AS uuid[]), :revoked_at, :revoked_by, :method)"
)


def _key(user_id: uuid.UUID, **values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "user": user_id,
        "name": "Claude Desktop",
        "lookup": uuid.uuid4().hex[:12],
        "hash": "a" * 64,
        "scopes": "{read,mcp}",
        "projects": None,
        "revoked_at": None,
        "revoked_by": None,
        "method": "sso",
    }
    row.update(values)
    return row


async def _fails(session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with session.begin_nested():
            await session.execute(INSERT_KEY, values)


async def test_api_keys_store_a_lookup_id_a_hash_and_known_scopes(
    db_session: AsyncSession,
) -> None:
    user_id = await _insert_user(db_session, "ada@x.io")
    first = _key(user_id)
    await db_session.execute(INSERT_KEY, first)
    await db_session.execute(
        INSERT_KEY, _key(user_id, name="Script", projects=f"{{{uuid.uuid4()}}}")
    )
    await db_session.execute(
        INSERT_KEY,
        _key(user_id, name="Agent", scopes="{read,write,evaluate,mcp}", method="dev_login"),
    )

    await _fails(
        db_session, _key(user_id, name="Other", lookup=first["lookup"]), "uq_api_keys_lookup_id"
    )
    await _fails(
        db_session, _key(user_id, name="A", lookup="short"), "ck_api_keys_lookup_id_format"
    )
    await _fails(
        db_session, _key(user_id, name="B", lookup="abc-def_ghij"), "ck_api_keys_lookup_id_format"
    )
    await _fails(
        db_session, _key(user_id, name="C", hash="A" * 64), "ck_api_keys_secret_hash_format"
    )
    await _fails(
        db_session, _key(user_id, name="D", hash="sdg_secret"), "ck_api_keys_secret_hash_format"
    )
    await _fails(db_session, _key(user_id, name="E", scopes="{}"), "ck_api_keys_scopes")
    await _fails(db_session, _key(user_id, name="F", scopes="{read,admin}"), "ck_api_keys_scopes")
    await _fails(
        db_session,
        _key(user_id, name="G", scopes="{read,write,evaluate,mcp,read}"),
        "ck_api_keys_scopes",
    )
    await _fails(
        db_session, _key(user_id, name="H", projects="{}"), "ck_api_keys_project_ids_not_empty"
    )
    # A NULL element must never make a restriction read as "every project".
    await _fails(
        db_session,
        _key(user_id, name="H2", projects=f"{{{uuid.uuid4()},NULL}}"),
        "ck_api_keys_project_ids_not_empty",
    )
    await _fails(db_session, _key(user_id, name="F2", scopes="{read,NULL}"), "ck_api_keys_scopes")
    # write and evaluate include read.
    for name, scopes in (("W", "{write}"), ("V", "{evaluate,mcp}"), ("WV", "{write,evaluate}")):
        await _fails(
            db_session, _key(user_id, name=name, scopes=scopes), "ck_api_keys_scopes_include_read"
        )
    await _fails(
        db_session,
        _key(user_id, name="M", method="password"),
        "ck_api_keys_created_auth_method",
    )
    await _fails(db_session, _key(user_id, name=""), "ck_api_keys_name_not_empty")
    await _fails(
        db_session,
        _key(user_id, name="I", revoked_by=user_id),
        "ck_api_keys_revoked_by_needs_revoked",
    )
    await db_session.rollback()


async def test_key_names_are_unique_per_owner_until_revoked(db_session: AsyncSession) -> None:
    ada = await _insert_user(db_session, "ada@x.io")
    bob = await _insert_user(db_session, "bob@x.io")
    first = _key(ada)
    await db_session.execute(INSERT_KEY, first)
    await db_session.execute(INSERT_KEY, _key(bob))  # another owner may use the name

    await _fails(db_session, _key(ada, name="claude DESKTOP"), "uq_api_keys_user_id_name_lower")

    await db_session.execute(
        text("UPDATE api_keys SET revoked_at = now(), revoked_by_id = :u WHERE id = :id"),
        {"u": ada, "id": first["id"]},
    )
    await db_session.execute(INSERT_KEY, _key(ada, name="claude desktop"))
    await db_session.rollback()


async def test_deleting_a_user_removes_their_keys_and_keeps_others(
    db_session: AsyncSession,
) -> None:
    ada = await _insert_user(db_session, "ada@x.io")
    admin = await _insert_user(db_session, "admin@x.io")
    revoked = datetime.now(UTC)
    await db_session.execute(INSERT_KEY, _key(ada))
    await db_session.execute(
        INSERT_KEY, _key(admin, name="Ops", revoked_at=revoked, revoked_by=ada)
    )

    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": ada})

    rows = (await db_session.execute(text("SELECT user_id, revoked_by_id FROM api_keys"))).all()
    assert rows == [(admin, None)]
    await db_session.rollback()


INSERT_SUGGESTION = text(
    "INSERT INTO proposal_suggestions (id, proposal_id, section_key, body_md, base_version,"
    " author_id, source, status, decided_by_id, decided_at)"
    " VALUES (:id, :proposal, :section, :body, :base, :author, :source, :status, :decider,"
    " :decided_at)"
)


def _suggestion(
    proposal_id: uuid.UUID, author_id: uuid.UUID | None, **values: object
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "proposal": proposal_id,
        "section": "risks",
        "body": "- Supplier lock-in",
        "base": 1,
        "author": author_id,
        "source": "mcp",
        "status": "pending",
        "decider": None,
        "decided_at": None,
    }
    row.update(values)
    return row


async def test_suggestions_are_one_pending_per_author_and_section(
    db_session: AsyncSession,
) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    other = await _insert_user(db_session, "agent@x.io")
    proposal_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO proposals (id, idea_id) VALUES (:id, :idea)"),
        {"id": proposal_id, "idea": idea_id},
    )
    now = datetime.now(UTC)
    first = _suggestion(proposal_id, user_id)
    await db_session.execute(INSERT_SUGGESTION, first)
    # Another author, another section, and decided suggestions don't collide.
    for values in (
        _suggestion(proposal_id, other),
        _suggestion(proposal_id, user_id, section="problem", source="api"),
        _suggestion(proposal_id, user_id, status="discarded", decider=user_id, decided_at=now),
        _suggestion(proposal_id, user_id, status="accepted", decider=other, decided_at=now),
    ):
        await db_session.execute(INSERT_SUGGESTION, values)

    cases: list[tuple[dict[str, object], str]] = [
        (_suggestion(proposal_id, user_id), "uq_proposal_suggestions_pending_author_section"),
        (
            _suggestion(proposal_id, user_id, section="Appendix"),
            "ck_proposal_suggestions_section_key_format",
        ),
        (
            _suggestion(proposal_id, user_id, section="cost", source="web"),
            "ck_proposal_suggestions_source",
        ),
        (
            _suggestion(proposal_id, user_id, section="cost", status="merged", decided_at=now),
            "ck_proposal_suggestions_status",
        ),
        (
            _suggestion(proposal_id, user_id, section="cost", base=0),
            "ck_proposal_suggestions_base_version_positive",
        ),
        (
            _suggestion(proposal_id, user_id, section="cost", body=""),
            "ck_proposal_suggestions_body_not_empty",
        ),
        (
            _suggestion(proposal_id, user_id, section="cost", decided_at=now),
            "ck_proposal_suggestions_decided_iff_not_pending",
        ),
        (
            _suggestion(proposal_id, user_id, section="cost", status="accepted"),
            "ck_proposal_suggestions_decided_iff_not_pending",
        ),
    ]
    for values, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(INSERT_SUGGESTION, values)

    # A deleted author leaves an anonymous suggestion; deleting the idea removes them all.
    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": other})
    authors = await db_session.scalars(
        text("SELECT author_id FROM proposal_suggestions WHERE id = :id"), {"id": first["id"]}
    )
    assert list(authors) == [user_id]
    await db_session.execute(text("DELETE FROM ideas WHERE id = :i"), {"i": idea_id})
    assert await db_session.scalar(text("SELECT count(*) FROM proposal_suggestions")) == 0
    await db_session.rollback()


def test_0010_downgrade_drops_keys_and_suggestions(scratch_database_url: str) -> None:  # noqa: F811
    """Going back below 0010 drops both tables (every key stops working); upgrading again
    recreates them empty and matching the models."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "head")
    user_id = uuid.uuid4()
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, 'ada@x.io', 'Ada')",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO api_keys (id, user_id, name, lookup_id, secret_hash, scopes,"
            " created_auth_method) VALUES (%s, %s, 'Script', 'abcdefABCDEF', %s, '{read}', 'sso')",
            (uuid.uuid4(), user_id, "0" * 64),
        )

    command.downgrade(config, "0009")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            " AND tablename IN ('api_keys', 'proposal_suggestions')"
        ).fetchall()
        users = connection.execute("SELECT count(*) FROM users").fetchone()
    assert tables == []
    assert users == (1,)

    command.upgrade(config, "head")
    command.check(config)
