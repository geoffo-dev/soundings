"""Admin settings -> AI agents (contract-phase6 sections 2 and 3.1), and c10 for an agent.

* **Register** (``platform.manage_agents``, session only, c20): the agent row, its
  service account (``users.is_service_account``, ``agent-<id>@soundings.invalid``), a
  direct ``member`` role in each project it serves and its **one** API key (scopes from
  its purposes, restricted to its projects, no expiry), shown once with a Kubernetes
  Secret manifest. Audited ``ai_agent.register``, ``project.member_add`` and
  ``api_key.create`` (rule ``platform.manage_agents``).
* **Update**: the key follows the agent (scopes and restriction change in place, unlike a
  person's immutable key); dropping a purpose or a project cancels the agent's active
  runs that it covered; disabling cancels every active run and **revokes** the key
  (enabling again needs a rotation). Audited ``ai_agent.update``.
* **Rotate**: a new key, the old one revoked in the same transaction.
* **Test connection**: the card from the **built** card URL (5 seconds, no redirects,
  64 KiB), shown as plain text; 10 a minute per admin.
* :func:`candidates` / :func:`usable`: c10, exactly as the role matrix states it.

Admin order of checks (Phase 2): 401 -> 422 shape -> 403 -> 404 -> 422 business -> 409.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.ai.a2a import A2AClient, A2AError
from app.ai.transitions import cancel as cancel_run
from app.ai.transitions import lock_idea
from app.api_keys.service import describe_key, issue_key, revoke_key
from app.api_keys.state import refusal_reason
from app.auth.sources import UnauthorizedProblem
from app.auth.throttle import get_throttle
from app.authz import Resource, Rule, can, require
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.ai import AiAgent, AiAgentProject, AiRun
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import AiAgentProtocol, AiRunError, AiRunKind, AiRunStatus, ProjectRole
from app.models.idea import Idea
from app.models.project import Project, ProjectMember, project_effective_roles
from app.models.user import User
from app.schemas import ai as schemas
from app.schemas.ai import (
    AI_AGENT_TESTS_PER_MINUTE,
    AI_AGENTS_MAX,
    AI_CARD_TIMEOUT,
    agent_a2a_url,
    agent_card_url,
    agent_key_name,
    agent_key_scopes,
    agent_secret_manifest,
    canonical_purposes,
    run_error_message,
    service_account_email,
)
from app.schemas.api_keys import ApiKeyCreate, CreatedApiKey
from app.schemas.users import UserRef
from app.services import audit

__all__ = [
    "AGENT_TEST_THROTTLE",
    "Candidate",
    "agent_out",
    "agent_ref",
    "candidates",
    "get_agent",
    "list_agents",
    "probe_agent",
    "register_agent",
    "rotate_key",
    "update_agent",
    "usable",
]

logger = logging.getLogger("soundings.ai")

AGENT_TEST_THROTTLE: Final = ("ai_agent_test", AI_AGENT_TESTS_PER_MINUTE, 60.0)
"""``test_ai_agent`` calls per platform admin per minute (per API process)."""
_CARD_TEXT_MAX: Final = 200
_CARD_SKILLS_MAX: Final = 20
_REGISTER_LOCK: Final = 0x50364149  # "P6AI": serialises registrations (the 50-agent cap)
_ACTIVE: Final = (AiRunStatus.QUEUED, AiRunStatus.RUNNING)


# --- Problems ---------------------------------------------------------------------------------
class _InvalidProject(ProblemError):
    def __init__(self) -> None:
        super().__init__(422, "invalid_project", detail="A project doesn't exist.")


class _NamespaceNotAllowed(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            422,
            "namespace_not_allowed",
            detail="Agents can't be registered in this namespace (SOUNDINGS_AI_AGENT_NAMESPACES).",
        )


def _agent_not_found() -> ProblemError:
    return NotFoundProblem("Not found.")


# --- c10 --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Candidate:
    """An agent serving one project, with what c10 needs: its service account, the
    account's effective role there and its key that isn't revoked (if any)."""

    agent: AiAgent
    service_account: User
    role: ProjectRole | None
    key: ApiKey | None

    def usable(self, kind: AiRunKind, settings: Settings, now: datetime) -> bool:
        """c10 for this agent and kind (role matrix section 4)."""
        return (
            settings.ai_enabled
            and self.agent.enabled
            and kind.value in self.agent.purposes
            and self.service_account.is_active
            and self.role is ProjectRole.MEMBER
            and self.key is not None
            and refusal_reason(self.key, self.service_account, settings=settings, now=now) is None
        )

    def kinds(self, settings: Settings, now: datetime) -> list[AiRunKind]:
        return [kind for kind in AiRunKind if self.usable(kind, settings, now)]


def _active_key(user_id: Any) -> Any:
    """The service account's newest key that isn't revoked (agents have one)."""
    key = aliased(ApiKey)
    return (
        select(key.id)
        .where(key.user_id == user_id, key.revoked_at.is_(None))
        .order_by(key.created_at.desc(), key.id.desc())
        .limit(1)
        .correlate_except(key)
        .scalar_subquery()
    )


async def candidates(
    db: AsyncSession, project_id: UUID, agent_id: UUID | None = None
) -> list[Candidate]:
    """The agents that serve ``project_id`` (or just ``agent_id``), by display name."""
    roles = project_effective_roles
    statement = (
        select(AiAgent, User, roles.c.role, ApiKey)
        .join(AiAgentProject, AiAgentProject.agent_id == AiAgent.id)
        .join(User, User.id == AiAgent.service_account_id)
        .outerjoin(
            roles, (roles.c.user_id == User.id) & (roles.c.project_id == AiAgentProject.project_id)
        )
        .outerjoin(ApiKey, ApiKey.id == _active_key(User.id))
        .where(AiAgentProject.project_id == project_id)
        .order_by(func.lower(AiAgent.display_name), AiAgent.id)
    )
    if agent_id is not None:
        statement = statement.where(AiAgent.id == agent_id)
    rows = await db.execute(statement)
    return [
        Candidate(agent=agent, service_account=user, role=role, key=key)
        for agent, user, role, key in rows.all()
    ]


async def usable(
    db: AsyncSession, settings: Settings, agent_id: UUID, project_id: UUID, kind: AiRunKind
) -> Candidate | None:
    """The agent when it passes c10 for ``kind`` on ``project_id`` now, else ``None``."""
    found = await candidates(db, project_id, agent_id)
    if found and found[0].usable(kind, settings, utcnow()):
        return found[0]
    return None


def agent_ref(agent: AiAgent) -> schemas.AiAgentRef:
    return schemas.AiAgentRef(
        id=agent.id,
        display_name=agent.display_name,
        purposes=[AiRunKind(purpose) for purpose in agent.purposes],
        user_id=agent.service_account_id,
    )


# --- Responses ---------------------------------------------------------------------------------
def _user_ref(user: User) -> UserRef:
    return UserRef(id=user.id, display_name=user.display_name, avatar_url=user.avatar_url)


async def agent_out(db: AsyncSession, settings: Settings, agent: AiAgent) -> schemas.AiAgent:
    """One agent as Admin settings -> AI agents shows it."""
    roles = project_effective_roles
    service_account = await db.get(User, agent.service_account_id, populate_existing=True)
    assert service_account is not None  # noqa: S101 - users are never deleted
    project_rows = await db.execute(
        select(Project, roles.c.role)
        .join(AiAgentProject, AiAgentProject.project_id == Project.id)
        .outerjoin(
            roles,
            (roles.c.project_id == Project.id) & (roles.c.user_id == agent.service_account_id),
        )
        .where(AiAgentProject.agent_id == agent.id)
        .order_by(func.lower(Project.name), Project.id)
    )
    key = await db.scalar(
        select(ApiKey)
        .where(ApiKey.id == _active_key(agent.service_account_id))
        .execution_options(populate_existing=True)
    )
    active = await db.scalar(
        select(func.count())
        .select_from(AiRun)
        .where(AiRun.agent_id == agent.id, AiRun.status.in_(_ACTIVE))
    )
    creator = await db.get(User, agent.created_by_id) if agent.created_by_id else None
    protocol = AiAgentProtocol(agent.protocol)
    return schemas.AiAgent(
        id=agent.id,
        display_name=agent.display_name,
        description=agent.description,
        namespace=agent.namespace,
        name=agent.name,
        protocol=protocol,
        purposes=[AiRunKind(purpose) for purpose in agent.purposes],
        enabled=agent.enabled,
        projects=[
            schemas.AiAgentProjectRef(
                id=project.id, slug=project.slug, key=project.key, name=project.name, role=role
            )
            for project, role in project_rows.all()
        ],
        service_account=_user_ref(service_account),
        key=await describe_key(db, key, service_account) if key is not None else None,
        a2a_url=agent_a2a_url(settings.kagent_url, protocol, agent.namespace, agent.name),
        card_url=agent_card_url(settings.kagent_url, protocol, agent.namespace, agent.name),
        active_run_count=int(active or 0),
        created_by=_user_ref(creator) if creator is not None else None,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def settings_in_effect(settings: Settings) -> schemas.AiSettingsInEffect:
    return schemas.AiSettingsInEffect(
        enabled=settings.ai_enabled,
        kagent_url=settings.kagent_url,
        kagent_token_set=settings.kagent_token is not None,
        default_protocol=AiAgentProtocol(settings.ai_default_protocol),
        run_timeout_seconds=settings.ai_run_timeout_seconds,
        max_concurrent_runs=settings.ai_max_concurrent_runs,
        agent_namespaces=list(settings.ai_agent_namespaces),
        mcp_url=settings.ai_mcp_url_effective,
    )


# --- Reading ------------------------------------------------------------------------------------
async def list_agents(
    db: AsyncSession, principal: Principal, settings: Settings
) -> schemas.AiAgentList:
    require(principal, Rule.PLATFORM_MANAGE_AGENTS)
    agents = list(
        await db.scalars(select(AiAgent).order_by(func.lower(AiAgent.display_name), AiAgent.id))
    )
    return schemas.AiAgentList(
        items=[await agent_out(db, settings, agent) for agent in agents],
        settings=settings_in_effect(settings),
        max_agents=AI_AGENTS_MAX,
        can_register=len(agents) < AI_AGENTS_MAX
        and can(principal, Rule.PLATFORM_MANAGE_AGENTS, Resource(issuing_api_key=True)),
    )


async def _load(db: AsyncSession, agent_id: UUID, *, for_update: bool = False) -> AiAgent:
    statement = select(AiAgent).where(AiAgent.id == agent_id)
    if for_update:
        # FOR NO KEY UPDATE: run inserts (which hold an idea's lock) take KEY SHARE on the
        # agent row; a full FOR UPDATE here would deadlock with them.
        statement = statement.with_for_update(key_share=True)
    agent = await db.scalar(statement.execution_options(populate_existing=True))
    if agent is None:
        raise _agent_not_found()
    return agent


async def get_agent(
    db: AsyncSession, principal: Principal, settings: Settings, agent_id: UUID
) -> schemas.AiAgent:
    require(principal, Rule.PLATFORM_MANAGE_AGENTS)
    return await agent_out(db, settings, await _load(db, agent_id))


# --- Registering ----------------------------------------------------------------------------------
async def _existing_projects(db: AsyncSession, project_ids: Sequence[UUID]) -> list[UUID]:
    """``project_ids`` in order, all existing; else 422 ``invalid_project``."""
    found = set(await db.scalars(select(Project.id).where(Project.id.in_(list(project_ids)))))
    if found != set(project_ids):
        raise _InvalidProject
    return list(project_ids)


def _check_namespace(settings: Settings, namespace: str) -> None:
    allowed = settings.ai_agent_namespaces
    if allowed and namespace not in allowed:
        raise _NamespaceNotAllowed


async def _add_memberships(
    db: AsyncSession, principal: Principal, user: User, project_ids: Iterable[UUID]
) -> None:
    """A direct ``member`` role where the service account has no direct role yet."""
    wanted = list(project_ids)
    existing = set(
        await db.scalars(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id, ProjectMember.project_id.in_(wanted)
            )
        )
    )
    for project_id in wanted:
        if project_id in existing:
            continue
        db.add(ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.MEMBER))
        await db.flush()
        await audit.record(
            db,
            "project.member_add",
            actor=principal,
            target_type="user",
            target_id=user.id,
            project_id=project_id,
            details={"rule": Rule.PLATFORM_MANAGE_AGENTS, "role": ProjectRole.MEMBER},
        )


async def _remove_memberships(
    db: AsyncSession, principal: Principal, user: User, project_ids: Iterable[UUID]
) -> None:
    """The service account's **direct** role in each project goes (group roles stay)."""
    for project_id in project_ids:
        member = await db.get(ProjectMember, (project_id, user.id))
        if member is None:
            continue
        previous = member.role
        await db.delete(member)
        await db.flush()
        await audit.record(
            db,
            "project.member_remove",
            actor=principal,
            target_type="user",
            target_id=user.id,
            project_id=project_id,
            details={"rule": Rule.PLATFORM_MANAGE_AGENTS, "from_role": previous},
        )


