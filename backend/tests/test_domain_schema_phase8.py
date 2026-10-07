"""Phase 8 tables and columns (migration 0012): per-project proposal templates, template
keys instead of the fixed eight, the research step, the research checklist and answers;
the data the upgrade carries over and what the downgrade does. tests/test_domain_schema.py
runs the full up/down/up and compares the migrated schema with the models."""

from __future__ import annotations

import importlib.util
import json
import uuid
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import MIGRATIONS_DIR, alembic_config
from app.models.enums import IdeaStatus, ProposalSectionKey, ResearchStep
from app.models.proposal import SECTION_KEY_PATTERN
from app.models.research import RESEARCH_ANSWER_MAX_LENGTH
from app.schemas.proposals import DEFAULT_PROPOSAL_TEMPLATE
from tests.conftest import make_settings
from tests.test_domain_schema import (  # noqa: F401 - scratch_database_url is a fixture
    _dsn,
    _idea_and_user,
    _insert_project,
    _insert_user,
    scratch_database_url,
)

INSERT_SECTION = text(
    "INSERT INTO proposal_template_sections (id, project_id, key, title, hint, position,"
    " archived_at) VALUES (:id, :project, :key, :title, '', :position, :archived)"
)
INSERT_ITEM = text(
    "INSERT INTO research_checklist_items (id, project_id, position, title, required,"
    " archived_at) VALUES (:id, :project, :position, :title, :required, :archived)"
)
INSERT_ANSWER = text(
    "INSERT INTO research_answers (idea_id, item_id, answer, answered_by_id, updated_by_id)"
    " VALUES (:idea, :item, :answer, :user, :user)"
)


