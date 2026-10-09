"""c22, the run scope of an agent's key (contract-phase6 sections 3.5 and 10; role matrix
c22).

An **open run** is a run of the principal's agent that is ``running`` and that nobody
asked to cancel. Every call an agent makes **names its run** (the tools' ``run_id``
argument, from the run's message), and reaches only that run's idea. For a
service-account principal (every service account is an agent's; one without an agent row
has no runs, so it can do nothing):

* REST is refused (:func:`app.authz.keys.check_route_for_key`: 403 ``insufficient_scope``);
* **the run comes first**, before anything is looked up: a tool naming an idea (or
  ``get_rubric`` a project) needs ``run_id`` to name one of its open runs and the idea
  (project) to be that run's, else ``ai_run_not_active``, whether the other idea exists
  or not (nothing tells the agent which ideas exist); then the idea is loaded as for
  anyone (``not_found`` while held); ``list_projects`` and ``search_ideas`` list only the
  named run's project and idea (nothing without an open run);
* the only write is the named run's kind's tool (:data:`~app.schemas.ai.AGENT_RUN_WRITE_TOOLS`;
  ``propose_proposal_section`` only for the run's section); ``create_idea`` and
  ``add_comment`` are always ``forbidden``;
* (Phase 8b guest review M1) the reads depend on the run's kind (:data:`RUN_READ_TOOLS`):
  a research run's note lands in the idea's feed, which its guest researcher reads (role
  matrix table L), so a research run reads what that guest may read and no more
  (:func:`reads_as_guest`): no proposal, no rubric (``ai_run_not_active``, like another
  kind's write tool), and ``get_idea`` / ``search_ideas`` in the guest's shape (no
  evaluation area, no sign of a proposal, the guest feed's ``last_activity_at``).

For people, ``run_id`` is ignored and c22 refuses only ``add_research_note``
(``forbidden``). So two runs of one agent open at once can't reach each other, a run that
was cancelled, timed out or lost stays over even while a newer run on the same idea is
open (an agent task that outlives its run names the old run), and text planted in one
idea can't make the agent read or write another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.idea_keys import parse_idea_key
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.ai import AiAgent, AiRun
from app.models.enums import AiRunKind, AiRunStatus
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.ai import AGENT_READ_TOOLS, AGENT_RUN_WRITE_TOOLS

__all__ = [
    "RESEARCH_NOTE_TOOL",
    "RUN_READ_TOOLS",
    "NamedRun",
    "RunNotActiveProblem",
    "check_write",
    "is_agent",
    "lock_run",
    "named_run",
    "reads_as_guest",
    "refuse_agent_write",
    "require_run",
]

RESEARCH_NOTE_TOOL: Final = AGENT_RUN_WRITE_TOOLS[AiRunKind.RESEARCH]
_KIND_OF_TOOL: Final = {tool: kind for kind, tool in AGENT_RUN_WRITE_TOOLS.items()}
RUN_READ_TOOLS: Final[dict[AiRunKind, frozenset[str]]] = {
    AiRunKind.EVALUATE: AGENT_READ_TOOLS,
    AiRunKind.DRAFT_SECTION: AGENT_READ_TOOLS,
    # Phase 8b guest review M1: what a guest researcher may read through MCP.
    AiRunKind.RESEARCH: frozenset({"list_projects", "search_ideas", "get_idea"}),
}
"""c22: the read tools of :data:`~app.schemas.ai.AGENT_READ_TOOLS` each run kind may call
on its idea; another one is ``ai_run_not_active`` (before anything is looked up)."""


class RunNotActiveProblem(ProblemError):
    """The MCP tool error ``ai_run_not_active`` (c22)."""

    def __init__(self) -> None:
        super().__init__(
            403,
            "ai_run_not_active",
            detail=(
                "This agent has no running Soundings AI run for that: its key works only "
                "during a run, on the run's idea, through the run's tool, with the run's id "
                "as run_id in every call."
            ),
        )


def _forbidden() -> ProblemError:
    return ProblemError(403, "forbidden", detail="You don't have permission to do that.")


def is_agent(principal: Principal) -> bool:
    return principal.user.is_service_account


@dataclass(frozen=True, slots=True)
class NamedRun:
    """The open run an agent's call names, with what c22 compares the call with."""

    id: UUID
    kind: AiRunKind
    section_key: str | None
    idea_id: UUID
    idea_number: int
    project_id: UUID
    project_key: str
    project_slug: str

    def names_idea(self, ref: str) -> bool:
        """Whether an idea reference (a UUID, or a key in any case) is this run's idea."""
        key = parse_idea_key(ref)
        if key is not None:
            return key.project_key == self.project_key and key.number == self.idea_number
        try:
            return UUID(ref) == self.idea_id
        except ValueError:
            return False

    def names_project(self, slug: str) -> bool:
        return slug.lower() == self.project_slug.lower()


