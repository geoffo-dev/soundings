"""Phase 6: kagent AI assistance.

* ``ai_agents``: kagent agents registered by a platform admin: display name,
  description, kagent ``namespace`` and ``name`` (DNS-1123 labels, unique together; the
  A2A URL is built from ``SOUNDINGS_KAGENT_URL`` and them, never stored), ``protocol``
  (``kagent_v0_10`` | ``kagent_v1_0``), ``purposes`` (a ``varchar[]`` of 1-3
  ``evaluate | research | draft_section``, each at most once), the service account it
  acts as (``service_account_id``, unique), ``enabled`` and who registered it.
* ``ai_agent_projects``: the projects each agent serves (cascade with either side).
* ``ai_runs``: one AI job on an idea (kind, the section for ``draft_section``, who asked,
  status ``queued | running | succeeded | failed | cancelled | timed_out``, timeout,
  timestamps and heartbeat, cancel request, the agent's A2A task and context ids, a
  sanitised error code and message, the event counter, the result: an evaluation, a
  proposal suggestion or the research note's activity event (each indexed where set, for
  the ``ON DELETE SET NULL`` cascades), and ``assigned_evaluator``: the run's request made
  the agent the idea's evaluator). At most one active run per idea, agent, kind and
  section (``uq_ai_runs_active``, NULLS NOT DISTINCT).
* ``ai_run_events``: each run's progress events, numbered from 1 (the SSE event ids).
* ``evaluation_scores.sources``: an AI evaluator's cited sources per criterion (a JSON
  array of at most five ``{title, url}`` objects; ``'[]'`` for every existing row).

Research notes need no table: they are ``activity_events`` rows of type
``ai_research_note`` (the note's Markdown and sources in ``payload``). The audit log
needs no change.

Downgrade first **revokes every agent's API key** (below 0011 nothing limits an agent's
key to its runs, c22, so a kept key would act as a full project member) and deletes the
research notes (``activity_events`` of type ``ai_research_note``, which older code
can't show), then drops the four tables and ``evaluation_scores.sources``: registered
agents, run history and every AI evaluation's cited sources are lost (the evaluations
themselves and the service accounts stay; their keys stay listed, revoked).

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase6.md.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABEL = r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$"
KINDS = ("evaluate", "research", "draft_section")
KINDS_SQL = "ARRAY['evaluate', 'research', 'draft_section']::varchar[]"
PROTOCOLS = ("kagent_v0_10", "kagent_v1_0")
STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "timed_out")
ACTIVE = "status IN ('queued', 'running')"
PURPOSES_DISTINCT = (
    "(cardinality(purposes) < 2 OR purposes[1] <> purposes[2])"
    " AND (cardinality(purposes) < 3"
    " OR (purposes[1] <> purposes[3] AND purposes[2] <> purposes[3]))"
)
SECTION_KEYS = (
    "summary",
    "problem",
    "solution",
    "market",
    "cost",
    "benefits",
    "risks",
    "next_steps",
)
EVENT_TYPES = (
    "queued",
    "started",
    "retrying",
    "agent_accepted",
    "agent_working",
    "tool_called",
    "result_recorded",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)
ERRORS = (
    "ai_disabled",
    "agent_unavailable",
    "agent_unreachable",
    "agent_protocol_error",
    "agent_rejected",
    "agent_failed",
    "agent_needs_input",
    "no_result",
    "timed_out",
    "queue_timeout",
    "worker_lost",
    "internal_error",
)


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_values(values)})", name=op.f(name))


def _fk(
    column: str, target: str, name: str, ondelete: str | None = "CASCADE"
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=op.f(name), ondelete=ondelete)


def _length(values: Sequence[str]) -> int:
    return max(len(value) for value in values)


def _ai_agents() -> None:
    op.create_table(
        "ai_agents",
        _id(),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("namespace", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("protocol", sa.String(length=_length(PROTOCOLS)), nullable=False),
        sa.Column("purposes", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("service_account_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(f"namespace ~ '{LABEL}'", name=op.f("ck_ai_agents_namespace_format")),
        sa.CheckConstraint(f"name ~ '{LABEL}'", name=op.f("ck_ai_agents_name_format")),
        sa.CheckConstraint(
            "length(display_name) > 0", name=op.f("ck_ai_agents_display_name_not_empty")
        ),
        sa.CheckConstraint(
            f"cardinality(purposes) BETWEEN 1 AND 3 AND purposes <@ {KINDS_SQL}"
            f" AND array_position(purposes, NULL) IS NULL AND {PURPOSES_DISTINCT}",
            name=op.f("ck_ai_agents_purposes"),
        ),
        _enum_check("protocol", PROTOCOLS, "ck_ai_agents_protocol"),
        _fk("service_account_id", "users.id", "fk_ai_agents_service_account_id_users", None),
        _fk("created_by_id", "users.id", "fk_ai_agents_created_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_agents")),
        sa.UniqueConstraint("namespace", "name", name=op.f("uq_ai_agents_namespace_name")),
        sa.UniqueConstraint("service_account_id", name=op.f("uq_ai_agents_service_account_id")),
    )


def _ai_agent_projects() -> None:
    op.create_table(
        "ai_agent_projects",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _fk("agent_id", "ai_agents.id", "fk_ai_agent_projects_agent_id_ai_agents"),
        _fk("project_id", "projects.id", "fk_ai_agent_projects_project_id_projects"),
        sa.PrimaryKeyConstraint("agent_id", "project_id", name=op.f("pk_ai_agent_projects")),
    )
    op.create_index(op.f("ix_ai_agent_projects_project_id"), "ai_agent_projects", ["project_id"])


def _ai_runs() -> None:
    op.create_table(
        "ai_runs",
        _id(),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=_length(KINDS)), nullable=False),
        sa.Column("section_key", sa.String(length=_length(SECTION_KEYS)), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=_length(STATUSES)),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        _timestamp("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("a2a_task_id", sa.String(length=200), nullable=True),
        sa.Column("a2a_context_id", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=_length(ERRORS)), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("suggestion_id", sa.Uuid(), nullable=True),
        sa.Column("activity_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "assigned_evaluator", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        _enum_check("kind", KINDS, "ck_ai_runs_kind"),
        _enum_check("section_key", SECTION_KEYS, "ck_ai_runs_section_key"),
        _enum_check("status", STATUSES, "ck_ai_runs_status"),
        _enum_check("error_code", ERRORS, "ck_ai_runs_error_code"),
        sa.CheckConstraint(
            "(kind = 'draft_section') = (section_key IS NOT NULL)",
            name=op.f("ck_ai_runs_section_iff_draft"),
        ),
        sa.CheckConstraint(
            f"({ACTIVE}) = (finished_at IS NULL)", name=op.f("ck_ai_runs_finished_iff_final")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'cancelled', 'timed_out', 'failed') OR started_at IS NOT NULL",
            name=op.f("ck_ai_runs_started_when_run"),
        ),
        sa.CheckConstraint(
            "(status IN ('failed', 'timed_out')) = (error_code IS NOT NULL)",
            name=op.f("ck_ai_runs_error_iff_failed"),
        ),
        sa.CheckConstraint(
            "(error_code IS NULL) = (error_message IS NULL)",
            name=op.f("ck_ai_runs_error_message_with_code"),
        ),
        sa.CheckConstraint(
            "(evaluation_id IS NULL OR kind = 'evaluate')"
            " AND (suggestion_id IS NULL OR kind = 'draft_section')"
            " AND (activity_event_id IS NULL OR kind = 'research')",
            name=op.f("ck_ai_runs_result_matches_kind"),
        ),
        sa.CheckConstraint(
            "timeout_seconds BETWEEN 30 AND 3600", name=op.f("ck_ai_runs_timeout_range")
        ),
        sa.CheckConstraint("event_count >= 0", name=op.f("ck_ai_runs_event_count_positive")),
        sa.CheckConstraint(
            "cancel_requested_by_id IS NULL OR cancel_requested_at IS NOT NULL",
            name=op.f("ck_ai_runs_cancel_requested_by_needs_at"),
        ),
        sa.CheckConstraint(
            "NOT assigned_evaluator OR kind = 'evaluate'",
            name=op.f("ck_ai_runs_assigned_evaluator_evaluate"),
        ),
        _fk("idea_id", "ideas.id", "fk_ai_runs_idea_id_ideas"),
        _fk("agent_id", "ai_agents.id", "fk_ai_runs_agent_id_ai_agents", None),
        _fk("requested_by_id", "users.id", "fk_ai_runs_requested_by_id_users", "SET NULL"),
        _fk(
            "cancel_requested_by_id",
            "users.id",
            "fk_ai_runs_cancel_requested_by_id_users",
            "SET NULL",
        ),
        _fk("evaluation_id", "evaluations.id", "fk_ai_runs_evaluation_id_evaluations", "SET NULL"),
        _fk(
            "suggestion_id",
            "proposal_suggestions.id",
            "fk_ai_runs_suggestion_id_proposal_suggestions",
            "SET NULL",
        ),
        _fk(
            "activity_event_id",
            "activity_events.id",
            "fk_ai_runs_activity_event_id_activity_events",
            "SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
    )
    op.create_index(op.f("ix_ai_runs_agent_id"), "ai_runs", ["agent_id"])
    op.create_index(
        "uq_ai_runs_active",
        "ai_runs",
        ["idea_id", "agent_id", "kind", "section_key"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text(ACTIVE),
    )
    op.create_index("ix_ai_runs_idea_id_created_at", "ai_runs", ["idea_id", "created_at"])
    op.create_index(
        "ix_ai_runs_created_at_active",
        "ai_runs",
        ["created_at"],
        postgresql_where=sa.text(ACTIVE),
    )
    op.create_index(
        "ix_ai_runs_requested_by_id_created_at", "ai_runs", ["requested_by_id", "created_at"]
    )
    for column in ("evaluation_id", "suggestion_id", "activity_event_id"):
        op.create_index(
            f"ix_ai_runs_{column}",
            "ai_runs",
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )


def _ai_run_events() -> None:
    op.create_table(
        "ai_run_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=_length(EVENT_TYPES)), nullable=False),
        sa.Column("message", sa.String(length=200), nullable=False),
        _timestamp("created_at"),
        _enum_check("type", EVENT_TYPES, "ck_ai_run_events_type"),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_ai_run_events_seq_positive")),
        sa.CheckConstraint("length(message) > 0", name=op.f("ck_ai_run_events_message_not_empty")),
        _fk("run_id", "ai_runs.id", "fk_ai_run_events_run_id_ai_runs"),
        sa.PrimaryKeyConstraint("run_id", "seq", name=op.f("pk_ai_run_events")),
    )


def _evaluation_sources() -> None:
    op.add_column(
        "evaluation_scores",
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_evaluation_scores_sources_array"),
        "evaluation_scores",
        "CASE WHEN jsonb_typeof(sources) = 'array'"
        " THEN jsonb_array_length(sources) <= 5 ELSE false END",
    )


def upgrade() -> None:
    _ai_agents()
    _ai_agent_projects()
    _ai_runs()
    _ai_run_events()
    _evaluation_sources()


def downgrade() -> None:
    # Older code doesn't confine agents' keys to their runs (c22): revoke them all.
    op.execute(
        "UPDATE api_keys SET revoked_at = now()"
        " WHERE revoked_at IS NULL"
        " AND user_id IN (SELECT service_account_id FROM ai_agents)"
    )
    # Older code can't show research notes (and would show nothing in their place).
    op.execute("DELETE FROM activity_events WHERE type = 'ai_research_note'")
    op.drop_constraint(
        op.f("ck_evaluation_scores_sources_array"), "evaluation_scores", type_="check"
    )
    op.drop_column("evaluation_scores", "sources")
    op.drop_table("ai_run_events")
    op.drop_table("ai_runs")
    op.drop_table("ai_agent_projects")
    op.drop_table("ai_agents")
