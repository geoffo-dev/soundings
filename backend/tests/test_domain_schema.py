"""Domain tables: migrations run down and up cleanly, match the models exactly, and
enforce the constraints the business rules rely on."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from psycopg import sql
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.models
from app.migrate import alembic_config
from app.models import ProjectRole, project_effective_roles
from app.models.base import Base
from tests.conftest import make_settings

DOMAIN_TABLES = {
    "activity_events",
    "audit_log",
    "comments",
    "evaluation_scores",
    "evaluations",
    "idea_evaluators",
    "idea_tags",
    "idea_votes",
    "idea_watchers",
    "ideas",
    "project_members",
    "projects",
    "rubric_criteria",
    "tags",
    "user_sessions",
    "users",
}

# Constraint and index definitions, normalised so two databases can be compared.
SCHEMA_QUERY = """
SELECT 'constraint', c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = current_schema() AND c.conrelid::regclass::text = ANY(%(tables)s)
UNION ALL
SELECT 'index', i.tablename, i.indexname, i.indexdef
FROM pg_indexes i
WHERE i.schemaname = current_schema() AND i.tablename = ANY(%(tables)s)
UNION ALL
SELECT 'column', c.table_name, c.column_name,
       concat_ws(' ', c.data_type, c.character_maximum_length, c.numeric_precision,
                 c.numeric_scale, c.is_nullable, c.column_default)
FROM information_schema.columns c
WHERE c.table_schema = current_schema() AND c.table_name = ANY(%(tables)s)
"""


def _dsn(url: str) -> str:
    return make_settings(database_url=url).database_dsn


def _schema(url: str) -> set[tuple[str, ...]]:
    with psycopg.connect(_dsn(url)) as connection:
        rows = connection.execute(SCHEMA_QUERY, {"tables": sorted(DOMAIN_TABLES)}).fetchall()
    return {tuple(str(value) for value in row) for row in rows}


@pytest.fixture
def scratch_database_url(database_url: str) -> Iterator[str]:
    """An empty database on the test server, dropped afterwards."""
    name = f"scratch_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(_dsn(database_url), autocommit=True)
    except psycopg.Error:  # pragma: no cover - only with an unusable TEST_DATABASE_URL
        pytest.skip("cannot connect to create a scratch database")
    with admin:
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        except psycopg.errors.InsufficientPrivilege:  # pragma: no cover
            pytest.skip("TEST_DATABASE_URL user may not create databases")
        try:
            yield make_url(database_url).set(database=name).render_as_string(hide_password=False)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_every_domain_model_is_registered() -> None:
    assert set(Base.metadata.tables) == DOMAIN_TABLES
    assert {name for name in app.models.__all__ if name[0].isupper()} >= {
        "User",
        "Project",
        "Idea",
        "Evaluation",
        "ActivityEvent",
        "AuditLog",
    }


def test_migrations_upgrade_downgrade_upgrade(scratch_database_url: str) -> None:
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        left = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            " AND tablename <> 'alembic_version'"
            " UNION ALL SELECT viewname FROM pg_views WHERE schemaname = current_schema()"
        ).fetchall()
        extension = connection.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
        ).fetchone()
    assert left == []
    assert extension is not None  # left installed: it may predate the migration

    command.upgrade(config, "head")
    command.check(config)


def test_migrated_schema_matches_the_models(database_url: str, scratch_database_url: str) -> None:
    """Stricter than `alembic check`: also compares CHECK constraints, index operator
    classes/expressions and server defaults."""
    engine = create_engine(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION pg_trgm"))
            Base.metadata.create_all(connection)
    finally:
        engine.dispose()

    migrated, from_models = _schema(database_url), _schema(scratch_database_url)

    assert migrated - from_models == set()
    assert from_models - migrated == set()


# --- Constraints the business rules rely on ------------------------------------------
async def _insert_project(session: AsyncSession) -> uuid.UUID:
    project_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO projects (id, slug, key, name) VALUES (:id, 'demo', 'DEMO', 'Demo')"),
        {"id": project_id},
    )
    return project_id


async def test_resolution_is_required_exactly_when_closed(db_session: AsyncSession) -> None:
    project_id = await _insert_project(db_session)
    insert = text(
        "INSERT INTO ideas (id, project_id, number, title, status, resolution)"
        " VALUES (:id, :project_id, :number, 'Idea', :status, :resolution)"
    )
    await db_session.execute(
        insert,
        {"id": uuid.uuid4(), "project_id": project_id, "number": 1, "status": "closed",
         "resolution": "parked"},
    )  # fmt: skip

    for number, status, resolution in [(2, "closed", None), (3, "new", "accepted")]:
        with pytest.raises(IntegrityError, match="ck_ideas_resolution_iff_closed"):
            async with db_session.begin_nested():
                await db_session.execute(
                    insert,
                    {"id": uuid.uuid4(), "project_id": project_id, "number": number,
                     "status": status, "resolution": resolution},
                )  # fmt: skip
    await db_session.rollback()


async def test_user_emails_are_unique_case_insensitively(db_session: AsyncSession) -> None:
    insert = text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'A')")
    await db_session.execute(insert, {"id": uuid.uuid4(), "email": "Ada@Example.com"})

    with pytest.raises(IntegrityError, match="uq_users_email_lower"):
        await db_session.execute(insert, {"id": uuid.uuid4(), "email": "ada@example.COM"})
    await db_session.rollback()


async def test_evaluation_requires_an_assignment_and_valid_scores(
    db_session: AsyncSession,
) -> None:
    project_id = await _insert_project(db_session)
    idea_id, user_id = uuid.uuid4(), uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO ideas (id, project_id, number, title) VALUES (:i, :p, 1, 'Idea')"),
        {"i": idea_id, "p": project_id},
    )
    await db_session.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:u, 'e@x.io', 'E')"),
        {"u": user_id},
    )
    insert_evaluation = text(
        "INSERT INTO evaluations (id, idea_id, evaluator_id) VALUES (:id, :i, :u)"
    )

    with pytest.raises(IntegrityError, match="fk_evaluations_idea_id_evaluator_id"):
        async with db_session.begin_nested():
            await db_session.execute(
                insert_evaluation, {"id": uuid.uuid4(), "i": idea_id, "u": user_id}
            )

    await db_session.execute(
        text("INSERT INTO idea_evaluators (idea_id, user_id) VALUES (:i, :u)"),
        {"i": idea_id, "u": user_id},
    )
    evaluation_id = uuid.uuid4()
    await db_session.execute(insert_evaluation, {"id": evaluation_id, "i": idea_id, "u": user_id})
    criterion_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO rubric_criteria (id, project_id, position, name)"
            " VALUES (:c, :p, 0, 'Value')"
        ),
        {"c": criterion_id, "p": project_id},
    )
    with pytest.raises(IntegrityError, match="ck_evaluation_scores_score_range"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO evaluation_scores (evaluation_id, criterion_id, score)"
                    " VALUES (:e, :c, 6)"
                ),
                {"e": evaluation_id, "c": criterion_id},
            )
    with pytest.raises(IntegrityError, match="ck_evaluations_submitted_complete"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE evaluations SET status = 'submitted' WHERE id = :e"),
                {"e": evaluation_id},
            )

    # Removing the assignment removes the evaluation with it.
    await db_session.execute(text("DELETE FROM idea_evaluators WHERE idea_id = :i"), {"i": idea_id})
    remaining = await db_session.scalar(text("SELECT count(*) FROM evaluations"))
    assert remaining == 0
    await db_session.rollback()


async def _scored_evaluation(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project with one criterion scored in one evaluation (committed)."""
    project_id = await _insert_project(session)
    idea_id, user_id, evaluation_id, criterion_id = (uuid.uuid4() for _ in range(4))
    ids = {"p": project_id, "i": idea_id, "u": user_id, "e": evaluation_id, "c": criterion_id}
    for statement in (
        "INSERT INTO ideas (id, project_id, number, title) VALUES (:i, :p, 1, 'Idea')",
        "INSERT INTO users (id, email, display_name) VALUES (:u, 'e@x.io', 'E')",
        "INSERT INTO idea_evaluators (idea_id, user_id) VALUES (:i, :u)",
        "INSERT INTO evaluations (id, idea_id, evaluator_id) VALUES (:e, :i, :u)",
        "INSERT INTO rubric_criteria (id, project_id, position, name) VALUES (:c, :p, 0, 'V')",
        "INSERT INTO evaluation_scores (evaluation_id, criterion_id, score) VALUES (:e, :c, 4)",
    ):
        await session.execute(text(statement), ids)
    await session.commit()
    return project_id, criterion_id


