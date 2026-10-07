"""kagent AI assistance (SPEC section 9; contract-phase6): registered agents, the projects
they serve, AI runs and their progress events.

* ``ai_agents``: a kagent agent a platform admin registered (Admin settings -> AI agents):
  its kagent ``namespace`` and ``name`` (Kubernetes labels; the A2A URL is **built** from
  ``SOUNDINGS_KAGENT_URL`` and these, never stored or taken from a request, so no
  arbitrary host can be reached), the protocol layout, the purposes it serves and the
  service account (``users.is_service_account``) it acts as on Soundings' MCP server.
  Agents are disabled (which revokes their key), never deleted (their evaluations and
  runs keep their author).
* ``ai_agent_projects``: the projects an agent serves. Its key is restricted to exactly
  these, and the service account is a member of them (contract-phase6 section 3.1).
* ``ai_runs``: one request to an agent ("Ask AI to evaluate", "Research this", "Draft
  section"), executed by the worker over A2A with a hard deadline and cooperative cancel.
  At most one active run (``queued`` / ``running``) per idea, agent, kind and section
  (``uq_ai_runs_active``). The result is a reference to what the agent recorded through
  MCP: an evaluation, a research note (an ``activity_events`` row of type
  ``ai_research_note``) or a proposal suggestion. A ``running`` run that nobody asked to
  cancel is also what lets the agent's key do anything at all (c22, run scope).
  Every status change is a compare-and-set (``UPDATE ... WHERE id = :id AND status IN
  (...) RETURNING``); a write that also touches the idea locks project, idea, then run.
* ``ai_run_events``: a run's progress, numbered from 1, replayed to SSE clients after
  ``Last-Event-ID``. Messages are Soundings' own sentences (never the agent's text, never
  score data).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import (
    AiAgentProtocol,
    AiRunError,
    AiRunEventType,
    AiRunKind,
    AiRunStatus,
)
from app.models.proposal import SECTION_KEY_MAX_LENGTH, SECTION_KEY_PATTERN
from app.models.types import str_enum

__all__ = [
    "AI_RUN_ACTIVE_STATUSES_SQL",
    "KUBERNETES_LABEL_PATTERN",
    "AiAgent",
    "AiAgentProject",
    "AiRun",
    "AiRunEvent",
]

KUBERNETES_LABEL_PATTERN = r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$"
"""A DNS-1123 label (1-63 characters): kagent namespaces and agent names. Only these
characters reach the A2A URL path, so a name can't add a path, query or host."""

AI_RUN_KINDS_SQL = "ARRAY['evaluate', 'research', 'draft_section']::varchar[]"
"""The ``AiRunKind`` values as a SQL array, for the ``purposes`` check."""

AI_RUN_ACTIVE_STATUSES_SQL = "status IN ('queued', 'running')"
"""An active run: the partial indexes' predicate."""

AI_PURPOSES_DISTINCT_SQL = (
    "(cardinality(purposes) < 2 OR purposes[1] <> purposes[2])"
    " AND (cardinality(purposes) < 3"
    " OR (purposes[1] <> purposes[3] AND purposes[2] <> purposes[3]))"
)
"""No purpose twice (at most three, so three comparisons; a CHECK can't use a subquery)."""


