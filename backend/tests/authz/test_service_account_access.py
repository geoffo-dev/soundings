"""A service account sees only the projects it has a role in (security review M3).

Role matrix section 1 and contract-phase5 section 3.7: an agent "needs a real project
role". Without one it is not the internal-project non-member (NMi) a person is: every
project and idea rule answers it as NMp (404), whatever the visibility, and lists leave
those projects out. Otherwise text planted in one project could make an agent read an
unrelated internal one (the cross-project prompt-injection path section 3.7 warns about).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.service import InvalidProjectProblem
from app.authz import (
    POLICY,
    IdeaFacts,
    ProjectFacts,
    Resource,
    Rule,
    authorize,
    visible_projects,
)
from app.authz.policy import Scope
from app.domain.principal import Principal
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility
from app.models.project import Project
from app.models.user import User
from tests.api_keys.helpers import API, World, key_client, make_key, problem
from tests.factories import add_member, make_idea
from tests.mcp.conftest import headers, rpc

PROJECT_AND_IDEA_RULES = sorted(
    (rule for rule, spec in POLICY.items() if spec.scope in (Scope.PROJECT, Scope.IDEA)),
    key=str,
)


def _principal(*, service_account: bool) -> Principal:
    user = User(id=uuid4(), email="agent@example.com", display_name="Agent")
    user.is_service_account = service_account
    user.is_platform_admin = False
    return Principal(user=user)


def _resource(visibility: ProjectVisibility, role: ProjectRole | None) -> Resource:
    project = ProjectFacts(
        id=uuid4(),
        visibility=visibility,
        archived=False,
        allow_volunteer_owners=True,
        public_submission_enabled=True,
        slug_reserved=False,
    )
    idea = IdeaFacts(
        id=uuid4(),
        status=IdeaStatus.SHORTLISTED,
        owner_id=None,
        submitted_by_id=None,
        evaluation_closed=False,
        held_for=None,
        my_evaluation=EvaluatorState.INVITED,
    )
    return Resource(project=project, role=role, idea=idea)


# --- The policy -------------------------------------------------------------------------
@pytest.mark.parametrize("rule", PROJECT_AND_IDEA_RULES, ids=str)
def test_without_a_role_an_internal_project_is_404_for_a_service_account(rule: Rule) -> None:
    decision = authorize(
        _principal(service_account=True), rule, _resource(ProjectVisibility.INTERNAL, None)
    )

    assert (decision.allowed, decision.status, decision.code) == (False, 404, "not_found")


@pytest.mark.parametrize("rule", PROJECT_AND_IDEA_RULES, ids=str)
def test_a_service_account_without_a_role_is_answered_like_a_private_non_member(
    rule: Rule,
) -> None:
    agent = _principal(service_account=True)
    person = _principal(service_account=False)

    internal = authorize(agent, rule, _resource(ProjectVisibility.INTERNAL, None))
    private = authorize(person, rule, _resource(ProjectVisibility.PRIVATE, None))

    assert (internal.allowed, internal.status, internal.code) == (
        private.allowed,
        private.status,
        private.code,
    )


@pytest.mark.parametrize("rule", PROJECT_AND_IDEA_RULES, ids=str)
@pytest.mark.parametrize("role", [ProjectRole.MEMBER, ProjectRole.VIEWER], ids=str)
@pytest.mark.parametrize("visibility", list(ProjectVisibility), ids=str)
def test_with_a_role_a_service_account_is_decided_like_a_person(
    rule: Rule, role: ProjectRole, visibility: ProjectVisibility
) -> None:
    resource = _resource(visibility, role)

    agent = authorize(_principal(service_account=True), rule, resource)
    person = authorize(_principal(service_account=False), rule, resource)

    # c21 (volunteering) is the one rule a person may pass and an agent not.
    if rule is Rule.IDEA_VOLUNTEER_OWNER and person.allowed:
        assert (agent.status, agent.code) == (403, "forbidden")
    else:
        assert (agent.allowed, agent.status, agent.code) == (
            person.allowed,
            person.status,
            person.code,
        )


def test_a_person_without_a_role_still_sees_internal_projects() -> None:
    decision = authorize(
        _principal(service_account=False),
        Rule.PROJECT_VIEW,
        _resource(ProjectVisibility.INTERNAL, None),
    )

    assert decision.allowed


# --- Lists, REST and MCP ----------------------------------------------------------------
async def _visible(db: AsyncSession, user: User) -> set[str]:
    return set(await db.scalars(select(Project.slug).where(visible_projects(Principal(user=user)))))


async def test_lists_leave_out_internal_projects_without_a_role(
    db_session: AsyncSession, world: World
) -> None:
    assert await _visible(db_session, world.bot) == {"customer-innovation"}
    assert await _visible(db_session, world.outsider) == {"internal-tools"}

    await add_member(db_session, world.tools, world.bot, ProjectRole.VIEWER)

    assert await _visible(db_session, world.bot) == {"customer-innovation", "internal-tools"}


async def _tool(app: FastAPI, key: str, tool: str, **arguments: Any) -> dict[str, Any]:
    """One ``tools/call`` over HTTP: its result (``isError``, ``structuredContent``)."""
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as http:
        response = await http.post(
            "/mcp",
            json=rpc("tools/call", {"name": tool, "arguments": arguments}),
            headers=headers(key),
        )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


async def test_an_agents_key_never_reaches_an_internal_project_without_a_role(
    app: FastAPI, db_session: AsyncSession, world: World
) -> None:
    idea = await make_idea(db_session, world.tools, title="Internal roadmap", summary="Plans")
    idea_key = f"TOOLS-{idea.number}"
    key = await make_key(db_session, world.bot, scopes=["read", "mcp"])

    projects = await _tool(app, key, "list_projects")
    found = await _tool(app, key, "search_ideas", query="roadmap")
    got = await _tool(app, key, "get_idea", idea=idea_key)
    rubric = await _tool(app, key, "get_rubric", project=world.tools.slug)

    slugs = [project["slug"] for project in projects["structuredContent"]["projects"]]
    assert slugs == ["customer-innovation"]
    assert found["structuredContent"]["items"] == []
    for result in (got, rubric):
        assert result["isError"] is True
        assert result["structuredContent"]["code"] == "not_found"

    async with key_client(app, key) as http:
        listed = await http.get(f"{API}/projects")
        project = await http.get(f"{API}/projects/{world.tools.slug}")
        by_key = await http.get(f"{API}/ideas/{idea_key}")

    assert listed.status_code == 200, listed.text
    assert [item["slug"] for item in listed.json()] == ["customer-innovation"]
    problem(project, 404, "not_found")
    problem(by_key, 404, "not_found")


async def test_an_agents_key_can_not_be_restricted_to_an_internal_project_without_a_role(
    db_session: AsyncSession, world: World
) -> None:
    with pytest.raises(InvalidProjectProblem):
        await make_key(db_session, world.bot, project_ids=[world.tools.id])

    await add_member(db_session, world.tools, world.bot, ProjectRole.MEMBER)

    assert await make_key(db_session, world.bot, project_ids=[world.tools.id])
