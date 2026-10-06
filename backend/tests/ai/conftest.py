"""Fixtures for the Phase 6 tests (AI agents, runs, the runner, SSE).

* ``team`` / ``api`` (tests/ideas/conftest.py): Customer Innovation with a person in
  every role; ``api(user)`` signs in.
* ``crew``: the team plus a registered agent (``crew.agent``: service account member of
  the project, its key in ``crew.agent.key``) and an idea owned by ``team.owner``.
* ``mcp_as(secret)``: an MCP identity (tests/mcp/conftest.py ``Agent``): ``ok`` /
  ``fails`` / ``call`` a tool over the real ``/mcp`` route.
* ``kagent``: the in-process fake controller (tests/ai/fake_kagent.py) whose agents do
  their work through ``/mcp`` with the crew's agent key; ``ai_runtime``: the runner's
  runtime on it, with short timings.

AI is on in this package (``SOUNDINGS_AI_ENABLED``); mark a test
``@pytest.mark.settings(ai_enabled=False)`` to turn it off.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runner import AiRuntime
from app.config import Settings
from app.models.enums import IdeaStatus
from app.models.idea import Idea
from tests.ai.fake_kagent import FakeKagent
from tests.ai.helpers import Agent, make_agent
from tests.factories import make_idea
from tests.ideas.conftest import API, AsUser, Team, api, assert_problem, ok, team  # noqa: F401
from tests.mcp.conftest import Agent as McpIdentity
from tests.mcp.conftest import Connect, connect, full_scores, make_key  # noqa: F401 - fixtures

__all__ = ["API", "AsUser", "Crew", "McpAs", "Team", "assert_problem", "evaluation_args", "ok"]


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {"ai_enabled": True}


@dataclass
class Crew:
    team: Team
    agent: Agent
    idea: Idea
    observations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"CUST-{self.idea.number}"


@pytest.fixture
async def crew(db_session: AsyncSession, team: Team) -> Crew:  # noqa: F811 - the fixture
    agent = await make_agent(
        db_session, [team.project], key=True, creator=team.platform, name="idea-evaluator"
    )
    idea = await make_idea(
        db_session, team.project, title="Parcel lockers", owner=team.owner, status=IdeaStatus.NEW
    )
    return Crew(team=team, agent=agent, idea=idea)


McpAs = Callable[[str], McpIdentity]


@pytest.fixture
def mcp_as(connect: Connect) -> McpAs:  # noqa: F811 - the fixture above
    def make(secret: str) -> McpIdentity:
        return McpIdentity(connect, secret)

    return make


def evaluation_args(crew: Crew, rubric: dict[str, Any], *, score: int = 4) -> dict[str, Any]:
    """A complete AI evaluation of ``crew.idea`` for ``submit_evaluation``: a rationale
    and two sources per criterion (as the fake agent sends)."""
    scores = []
    for position, criterion in enumerate(rubric["criteria"]):
        scores.append(
            {
                "criterion_id": criterion["id"],
                "score": max(1, min(5, score - position % 2)),
                "comment": f"RATIONALE {criterion['name']} for {crew.ref}",
                "sources": [
                    {"title": f"Source {n}", "url": f"https://example.org/{crew.ref}/{n}"}
                    for n in (1, 2)
                ],
            }
        )
    return {
        "idea": crew.ref,
        "scores": scores,
        "recommendation": "maybe",
        "comment": "SUMMARY by the AI",
    }


Work = Callable[[dict[str, Any]], Awaitable[None]]


def agent_work(crew: Crew, identity: McpIdentity) -> Work:
    """What a well-behaved agent does for each kind (contract-phase6 section 3.12)."""

    async def work(metadata: dict[str, Any]) -> None:
        idea = metadata["idea"]
        kind = metadata["kind"]
        if kind == "evaluate":
            rubric = await identity.ok("get_rubric", idea=idea)
            seen = await identity.ok("get_idea", idea=idea)
            crew.observations.append({"score_hidden": seen["idea"]["score_hidden"]})
            await identity.ok("submit_evaluation", **evaluation_args(crew, rubric))
        elif kind == "research":
            seen = await identity.ok("get_idea", idea=idea)
            crew.observations.append({"score_hidden": seen["idea"]["score_hidden"]})
            await identity.ok(
                "add_research_note",
                idea=idea,
                body_md="## Findings\n\nNOTE TEXT with [a link](https://example.org/x).",
                sources=[
                    {"title": f"Study {n}", "url": f"https://example.org/study/{n}"}
                    for n in (1, 2, 3)
                ],
            )
        elif kind == "draft_section":
            await identity.ok("get_idea", idea=idea)
            await identity.ok("get_proposal", idea=idea)
            await identity.ok(
                "propose_proposal_section",
                idea=idea,
                section_key=metadata["section_key"],
                body_md="DRAFT TEXT for the section.",
            )

    return work


@pytest.fixture
def kagent(crew: Crew, mcp_as: McpAs) -> FakeKagent:
    assert crew.agent.key is not None
    return FakeKagent(agent_work(crew, mcp_as(crew.agent.key)))


@pytest.fixture
def ai_runtime(app: FastAPI, settings: Settings, kagent: FakeKagent) -> AiRuntime:
    return AiRuntime(
        settings=settings,
        sessionmaker=app.state.sessionmaker,
        transport=kagent.transport,
        cancel_poll=0.05,
        heartbeat=0.2,
        poll_interval=0.05,
        retry_waits=(0.01, 0.02),
    )
