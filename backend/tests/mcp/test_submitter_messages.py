"""Phase 11 (contract-phase11 section 11): the conversation with a public submitter is in no
MCP tool, result or export: no tool reads or writes it, ``get_idea`` and ``search_ideas``
carry nothing of it for any key (a platform admin's with every scope included), and the
proposal's exports leave it out."""

from __future__ import annotations

import json

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import IdeaStatus
from app.models.idea import Idea
from tests.ideas.conftest import AsUser
from tests.mcp.conftest import AsAgent, Connect, MakeKey, Team, ok
from tests.public.conftest import add_message, make_public_idea

TEAM_TEXT = "Quokka-zeppelin question for Sam"
REPLY_TEXT = "Quokka-zeppelin answer from Sam"


async def public_idea(db: AsyncSession, settings: Settings, team: Team) -> Idea:
    _, idea = await make_public_idea(
        db, settings, team, email="sam@example.org", verified=True, owner=team.owner
    )
    await add_message(db, idea, author=team.admin, body=TEAM_TEXT)
    await add_message(db, idea, "submitter", body=REPLY_TEXT)
    return idea


async def test_no_tool_reads_or_writes_the_conversation(
    team: Team, db_session: AsyncSession, settings: Settings, make_key: MakeKey, connect: Connect
) -> None:
    await public_idea(db_session, settings, team)
    secret = await make_key(team.platform)

    async with connect(secret) as client:
        tools = (await client.list_tools()).tools

    assert len(tools) == 13  # unchanged since Phase 10
    for tool in tools:
        described = json.dumps(tool.model_dump()).lower()
        assert "submitter" not in tool.name
        assert "conversation" not in described


async def test_idea_results_carry_nothing_of_it(
    team: Team, db_session: AsyncSession, settings: Settings, as_agent: AsAgent
) -> None:
    idea = await public_idea(db_session, settings, team)
    key = f"{team.project.key}-{idea.number}"

    for user in (team.platform, team.admin, team.owner):
        agent = await as_agent(user)
        detail = await agent.ok("get_idea", idea=key)
        found = await agent.ok("search_ideas", query="Quokka-zeppelin")
        listed = await agent.ok("search_ideas", query=key)
        for result in (detail, found, listed):
            assert "Quokka" not in json.dumps(result)
        assert found["items"] == []


async def test_the_proposals_exports_leave_it_out(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    idea = await public_idea(db_session, settings, team)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(status=IdeaStatus.SHORTLISTED)
    )
    await db_session.commit()
    owner = await api(team.owner)
    ok(await owner.post(f"/ideas/{idea.id}/proposal"), 201)

    markdown = await owner.get(f"/ideas/{idea.id}/proposal/markdown")

    assert markdown.status_code == 200, markdown.text
    assert "Quokka" not in markdown.text
