"""c22, the run scope of an agent's key (contract-phase6 section 3.5; role matrix c22).

An **open run** is a run of the principal's agent that is ``running`` and that nobody
asked to cancel. For a service-account principal (every service account is an agent's;
one without an agent row has no runs, so it can do nothing):

* REST is refused (:func:`app.authz.keys.check_route_for_key`: 403 ``insufficient_scope``);
* every MCP tool naming an idea must name the idea of an open run (else
  ``ai_run_not_active``; an idea it can't see stays ``not_found``, checked first);
  ``get_rubric`` by a project needs an open run on an idea there; ``list_projects`` and
  ``search_ideas`` list only the projects and ideas of its open runs;
* the only write is the open run's kind's tool (:data:`~app.schemas.ai.AGENT_RUN_WRITE_TOOLS`;
  ``propose_proposal_section`` only for the run's section); ``create_idea`` and
  ``add_comment`` are always ``forbidden``.

For people, c22 refuses only ``add_research_note`` (``forbidden``). So a cancelled,
timed-out or lost run is final: the agent can't finish later, and text planted in one
idea can't make it read or write another.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.ai import AiAgent, AiRun
from app.models.enums import AiRunKind, AiRunStatus, ProposalSectionKey
from app.models.idea import Idea
from app.schemas.ai import AGENT_READ_TOOLS, AGENT_RUN_WRITE_TOOLS

__all__ = [
    "RESEARCH_NOTE_TOOL",
    "RunNotActiveProblem",
    "is_agent",
    "open_run_ideas",
    "open_run_projects",
    "open_runs",
    "require_open_run",
    "require_open_run_in_project",
    "write_run",
]

RESEARCH_NOTE_TOOL: Final = AGENT_RUN_WRITE_TOOLS[AiRunKind.RESEARCH]
_KIND_OF_TOOL: Final = {tool: kind for kind, tool in AGENT_RUN_WRITE_TOOLS.items()}


class RunNotActiveProblem(ProblemError):
    """The MCP tool error ``ai_run_not_active`` (c22)."""

    def __init__(self) -> None:
        super().__init__(
            403,
            "ai_run_not_active",
            detail=(
                "This agent has no running Soundings AI run for that: its key works only "
                "during a run, on the run's idea, through the run's tool."
            ),
        )


def _forbidden() -> ProblemError:
    return ProblemError(403, "forbidden", detail="You don't have permission to do that.")


def is_agent(principal: Principal) -> bool:
    return principal.user.is_service_account


def _agent_id(principal: Principal) -> ColumnElement[UUID]:
    return (
        select(AiAgent.id).where(AiAgent.service_account_id == principal.user_id).scalar_subquery()
    )


def _open(principal: Principal) -> ColumnElement[bool]:
    return and_(
        AiRun.agent_id == _agent_id(principal),
        AiRun.status == AiRunStatus.RUNNING,
        AiRun.cancel_requested_at.is_(None),
    )


def open_run_ideas(principal: Principal) -> Select[UUID]:
    """Ids of the ideas of the principal's open runs (empty for people)."""
    return select(AiRun.idea_id).where(_open(principal))


def open_run_projects(principal: Principal) -> Select[UUID]:
    return select(Idea.project_id).where(Idea.id.in_(open_run_ideas(principal)))


async def open_runs(
    db: AsyncSession, principal: Principal, idea_id: UUID, kind: AiRunKind | None = None
) -> list[AiRun]:
    """The principal's open runs on the idea (of ``kind``), oldest first."""
    statement = select(AiRun).where(_open(principal), AiRun.idea_id == idea_id)
    if kind is not None:
        statement = statement.where(AiRun.kind == kind)
    return list(await db.scalars(statement.order_by(AiRun.created_at, AiRun.id)))


async def require_open_run(db: AsyncSession, principal: Principal, idea_id: UUID) -> None:
    """A read tool on an idea: an agent needs an open run there (people pass)."""
    if not is_agent(principal):
        return
    found = await db.scalar(select(AiRun.id).where(_open(principal), AiRun.idea_id == idea_id))
    if found is None:
        raise RunNotActiveProblem


async def require_open_run_in_project(
    db: AsyncSession, principal: Principal, project_id: UUID
) -> None:
    """``get_rubric`` by project: an agent needs an open run on an idea there."""
    if not is_agent(principal):
        return
    found = await db.scalar(
        select(AiRun.id)
        .join(Idea, Idea.id == AiRun.idea_id)
        .where(_open(principal), Idea.project_id == project_id)
        .limit(1)
    )
    if found is None:
        raise RunNotActiveProblem


async def write_run(
    db: AsyncSession,
    principal: Principal,
    tool: str,
    idea_id: UUID,
    section_key: ProposalSectionKey | None = None,
) -> AiRun | None:
    """c22 for a write tool, after the idea was loaded (``not_found`` first): for an agent,
    its open run of the tool's kind on the idea (and section), locked until commit, so a
    cancel request can't slip in between this check and attaching the result (lock order:
    project, idea, run); ``None`` for people. Refusals: ``forbidden`` (an agent's
    ``create_idea``, ``add_comment``, any tool that isn't a run's; a person's
    ``add_research_note``), ``ai_run_not_active`` (no such open run)."""
    if not is_agent(principal):
        if tool == RESEARCH_NOTE_TOOL:
            raise _forbidden()
        return None
    kind = _KIND_OF_TOOL.get(tool)
    if kind is None or tool in AGENT_READ_TOOLS:
        raise _forbidden()
    statement = select(AiRun).where(_open(principal), AiRun.idea_id == idea_id, AiRun.kind == kind)
    if kind is AiRunKind.DRAFT_SECTION:
        statement = statement.where(AiRun.section_key == section_key)
    run: AiRun | None = await db.scalar(
        statement.order_by(AiRun.created_at, AiRun.id)
        .limit(1)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise RunNotActiveProblem
    return run


def refuse_agent_write() -> ProblemError:
    """``create_idea`` and ``add_comment`` by an agent: always ``forbidden`` (c22)."""
    return _forbidden()