class AiAgent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered kagent agent and the service account it acts as."""

    __tablename__ = "ai_agents"
    __table_args__ = (
        UniqueConstraint("namespace", "name"),
        CheckConstraint(f"namespace ~ '{KUBERNETES_LABEL_PATTERN}'", name="namespace_format"),
        CheckConstraint(f"name ~ '{KUBERNETES_LABEL_PATTERN}'", name="name_format"),
        CheckConstraint("length(display_name) > 0", name="display_name_not_empty"),
        CheckConstraint(
            f"cardinality(purposes) BETWEEN 1 AND 3 AND purposes <@ {AI_RUN_KINDS_SQL}"
            f" AND array_position(purposes, NULL) IS NULL AND {AI_PURPOSES_DISTINCT_SQL}",
            name="purposes",
        ),
    )

    # One line; also the service account's display name (what people see next to its
    # evaluations, notes and suggestions, with an AI badge).
    display_name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    # The kagent Agent resource: metadata.namespace and metadata.name.
    namespace: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(63))
    protocol: Mapped[AiAgentProtocol] = mapped_column(str_enum(AiAgentProtocol, "protocol"))
    # AiRunKind values, canonical order (evaluate, research, draft_section), no duplicates.
    purposes: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    # The users row it acts as (is_service_account); one agent per service account.
    # NO ACTION: users are deactivated, never deleted.
    service_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    # Disabled: no new runs, active runs are cancelled, its key is revoked (enabling it
    # again needs a key rotation).
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AiAgentProject(Base):
    """A project an agent serves (the platform admin's grant)."""

    __tablename__ = "ai_agent_projects"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_agents.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AiRun(UUIDPrimaryKeyMixin, Base):
    """One AI job on one idea, from request to a final status (contract-phase6 section 3.3)."""

    __tablename__ = "ai_runs"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'draft_section') = (section_key IS NOT NULL)", name="section_iff_draft"
        ),
        CheckConstraint(f"section_key ~ '{SECTION_KEY_PATTERN}'", name="section_key_format"),
        CheckConstraint(
            f"({AI_RUN_ACTIVE_STATUSES_SQL}) = (finished_at IS NULL)",
            name="finished_iff_final",
        ),
        CheckConstraint(
            "status IN ('queued', 'cancelled', 'timed_out', 'failed') OR started_at IS NOT NULL",
            name="started_when_run",
        ),
        CheckConstraint(
            "(status IN ('failed', 'timed_out')) = (error_code IS NOT NULL)",
            name="error_iff_failed",
        ),
        CheckConstraint(
            "(error_code IS NULL) = (error_message IS NULL)", name="error_message_with_code"
        ),
        CheckConstraint(
            "(evaluation_id IS NULL OR kind = 'evaluate')"
            " AND (suggestion_id IS NULL OR kind = 'draft_section')"
            " AND (activity_event_id IS NULL OR kind = 'research')",
            name="result_matches_kind",
        ),
        CheckConstraint("timeout_seconds BETWEEN 30 AND 3600", name="timeout_range"),
        CheckConstraint("event_count >= 0", name="event_count_positive"),
        CheckConstraint(
            "cancel_requested_by_id IS NULL OR cancel_requested_at IS NOT NULL",
            name="cancel_requested_by_needs_at",
        ),
        CheckConstraint(
            "NOT assigned_evaluator OR kind = 'evaluate'", name="assigned_evaluator_evaluate"
        ),
        # Idempotency: one active run per idea, agent, kind and section (sections are
        # null for evaluate and research, and NULLs count as equal here).
        Index(
            "uq_ai_runs_active",
            "idea_id",
            "agent_id",
            "kind",
            "section_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text(AI_RUN_ACTIVE_STATUSES_SQL),
        ),
        # The idea's run list, newest first.
        Index("ix_ai_runs_idea_id_created_at", "idea_id", "created_at"),
        # The sweep (stale running runs, queued runs past the queue timeout).
        Index(
            "ix_ai_runs_created_at_active",
            "created_at",
            postgresql_where=text(AI_RUN_ACTIVE_STATUSES_SQL),
        ),
        # The per-person request limit (runs requested in the last hour).
        Index("ix_ai_runs_requested_by_id_created_at", "requested_by_id", "created_at"),
        # The result references are ON DELETE SET NULL: without these, deleting an
        # evaluation, a suggestion or an activity event would scan every run.
        Index(
            "ix_ai_runs_evaluation_id",
            "evaluation_id",
            postgresql_where=text("evaluation_id IS NOT NULL"),
        ),
        Index(
            "ix_ai_runs_suggestion_id",
            "suggestion_id",
            postgresql_where=text("suggestion_id IS NOT NULL"),
        ),
        Index(
            "ix_ai_runs_activity_event_id",
            "activity_event_id",
            postgresql_where=text("activity_event_id IS NOT NULL"),
        ),
    )

    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"))
    # NO ACTION: agents are disabled, never deleted.
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_agents.id"), index=True)
    kind: Mapped[AiRunKind] = mapped_column(str_enum(AiRunKind, "kind"))
    # draft_section only: the key of the template section to draft (Phase 8: a section
    # of the idea's project's template; runs of a section removed later keep its key).
    section_key: Mapped[str | None] = mapped_column(String(SECTION_KEY_MAX_LENGTH))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[AiRunStatus] = mapped_column(
        str_enum(AiRunStatus, "status"),
        default=AiRunStatus.QUEUED,
        server_default=AiRunStatus.QUEUED.value,
    )
    # SOUNDINGS_AI_RUN_TIMEOUT when it was requested: the deadline is started_at + this.
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Written by the worker every 15 seconds while running; the sweep fails a run whose
    # heartbeat is 2 minutes old (worker_lost).
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # The agent's A2A task and context, once it created them (for tasks/get, tasks/cancel);
    # an id longer than 200 characters is agent_protocol_error, never stored.
    a2a_task_id: Mapped[str | None] = mapped_column(String(200))
    a2a_context_id: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[AiRunError | None] = mapped_column(str_enum(AiRunError, "error_code"))
    # Soundings' own sentence for the code (with at most an HTTP status or an A2A state
    # name in it): never the agent's text, a URL, a token or a stack trace.
    error_message: Mapped[str | None] = mapped_column(String(300))
    # How many events it has (the last event's seq): "UPDATE ... SET event_count =
    # event_count + 1 RETURNING event_count" numbers the next event without a race.
    event_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # The result the agent recorded through MCP (by kind; kept if the run later fails).
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evaluations.id", ondelete="SET NULL")
    )
    suggestion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proposal_suggestions.id", ondelete="SET NULL")
    )
    # research: the ai_research_note activity event that holds the note (the API's
    # note_id).
    activity_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activity_events.id", ondelete="SET NULL")
    )
    # evaluate: this run's request assigned the agent as the idea's evaluator. If the run
    # ends without the agent's submitted evaluation, the worker removes that assignment
    # (and the agent's draft), so it never waits for an evaluation that won't come.
    assigned_evaluator: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )


class AiRunEvent(Base):
    """One progress step of a run (``seq`` 1, 2, ...): the SSE event id."""

    __tablename__ = "ai_run_events"
    __table_args__ = (
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("length(message) > 0", name="message_not_empty"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[AiRunEventType] = mapped_column(str_enum(AiRunEventType, "type"))
    # Soundings' own sentence ("Read the idea", "Submitted the evaluation"): never the
    # agent's text, never score data.
    message: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
