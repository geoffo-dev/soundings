"""Domain tables: migrations run down and up cleanly, match the models exactly, and
enforce the constraints the business rules rely on."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

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
    "group_idp_values",
    "group_memberships",
    "groups",
    "idea_evaluators",
    "idea_tags",
    "idea_votes",
    "idea_watchers",
    "ideas",
    "notification_preferences",
    "notifications",
    "outbound_email",
    "project_group_grants",
    "project_members",
    "projects",
    "rubric_criteria",
    "tags",
    "user_external_ids",
    "user_identities",
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


# --- Phase 2: identities, groups and group-granted roles -------------------------------
async def _insert_user(
    session: AsyncSession, email: str, *, is_break_glass: bool = False
) -> uuid.UUID:
    user_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_break_glass)"
            " VALUES (:u, :e, 'U', :break_glass)"
        ),
        {"u": user_id, "e": email, "break_glass": is_break_glass},
    )
    return user_id


async def _insert_group(session: AsyncSession, name: str) -> uuid.UUID:
    group_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO groups (id, name) VALUES (:g, :n)"), {"g": group_id, "n": name}
    )
    return group_id


async def _roles(session: AsyncSession, project_id: uuid.UUID) -> dict[uuid.UUID, ProjectRole]:
    rows = await session.execute(
        select(project_effective_roles.c.user_id, project_effective_roles.c.role).where(
            project_effective_roles.c.project_id == project_id
        )
    )
    found: dict[uuid.UUID, ProjectRole] = dict(rows.all())
    return found


async def test_effective_role_is_the_highest_of_direct_and_group_roles(
    db_session: AsyncSession,
) -> None:
    project_id = await _insert_project(db_session)
    direct_only, group_only, both, two_groups = [
        await _insert_user(db_session, f"{name}@x.io") for name in ("d", "g", "b", "t")
    ]
    viewers, members, admins = [await _insert_group(db_session, n) for n in ("V", "M", "A")]
    for group_id, role in ((viewers, "viewer"), (members, "member"), (admins, "admin")):
        await db_session.execute(
            text(
                "INSERT INTO project_group_grants (project_id, group_id, role) VALUES (:p, :g, :r)"
            ),
            {"p": project_id, "g": group_id, "r": role},
        )
    for user_id, role in ((direct_only, "member"), (both, "admin")):
        await db_session.execute(
            text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, :r)"),
            {"p": project_id, "u": user_id, "r": role},
        )
    memberships = [
        (viewers, group_only, "manual"),
        (members, both, "synced"),  # direct admin beats group member
        (viewers, two_groups, "synced"),
        (admins, two_groups, "manual"),  # highest group wins
    ]
    for group_id, user_id, source in memberships:
        await db_session.execute(
            text(
                "INSERT INTO group_memberships (group_id, user_id, manual, synced)"
                " VALUES (:g, :u, :manual, :synced)"
            ),
            {
                "g": group_id,
                "u": user_id,
                "manual": source == "manual",
                "synced": source == "synced",
            },
        )

    assert await _roles(db_session, project_id) == {
        direct_only: ProjectRole.MEMBER,
        group_only: ProjectRole.VIEWER,
        both: ProjectRole.ADMIN,
        two_groups: ProjectRole.ADMIN,
    }

    # Leaving the group (sync removing it, or an admin) removes the access with it.
    await db_session.execute(
        text("DELETE FROM group_memberships WHERE group_id = :g AND user_id = :u"),
        {"g": admins, "u": two_groups},
    )
    await db_session.execute(
        text("DELETE FROM group_memberships WHERE user_id = :u"), {"u": group_only}
    )
    roles = await _roles(db_session, project_id)
    assert roles[two_groups] is ProjectRole.VIEWER
    assert group_only not in roles

    # Deleting a group removes its memberships and grants.
    await db_session.execute(text("DELETE FROM groups WHERE id = :g"), {"g": viewers})
    assert two_groups not in await _roles(db_session, project_id)
    await db_session.rollback()


async def test_group_membership_needs_a_source_and_names_are_unique(
    db_session: AsyncSession,
) -> None:
    group_id = await _insert_group(db_session, "Innovation")
    user_id = await _insert_user(db_session, "u@x.io")

    with pytest.raises(IntegrityError, match="uq_groups_name_lower"):
        async with db_session.begin_nested():
            await _insert_group(db_session, "INNOVATION")
    with pytest.raises(IntegrityError, match="ck_group_memberships_has_source"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("INSERT INTO group_memberships (group_id, user_id) VALUES (:g, :u)"),
                {"g": group_id, "u": user_id},
            )
    with pytest.raises(IntegrityError, match="ck_groups_sync_mode"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE groups SET sync_mode = 'mirror' WHERE id = :g"), {"g": group_id}
            )
    insert_value = text("INSERT INTO group_idp_values (group_id, value) VALUES (:g, :v)")
    await db_session.execute(insert_value, {"g": group_id, "v": "innovation/admins"})
    with pytest.raises(IntegrityError, match="pk_group_idp_values"):
        async with db_session.begin_nested():
            await db_session.execute(insert_value, {"g": group_id, "v": "innovation/admins"})
    await db_session.rollback()


async def test_identities_and_external_ids_are_unique(db_session: AsyncSession) -> None:
    ada, bob = await _insert_user(db_session, "ada@x.io"), await _insert_user(db_session, "b@x.io")
    insert_identity = text(
        "INSERT INTO user_identities (id, user_id, issuer, subject) VALUES (:id, :u, :i, :s)"
    )
    issuer = "https://idp.example.com/realms/acme"
    await db_session.execute(
        insert_identity, {"id": uuid.uuid4(), "u": ada, "i": issuer, "s": "sub-1"}
    )
    for user_id, subject, constraint in (
        (bob, "sub-1", "uq_user_identities_issuer_subject"),  # one user per IdP account
        (ada, "sub-2", "uq_user_identities_user_id_issuer"),  # one IdP account per user
    ):
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(
                    insert_identity, {"id": uuid.uuid4(), "u": user_id, "i": issuer, "s": subject}
                )

    insert_external_id = text(
        "INSERT INTO user_external_ids (user_id, kind, value) VALUES (:u, :k, :v)"
    )
    await db_session.execute(insert_external_id, {"u": ada, "k": "employee_no", "v": "E1001"})
    for user_id, kind, value, constraint in (
        (bob, "employee_no", "e1001", "uq_user_external_ids_kind_value_lower"),
        (ada, "employee_no", "E2", "pk_user_external_ids"),  # one value per kind
        (bob, "Employee No", "E3", "ck_user_external_ids_kind"),
        (bob, "gitlab", "", "ck_user_external_ids_value_not_empty"),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(insert_external_id, {"u": user_id, "k": kind, "v": value})
    # The same value under another kind is fine.
    await db_session.execute(insert_external_id, {"u": bob, "k": "gitlab", "v": "E1001"})
    await db_session.rollback()


async def test_one_break_glass_user_and_known_session_methods(db_session: AsyncSession) -> None:
    await _insert_user(db_session, "bg@x.invalid", is_break_glass=True)
    await _insert_user(db_session, "plain@x.io", is_break_glass=False)
    with pytest.raises(IntegrityError, match="uq_users_is_break_glass"):
        async with db_session.begin_nested():
            await _insert_user(db_session, "bg2@x.invalid", is_break_glass=True)

    user_id = await _insert_user(db_session, "s@x.io")
    with pytest.raises(IntegrityError, match="ck_user_sessions_auth_method"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO user_sessions (id, token_hash, user_id, csrf_token, expires_at,"
                    " auth_method) VALUES (:id, 'h', :u, 'c', now(), 'password')"
                ),
                {"id": uuid.uuid4(), "u": user_id},
            )
    with pytest.raises(IntegrityError, match="auth_method"):  # no default: always named
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO user_sessions (id, token_hash, user_id, csrf_token, expires_at)"
                    " VALUES (:id, 'h', :u, 'c', now())"
                ),
                {"id": uuid.uuid4(), "u": user_id},
            )
    await db_session.rollback()


def test_phase2_downgrade_keeps_direct_roles_and_sessions(scratch_database_url: str) -> None:
    """0003 down and up again: group grants go, direct roles and sessions stay."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0002")
    ids = {name: uuid.uuid4() for name in ("project", "member", "session", "group", "grouped")}
    with psycopg.connect(_dsn(scratch_database_url), autocommit=True) as connection:
        for statement in (
            "INSERT INTO projects (id, slug, key, name) VALUES (%(project)s, 'demo', 'DEMO', 'D')",
            "INSERT INTO users (id, email, display_name) VALUES (%(member)s, 'm@x.io', 'M'),"
            " (%(grouped)s, 'g@x.io', 'G')",
            "INSERT INTO project_members (project_id, user_id, role)"
            " VALUES (%(project)s, %(member)s, 'admin')",
            "INSERT INTO user_sessions (id, token_hash, user_id, csrf_token, expires_at)"
            " VALUES (%(session)s, 'h', %(member)s, 'c', now() + interval '1 day')",
        ):
            connection.execute(statement, ids)

        command.upgrade(config, "head")
        method = connection.execute(
            "SELECT auth_method FROM user_sessions WHERE id = %(session)s", ids
        ).fetchone()
        for statement in (
            "INSERT INTO groups (id, name) VALUES (%(group)s, 'G')",
            "INSERT INTO group_memberships (group_id, user_id, synced)"
            " VALUES (%(group)s, %(grouped)s, true)",
            "INSERT INTO project_group_grants (project_id, group_id, role)"
            " VALUES (%(project)s, %(group)s, 'member')",
        ):
            connection.execute(statement, ids)
        roles_at_head = connection.execute(
            "SELECT user_id, role FROM project_effective_roles ORDER BY role"
        ).fetchall()

        command.downgrade(config, "0002")
        roles_after = connection.execute(
            "SELECT user_id, role FROM project_effective_roles"
        ).fetchall()
        sessions_after = connection.execute("SELECT count(*) FROM user_sessions").fetchone()

    assert method == ("dev_login",)
    assert roles_at_head == [(ids["member"], "admin"), (ids["grouped"], "member")]
    assert roles_after == [(ids["member"], "admin")]
    assert sessions_after == (1,)
    command.upgrade(config, "head")
    command.check(config)