async def test_scored_criterion_cannot_be_deleted_but_its_project_can(
    db_session: AsyncSession,
) -> None:
    project_id, criterion_id = await _scored_evaluation(db_session)

    # The FK is checked at commit (DEFERRABLE INITIALLY DEFERRED).
    await db_session.execute(text("DELETE FROM rubric_criteria WHERE id = :c"), {"c": criterion_id})
    with pytest.raises(IntegrityError, match="fk_evaluation_scores_criterion_id_rubric_criteria"):
        await db_session.commit()
    await db_session.rollback()

    await db_session.execute(text("DELETE FROM projects WHERE id = :p"), {"p": project_id})
    await db_session.commit()
    for table in ("rubric_criteria", "evaluations", "evaluation_scores"):
        assert await db_session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608


async def test_active_criterion_names_are_unique_and_weights_positive(
    db_session: AsyncSession,
) -> None:
    project_id = await _insert_project(db_session)
    insert = text(
        "INSERT INTO rubric_criteria (id, project_id, position, name, weight)"
        " VALUES (:id, :p, 0, :name, :weight)"
    )
    first = uuid.uuid4()
    await db_session.execute(insert, {"id": first, "p": project_id, "name": "Value", "weight": 1})

    with pytest.raises(IntegrityError, match="uq_rubric_criteria_project_id_name_lower"):
        async with db_session.begin_nested():
            await db_session.execute(
                insert, {"id": uuid.uuid4(), "p": project_id, "name": "value", "weight": 1}
            )
    # numeric(4,2) rounds 0.004 to 0.00: the API only accepts 0.01 and up.
    with pytest.raises(IntegrityError, match="ck_rubric_criteria_weight_positive"):
        async with db_session.begin_nested():
            await db_session.execute(
                insert, {"id": uuid.uuid4(), "p": project_id, "name": "Tiny", "weight": 0.004}
            )

    # An archived criterion's name can be used again.
    await db_session.execute(
        text("UPDATE rubric_criteria SET archived_at = now() WHERE id = :id"), {"id": first}
    )
    await db_session.execute(
        insert, {"id": uuid.uuid4(), "p": project_id, "name": "VALUE", "weight": 1}
    )
    await db_session.rollback()


async def test_effective_roles_view_mirrors_direct_membership(db_session: AsyncSession) -> None:
    project_id, user_id = await _insert_project(db_session), uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:u, 'm@x.io', 'M')"),
        {"u": user_id},
    )
    await db_session.execute(
        text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'admin')"),
        {"p": project_id, "u": user_id},
    )

    rows = (await db_session.execute(select(project_effective_roles))).all()

    assert [tuple(row) for row in rows] == [(project_id, user_id, ProjectRole.ADMIN)]
    await db_session.rollback()
