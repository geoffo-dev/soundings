"""Builders for Phase 6 tests: agents (with their service account, memberships and
optionally a key), runs in any state, and the run's events.

* ``make_agent(db, projects, ...)``: an ``ai_agents`` row with a new service account
  that is a ``member`` of each project (or the given ``user``), serving those projects.
  ``key=True`` also issues its key through the key service (scopes from the purposes,
  restricted to the projects) and returns the secret in ``Agent.key``.
* ``open_run(db, agent, idea, kind)``: an ``ai_runs`` row, ``running`` by default (an
  **open run**: what c22 needs before the agent's key does anything).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.service import issue_key
from app.domain.principal import Principal
from app.models.ai import AiAgent, AiAgentProject, AiRun, AiRunEvent
from app.models.base import utcnow
from app.models.enums import (
    AiAgentProtocol,
    AiRunKind,
    AiRunStatus,
    AuthMethod,
    ProjectRole,
    ProposalSectionKey,
)
from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.schemas.ai import agent_key_name, agent_key_scopes
from app.schemas.api_keys import ApiKeyCreate
from tests.factories import make_user

ALL_KINDS = (AiRunKind.EVALUATE, AiRunKind.RESEARCH, AiRunKind.DRAFT_SECTION)


@dataclass
class Agent:
    agent: AiAgent
    user: User
    key: str | None = None

    @property
    def id(self) -> UUID:
        return self.agent.id


async def make_agent(
    db: AsyncSession,
    projects: Iterable[Project],
    *,
    purposes: Sequence[AiRunKind] = ALL_KINDS,
    name: str | None = None,
    namespace: str = "soundings",
    display_name: str = "Idea evaluator",
    user: User | None = None,
    enabled: bool = True,
    key: bool = False,
    protocol: AiAgentProtocol = AiAgentProtocol.KAGENT_V0_10,
    role: ProjectRole | None = ProjectRole.MEMBER,
    creator: User | None = None,
) -> Agent:
    wanted = list(projects)
    user = user or await make_user(db, display_name, service_account=True)
    if role is not None:
        for project in wanted:
            exists = await db.get(ProjectMember, (project.id, user.id))
            if exists is None:
                db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    agent = AiAgent(
        id=uuid4(),
        display_name=display_name,
        description="",
        namespace=namespace,
        name=name or f"agent-{uuid4().hex[:8]}",
        protocol=protocol,
        purposes=[kind.value for kind in AiRunKind if kind in purposes],
        service_account_id=user.id,
        enabled=enabled,
        created_by_id=creator.id if creator else None,
    )
    db.add(agent)
    await db.flush()
    db.add_all(AiAgentProject(agent_id=agent.id, project_id=project.id) for project in wanted)
    await db.commit()
    secret = None
    if key:
        _, secret = await issue_key(
            db,
            owner=user,
            creator=Principal(user=creator or user, auth_method=AuthMethod.DEV_LOGIN),
            created_auth_method=AuthMethod.DEV_LOGIN,
            body=ApiKeyCreate(
                name=agent_key_name(agent.namespace, agent.name),
                scopes=agent_key_scopes(list(purposes)),
                project_ids=[project.id for project in wanted],
            ),
            check_projects=False,
        )
        await db.commit()
    return Agent(agent=agent, user=user, key=secret)


async def open_run(
    db: AsyncSession,
    agent: Agent | AiAgent,
    idea: Idea,
    kind: AiRunKind = AiRunKind.EVALUATE,
    *,
    section_key: ProposalSectionKey | None = None,
    status: AiRunStatus = AiRunStatus.RUNNING,
    cancel_requested: bool = False,
    requested_by: User | None = None,
    started_at: datetime | None = None,
    created_at: datetime | None = None,
    heartbeat_at: datetime | None = None,
    timeout_seconds: int = 300,
    assigned_evaluator: bool = False,
) -> AiRun:
    agent_id = agent.id
    if kind is AiRunKind.DRAFT_SECTION and section_key is None:
        section_key = ProposalSectionKey.RISKS
    now = utcnow()
    final = status not in (AiRunStatus.QUEUED, AiRunStatus.RUNNING)
    run = AiRun(
        id=uuid4(),
        idea_id=idea.id,
        agent_id=agent_id,
        kind=kind,
        section_key=section_key,
        requested_by_id=requested_by.id if requested_by else None,
        status=status,
        timeout_seconds=timeout_seconds,
        created_at=created_at or now,
        started_at=None if status is AiRunStatus.QUEUED else (started_at or now),
        heartbeat_at=heartbeat_at
        if heartbeat_at is not None
        else (None if status is AiRunStatus.QUEUED else now),
        finished_at=now if final else None,
        cancel_requested_at=now if cancel_requested else None,
        error_code="agent_failed"
        if status in (AiRunStatus.FAILED,)
        else ("timed_out" if status is AiRunStatus.TIMED_OUT else None),
        error_message="The agent stopped with an error."
        if status is AiRunStatus.FAILED
        else ("The agent didn't finish in time." if status is AiRunStatus.TIMED_OUT else None),
        assigned_evaluator=assigned_evaluator,
    )
    db.add(run)
    await db.commit()
    return run


async def run_row(db: AsyncSession, run_id: UUID) -> AiRun:
    run = await db.scalar(
        select(AiRun).where(AiRun.id == run_id).execution_options(populate_existing=True)
    )
    assert run is not None
    return run


async def events(db: AsyncSession, run_id: UUID) -> list[AiRunEvent]:
    rows = await db.scalars(
        select(AiRunEvent)
        .where(AiRunEvent.run_id == run_id)
        .order_by(AiRunEvent.seq)
        .execution_options(populate_existing=True)
    )
    return list(rows)


def ago(**kwargs: float) -> datetime:
    return utcnow() - timedelta(**kwargs)
