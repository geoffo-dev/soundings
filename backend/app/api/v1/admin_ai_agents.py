"""Admin settings -> AI agents: register kagent agents, their service accounts and keys
(SPEC section 9; contract-phase6 sections 2 and 3.1).

Rule ``platform.manage_agents``: platform admins, **session only** (an API key gets 403
``insufficient_scope``). Admin order of checks as in Phase 2: 401 -> 422 shape -> 403
(``forbidden``; ``break_glass_account`` for creating a key, c20) -> 404 -> 422 business
(``invalid_project``, ``namespace_not_allowed``) -> 409. Agents are never deleted:
disable them (``PATCH enabled: false``, which also revokes their key). An agent's key
works on ``/mcp`` only and only during its running runs (c22, run scope).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response, status

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.ai import (
    AiAgent,
    AiAgentCreate,
    AiAgentList,
    AiAgentTest,
    AiAgentUpdate,
    CreatedAiAgent,
    RotatedAiAgentKey,
)

router = APIRouter(prefix="/admin/ai-agents", tags=["admin"])

AgentId = Annotated[UUID, Path(description="A registered agent's id.")]

_ADMIN = "Platform admins (platform.manage_agents, session only). "


@router.get(
    "",
    operation_id="list_ai_agents",
    summary="List AI agents",
    description=(
        _ADMIN + "Every registered agent by display name (disabled ones too), with its "
        "projects, service account, key (never the secret), the A2A URL Soundings builds "
        "for it and its active runs; plus the AI settings in effect (read-only)."
    ),
    responses=problems(401, 403),
)
async def list_ai_agents(principal: PrincipalDep) -> AiAgentList:
    raise NotImplementedProblem


@router.post(
    "",
    operation_id="register_ai_agent",
    status_code=status.HTTP_201_CREATED,
    summary="Register an AI agent",
    description=(
        _ADMIN + "Creates the agent, its service account (a member of each project it "
        "serves) and its API key (scopes read and mcp, plus evaluate for evaluate and "
        "write for research or draft_section; restricted to its projects; no expiry; MCP "
        "only, and only during the agent's running runs: c22), and "
        "returns the key once with a Secret manifest (Cache-Control: no-store). The A2A URL "
        "is built from SOUNDINGS_KAGENT_URL, the protocol and the namespace and name. 403 "
        "break_glass_account (c20); 409 agent_taken (namespace and name already "
        "registered), too_many_agents (50); 422 invalid_project, namespace_not_allowed. "
        "Audited as ai_agent.register and api_key.create."
    ),
    responses=problems(401, 403, 409, 422),
)
async def register_ai_agent(
    principal: PrincipalDep, body: AiAgentCreate, response: Response
) -> CreatedAiAgent:
    response.headers["Cache-Control"] = "no-store"
    raise NotImplementedProblem


@router.get(
    "/{agent_id}",
    operation_id="get_ai_agent",
    summary="Get an AI agent",
    description=_ADMIN + "One agent, as in the list.",
    responses=problems(401, 403, 404),
)
async def get_ai_agent(principal: PrincipalDep, agent_id: AgentId) -> AiAgent:
    raise NotImplementedProblem


@router.patch(
    "/{agent_id}",
    operation_id="update_ai_agent",
    summary="Change or disable an AI agent",
    description=(
        _ADMIN + "Display name (also its service account's), description, protocol, "
        "purposes, projects, enabled. Purposes and projects also change its key's scopes "
        "and project restriction (the same key keeps working) and add or remove its member "
        "role in those projects; dropping a purpose or a project cancels its active runs of "
        "that kind or there. enabled false: no new runs, its queued and running runs are "
        "cancelled and its key is revoked (audited api_key.revoke); after enabling it again, "
        "rotate the key. Namespace and name can't change (422). 422 invalid_project. "
        "Audited as ai_agent.update."
    ),
    responses=problems(401, 403, 404, 422),
)
async def update_ai_agent(
    principal: PrincipalDep, agent_id: AgentId, body: AiAgentUpdate
) -> AiAgent:
    raise NotImplementedProblem


@router.post(
    "/{agent_id}/key",
    operation_id="rotate_ai_agent_key",
    status_code=status.HTTP_201_CREATED,
    summary="Rotate an AI agent's key",
    description=(
        _ADMIN + "Creates a new key for the agent (as at registration) and revokes the "
        "previous one in the same change, so the agent stops working until the operator "
        "updates its Secret. Returns the key once with a Secret manifest (Cache-Control: "
        "no-store). 403 break_glass_account (c20). Audited as api_key.create and "
        "api_key.revoke (rule platform.manage_agents)."
    ),
    responses=problems(401, 403, 404),
)
async def rotate_ai_agent_key(
    principal: PrincipalDep, agent_id: AgentId, response: Response
) -> RotatedAiAgentKey:
    response.headers["Cache-Control"] = "no-store"
    raise NotImplementedProblem


@router.post(
    "/{agent_id}/test",
    operation_id="test_ai_agent",
    summary="Test an AI agent's connection",
    description=(
        _ADMIN + "Fetches the agent card from the built card URL (5 seconds, no redirects, "
        "at most 64 KiB, the controller token if set) and reports what it says. Always 200: "
        "ok false with error_code agent_unreachable or agent_protocol_error when it fails. "
        "10 a minute per admin (429 too_many_attempts). Not audited."
    ),
    responses=problems(401, 403, 404, 429),
)
async def test_ai_agent(principal: PrincipalDep, agent_id: AgentId) -> AiAgentTest:
    raise NotImplementedProblem