async def _new_key(
    db: AsyncSession, principal: Principal, user: User, agent: AiAgent, project_ids: list[UUID]
) -> tuple[ApiKey, str]:
    if principal.auth_method is None:  # only sessions manage agents, and they have one
        raise UnauthorizedProblem
    body = ApiKeyCreate(
        name=agent_key_name(agent.namespace, agent.name),
        scopes=agent_key_scopes([AiRunKind(purpose) for purpose in agent.purposes]),
        project_ids=project_ids,
    )
    return await issue_key(
        db,
        owner=user,
        creator=principal,
        created_auth_method=principal.auth_method,
        body=body,
        rule=Rule.PLATFORM_MANAGE_AGENTS,
        check_projects=False,
    )


async def _created_key(db: AsyncSession, row: ApiKey, user: User, secret: str) -> CreatedApiKey:
    return CreatedApiKey(key=await describe_key(db, row, user), secret=secret)


async def register_agent(
    db: AsyncSession, principal: Principal, settings: Settings, body: schemas.AiAgentCreate
) -> schemas.CreatedAiAgent:
    """``POST /admin/ai-agents`` (see the module docstring)."""
    require(principal, Rule.PLATFORM_MANAGE_AGENTS, Resource(issuing_api_key=True))
    _check_namespace(settings, body.namespace)
    project_ids = await _existing_projects(db, body.project_ids)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _REGISTER_LOCK})
    taken = await db.scalar(
        select(AiAgent.id).where(AiAgent.namespace == body.namespace, AiAgent.name == body.name)
    )
    if taken is not None:
        raise ConflictProblem(
            "An agent with this namespace and name is already registered.", code="agent_taken"
        )
    if (await db.scalar(select(func.count()).select_from(AiAgent)) or 0) >= AI_AGENTS_MAX:
        raise ConflictProblem(
            f"Soundings has {AI_AGENTS_MAX} agents: disable or reuse one.", code="too_many_agents"
        )
    agent_id = uuid4()
    user = User(
        id=uuid4(),
        email=service_account_email(agent_id),
        display_name=body.display_name,
        is_service_account=True,
        is_active=True,
        is_platform_admin=False,
    )
    db.add(user)
    await db.flush()
    protocol = body.protocol or AiAgentProtocol(settings.ai_default_protocol)
    purposes = canonical_purposes(body.purposes)
    agent = AiAgent(
        id=agent_id,
        display_name=body.display_name,
        description=body.description,
        namespace=body.namespace,
        name=body.name,
        protocol=protocol,
        purposes=[purpose.value for purpose in purposes],
        service_account_id=user.id,
        enabled=True,
        created_by_id=principal.user_id,
    )
    try:
        async with db.begin_nested():
            db.add(agent)
    except IntegrityError as error:
        raise ConflictProblem(
            "An agent with this namespace and name is already registered.", code="agent_taken"
        ) from error
    db.add_all(AiAgentProject(agent_id=agent.id, project_id=pid) for pid in project_ids)
    await db.flush()
    await _add_memberships(db, principal, user, project_ids)
    row, secret = await _new_key(db, principal, user, agent, project_ids)
    await audit.record(
        db,
        "ai_agent.register",
        actor=principal,
        target_type="user",
        target_id=user.id,
        details={
            "rule": Rule.PLATFORM_MANAGE_AGENTS,
            "agent_id": agent.id,
            "namespace": agent.namespace,
            "name": agent.name,
            "protocol": protocol,
            "purposes": list(agent.purposes),
            "project_ids": project_ids,
        },
    )
    await db.flush()
    logger.info("ai agent registered", extra={"agent_id": str(agent.id)})
    return schemas.CreatedAiAgent(
        agent=await agent_out(db, settings, agent),
        key=await _created_key(db, row, user, secret),
        secret_manifest=agent_secret_manifest(agent.namespace, agent.name, secret),
    )