def _migration() -> Any:
    path = MIGRATIONS_DIR / "versions" / "20261007_0012_templates_and_research.py"
    spec = importlib.util.spec_from_file_location("migration_0012", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


async def _fails(
    session: AsyncSession, statement: object, values: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with session.begin_nested():
            await session.execute(statement, values)  # type: ignore[call-overload]


def _section(
    project: uuid.UUID, key: str, title: str, position: int, **values: object
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "project": project,
        "key": key,
        "title": title,
        "position": position,
        "archived": None,
        **values,
    }


def test_enum_values_are_the_migrations() -> None:
    """The migration spells the values out (it must not import app code that may change)."""
    migration = _migration()

    assert tuple(IdeaStatus) == migration.STATUSES
    assert tuple(s for s in IdeaStatus if s is not IdeaStatus.RESEARCH) == migration.STATUSES_BEFORE
    assert tuple(ResearchStep) == migration.RESEARCH_STEPS
    assert tuple(ProposalSectionKey) == migration.DEFAULT_KEYS
    assert migration.SECTION_KEY == SECTION_KEY_PATTERN
    assert (
        tuple((s.key.value, s.title, s.prompt) for s in DEFAULT_PROPOSAL_TEMPLATE)
        == migration.DEFAULT_SECTIONS
    )


async def test_template_sections_have_stable_unique_keys(db_session: AsyncSession) -> None:
    project = await _insert_project(db_session)
    await db_session.execute(INSERT_SECTION, _section(project, "summary", "Summary", 0))
    # A removed section keeps its key (no other section may take it), not its title.
    await db_session.execute(
        INSERT_SECTION,
        _section(project, "carbon_impact", "Carbon impact", 1, archived="2026-10-07T10:00Z"),
    )
    await db_session.execute(INSERT_SECTION, _section(project, "carbon", "Carbon impact", 1))

    cases = [
        (
            _section(project, "summary", "Overview", 2),
            "uq_proposal_template_sections_project_id_key",
        ),
        (
            _section(project, "carbon_impact", "Carbon", 2),
            "uq_proposal_template_sections_project_id_key",
        ),
        (
            _section(project, "overview", "SUMMARY", 2),
            "uq_proposal_template_sections_project_id_title_lower",
        ),
        (_section(project, "Overview", "Overview", 2), "ck_proposal_template_sections_key_format"),
        (_section(project, "next-steps", "Next", 2), "ck_proposal_template_sections_key_format"),
        (_section(project, "1st", "First", 2), "ck_proposal_template_sections_key_format"),
        (_section(project, "empty", "", 2), "ck_proposal_template_sections_title_not_empty"),
        (
            _section(project, "minus", "Minus", -1),
            "ck_proposal_template_sections_position_non_negative",
        ),
    ]
    for values, constraint in cases:
        await _fails(db_session, INSERT_SECTION, values, constraint)

    # Another project may use the same keys and titles; deleting a project removes its template.
    other = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO projects (id, slug, key, name) VALUES (:id, 'other', 'OTHR', 'O')"),
        {"id": other},
    )
    await db_session.execute(INSERT_SECTION, _section(other, "summary", "Summary", 0))
    await db_session.execute(text("DELETE FROM projects WHERE id = :p"), {"p": project})
    left = await db_session.scalar(text("SELECT count(*) FROM proposal_template_sections"))
    assert left == 1
    await db_session.rollback()


async def test_section_rows_take_any_template_key(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    proposal_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO proposals (id, idea_id) VALUES (:id, :idea)"),
        {"id": proposal_id, "idea": idea_id},
    )
    insert = text("INSERT INTO proposal_sections (proposal_id, key) VALUES (:p, :k)")
    await db_session.execute(insert, {"p": proposal_id, "k": "carbon_impact"})
    await db_session.execute(insert, {"p": proposal_id, "k": "x" * 40})
    for key in ("Carbon", "carbon-impact", "_x", "9lives"):
        await _fails(
            db_session, insert, {"p": proposal_id, "k": key}, "ck_proposal_sections_key_format"
        )

    thread = text("INSERT INTO proposal_threads (id, proposal_id, section_key) VALUES (:t, :p, :k)")
    await db_session.execute(thread, {"t": uuid.uuid4(), "p": proposal_id, "k": "carbon_impact"})
    await _fails(
        db_session,
        thread,
        {"t": uuid.uuid4(), "p": proposal_id, "k": "Carbon"},
        "ck_proposal_threads_section_key_format",
    )
    suggestion = text(
        "INSERT INTO proposal_suggestions (id, proposal_id, section_key, body_md, base_version,"
        " author_id, source) VALUES (:s, :p, :k, 'Text', 1, :u, 'api')"
    )
    await db_session.execute(
        suggestion, {"s": uuid.uuid4(), "p": proposal_id, "k": "carbon_impact", "u": user_id}
    )
    await _fails(
        db_session,
        suggestion,
        {"s": uuid.uuid4(), "p": proposal_id, "k": "Carbon", "u": user_id},
        "ck_proposal_suggestions_section_key_format",
    )
    await db_session.rollback()


async def test_ideas_may_be_in_research_and_projects_know_their_step(
    db_session: AsyncSession,
) -> None:
    project = await _insert_project(db_session)
    step = await db_session.scalar(
        text("SELECT research_step FROM projects WHERE id = :p"), {"p": project}
    )
    assert step == "off"
    for value in ("before_evaluation", "before_proposal", "off"):
        await db_session.execute(
            text("UPDATE projects SET research_step = :s WHERE id = :p"), {"s": value, "p": project}
        )
    await _fails(
        db_session,
        text("UPDATE projects SET research_step = 'always' WHERE id = :p"),
        {"p": project},
        "ck_projects_research_step",
    )
    insert = text(
        "INSERT INTO ideas (id, project_id, number, title, status) VALUES (:i, :p, :n, 'I', :s)"
    )
    await db_session.execute(insert, {"i": uuid.uuid4(), "p": project, "n": 1, "s": "research"})
    await _fails(
        db_session,
        insert,
        {"i": uuid.uuid4(), "p": project, "n": 2, "s": "researching"},
        "ck_ideas_status",
    )
    await db_session.rollback()


async def test_checklist_items_and_answers(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    project = await db_session.scalar(
        text("SELECT project_id FROM ideas WHERE id = :i"), {"i": idea_id}
    )
    item, optional, removed = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for row in (
        {
            "id": item,
            "project": project,
            "position": 0,
            "title": "Consulted",
            "required": True,
            "archived": None,
        },
        {
            "id": optional,
            "project": project,
            "position": 1,
            "title": "Data",
            "required": False,
            "archived": None,
        },
        {
            "id": removed,
            "project": project,
            "position": 2,
            "title": "CONSULTED",
            "required": True,
            "archived": "2026-10-07T10:00Z",
        },
    ):
        await db_session.execute(INSERT_ITEM, row)
    required = await db_session.scalar(
        text("SELECT required FROM research_checklist_items WHERE id = :i"), {"i": item}
    )
    assert required is True

    duplicate = {
        "id": uuid.uuid4(),
        "project": project,
        "position": 3,
        "title": "consulted",
        "required": True,
        "archived": None,
    }
    await _fails(
        db_session, INSERT_ITEM, duplicate, "uq_research_checklist_items_project_id_title_lower"
    )
    await _fails(
        db_session,
        INSERT_ITEM,
        duplicate | {"title": ""},
        "ck_research_checklist_items_title_not_empty",
    )
    await _fails(
        db_session,
        INSERT_ITEM,
        duplicate | {"title": "Neg", "position": -1},
        "ck_research_checklist_items_position_non_negative",
    )

    answer = "Legal (contracts team), 3 Oct: fine if we keep the standard terms."
    await db_session.execute(
        INSERT_ANSWER, {"idea": idea_id, "item": item, "answer": answer, "user": user_id}
    )
    await db_session.execute(
        INSERT_ANSWER,
        {
            "idea": idea_id,
            "item": optional,
            "answer": "x" * RESEARCH_ANSWER_MAX_LENGTH,
            "user": user_id,
        },
    )
    for values, constraint in (
        (
            {"idea": idea_id, "item": item, "answer": "Again", "user": user_id},
            "pk_research_answers",
        ),
        (
            {"idea": idea_id, "item": removed, "answer": "", "user": user_id},
            "ck_research_answers_answer_length",
        ),
        (
            {"idea": idea_id, "item": removed, "answer": "x" * 2001, "user": user_id},
            "ck_research_answers_answer_length",
        ),
        (
            {"idea": idea_id, "item": uuid.uuid4(), "answer": "No item", "user": user_id},
            "fk_research_answers_item_id",
        ),
    ):
        await _fails(db_session, INSERT_ANSWER, values, constraint)

    # An answered item can't be deleted (it is archived instead)...
    await _fails(
        db_session,
        text("DELETE FROM research_checklist_items WHERE id = :i"),
        {"i": item},
        "fk_research_answers_item_id",
    )
    # ... a deleted user leaves the answer anonymous ...
    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    authors = (
        await db_session.execute(text("SELECT answered_by_id, updated_by_id FROM research_answers"))
    ).all()
    assert authors == [(None, None), (None, None)]
    # ... and deleting the project removes items and answers in one statement.
    await db_session.execute(text("DELETE FROM projects WHERE id = :p"), {"p": project})
    for table in ("research_checklist_items", "research_answers"):
        assert await db_session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608
    await db_session.rollback()


# --- The upgrade carries Phase 7 data over; the downgrade -----------------------------------
def _seed_phase7(connection: psycopg.Connection[Any]) -> dict[str, uuid.UUID]:
    """A Phase 7 (0011) project with a proposal in every section, a margin thread, a
    pending suggestion and an AI draft run, plus a second project without proposals."""
    ids = {
        name: uuid.uuid4()
        for name in (
            "user",
            "agent_user",
            "agent",
            "cust",
            "tool",
            "idea",
            "proposal",
            "thread",
            "suggestion",
            "run",
        )
    }
    connection.execute(
        "INSERT INTO users (id, email, display_name, is_service_account) VALUES"
        " (%s, 'ada@example.com', 'Ada', false), (%s, 'agent@soundings.invalid', 'Drafter', true)",
        (ids["user"], ids["agent_user"]),
    )
    connection.execute(
        "INSERT INTO projects (id, slug, key, name, status_labels) VALUES"
        " (%s, 'customer-innovation', 'CUST', 'Customer Innovation',"
        ' \'{"shortlisted": "Short list"}\'),'
        " (%s, 'internal-tools', 'TOOL', 'Internal Tools', '{}')",
        (ids["cust"], ids["tool"]),
    )
    connection.execute(
        "INSERT INTO ideas (id, project_id, number, title, status, owner_id) VALUES"
        " (%s, %s, 1, 'Self-service returns', 'proposal', %s)",
        (ids["idea"], ids["cust"], ids["user"]),
    )
    connection.execute(
        "INSERT INTO proposals (id, idea_id, created_by_id) VALUES (%s, %s, %s)",
        (ids["proposal"], ids["idea"], ids["user"]),
    )
    for n, key in enumerate(ProposalSectionKey):
        connection.execute(
            "INSERT INTO proposal_sections (proposal_id, key, body_md, version, updated_by_id)"
            " VALUES (%s, %s, %s, %s, %s)",
            (ids["proposal"], key.value, f"Text of {key.value}", n + 1, ids["user"]),
        )
    connection.execute(
        "INSERT INTO proposal_threads (id, proposal_id, section_key, created_by_id)"
        " VALUES (%s, %s, 'risks', %s)",
        (ids["thread"], ids["proposal"], ids["user"]),
    )
    connection.execute(
        "INSERT INTO proposal_comments (id, thread_id, author_id, body_md)"
        " VALUES (%s, %s, %s, 'Supplier lock-in?')",
        (uuid.uuid4(), ids["thread"], ids["user"]),
    )
    connection.execute(
        "INSERT INTO proposal_suggestions (id, proposal_id, section_key, body_md, base_version,"
        " author_id, source) VALUES (%s, %s, 'next_steps', 'Ask for budget.', 8, %s, 'ai')",
        (ids["suggestion"], ids["proposal"], ids["agent_user"]),
    )
    connection.execute(
        "INSERT INTO ai_agents (id, display_name, namespace, name, protocol, purposes,"
        " service_account_id) VALUES (%s, 'Drafter', 'soundings', 'drafter', 'kagent_v0_10',"
        " '{draft_section}', %s)",
        (ids["agent"], ids["agent_user"]),
    )
    connection.execute(
        "INSERT INTO ai_runs (id, idea_id, agent_id, kind, section_key, status, timeout_seconds,"
        " started_at, finished_at, suggestion_id) VALUES (%s, %s, %s, 'draft_section',"
        " 'next_steps', 'succeeded', 300, now(), now(), %s)",
        (ids["run"], ids["idea"], ids["agent"], ids["suggestion"]),
    )
    return ids


def _snapshot(connection: psycopg.Connection[Any]) -> dict[str, list[tuple[Any, ...]]]:
    queries = {
        "sections": "SELECT proposal_id, key, body_md, version, updated_by_id"
        " FROM proposal_sections ORDER BY key",
        "threads": "SELECT id, proposal_id, section_key FROM proposal_threads ORDER BY id",
        "comments": "SELECT thread_id, body_md FROM proposal_comments ORDER BY id",
        "suggestions": "SELECT id, section_key, body_md, status"
        " FROM proposal_suggestions ORDER BY id",
        "runs": "SELECT id, kind, section_key, status, suggestion_id FROM ai_runs ORDER BY id",
        "ideas": "SELECT id, status, resolution FROM ideas ORDER BY id",
        "labels": "SELECT id, status_labels FROM projects ORDER BY id",
    }
    return {name: connection.execute(sql).fetchall() for name, sql in queries.items()}


def test_0012_carries_proposals_threads_suggestions_and_runs_over(
    scratch_database_url: str,  # noqa: F811
) -> None:
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0011")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        ids = _seed_phase7(connection)
        before = _snapshot(connection)

    command.upgrade(config, "head")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        after = _snapshot(connection)
        template = connection.execute(
            "SELECT project_id, key, title, hint, position, archived_at"
            " FROM proposal_template_sections ORDER BY project_id, position"
        ).fetchall()
        steps = connection.execute("SELECT research_step FROM projects").fetchall()
        research = connection.execute(
            "SELECT (SELECT count(*) FROM research_checklist_items),"
            " (SELECT count(*) FROM research_answers)"
        ).fetchone()

    assert after == before  # nothing lost or changed
    defaults = [(s.key.value, s.title, s.prompt) for s in DEFAULT_PROPOSAL_TEMPLATE]
    for project in (ids["cust"], ids["tool"]):
        rows = [row for row in template if row[0] == project]
        assert [(key, title, hint) for _, key, title, hint, _, _ in rows] == defaults
        assert [position for *_, position, _ in rows] == list(range(8))
        assert all(archived is None for *_, archived in rows)
    assert steps == [("off",), ("off",)]
    assert research == (0, 0)


def test_0012_downgrade_returns_to_the_fixed_template(scratch_database_url: str) -> None:  # noqa: F811
    """Below 0012: ideas in Research go back to the stage before it (and status payloads
    with them), research data is dropped, sections that aren't one of the eight defaults
    (their text, threads, suggestions and AI runs) are deleted, and every proposal has all
    eight default sections again."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0011")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        ids = _seed_phase7(connection)
    command.upgrade(config, "head")
    research_idea, proposal_idea = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        cust, tool = ids["cust"], ids["tool"]
        connection.execute(
            "UPDATE projects SET research_step = 'before_proposal', status_labels ="
            ' status_labels || \'{"research": "Due diligence"}\' WHERE id = %s',
            (cust,),
        )
        connection.execute(
            "UPDATE projects SET research_step = 'before_evaluation' WHERE id = %s", (tool,)
        )
        connection.execute(
            "INSERT INTO ideas (id, project_id, number, title, status) VALUES"
            " (%s, %s, 1, 'Laptop loans', 'research'), (%s, %s, 2, 'Returns', 'research')",
            (research_idea, tool, proposal_idea, cust),
        )
        for idea, project in ((research_idea, tool), (proposal_idea, cust)):
            payload = json.dumps(
                {
                    "from_status": "new",
                    "to_status": "research",
                    "from_resolution": None,
                    "to_resolution": None,
                }
            )
            connection.execute(
                "INSERT INTO activity_events (id, project_id, idea_id, type, payload)"
                " VALUES (%s, %s, %s, 'status_changed', %s)",
                (uuid.uuid4(), project, idea, payload),
            )
            connection.execute(
                "INSERT INTO notifications (id, user_id, type, idea_id, payload, dedupe_key,"
                " email_mode)"
                " VALUES (%s, %s, 'status_changed', %s, %s, %s, 'off')",
                (uuid.uuid4(), ids["user"], idea, payload, f"status_changed:{uuid.uuid4()}"),
            )
        item = uuid.uuid4()
        connection.execute(
            "INSERT INTO research_checklist_items (id, project_id, position, title)"
            " VALUES (%s, %s, 0, 'Consulted')",
            (item, tool),
        )
        connection.execute(
            "INSERT INTO research_answers (idea_id, item_id, answer)"
            " VALUES (%s, %s, 'Legal: fine')",
            (research_idea, item),
        )
        # A custom section with text, a thread and a suggestion; "market" removed (archived).
        connection.execute(
            "INSERT INTO proposal_template_sections (id, project_id, key, title, position)"
            " VALUES (%s, %s, 'carbon_impact', 'Carbon impact', 8)",
            (uuid.uuid4(), cust),
        )
        connection.execute(
            "UPDATE proposal_template_sections SET archived_at = now()"
            " WHERE project_id = %s AND key = 'market'",
            (cust,),
        )
        connection.execute(
            "INSERT INTO proposal_sections (proposal_id, key, body_md)"
            " VALUES (%s, 'carbon_impact', 'Low')",
            (ids["proposal"],),
        )
        connection.execute(
            "INSERT INTO proposal_threads (id, proposal_id, section_key)"
            " VALUES (%s, %s, 'carbon_impact')",
            (uuid.uuid4(), ids["proposal"]),
        )
        connection.execute(
            "INSERT INTO proposal_suggestions (id, proposal_id, section_key, body_md, base_version,"
            " author_id, source) VALUES (%s, %s, 'carbon_impact', 'Tiny', 1, %s, 'api')",
            (uuid.uuid4(), ids["proposal"], ids["user"]),
        )
        # A default section a project removed while it was empty (deleted, not archived):
        # its row is gone from the proposal.
        connection.execute("DELETE FROM proposal_sections WHERE key = 'cost'")

    command.downgrade(config, "0011")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        statuses: dict[uuid.UUID, str] = dict(
            connection.execute("SELECT id, status FROM ideas").fetchall()
        )
        events = connection.execute(
            "SELECT idea_id, payload->>'to_status' FROM activity_events ORDER BY idea_id"
        ).fetchall()
        notified = connection.execute(
            "SELECT idea_id, payload->>'to_status' FROM notifications ORDER BY idea_id"
        ).fetchall()
        labels = connection.execute(
            "SELECT status_labels FROM projects WHERE id = %s", (ids["cust"],)
        ).fetchone()
        sections = connection.execute(
            "SELECT key, body_md FROM proposal_sections WHERE proposal_id = %s ORDER BY key",
            (ids["proposal"],),
        ).fetchall()
        threads = connection.execute("SELECT section_key FROM proposal_threads").fetchall()
        suggestions = connection.execute("SELECT section_key FROM proposal_suggestions").fetchall()
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND"
            " (tablename LIKE 'research%%' OR tablename = 'proposal_template_sections')"
        ).fetchall()
        column = connection.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'projects'"
            " AND column_name = 'research_step'"
        ).fetchone()
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO proposal_sections (proposal_id, key) VALUES (%s, 'carbon')",
                (ids["proposal"],),
            )

    assert statuses[research_idea] == "new"  # before_evaluation: back to New
    assert statuses[proposal_idea] == "shortlisted"  # before_proposal: back to Shortlisted
    assert statuses[ids["idea"]] == "proposal"
    expected = sorted([(research_idea, "new"), (proposal_idea, "shortlisted")])
    assert sorted(events) == expected
    assert sorted(notified) == expected
    assert labels == ({"shortlisted": "Short list"},)
    keys = [key for key, _ in sections]
    assert keys == sorted(key.value for key in ProposalSectionKey)  # all eight, carbon gone
    texts: dict[str, str] = dict(sections)
    assert texts["market"] == "Text of market"  # an archived default comes back
    assert texts["cost"] == ""  # a deleted default comes back empty
    assert threads == [("risks",)]
    assert suggestions == [("next_steps",)]
    assert tables == []
    assert column is None

    command.upgrade(config, "head")
    command.check(config)
