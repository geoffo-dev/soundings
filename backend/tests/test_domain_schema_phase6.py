"""Phase 6 tables (migration 0011): the constraints AI agents, runs, run events and cited
sources rely on, and the downgrade. tests/test_domain_schema.py runs the full up/down/up
and compares the migrated schema with the models."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import MIGRATIONS_DIR, alembic_config
from app.models.ai import KUBERNETES_LABEL_PATTERN
from app.models.enums import (
    AiAgentProtocol,
    AiRunError,
    AiRunEventType,
    AiRunKind,
    AiRunStatus,
)
from tests.conftest import make_settings
from tests.test_domain_schema import (  # noqa: F401 - scratch_database_url is a fixture
    _dsn,
    _idea_and_user,
    _insert_user,
    scratch_database_url,
)

INSERT_AGENT = text(
    "INSERT INTO ai_agents (id, display_name, namespace, name, protocol, purposes,"
    " service_account_id) VALUES (:id, :display, :ns, :name, :protocol,"
    " CAST(:purposes AS varchar[]), :sa)"
)
INSERT_RUN = text(
    "INSERT INTO ai_runs (id, idea_id, agent_id, kind, section_key, status, timeout_seconds,"
    " started_at, finished_at, error_code, error_message, evaluation_id, suggestion_id,"
    " activity_event_id, assigned_evaluator) VALUES (:id, :idea, :agent, :kind, :section,"
    " :status, :timeout, :started, :finished, :error, :message, :evaluation, :suggestion,"
    " :event, :assigned)"
)


def _agent(service_account: uuid.UUID, **values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "display": "Idea evaluator",
        "ns": "soundings",
        "name": "idea-evaluator",
        "protocol": "kagent_v0_10",
        "purposes": "{evaluate}",
        "sa": service_account,
    }
    row.update(values)
    return row


def _run(idea: uuid.UUID, agent: object, **values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "idea": idea,
        "agent": agent,
        "kind": "evaluate",
        "section": None,
        "status": "queued",
        "timeout": 300,
        "started": None,
        "finished": None,
        "error": None,
        "message": None,
        "evaluation": None,
        "suggestion": None,
        "event": None,
        "assigned": False,
    }
    row.update(values)
    return row


async def _fails(
    session: AsyncSession, statement: object, values: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with session.begin_nested():
            await session.execute(statement, values)  # type: ignore[call-overload]


async def _service_account(session: AsyncSession, email: str) -> uuid.UUID:
    user_id = await _insert_user(session, email)
    await session.execute(
        text("UPDATE users SET is_service_account = true WHERE id = :u"), {"u": user_id}
    )
    return user_id


def test_enum_values_are_the_migrations() -> None:
    """The migration spells the enums out (it must not import app code that may change)."""
    path = MIGRATIONS_DIR / "versions" / "20261006_0011_ai_agents_and_runs.py"
    spec = importlib.util.spec_from_file_location("migration_0011", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert tuple(AiRunKind) == migration.KINDS
    assert tuple(AiAgentProtocol) == migration.PROTOCOLS
    assert tuple(AiRunStatus) == migration.STATUSES
    assert tuple(AiRunEventType) == migration.EVENT_TYPES
    assert tuple(AiRunError) == migration.ERRORS
    assert migration.LABEL == KUBERNETES_LABEL_PATTERN


async def test_agents_have_kubernetes_names_known_purposes_and_one_service_account(
    db_session: AsyncSession,
) -> None:
    account = await _service_account(db_session, "agent-1@soundings.invalid")
    other = await _service_account(db_session, "agent-2@soundings.invalid")
    first = _agent(account, purposes="{evaluate,research,draft_section}")
    await db_session.execute(INSERT_AGENT, first)

    await _fails(db_session, INSERT_AGENT, _agent(other), "uq_ai_agents_namespace_name")
    await _fails(
        db_session, INSERT_AGENT, _agent(account, name="other"), "uq_ai_agents_service_account_id"
    )
    for bad in ("Idea-Evaluator", "-x", "x-", "a/b", "a.b", "", "a b", "a_b"):
        await _fails(db_session, INSERT_AGENT, _agent(other, name=bad), "ck_ai_agents_name_format")
        await _fails(
            db_session, INSERT_AGENT, _agent(other, ns=bad), "ck_ai_agents_namespace_format"
        )
    for purposes in (
        "{}",
        "{evaluate,research,draft_section,evaluate}",
        "{summarise}",
        "{NULL}",
        "{evaluate,evaluate}",
        "{research,evaluate,research}",
        "{evaluate,draft_section,draft_section}",
    ):
        await _fails(
            db_session, INSERT_AGENT, _agent(other, purposes=purposes), "ck_ai_agents_purposes"
        )
    await _fails(db_session, INSERT_AGENT, _agent(other, protocol="a2a"), "ck_ai_agents_protocol")
    await _fails(
        db_session, INSERT_AGENT, _agent(other, display=""), "ck_ai_agents_display_name_not_empty"
    )
    await db_session.execute(INSERT_AGENT, _agent(other, name="x" * 63, ns="a"))
    await db_session.rollback()


async def test_one_active_run_per_idea_agent_kind_and_section(db_session: AsyncSession) -> None:
    idea_id, _ = await _idea_and_user(db_session)
    account = await _service_account(db_session, "agent@soundings.invalid")
    agent = _agent(account, purposes="{evaluate,research,draft_section}")
    await db_session.execute(INSERT_AGENT, agent)
    now = datetime.now(UTC)

    await db_session.execute(INSERT_RUN, _run(idea_id, agent["id"]))
    # Another active evaluate run for the same idea and agent: refused, queued or running.
    await _fails(db_session, INSERT_RUN, _run(idea_id, agent["id"]), "uq_ai_runs_active")
    await _fails(
        db_session,
        INSERT_RUN,
        _run(idea_id, agent["id"], status="running", started=now),
        "uq_ai_runs_active",
    )
    # Finished runs never block, and other kinds and sections are independent.
    await db_session.execute(
        INSERT_RUN,
        _run(idea_id, agent["id"], status="succeeded", started=now, finished=now),
    )
    await db_session.execute(INSERT_RUN, _run(idea_id, agent["id"], kind="research"))
    await db_session.execute(
        INSERT_RUN, _run(idea_id, agent["id"], kind="draft_section", section="risks")
    )
    await db_session.execute(
        INSERT_RUN, _run(idea_id, agent["id"], kind="draft_section", section="summary")
    )
    await _fails(
        db_session,
        INSERT_RUN,
        _run(idea_id, agent["id"], kind="draft_section", section="risks"),
        "uq_ai_runs_active",
    )
    await _fails(
        db_session, INSERT_RUN, _run(idea_id, agent["id"], kind="research"), "uq_ai_runs_active"
    )
    await db_session.rollback()


async def test_run_states_are_consistent(db_session: AsyncSession) -> None:
    idea_id, _ = await _idea_and_user(db_session)
    account = await _service_account(db_session, "agent@soundings.invalid")
    agent = _agent(account)
    await db_session.execute(INSERT_AGENT, agent)
    now = datetime.now(UTC)
    a = agent["id"]

    cases: list[tuple[dict[str, object], str]] = [
        (_run(idea_id, a, kind="draft_section"), "ck_ai_runs_section_iff_draft"),
        (_run(idea_id, a, kind="research", section="risks"), "ck_ai_runs_section_iff_draft"),
        (
            _run(idea_id, a, section="Appendix", kind="draft_section"),
            "ck_ai_runs_section_key_format",
        ),
        (_run(idea_id, a, status="succeeded", started=now), "ck_ai_runs_finished_iff_final"),
        (_run(idea_id, a, finished=now), "ck_ai_runs_finished_iff_final"),
        (_run(idea_id, a, status="running"), "ck_ai_runs_started_when_run"),
        (_run(idea_id, a, status="succeeded", finished=now), "ck_ai_runs_started_when_run"),
        (_run(idea_id, a, status="failed", finished=now), "ck_ai_runs_error_iff_failed"),
        (
            _run(idea_id, a, status="timed_out", finished=now, message="Timed out."),
            "ck_ai_runs_error_iff_failed",
        ),
        (
            _run(idea_id, a, status="cancelled", finished=now, error="timed_out", message="x"),
            "ck_ai_runs_error_iff_failed",
        ),
        (
            _run(idea_id, a, status="failed", finished=now, error="no_result"),
            "ck_ai_runs_error_message_with_code",
        ),
        (
            _run(idea_id, a, status="failed", finished=now, error="oops", message="x"),
            "ck_ai_runs_error_code",
        ),
        (_run(idea_id, a, status="paused", started=now, finished=now), "ck_ai_runs_status"),
        (_run(idea_id, a, kind="summarise"), "ck_ai_runs_kind"),
        (_run(idea_id, a, timeout=29), "ck_ai_runs_timeout_range"),
        (_run(idea_id, a, timeout=3601), "ck_ai_runs_timeout_range"),
        (
            _run(idea_id, a, kind="research", assigned=True),
            "ck_ai_runs_assigned_evaluator_evaluate",
        ),
    ]
    for values, constraint in cases:
        await _fails(db_session, INSERT_RUN, values, constraint)

    # A queued run cancelled or timed out in the queue never started.
    await db_session.execute(
        INSERT_RUN, _run(idea_id, a, status="cancelled", finished=now, assigned=True)
    )
    await db_session.execute(
        INSERT_RUN,
        _run(
            idea_id,
            a,
            status="timed_out",
            finished=now,
            error="queue_timeout",
            message="It waited too long to start.",
        ),
    )
    await db_session.rollback()


async def test_a_runs_result_matches_its_kind(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    account = await _service_account(db_session, "agent@soundings.invalid")
    agent = _agent(account)
    await db_session.execute(INSERT_AGENT, agent)
    project_id = await db_session.scalar(
        text("SELECT project_id FROM ideas WHERE id = :i"), {"i": idea_id}
    )
    event_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO activity_events (id, project_id, idea_id, actor_id, type, payload)"
            " VALUES (:id, :p, :i, :u, 'ai_research_note', CAST(:payload AS jsonb))"
        ),
        {
            "id": event_id,
            "p": project_id,
            "i": idea_id,
            "u": account,
            "payload": json.dumps({"body_md": "Notes", "sources": []}),
        },
    )
    await _fails(
        db_session,
        INSERT_RUN,
        _run(idea_id, agent["id"], kind="evaluate", event=event_id),
        "ck_ai_runs_result_matches_kind",
    )
    run = _run(idea_id, agent["id"], kind="research", event=event_id)
    await db_session.execute(INSERT_RUN, run)

    # Deleting what a run points at keeps the run (its result reference becomes null).
    await db_session.execute(text("DELETE FROM activity_events WHERE id = :e"), {"e": event_id})
    left = await db_session.scalar(
        text("SELECT activity_event_id FROM ai_runs WHERE id = :r"), {"r": run["id"]}
    )
    assert left is None

    # Deleting the idea deletes its runs and their events.
    await db_session.execute(
        text(
            "INSERT INTO ai_run_events (run_id, seq, type, message) VALUES (:r, 1, 'queued', 'x')"
        ),
        {"r": run["id"]},
    )
    await db_session.execute(text("DELETE FROM ideas WHERE id = :i"), {"i": idea_id})
    assert await db_session.scalar(text("SELECT count(*) FROM ai_runs")) == 0
    assert await db_session.scalar(text("SELECT count(*) FROM ai_run_events")) == 0
    assert user_id
    await db_session.rollback()


async def test_run_events_are_numbered_per_run_with_known_types(db_session: AsyncSession) -> None:
    idea_id, _ = await _idea_and_user(db_session)
    account = await _service_account(db_session, "agent@soundings.invalid")
    agent = _agent(account)
    await db_session.execute(INSERT_AGENT, agent)
    run = _run(idea_id, agent["id"])
    await db_session.execute(INSERT_RUN, run)
    insert = text(
        "INSERT INTO ai_run_events (run_id, seq, type, message) VALUES (:r, :seq, :type, :m)"
    )
    await db_session.execute(insert, {"r": run["id"], "seq": 1, "type": "queued", "m": "Queued"})

    await _fails(
        db_session,
        insert,
        {"r": run["id"], "seq": 1, "type": "started", "m": "Started"},
        "pk_ai_run_events",
    )
    await _fails(
        db_session,
        insert,
        {"r": run["id"], "seq": 0, "type": "started", "m": "Started"},
        "ck_ai_run_events_seq_positive",
    )
    await _fails(
        db_session,
        insert,
        {"r": run["id"], "seq": 2, "type": "thinking", "m": "Hmm"},
        "ck_ai_run_events_type",
    )
    await _fails(
        db_session,
        insert,
        {"r": run["id"], "seq": 2, "type": "started", "m": ""},
        "ck_ai_run_events_message_not_empty",
    )
    await db_session.rollback()


async def test_evaluation_scores_hold_at_most_five_sources(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    project_id = await db_session.scalar(
        text("SELECT project_id FROM ideas WHERE id = :i"), {"i": idea_id}
    )
    criterion_id, evaluation_id = uuid.uuid4(), uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO idea_evaluators (idea_id, user_id) VALUES (:i, :u)"),
        {"i": idea_id, "u": user_id},
    )
    await db_session.execute(
        text("INSERT INTO evaluations (id, idea_id, evaluator_id) VALUES (:e, :i, :u)"),
        {"e": evaluation_id, "i": idea_id, "u": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO rubric_criteria (id, project_id, position, name)"
            " VALUES (:c, :p, 0, 'Value')"
        ),
        {"c": criterion_id, "p": project_id},
    )
    insert = text(
        "INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, sources)"
        " VALUES (:e, :c, 4, CAST(:sources AS jsonb))"
    )
    source = {"title": "ONS retail sales", "url": "https://www.ons.gov.uk/"}

    for bad in (json.dumps([source] * 6), json.dumps(source), '"x"', "null"):
        await _fails(
            db_session,
            insert,
            {"e": evaluation_id, "c": criterion_id, "sources": bad},
            "ck_evaluation_scores_sources_array",
        )
    await db_session.execute(
        text(
            "INSERT INTO evaluation_scores (evaluation_id, criterion_id, score) VALUES (:e, :c, 4)"
        ),
        {"e": evaluation_id, "c": criterion_id},
    )
    default = await db_session.scalar(
        text("SELECT sources FROM evaluation_scores WHERE evaluation_id = :e"),
        {"e": evaluation_id},
    )
    assert default == []
    await db_session.execute(
        text("UPDATE evaluation_scores SET sources = CAST(:s AS jsonb)"),
        {"s": json.dumps([source] * 5)},
    )
    await db_session.rollback()


def test_0011_downgrade_drops_agents_runs_and_sources(scratch_database_url: str) -> None:  # noqa: F811
    """Going back below 0011 revokes every agent's key (older code doesn't confine it to
    its runs, c22) and deletes research notes (older code can't show them), then drops
    the AI tables and the sources column; people, evaluations, service accounts and other
    keys stay. Upgrading again recreates them matching the models."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "head")
    account, person, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        connection.execute(
            "INSERT INTO users (id, email, display_name, is_service_account)"
            " VALUES (%s, 'agent@soundings.invalid', 'Idea evaluator', true),"
            " (%s, 'person@example.com', 'Person', false)",
            (account, person),
        )
        connection.execute(
            "INSERT INTO ai_agents (id, display_name, namespace, name, protocol, purposes,"
            " service_account_id) VALUES (%s, 'Idea evaluator', 'soundings', 'evaluator',"
            " 'kagent_v0_10', '{evaluate}', %s)",
            (uuid.uuid4(), account),
        )
        for owner, lookup in ((account, "agentKey0001"), (person, "personKey001")):
            connection.execute(
                "INSERT INTO api_keys (id, user_id, name, lookup_id, secret_hash, scopes,"
                " created_auth_method) VALUES (%s, %s, 'Key', %s, %s, '{read,mcp}', 'sso')",
                (uuid.uuid4(), owner, lookup, "0" * 64),
            )
        connection.execute(
            "INSERT INTO projects (id, slug, key, name) VALUES (%s, 'demo', 'DEMO', 'D')",
            (project,),
        )
        connection.execute(
            "INSERT INTO activity_events (id, project_id, actor_id, type, payload) VALUES"
            " (%s, %s, %s, 'ai_research_note', '{}'), (%s, %s, %s, 'comment', '{}')",
            (uuid.uuid4(), project, account, uuid.uuid4(), project, person),
        )

    command.downgrade(config, "0010")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            " AND tablename LIKE 'ai\\_%'"
        ).fetchall()
        column = connection.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'evaluation_scores'"
            " AND column_name = 'sources'"
        ).fetchone()
        users = connection.execute("SELECT count(*) FROM users").fetchone()
        keys = connection.execute(
            "SELECT user_id, revoked_at IS NOT NULL FROM api_keys ORDER BY lookup_id"
        ).fetchall()
        events = connection.execute("SELECT type FROM activity_events").fetchall()
    assert tables == []
    assert column is None
    assert users == (2,)
    assert keys == [(account, True), (person, False)]
    assert events == [("comment",)]

    command.upgrade(config, "head")
    command.check(config)