# --- Changing ------------------------------------------------------------------------------------
async def _active_key_row(db: AsyncSession, user_id: UUID) -> ApiKey | None:
    key: ApiKey | None = await db.scalar(
        select(ApiKey)
        .where(ApiKey.id == _active_key(user_id))
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    return key


async def _cancel_runs(
    db: AsyncSession,
    principal: Principal,
    agent: AiAgent,
    *,
    kinds: Iterable[AiRunKind] | None = None,
    project_ids: Iterable[UUID] | None = None,
) -> int:
    """A cancel request by the admin for each of the agent's active runs (of ``kinds``,
    or on ideas in ``project_ids``; all of them when both are ``None``). Audited
    ``ai_run.cancel`` (rule ``platform.manage_agents``)."""
    statement = (
        select(AiRun.id, AiRun.idea_id, Idea.project_id)
        .join(Idea, Idea.id == AiRun.idea_id)
        .where(AiRun.agent_id == agent.id, AiRun.status.in_(_ACTIVE))
        .order_by(AiRun.created_at, AiRun.id)
    )
    if kinds is not None:
        statement = statement.where(AiRun.kind.in_(list(kinds)))
    if project_ids is not None:
        statement = statement.where(Idea.project_id.in_(list(project_ids)))
    cancelled = 0
    for run_id, idea_id, project_id in (await db.execute(statement)).all():
        await lock_idea(db, idea_id)
        status = await cancel_run(db, run_id, by_id=principal.user_id)
        if status is None:
            continue
        cancelled += 1
        await audit.record(
            db,
            "ai_run.cancel",
            actor=principal,
            target_type="idea",
            target_id=idea_id,
            project_id=project_id,
            details={
                "rule": Rule.PLATFORM_MANAGE_AGENTS,
                "run_id": run_id,
                "agent_id": agent.id,
                "status": status,
            },
        )
    return cancelled


async def update_agent(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    agent_id: UUID,
    body: schemas.AiAgentUpdate,
) -> schemas.AiAgent:
    """``PATCH /admin/ai-agents/{agent_id}`` (see the module docstring)."""
    require(principal, Rule.PLATFORM_MANAGE_AGENTS)
    agent = await _load(db, agent_id, for_update=True)
    new_projects = (
        await _existing_projects(db, body.project_ids) if body.project_ids is not None else None
    )
    user = await db.get(User, agent.service_account_id, with_for_update={"key_share": True})
    assert user is not None  # noqa: S101 - users are never deleted
    changed: list[str] = []
    if body.display_name is not None and body.display_name != agent.display_name:
        agent.display_name = body.display_name
        user.display_name = body.display_name
        changed.append("display_name")
    if body.description is not None and body.description != agent.description:
        agent.description = body.description
        changed.append("description")
    if body.protocol is not None and body.protocol != agent.protocol:
        agent.protocol = body.protocol
        changed.append("protocol")
    key = await _active_key_row(db, user.id)
    if body.purposes is not None:
        purposes = [purpose.value for purpose in canonical_purposes(body.purposes)]
        if purposes != list(agent.purposes):
            dropped = [AiRunKind(p) for p in agent.purposes if p not in purposes]
            agent.purposes = purposes
            changed.append("purposes")
            if key is not None:
                key.scopes = [
                    scope.value for scope in agent_key_scopes([AiRunKind(p) for p in purposes])
                ]
            if dropped:
                await _cancel_runs(db, principal, agent, kinds=dropped)
    if new_projects is not None:
        current = list(
            await db.scalars(
                select(AiAgentProject.project_id).where(AiAgentProject.agent_id == agent.id)
            )
        )
        if set(new_projects) != set(current):
            added = [pid for pid in new_projects if pid not in current]
            dropped_projects = [pid for pid in current if pid not in new_projects]
            changed.append("project_ids")
            for project_id in dropped_projects:
                link = await db.get(AiAgentProject, (agent.id, project_id))
                if link is not None:
                    await db.delete(link)
            db.add_all(AiAgentProject(agent_id=agent.id, project_id=pid) for pid in added)
            await db.flush()
            if dropped_projects:
                await _cancel_runs(db, principal, agent, project_ids=dropped_projects)
            await _remove_memberships(db, principal, user, dropped_projects)
            await _add_memberships(db, principal, user, added)
            if key is not None:
                key.project_ids = list(new_projects)
    enabled_changed = body.enabled is not None and body.enabled != agent.enabled
    if enabled_changed:
        assert body.enabled is not None  # noqa: S101 - narrowed above
        agent.enabled = body.enabled
        changed.append("enabled")
        if not body.enabled:
            await _cancel_runs(db, principal, agent)
            if key is not None:
                await revoke_key(db, key, actor=principal, rule=Rule.PLATFORM_MANAGE_AGENTS)
    if changed:
        agent.updated_at = utcnow()
        details: dict[str, Any] = {
            "rule": Rule.PLATFORM_MANAGE_AGENTS,
            "agent_id": agent.id,
            "changed": changed,
        }
        if enabled_changed:
            details["enabled"] = agent.enabled
        await audit.record(
            db,
            "ai_agent.update",
            actor=principal,
            target_type="user",
            target_id=user.id,
            details=details,
        )
    await db.flush()
    return await agent_out(db, settings, agent)


async def rotate_key(
    db: AsyncSession, principal: Principal, settings: Settings, agent_id: UUID
) -> schemas.RotatedAiAgentKey:
    """``POST /admin/ai-agents/{agent_id}/key``: a new key; the old one is revoked in the
    same transaction (no overlap: the agent fails until its Secret is updated)."""
    require(principal, Rule.PLATFORM_MANAGE_AGENTS, Resource(issuing_api_key=True))
    agent = await _load(db, agent_id, for_update=True)
    user = await db.get(User, agent.service_account_id)
    assert user is not None  # noqa: S101 - users are never deleted
    if not user.is_active:
        raise ConflictProblem(
            "The agent's service account is deactivated: reactivate it in Admin settings -> "
            "Users first.",
            code="ai_unavailable",
        )
    old = await _active_key_row(db, user.id)
    revoked_id = None
    if old is not None:
        await revoke_key(db, old, actor=principal, rule=Rule.PLATFORM_MANAGE_AGENTS)
        revoked_id = old.id
        await db.flush()
    project_ids = list(
        await db.scalars(
            select(AiAgentProject.project_id)
            .join(Project, Project.id == AiAgentProject.project_id)
            .where(AiAgentProject.agent_id == agent.id)
            .order_by(func.lower(Project.name), Project.id)
        )
    )
    row, secret = await _new_key(db, principal, user, agent, project_ids)
    await db.flush()
    return schemas.RotatedAiAgentKey(
        agent=await agent_out(db, settings, agent),
        key=await _created_key(db, row, user, secret),
        secret_manifest=agent_secret_manifest(agent.namespace, agent.name, secret),
        revoked_key_id=revoked_id,
    )


# --- Test connection -----------------------------------------------------------------------------
def _text(value: object) -> str:
    return value[:_CARD_TEXT_MAX] if isinstance(value, str) else ""


def card_summary(card: object) -> schemas.AiAgentCard:
    """What an agent card says, as plain text (strings cut, at most 20 skills). Its URLs
    are never read: every request goes to the built URL."""
    if not isinstance(card, dict):
        raise ValueError("not an agent card")
    versions: list[str] = []
    interfaces = card.get("supportedInterfaces")
    if isinstance(interfaces, list):
        for interface in interfaces:
            if isinstance(interface, dict) and isinstance(interface.get("protocolVersion"), str):
                versions.append(_text(interface["protocolVersion"]))
    if isinstance(card.get("protocolVersion"), str):
        versions.append(_text(card["protocolVersion"]))
    capabilities = card.get("capabilities")
    streaming = isinstance(capabilities, dict) and capabilities.get("streaming") is True
    skills = []
    raw_skills = card.get("skills")
    if isinstance(raw_skills, list):
        for skill in raw_skills[:_CARD_SKILLS_MAX]:
            if isinstance(skill, dict):
                skills.append(
                    schemas.AiAgentSkill(id=_text(skill.get("id")), name=_text(skill.get("name")))
                )
    return schemas.AiAgentCard(
        name=_text(card.get("name")),
        description=_text(card.get("description")),
        protocol_versions=list(dict.fromkeys(version for version in versions if version)),
        streaming=streaming,
        skills=skills,
    )


async def probe_agent(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    agent_id: UUID,
    *,
    app: Any,
    transport: httpx.AsyncBaseTransport | None = None,
) -> schemas.AiAgentTest:
    """``POST /admin/ai-agents/{agent_id}/test``: always an answer (``ok`` or why not)."""
    require(principal, Rule.PLATFORM_MANAGE_AGENTS)
    agent = await _load(db, agent_id)
    throttle = get_throttle(app, AGENT_TEST_THROTTLE)
    who = str(principal.user_id)
    retry_after = throttle.retry_after(who)
    if retry_after is not None:
        raise ProblemError(
            429,
            "too_many_attempts",
            detail="Too many connection tests. Try again in a minute.",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )
    throttle.hit(who)
    client = A2AClient(
        settings,
        AiAgentProtocol(agent.protocol),
        agent.namespace,
        agent.name,
        transport=transport,
    )
    started = time.monotonic()
    status: int | None = None
    try:
        async with asyncio.timeout(AI_CARD_TIMEOUT.total_seconds()):
            status, card = await client.fetch_card()
        summary = card_summary(card)
    except TimeoutError:
        return _failed(client.card_url, started, AiRunError.AGENT_UNREACHABLE, None)
    except A2AError as error:
        return _failed(client.card_url, started, error.code, error.http_status)
    except ValueError:
        return _failed(client.card_url, started, AiRunError.AGENT_PROTOCOL_ERROR, status)
    return schemas.AiAgentTest(
        ok=True,
        url=client.card_url,
        http_status=status,
        duration_ms=_elapsed_ms(started),
        card=summary,
        error_code=None,
        error_message=None,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _failed(
    url: str, started: float, code: AiRunError, http_status: int | None
) -> schemas.AiAgentTest:
    logger.info(
        "ai agent test failed", extra={"error_code": code.value, "http_status": http_status}
    )
    return schemas.AiAgentTest(
        ok=False,
        url=url,
        http_status=http_status,
        duration_ms=_elapsed_ms(started),
        card=None,
        error_code=code,
        error_message=run_error_message(code, http_status=http_status),
    )