def test_0004_stateless_sign_in_drops_attempts_and_plain_id_tokens(
    scratch_database_url: str,
) -> None:
    """Review H1/L4: no login-attempt table, and no ID token left in plain text."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0003")
    ids = {"user": uuid.uuid4(), "session": uuid.uuid4()}
    tables = "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
    with psycopg.connect(_dsn(scratch_database_url), autocommit=True) as connection:
        for statement in (
            "INSERT INTO users (id, email, display_name) VALUES (%(user)s, 'e@x.io', 'E')",
            "INSERT INTO user_sessions (id, token_hash, user_id, csrf_token, expires_at,"
            " auth_method, id_token) VALUES (%(session)s, 'h', %(user)s, 'c',"
            " now() + interval '1 day', 'sso', 'header.claims.signature')",
        ):
            connection.execute(statement, ids)

        command.upgrade(config, "head")
        kept = connection.execute(
            "SELECT auth_method, id_token FROM user_sessions WHERE id = %(session)s", ids
        ).fetchone()
        tables_at_head = {row[0] for row in connection.execute(tables)}
        command.downgrade(config, "0003")
        tables_after = {row[0] for row in connection.execute(tables)}

    assert kept == ("sso", None)  # the session stays, its plain ID token goes
    assert "oidc_login_attempts" not in tables_at_head
    assert "oidc_login_attempts" in tables_after
    command.upgrade(config, "head")
    command.check(config)


# --- Phase 3: outbox, notifications and preferences -------------------------------------
async def _idea_and_user(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    project_id = await _insert_project(session)
    idea_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO ideas (id, project_id, number, title) VALUES (:i, :p, 1, 'Idea')"),
        {"i": idea_id, "p": project_id},
    )
    return idea_id, await _insert_user(session, "n@x.io")


INSERT_EMAIL = text(
    "INSERT INTO outbound_email (id, type, status, recipient_user_id, to_address, message_id,"
    " idempotency_key, next_attempt_at, sent_at)"
    " VALUES (:id, :type, :status, :user, :address, :message_id, :key, :next, :sent)"
)


def _email(**values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(), "type": "test", "status": "queued", "user": None,
        "address": "someone@example.com", "key": None, "sent": None,
        "next": datetime.now(UTC),
    }  # fmt: skip
    row.update(values)
    row.setdefault("message_id", f"<{row['id']}@soundings.example>")
    return row


async def test_outbound_email_has_exactly_one_recipient_and_consistent_state(
    db_session: AsyncSession,
) -> None:
    _, user_id = await _idea_and_user(db_session)
    await db_session.execute(INSERT_EMAIL, _email())
    await db_session.execute(INSERT_EMAIL, _email(user=user_id, address=None))

    cases: list[tuple[dict[str, object], str]] = [
        ({"user": user_id}, "ck_outbound_email_one_recipient"),
        ({"address": None}, "ck_outbound_email_one_recipient"),
        ({"next": None}, "ck_outbound_email_next_attempt_iff_pending"),
        ({"status": "failed"}, "ck_outbound_email_next_attempt_iff_pending"),
        ({"status": "sent", "next": None}, "ck_outbound_email_sent_at_iff_sent"),
        ({"type": "newsletter"}, "ck_outbound_email_type"),
        ({"status": "bounced", "next": None}, "ck_outbound_email_status"),
    ]
    for values, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(INSERT_EMAIL, _email(**values))
    await db_session.execute(INSERT_EMAIL, _email(status="sent", next=None, sent=datetime.now(UTC)))
    await db_session.rollback()


async def test_outbound_email_message_ids_and_idempotency_keys_are_unique(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(INSERT_EMAIL, _email(message_id="<a@x>", key="digest:u:2026-10-01"))
    await db_session.execute(INSERT_EMAIL, _email(key=None))
    await db_session.execute(INSERT_EMAIL, _email(key=None))  # no key: no limit

    for values, constraint in [
        ({"message_id": "<a@x>"}, "uq_outbound_email_message_id"),
        ({"key": "digest:u:2026-10-01"}, "uq_outbound_email_idempotency_key"),
    ]:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(INSERT_EMAIL, _email(**values))
    await db_session.rollback()


INSERT_NOTIFICATION = text(
    "INSERT INTO notifications (id, user_id, type, idea_id, comment_id, dedupe_key,"
    " email_mode, email_id) VALUES (:id, :user, :type, :idea, :comment, :key, :mode, :email)"
)


async def test_notifications_are_deduplicated_per_user_and_consistent(
    db_session: AsyncSession,
) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    other = await _insert_user(db_session, "o@x.io")
    email_id = uuid.uuid4()
    await db_session.execute(INSERT_EMAIL, _email(id=email_id, user=user_id, address=None))
    comment_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO comments (id, idea_id, body_md) VALUES (:c, :i, 'Hi')"),
        {"c": comment_id, "i": idea_id},
    )

    def row(**values: object) -> dict[str, object]:
        base: dict[str, object] = {
            "id": uuid.uuid4(), "user": user_id, "type": "status_changed", "idea": idea_id,
            "comment": None, "key": "status_changed:e1", "mode": "immediate", "email": email_id,
        }  # fmt: skip
        return base | values

    await db_session.execute(INSERT_NOTIFICATION, row())
    await db_session.execute(INSERT_NOTIFICATION, row(user=other, email=None, mode="off"))
    await db_session.execute(
        INSERT_NOTIFICATION, row(type="mention", comment=comment_id, key=f"mention:{comment_id}")
    )
    cases: list[tuple[dict[str, object], str]] = [
        ({}, "uq_notifications_user_id_dedupe_key"),
        ({"key": "k2", "type": "comment"}, "ck_notifications_comment_iff_comment_type"),
        ({"key": "k3", "comment": comment_id}, "ck_notifications_comment_iff_comment_type"),
        ({"key": "k4", "mode": "off"}, "ck_notifications_no_email_when_off"),
        ({"key": "k5", "mode": "weekly"}, "ck_notifications_email_mode"),
    ]
    for values, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(INSERT_NOTIFICATION, row(**values))

    # Pruning the email keeps the notification; deleting the idea removes both kinds.
    await db_session.execute(text("DELETE FROM outbound_email WHERE id = :e"), {"e": email_id})
    assert (
        await db_session.scalar(text("SELECT count(*) FROM notifications WHERE email_id IS NULL"))
        == 3
    )
    await db_session.execute(text("DELETE FROM ideas WHERE id = :i"), {"i": idea_id})
    assert await db_session.scalar(text("SELECT count(*) FROM notifications")) == 0
    await db_session.rollback()


async def test_notification_preferences_are_one_per_user_and_type(
    db_session: AsyncSession,
) -> None:
    user_id = await _insert_user(db_session, "p@x.io")
    insert = text("INSERT INTO notification_preferences (user_id, type, mode) VALUES (:u, :t, :m)")
    await db_session.execute(insert, {"u": user_id, "t": "comment", "m": "off"})

    for values, constraint in [
        ({"t": "comment", "m": "digest"}, "pk_notification_preferences"),
        ({"t": "comments", "m": "off"}, "ck_notification_preferences_type"),
        ({"t": "mention", "m": "weekly"}, "ck_notification_preferences_mode"),
    ]:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(insert, {"u": user_id} | values)
    await db_session.rollback()