def _open(principal: Principal) -> ColumnElement[bool]:
    return and_(
        AiRun.agent_id
        == select(AiAgent.id)
        .where(AiAgent.service_account_id == principal.user_id)
        .scalar_subquery(),
        AiRun.status == AiRunStatus.RUNNING,
        AiRun.cancel_requested_at.is_(None),
    )


async def named_run(db: AsyncSession, principal: Principal, run_id: UUID | None) -> NamedRun | None:
    """The agent's open run that ``run_id`` names; ``None`` without one (no ``run_id``,
    someone else's run, or one that isn't open) and for people."""
    if run_id is None or not is_agent(principal):
        return None
    row = (
        await db.execute(
            select(AiRun, Idea.number, Project.id, Project.key, Project.slug)
            .join(Idea, Idea.id == AiRun.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(AiRun.id == run_id, _open(principal))
        )
    ).first()
    if row is None:
        return None
    run, number, project_id, project_key, project_slug = row
    return NamedRun(
        id=run.id,
        kind=AiRunKind(run.kind),
        section_key=run.section_key,
        idea_id=run.idea_id,
        idea_number=number,
        project_id=project_id,
        project_key=project_key,
        project_slug=project_slug,
    )


async def require_run(
    db: AsyncSession,
    principal: Principal,
    run_id: UUID | None,
    *,
    idea: str | None = None,
    project: str | None = None,
    read: str | None = None,
) -> NamedRun | None:
    """c22 for a call by an agent, before anything is looked up: the open run ``run_id``
    names, whose idea ``idea`` (or project ``project``) must be, and whose kind may call
    the read tool ``read`` (:data:`RUN_READ_TOOLS`); else ``ai_run_not_active``. ``None``
    for people (nothing to check)."""
    if not is_agent(principal):
        return None
    run = await named_run(db, principal, run_id)
    if run is None:
        raise RunNotActiveProblem
    if idea is not None and not run.names_idea(idea):
        raise RunNotActiveProblem
    if project is not None and not run.names_project(project):
        raise RunNotActiveProblem
    if read is not None and read not in RUN_READ_TOOLS[run.kind]:
        raise RunNotActiveProblem
    return run


def reads_as_guest(run: NamedRun | None) -> bool:
    """Phase 8b guest review M1: the call is an agent's in a research run, so it reads
    the idea in its guest researcher's shape (role matrix table L)."""
    return run is not None and run.kind is AiRunKind.RESEARCH


def check_write(
    principal: Principal,
    tool: str,
    run: NamedRun | None,
    section_key: str | None = None,
) -> None:
    """c22 for a write tool, with the run :func:`require_run` found: an agent writes only
    with its run kind's tool (``create_idea``, ``add_comment`` and anything else:
    ``forbidden``; another kind's tool or another section: ``ai_run_not_active``); a
    person's ``add_research_note`` is ``forbidden`` (call it after the idea was loaded,
    so an idea the person can't see stays ``not_found``)."""
    if not is_agent(principal):
        if tool == RESEARCH_NOTE_TOOL:
            raise _forbidden()
        return
    kind = _KIND_OF_TOOL.get(tool)
    if kind is None or tool in AGENT_READ_TOOLS:
        raise _forbidden()
    if run is None or run.kind is not kind:
        raise RunNotActiveProblem
    if kind is AiRunKind.DRAFT_SECTION and run.section_key != section_key:
        raise RunNotActiveProblem


async def lock_run(db: AsyncSession, principal: Principal, run: NamedRun | None) -> AiRun | None:
    """The named run, locked until commit and still open, after the tool loaded and
    locked the idea (lock order: project, idea, run), so a cancel request can't slip in
    between this check and attaching the result. ``None`` for people; an agent's run that
    ended meanwhile is ``ai_run_not_active``."""
    if not is_agent(principal):
        return None
    if run is None:
        raise RunNotActiveProblem
    locked: AiRun | None = await db.scalar(
        select(AiRun)
        .where(AiRun.id == run.id, _open(principal))
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise RunNotActiveProblem
    return locked


def refuse_agent_write() -> ProblemError:
    """``create_idea`` and ``add_comment`` by an agent: always ``forbidden`` (c22)."""
    return _forbidden()
