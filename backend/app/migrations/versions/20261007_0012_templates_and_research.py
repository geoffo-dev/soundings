"""Phase 8: per-project proposal templates and the research step.

* ``proposal_template_sections``: each project's proposal template, 1-12 active sections
  in ``position`` order (key, title, hint; ``archived_at`` set = removed, its text kept).
  Keys are unique per project (archived ones included) and match
  ``^[a-z][a-z0-9_]{0,39}$``; active titles are unique per project, any case. **Every
  existing project gets today's eight sections** (``summary`` ... ``next_steps``, the
  titles and hints of the fixed template, positions 0-7), so every proposal, thread,
  suggestion and AI run keeps pointing at a section of its project.
* ``proposal_sections.key``, ``proposal_threads.section_key``,
  ``proposal_suggestions.section_key`` and ``ai_runs.section_key``: from the fixed
  eight-key ``CHECK`` (``varchar(10)``) to ``varchar(40)`` with a format ``CHECK``
  (``ck_<table>_<column>_format``). Existing rows are untouched (their keys are the
  defaults' keys). No foreign key to the template: keys are immutable and a key anything
  refers to is archived, never deleted (contract-phase8 section 2.6).
* ``projects.research_step``: ``off`` (every existing project) | ``before_evaluation`` |
  ``before_proposal``.
* ``ideas.status`` gains ``research`` (the ``CHECK`` is swapped; ``varchar(11)`` already
  fits it).
* ``research_checklist_items``: each project's research checklist (title, hint,
  required, position, archived_at). Empty for every existing project: the defaults are
  offered when a project admin turns the step on.
* ``research_answers``: one free-text answer (1-2,000 characters) per idea and item, with
  who answered first and when, and who changed it last and when.

Downgrade (below 0012 there is one fixed template and no Research status):

1. Ideas in Research move back to the stage before it (``new``, or ``shortlisted`` for a
   ``before_proposal`` project), and ``from_status`` / ``to_status`` values ``research``
   in activity events, notifications and outbox payloads are rewritten the same way
   (older code can't read the status). ``research`` label overrides are removed. Known
   effects, accepted for an emergency path: a move into or out of Research may become a
   no-op line in the feed ("Shortlisted -> Shortlisted"), and a pending team email (an
   outbox row without an idea: only submitter emails name one) gets ``new`` whatever its
   project's step was.
2. The research tables and ``projects.research_step`` are dropped: **every research
   answer and checklist is lost**.
3. AI runs, suggestions, margin threads (with their comments) and section texts of
   sections that aren't one of the eight defaults are **deleted** (their text is lost);
   every proposal gets back a row for each of the eight defaults it lacks (empty), so the
   fixed template is whole again (a default section a project had removed reappears with
   its text). Then the key columns get their eight-key ``CHECK`` back and the template
   table is dropped.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase8.md.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-07
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SECTION_KEY = r"^[a-z][a-z0-9_]{0,39}$"
SECTION_KEY_LENGTH = 40
DEFAULT_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("summary", "Summary", "The idea in a few sentences: what we would do and why it matters."),
    ("problem", "Problem", "Who has this problem, and how do we know?"),
    (
        "solution",
        "Solution",
        "Describe what we would build or change, and how it solves the problem.",
    ),
    (
        "market",
        "Market & users",
        "Who would use or buy this, how many of them are there, and how do we reach them?",
    ),
    ("cost", "Cost & effort", "What would it take: people, time, money and dependencies?"),
    (
        "benefits",
        "Benefits / revenue",
        "What do we gain: revenue, savings or other benefits, and how will we measure them?",
    ),
    ("risks", "Risks", "What could go wrong, and how would we reduce it?"),
    ("next_steps", "Next steps / the ask", "What do you need, from whom, and by when?"),
)
"""The fixed template of Phases 4-7 (``app.schemas.proposals.DEFAULT_PROPOSAL_TEMPLATE``),
spelled out here: a migration must not import app code that may change."""
DEFAULT_KEYS = tuple(key for key, _, _ in DEFAULT_SECTIONS)
OLD_KEY_LENGTH = max(len(key) for key in DEFAULT_KEYS)  # 10: "next_steps"

STATUSES_BEFORE = ("new", "evaluating", "shortlisted", "proposal", "closed")
STATUSES = ("new", "research", "evaluating", "shortlisted", "proposal", "closed")
RESEARCH_STEPS = ("off", "before_evaluation", "before_proposal")

KEY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("proposal_sections", "key"),
    ("proposal_threads", "section_key"),
    ("proposal_suggestions", "section_key"),
    ("ai_runs", "section_key"),
)
"""Every column that names a proposal section (``ck_<table>_<column>`` was the eight-key
check; ``ck_<table>_<column>_format`` is the new one)."""

ACTIVE_RUNS = "status IN ('queued', 'running')"

PAYLOAD_TABLES = ("activity_events", "notifications", "outbound_email")
"""Tables whose JSON ``payload`` may hold ``from_status`` / ``to_status`` (status changes)."""


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# --- Upgrade ---------------------------------------------------------------------------
def _research_step() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "research_step",
            sa.String(length=max(len(step) for step in RESEARCH_STEPS)),
            server_default="off",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_projects_research_step"),
        "projects",
        f"research_step IN ({_values(RESEARCH_STEPS)})",
    )


def _idea_statuses(statuses: Sequence[str]) -> None:
    op.drop_constraint(op.f("ck_ideas_status"), "ideas", type_="check")
    op.create_check_constraint(op.f("ck_ideas_status"), "ideas", f"status IN ({_values(statuses)})")


def _template_sections() -> None:
    op.create_table(
        "proposal_template_sections",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=SECTION_KEY_LENGTH), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column("hint", sa.String(length=200), server_default="", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            f"key ~ '{SECTION_KEY}'", name=op.f("ck_proposal_template_sections_key_format")
        ),
        sa.CheckConstraint(
            "length(title) > 0", name=op.f("ck_proposal_template_sections_title_not_empty")
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_proposal_template_sections_position_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_proposal_template_sections_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_template_sections")),
        sa.UniqueConstraint(
            "project_id", "key", name=op.f("uq_proposal_template_sections_project_id_key")
        ),
    )
    op.create_index(
        "ix_proposal_template_sections_project_id_position",
        "proposal_template_sections",
        ["project_id", "position"],
    )
    op.create_index(
        "uq_proposal_template_sections_project_id_title_lower",
        "proposal_template_sections",
        ["project_id", sa.text("lower(title)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    rows = ", ".join(
        f"({position}, {_sql_text(key)}, {_sql_text(title)}, {_sql_text(hint)})"
        for position, (key, title, hint) in enumerate(DEFAULT_SECTIONS)
    )
    op.execute(
        "INSERT INTO proposal_template_sections (id, project_id, key, title, hint, position)"  # noqa: S608
        " SELECT gen_random_uuid(), projects.id, d.key, d.title, d.hint, d.position"
        f" FROM projects CROSS JOIN (VALUES {rows}) AS d (position, key, title, hint)"
    )


def _drop_active_runs_index() -> None:
    """``uq_ai_runs_active`` covers ``ai_runs.section_key``: Postgres would keep it across
    the type change with its predicate re-written, so it is dropped and created again as
    the model defines it."""
    op.drop_index("uq_ai_runs_active", table_name="ai_runs")


def _create_active_runs_index() -> None:
    op.create_index(
        "uq_ai_runs_active",
        "ai_runs",
        ["idea_id", "agent_id", "kind", "section_key"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text(ACTIVE_RUNS),
    )


def _key_columns_to_template_keys() -> None:
    _drop_active_runs_index()
    for table, column in KEY_COLUMNS:
        op.drop_constraint(op.f(f"ck_{table}_{column}"), table, type_="check")
        op.alter_column(
            table,
            column,
            type_=sa.String(length=SECTION_KEY_LENGTH),
            existing_type=sa.String(length=OLD_KEY_LENGTH),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_{column}_format"), table, f"{column} ~ '{SECTION_KEY}'"
        )
    _create_active_runs_index()


def _research_tables() -> None:
    op.create_table(
        "research_checklist_items",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("hint", sa.String(length=200), server_default="", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "length(title) > 0", name=op.f("ck_research_checklist_items_title_not_empty")
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_research_checklist_items_position_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_research_checklist_items_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_checklist_items")),
    )
    op.create_index(
        "ix_research_checklist_items_project_id_position",
        "research_checklist_items",
        ["project_id", "position"],
    )
    op.create_index(
        "uq_research_checklist_items_project_id_title_lower",
        "research_checklist_items",
        ["project_id", sa.text("lower(title)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_table(
        "research_answers",
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("answered_by_id", sa.Uuid(), nullable=True),
        _timestamp("answered_at"),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "length(answer) BETWEEN 1 AND 2000", name=op.f("ck_research_answers_answer_length")
        ),
        sa.ForeignKeyConstraint(
            ["idea_id"],
            ["ideas.id"],
            name=op.f("fk_research_answers_idea_id_ideas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["research_checklist_items.id"],
            name=op.f("fk_research_answers_item_id_research_checklist_items"),
        ),
        sa.ForeignKeyConstraint(
            ["answered_by_id"],
            ["users.id"],
            name=op.f("fk_research_answers_answered_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_research_answers_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("idea_id", "item_id", name=op.f("pk_research_answers")),
    )
    op.create_index(op.f("ix_research_answers_item_id"), "research_answers", ["item_id"])


def upgrade() -> None:
    _research_step()
    _idea_statuses(STATUSES)
    _template_sections()
    _key_columns_to_template_keys()
    _research_tables()


# --- Downgrade -------------------------------------------------------------------------
_STAGE_BEFORE_RESEARCH = (
    "CASE WHEN projects.research_step = 'before_proposal' THEN 'shortlisted' ELSE 'new' END"
)
"""The stage an idea in Research goes back to (the one before Research in its project)."""


def _ideas_out_of_research() -> None:
    for table in PAYLOAD_TABLES:
        for key in ("from_status", "to_status"):
            op.execute(
                f"UPDATE {table} SET payload = jsonb_set(payload, '{{{key}}}',"  # noqa: S608
                f" to_jsonb({_STAGE_BEFORE_RESEARCH}::text))"
                f" FROM ideas JOIN projects ON projects.id = ideas.project_id"
                f" WHERE {table}.idea_id = ideas.id AND {table}.payload->>'{key}' = 'research'"
            )
        op.execute(
            f"UPDATE {table} SET payload = jsonb_set(payload, '{{to_status}}', '\"new\"')"  # noqa: S608
            f" WHERE idea_id IS NULL AND payload->>'to_status' = 'research'"
        )
        op.execute(
            f"UPDATE {table} SET payload = jsonb_set(payload, '{{from_status}}', '\"new\"')"  # noqa: S608
            f" WHERE idea_id IS NULL AND payload->>'from_status' = 'research'"
        )
    op.execute(
        f"UPDATE ideas SET status = {_STAGE_BEFORE_RESEARCH}"  # noqa: S608
        " FROM projects WHERE projects.id = ideas.project_id AND ideas.status = 'research'"
    )
    op.execute("UPDATE projects SET status_labels = status_labels - 'research'")


def _back_to_the_fixed_template() -> None:
    custom = f"NOT IN ({_values(DEFAULT_KEYS)})"
    op.execute(f"DELETE FROM ai_runs WHERE section_key {custom}")  # noqa: S608
    op.execute(f"DELETE FROM proposal_suggestions WHERE section_key {custom}")  # noqa: S608
    op.execute(f"DELETE FROM proposal_threads WHERE section_key {custom}")  # noqa: S608
    op.execute(f"DELETE FROM proposal_sections WHERE key {custom}")  # noqa: S608
    keys = ", ".join(f"({_sql_text(key)})" for key in DEFAULT_KEYS)
    op.execute(
        "INSERT INTO proposal_sections (proposal_id, key)"  # noqa: S608
        f" SELECT proposals.id, d.key FROM proposals CROSS JOIN (VALUES {keys}) AS d (key)"
        " ON CONFLICT DO NOTHING"
    )
    _drop_active_runs_index()
    for table, column in KEY_COLUMNS:
        op.drop_constraint(op.f(f"ck_{table}_{column}_format"), table, type_="check")
        op.alter_column(
            table,
            column,
            type_=sa.String(length=OLD_KEY_LENGTH),
            existing_type=sa.String(length=SECTION_KEY_LENGTH),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_{column}"), table, f"{column} IN ({_values(DEFAULT_KEYS)})"
        )
    _create_active_runs_index()
    op.drop_table("proposal_template_sections")


def downgrade() -> None:
    _ideas_out_of_research()
    op.drop_table("research_answers")
    op.drop_table("research_checklist_items")
    _back_to_the_fixed_template()
    _idea_statuses(STATUSES_BEFORE)
    op.drop_constraint(op.f("ck_projects_research_step"), "projects", type_="check")
    op.drop_column("projects", "research_step")
