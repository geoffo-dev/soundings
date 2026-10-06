"""Admin settings -> AI agents (contract-phase6 sections 2 and 3.1): registration with its
service account, memberships and one key; updates that keep the key in step and cancel
what a narrowing drops; disable = revoke; rotation; test connection (SSRF-safe)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.ai import AiAgent
from app.models.api_key import ApiKey
from app.models.enums import AiRunKind, AiRunStatus, ProjectRole
from app.models.project import ProjectMember
from app.models.user import User
from app.schemas.ai import AI_AGENTS_MAX
from tests.ai.conftest import API, AsUser, Crew, McpAs, Team, assert_problem, ok
from tests.ai.fake_kagent import FakeKagent
from tests.ai.helpers import make_agent, open_run, run_row
from tests.api_keys.helpers import key_client, key_row
from tests.factories import make_idea, make_project
from tests.mcp.conftest import JSON_HEADERS, rpc

AGENTS = "/admin/ai-agents"


def _body(team: Team, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "display_name": "Idea evaluator",
        "description": "Scores ideas.",
        "namespace": "soundings",
        "name": "idea-evaluator",
        "purposes": ["evaluate", "research"],
        "project_ids": [str(team.project.id)],
    }
    body.update(overrides)
    return body


async def _audit(db: AsyncSession, action: str) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.action == action)
        .order_by(AuditLog.created_at, AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- Registering --------------------------------------------------------------------------
async def test_registering_creates_the_service_account_membership_and_one_key(
    api: AsUser, team: Team, db_session: AsyncSession, app: FastAPI, mcp_as: McpAs
) -> None:
    admin = await api(team.platform)

    response = await admin.post(AGENTS, _body(team))

    created = ok(response, 201)
    assert response.headers["cache-control"] == "no-store"
    agent, key = created["agent"], created["key"]
    assert (
        agent["a2a_url"] == "http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator/"
    )
    assert agent["card_url"].endswith("/idea-evaluator/.well-known/agent-card.json")
    assert (agent["protocol"], agent["enabled"], agent["active_run_count"]) == (
        "kagent_v0_10",
        True,
        0,
    )
    assert agent["purposes"] == ["evaluate", "research"]
    assert [(p["key"], p["role"]) for p in agent["projects"]] == [("CUST", "member")]
    assert agent["created_by"]["id"] == str(team.platform.id)
    assert key["key"]["scopes"] == ["read", "write", "evaluate", "mcp"]
    assert [p["id"] for p in key["key"]["projects"]] == [str(team.project.id)]
    assert key["key"]["expires_at"] is None
    secret = key["secret"]
    assert secret.startswith("sdg_")
    assert created["secret_manifest"].count(secret) == 1
    assert "name: soundings-agent-idea-evaluator\n" in created["secret_manifest"]
    assert "namespace: soundings\n" in created["secret_manifest"]
    # The service account: an agent's, never mailed or matched by SSO.
    user = await db_session.get(User, UUID(agent["service_account"]["id"]))
    assert user is not None
    assert user.is_service_account
    assert user.is_active
    assert not user.is_platform_admin
    assert user.email == f"agent-{agent['id']}@soundings.invalid"
    assert user.display_name == "Idea evaluator"
    member = await db_session.get(ProjectMember, (team.project.id, user.id))
    assert member is not None
    assert member.role is ProjectRole.MEMBER
    # Shown once: never in a list again.
    listed = ok(await admin.get(AGENTS))
    assert secret not in str(listed)
    assert secret[17:] not in str(listed)
    assert listed["items"][0]["key"]["prefix"] == key["key"]["prefix"]
    assert listed["can_register"] is True
    assert listed["max_agents"] == AI_AGENTS_MAX
    assert listed["settings"]["kagent_token_set"] is False
    # Audited with the agent rule.
    [register] = await _audit(db_session, "ai_agent.register")
    assert register.actor_id == team.platform.id
    assert register.target_id == user.id
    assert register.details["rule"] == "platform.manage_agents"
    assert register.details["purposes"] == ["evaluate", "research"]
    assert register.details["project_ids"] == [str(team.project.id)]
    [created_key] = await _audit(db_session, "api_key.create")
    assert created_key.details["rule"] == "platform.manage_agents"
    [member_add] = await _audit(db_session, "project.member_add")
    assert member_add.details["rule"] == "platform.manage_agents"
    assert secret not in str([e.details for e in await _audit(db_session, "api_key.create")])
    # The key: MCP works, REST never (c22).
    assert (await mcp_as(secret).ok("list_projects"))["projects"] == []
    async with key_client(app, secret) as http:
        assert_problem(await http.get(f"{API}/auth/me"), 403, "insufficient_scope")
        assert_problem(await http.get(f"{API}/projects"), 403, "insufficient_scope")


@pytest.mark.parametrize(
    ("purposes", "scopes"),
    [
        (["evaluate"], ["read", "evaluate", "mcp"]),
        (["research"], ["read", "write", "mcp"]),
        (["draft_section"], ["read", "write", "mcp"]),
        (["draft_section", "evaluate"], ["read", "write", "evaluate", "mcp"]),
    ],
)
async def test_key_scopes_follow_the_purposes(
    api: AsUser, team: Team, purposes: list[str], scopes: list[str]
) -> None:
    created = ok(await (await api(team.platform)).post(AGENTS, _body(team, purposes=purposes)), 201)

    assert created["key"]["key"]["scopes"] == scopes


async def test_registration_refusals(
    api: AsUser, team: Team, db_session: AsyncSession, app: FastAPI
) -> None:
    admin = await api(team.platform)
    ok(await admin.post(AGENTS, _body(team)), 201)

    taken = await admin.post(AGENTS, _body(team, display_name="Again"))
    unknown = await admin.post(AGENTS, _body(team, name="other", project_ids=[str(uuid4())]))

    assert_problem(taken, 409, "agent_taken")
    assert_problem(unknown, 422, "invalid_project")
    for who in (team.admin, team.member, team.owner):
        assert_problem(await (await api(who)).post(AGENTS, _body(team, name="x")), 403, "forbidden")
        assert_problem(await (await api(who)).get(AGENTS), 403, "forbidden")
    # Session only: a platform admin's own key is refused.
    from tests.api_keys.helpers import make_key

    key = await make_key(db_session, team.platform)
    async with key_client(app, key) as http:
        refused = await http.post(f"{API}{AGENTS}", json=_body(team, name="y"))
    assert_problem(refused, 403, "insufficient_scope")


async def test_by_default_agents_are_registered_in_soundings_only(api: AsUser, team: Team) -> None:
    """L8: without SOUNDINGS_AI_AGENT_NAMESPACES (outside the chart, which sets the release
    namespace), kagent's own built-in agents in its namespace can't be registered."""
    admin = await api(team.platform)

    refused = await admin.post(AGENTS, _body(team, namespace="kagent"))
    allowed = await admin.post(AGENTS, _body(team, namespace="soundings"))

    assert_problem(refused, 422, "namespace_not_allowed")
    assert allowed.status_code == 201, allowed.text


@pytest.mark.settings(ai_agent_namespaces=["soundings", "agents"])
async def test_namespaces_outside_the_allow_list_are_refused(api: AsUser, team: Team) -> None:
    admin = await api(team.platform)

    refused = await admin.post(AGENTS, _body(team, namespace="kagent"))
    allowed = await admin.post(AGENTS, _body(team, namespace="agents"))

    assert_problem(refused, 422, "namespace_not_allowed")
    ok(allowed, 201)


async def test_a_51st_agent_is_refused(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    for n in range(AI_AGENTS_MAX):
        await make_agent(db_session, [team.project], name=f"agent-{n}")

    refused = await (await api(team.platform)).post(AGENTS, _body(team))
    listed = ok(await (await api(team.platform)).get(AGENTS))

    assert_problem(refused, 409, "too_many_agents")
    assert listed["can_register"] is False


BREAK_GLASS = {
    "break_glass_enabled": True,
    "break_glass_username": "emergency-admin",
    "break_glass_password": "correct horse battery staple",
    "dev_login_enabled": False,
}


@pytest.mark.settings(**BREAK_GLASS)
async def test_the_break_glass_account_cannot_register_or_rotate(
    client: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    agent = await make_agent(db_session, [team.project], key=True)
    signed_in = await client.post(
        f"{API}/auth/break-glass",
        json={"username": "emergency-admin", "password": "correct horse battery staple"},
    )
    assert signed_in.status_code == 200, signed_in.text
    client.headers["X-CSRF-Token"] = client.cookies["soundings_csrf"]

    register = await client.post(f"{API}{AGENTS}", json=_body(team))
    rotate = await client.post(f"{API}{AGENTS}/{agent.id}/key")
    listed = await client.get(f"{API}{AGENTS}")

    assert_problem(register, 403, "break_glass_account")
    assert_problem(rotate, 403, "break_glass_account")
    assert listed.json()["can_register"] is False


@pytest.mark.settings(**BREAK_GLASS)
async def test_the_break_glass_account_cannot_widen_an_agent(
    client: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    """L5 (c20): adding a purpose or a project widens the agent's key, which is issuing
    a key; narrowing, renaming and disabling (an emergency stop) still work."""
    other = await make_project(db_session, slug="other", key="OTH", name="Other")
    agent = await make_agent(
        db_session, [team.project], key=True, purposes=[AiRunKind.EVALUATE, AiRunKind.RESEARCH]
    )
    signed_in = await client.post(
        f"{API}/auth/break-glass",
        json={"username": "emergency-admin", "password": "correct horse battery staple"},
    )
    assert signed_in.status_code == 200, signed_in.text
    client.headers["X-CSRF-Token"] = client.cookies["soundings_csrf"]
    path = f"{API}{AGENTS}/{agent.id}"
    projects = [str(team.project.id)]

    purpose = await client.patch(path, json={"purposes": ["evaluate", "draft_section"]})
    project = await client.patch(path, json={"project_ids": [*projects, str(other.id)]})
    unknown = await client.patch(path, json={"project_ids": [*projects, str(uuid4())]})
    narrowed = await client.patch(path, json={"purposes": ["evaluate"], "display_name": "Bot"})
    disabled = await client.patch(path, json={"enabled": False})

    assert_problem(purpose, 403, "break_glass_account")
    assert_problem(project, 403, "break_glass_account")
    assert_problem(unknown, 403, "break_glass_account")  # 403 before 422
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["purposes"] == ["evaluate"]
    assert disabled.status_code == 200, disabled.text
    key = await db_session.scalar(
        select(ApiKey)
        .where(ApiKey.user_id == agent.user.id)
        .execution_options(populate_existing=True)
    )
    assert key is not None
    assert key.scopes == ["read", "evaluate", "mcp"]
    assert key.project_ids == [team.project.id]
    assert key.revoked_at is not None


# --- Updating -----------------------------------------------------------------------------
async def test_purposes_and_projects_change_the_same_key_and_memberships(
    api: AsUser, team: Team, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    admin = await api(team.platform)
    other = await make_project(db_session, slug="other", key="OTH", name="Other")
    created = ok(await admin.post(AGENTS, _body(team, purposes=["evaluate"])), 201)
    agent_id, secret = created["agent"]["id"], created["key"]["secret"]
    sa = UUID(created["agent"]["service_account"]["id"])

    updated = ok(
        await admin.patch(
            f"{AGENTS}/{agent_id}",
            {"purposes": ["research", "draft_section"], "project_ids": [str(other.id)]},
        )
    )

    key = await key_row(db_session, secret)
    assert key.revoked_at is None
    assert key.scopes == ["read", "write", "mcp"]
    assert key.project_ids == [other.id]
    assert updated["key"]["id"] == created["key"]["key"]["id"]
    assert [p["key"] for p in updated["projects"]] == ["OTH"]
    assert (
        await db_session.get(ProjectMember, (team.project.id, sa), populate_existing=True) is None
    )
    moved = await db_session.get(ProjectMember, (other.id, sa))
    assert moved is not None
    assert moved.role is ProjectRole.MEMBER
    [update] = await _audit(db_session, "ai_agent.update")
    assert update.details["changed"] == ["purposes", "project_ids"]
    # L4: what the agent (and so its key) may now do, not only which fields changed.
    assert update.details["purposes"] == ["research", "draft_section"]
    assert update.details["project_ids"] == [str(other.id)]
    assert update.details["key_id"] == created["key"]["key"]["id"]
    assert update.details["key_scopes"] == ["read", "write", "mcp"]
    assert update.details["key_project_ids"] == [str(other.id)]
    assert [e.details["rule"] for e in await _audit(db_session, "project.member_remove")] == [
        "platform.manage_agents"
    ]
    # The same secret still works (no Secret to redeploy).
    assert (await mcp_as(secret).ok("list_projects"))["projects"] == []


async def test_dropping_a_purpose_or_a_project_cancels_the_runs_it_covered(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    team = crew.team
    other = await make_project(db_session, slug="other", key="OTH", name="Other")
    elsewhere = await make_idea(db_session, other)
    research = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    evaluate = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    queued = await open_run(
        db_session, crew.agent, elsewhere, AiRunKind.EVALUATE, status=AiRunStatus.QUEUED
    )
    admin = await api(team.platform)
    ok(
        await admin.patch(
            f"{AGENTS}/{crew.agent.id}", {"project_ids": [str(team.project.id), str(other.id)]}
        )
    )

    ok(await admin.patch(f"{AGENTS}/{crew.agent.id}", {"purposes": ["evaluate", "draft_section"]}))
    ok(await admin.patch(f"{AGENTS}/{crew.agent.id}", {"project_ids": [str(team.project.id)]}))

    assert (await run_row(db_session, research.id)).cancel_requested_at is not None
    assert (await run_row(db_session, evaluate.id)).cancel_requested_at is None
    assert (await run_row(db_session, queued.id)).status is AiRunStatus.CANCELLED
    cancels = await _audit(db_session, "ai_run.cancel")
    assert [(e.details["run_id"], e.details["rule"]) for e in cancels] == [
        (str(research.id), "platform.manage_agents"),
        (str(queued.id), "platform.manage_agents"),
    ]


async def test_disabling_cancels_everything_and_revokes_the_key(
    api: AsUser, crew: Crew, db_session: AsyncSession, app: FastAPI, mcp_as: McpAs
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    admin = await api(crew.team.platform)

    disabled = ok(await admin.patch(f"{AGENTS}/{crew.agent.id}", {"enabled": False}))
    enabled = ok(await admin.patch(f"{AGENTS}/{crew.agent.id}", {"enabled": True}))

    assert disabled["enabled"] is False
    assert disabled["key"] is None
    assert enabled["enabled"] is True
    assert enabled["key"] is None
    assert (await run_row(db_session, run.id)).cancel_requested_at is not None
    assert (await key_row(db_session, crew.agent.key)).revoked_at is not None
    [revoke] = await _audit(db_session, "api_key.revoke")
    assert revoke.details["rule"] == "platform.manage_agents"
    updates = await _audit(db_session, "ai_agent.update")
    assert [(e.details["changed"], e.details["enabled"]) for e in updates] == [
        (["enabled"], False),
        (["enabled"], True),
    ]
    async with key_client(app, crew.agent.key, **JSON_HEADERS) as http:
        refused = await http.post("/mcp", json=rpc("tools/list"))
    assert refused.status_code == 401


async def test_the_display_name_renames_the_service_account(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    ok(
        await (await api(crew.team.platform)).patch(
            f"{AGENTS}/{crew.agent.id}", {"display_name": "Scout"}
        )
    )

    user = await db_session.get(User, crew.agent.user.id, populate_existing=True)
    agent = await db_session.get(AiAgent, crew.agent.id, populate_existing=True)
    assert user is not None
    assert agent is not None
    assert (user.display_name, agent.display_name) == ("Scout", "Scout")


# --- Rotating -----------------------------------------------------------------------------
async def test_rotation_revokes_the_old_key_in_the_same_change(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    assert crew.agent.key is not None
    old = await key_row(db_session, crew.agent.key)

    response = await (await api(crew.team.platform)).post(f"{AGENTS}/{crew.agent.id}/key")

    rotated = ok(response, 201)
    assert response.headers["cache-control"] == "no-store"
    assert rotated["revoked_key_id"] == str(old.id)
    assert (await key_row(db_session, crew.agent.key)).revoked_at is not None
    new = await key_row(db_session, rotated["key"]["secret"])
    assert new.revoked_at is None
    assert new.scopes == ["read", "write", "evaluate", "mcp"]
    assert new.project_ids == [crew.team.project.id]
    assert rotated["agent"]["key"]["id"] == str(new.id)
    assert rotated["secret_manifest"].count(rotated["key"]["secret"]) == 1
    keys = list(
        await db_session.scalars(select(ApiKey).where(ApiKey.user_id == crew.agent.user.id))
    )
    assert len(keys) == 2


# --- Test connection ----------------------------------------------------------------------
async def test_connection_reads_the_built_card_url_only(
    api: AsUser, crew: Crew, app: FastAPI
) -> None:
    kagent = FakeKagent()
    app.state.ai_transport = kagent.transport

    tested = ok(await (await api(crew.team.platform)).post(f"{AGENTS}/{crew.agent.id}/test"))

    url = "http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator/.well-known/agent-card.json"
    assert tested["ok"] is True
    assert tested["url"] == url
    assert tested["http_status"] == 200
    assert kagent.urls == {url}
    assert tested["card"]["name"] == "idea_evaluator"
    assert tested["card"]["streaming"] is True
    assert len(tested["card"]["skills"]) == 20
    assert "evil.example" not in str(tested)


async def test_connection_failures_are_answered_not_raised(
    api: AsUser, crew: Crew, app: FastAPI, db_session: AsyncSession
) -> None:
    app.state.ai_transport = FakeKagent().transport
    admin = await api(crew.team.platform)
    down = await make_agent(db_session, [crew.team.project], name="x-down")
    moved = await make_agent(db_session, [crew.team.project], name="x-redirect")

    unreachable = ok(await admin.post(f"{AGENTS}/{down.id}/test"))
    redirected = ok(await admin.post(f"{AGENTS}/{moved.id}/test"))

    assert (unreachable["ok"], unreachable["error_code"], unreachable["http_status"]) == (
        False,
        "agent_unreachable",
        503,
    )
    assert unreachable["error_message"] == "Couldn't reach the agent. (HTTP 503)"
    assert (redirected["ok"], redirected["error_code"]) == (False, "agent_protocol_error")
    assert redirected["card"] is None


async def test_connection_tests_are_limited(api: AsUser, crew: Crew, app: FastAPI) -> None:
    app.state.ai_transport = FakeKagent().transport
    admin = await api(crew.team.platform)
    for _ in range(10):
        ok(await admin.post(f"{AGENTS}/{crew.agent.id}/test"))

    refused = await admin.post(f"{AGENTS}/{crew.agent.id}/test")

    assert_problem(refused, 429, "too_many_attempts")
    assert int(refused.headers["retry-after"]) >= 1


async def test_unknown_agents_are_404_after_the_403(api: AsUser, team: Team) -> None:
    admin = await api(team.platform)
    member = await api(team.member)
    missing = uuid4()

    for path in (f"{AGENTS}/{missing}", f"{AGENTS}/{missing}/test"):
        response = await (admin.get(path) if path.endswith(str(missing)) else admin.post(path))
        assert_problem(response, 404, "not_found")
    assert_problem(await member.get(f"{AGENTS}/{missing}"), 403, "forbidden")
    assert_problem(await admin.patch(f"{AGENTS}/{missing}", {"enabled": False}), 404, "not_found")
    assert_problem(await admin.post(f"{AGENTS}/{missing}/key"), 404, "not_found")
