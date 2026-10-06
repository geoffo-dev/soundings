"""c22, the run scope (contract-phase6 section 3.5), for every MCP tool with and without an
open run; and rule 9: an agent never sees others' score data, before or after it
submits, on evaluate and research runs."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    AiRunKind,
    AiRunStatus,
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ProposalSectionKey,
)
from app.models.idea import Idea
from app.models.project import ProjectMember
from tests.ai.conftest import AsUser, Crew, McpAs, evaluation_args, ok
from tests.ai.helpers import open_run
from tests.factories import add_evaluator, make_idea, make_project, make_user
from tests.mcp.conftest import MakeKey


def _calls(crew: Crew, idea: Idea, rubric_project: str | None = None) -> dict[str, dict[str, Any]]:
    ref = f"CUST-{idea.number}"
    return {
        "get_idea": {"idea": ref},
        "get_rubric": {"idea": ref},
        "get_proposal": {"idea": ref},
        "submit_evaluation": {"idea": ref, "scores": [], "submit": False},
        "propose_proposal_section": {"idea": ref, "section_key": "risks", "body_md": "x"},
        "add_research_note": {"idea": ref, "body_md": "A note."},
        "add_comment": {"idea": ref, "body_md": "Hi"},
        "create_idea": {"project": crew.team.slug, "title": "Mine", "summary": "One line."},
    }


EXPECTED_WITHOUT_RUN = {
    "get_idea": "ai_run_not_active",
    "get_rubric": "ai_run_not_active",
    "get_proposal": "ai_run_not_active",
    "submit_evaluation": "ai_run_not_active",
    "propose_proposal_section": "ai_run_not_active",
    "add_research_note": "ai_run_not_active",
    "add_comment": "forbidden",
    "create_idea": "forbidden",
}


@pytest.mark.parametrize(
    "state",
    ["none", "cancel_requested", "queued", "cancelled", "timed_out", "failed", "succeeded"],
)
async def test_without_an_open_run_an_agent_can_do_nothing(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, state: str
) -> None:
    if state != "none":
        status = AiRunStatus.RUNNING if state == "cancel_requested" else AiRunStatus(state)
        await open_run(
            db_session,
            crew.agent,
            crew.idea,
            AiRunKind.EVALUATE,
            status=status,
            cancel_requested=state == "cancel_requested",
        )
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)

    projects = await agent.ok("list_projects")
    found = await agent.ok("search_ideas")
    rubric = await agent.fails("get_rubric", project=crew.team.slug)
    refusals = {
        tool: await agent.fails(tool, **args) for tool, args in _calls(crew, crew.idea).items()
    }

    assert projects["projects"] == []
    assert found["items"] == []
    assert rubric == "ai_run_not_active"
    assert refusals == EXPECTED_WITHOUT_RUN


async def test_an_open_run_reaches_its_idea_only(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    team = crew.team
    sibling = await make_idea(db_session, team.project, title="Sibling idea")
    other = await make_project(db_session, slug="other", key="OTH", name="Other")
    elsewhere = await make_idea(db_session, other)
    db_session.add(  # a member there too, but its key is restricted to the crew's project
        ProjectMember(project_id=other.id, user_id=crew.agent.user.id, role=ProjectRole.MEMBER)
    )
    await db_session.commit()
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)

    projects = await agent.ok("list_projects")
    found = await agent.ok("search_ideas")
    by_text = await agent.ok("search_ideas", query="Sibling")
    rubric = await agent.ok("get_rubric", project=team.slug)
    detail = await agent.ok("get_idea", idea=crew.ref)

    assert [p["slug"] for p in projects["projects"]] == [team.slug]
    assert [i["key"] for i in found["items"]] == [crew.ref]
    assert by_text["items"] == []
    assert len(rubric["criteria"]) == len(team.rubric)
    assert detail["idea"]["key"] == crew.ref
    # Another idea, in the same project or another: not this run's.
    assert await agent.fails("get_idea", idea=f"CUST-{sibling.number}") == "ai_run_not_active"
    assert (
        await agent.fails("get_rubric", project="other") == "not_found"
    )  # key not restricted there
    assert await agent.fails("get_idea", idea=f"OTH-{elsewhere.number}") == "not_found"
    # Writes: only the run kind's tool.
    calls = _calls(crew, crew.idea)
    assert (
        await agent.fails("add_research_note", **calls["add_research_note"]) == "ai_run_not_active"
    )
    assert await agent.fails("propose_proposal_section", **calls["propose_proposal_section"]) == (
        "ai_run_not_active"
    )
    assert await agent.fails("add_comment", **calls["add_comment"]) == "forbidden"
    assert await agent.fails("create_idea", **calls["create_idea"]) == "forbidden"
    saved = await agent.ok("submit_evaluation", **calls["submit_evaluation"])
    assert saved["evaluation"]["state"] == "draft"


async def test_a_draft_run_writes_its_section_only(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    idea = await make_idea(
        db_session, crew.team.project, status=IdeaStatus.SHORTLISTED, owner=crew.team.owner
    )
    ref = f"CUST-{idea.number}"
    ok(await (await api(crew.team.owner)).post(f"/ideas/{ref}/proposal"), 201)
    await open_run(
        db_session, crew.agent, idea, AiRunKind.DRAFT_SECTION, section_key=ProposalSectionKey.RISKS
    )
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)

    proposal = await agent.ok("get_proposal", idea=ref)
    risks = await agent.ok("propose_proposal_section", idea=ref, section_key="risks", body_md="R")
    market = await agent.fails(
        "propose_proposal_section", idea=ref, section_key="market", body_md="M"
    )
    evaluate = await agent.fails("submit_evaluation", idea=ref, scores=[], submit=False)

    assert proposal["proposal"] is not None
    assert risks["suggestion"]["source"] == "ai"
    assert (market, evaluate) == ("ai_run_not_active", "ai_run_not_active")


async def test_a_service_account_without_an_agent_is_refused_everything(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, make_key: MakeKey
) -> None:
    bot = await make_user(db_session, "Loose bot", service_account=True)
    db_session.add(
        ProjectMember(project_id=crew.team.project.id, user_id=bot.id, role=ProjectRole.MEMBER)
    )
    await db_session.commit()
    agent = mcp_as(await make_key(bot, projects=[crew.team.project]))

    assert (await agent.ok("list_projects"))["projects"] == []
    assert (await agent.ok("search_ideas"))["items"] == []
    for tool, args in _calls(crew, crew.idea).items():
        assert await agent.fails(tool, **args) == EXPECTED_WITHOUT_RUN[tool], tool


async def test_people_never_write_research_notes(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, make_key: MakeKey
) -> None:
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    for who in (crew.team.owner, crew.team.admin, crew.team.platform):
        person = mcp_as(await make_key(who))
        assert await person.fails("add_research_note", idea=crew.ref, body_md="x") == "forbidden"
    # An idea the person can't see stays not_found (checked first).
    stranger = mcp_as(await make_key(crew.team.outsider))
    assert await stranger.fails("add_research_note", idea=crew.ref, body_md="x") == "not_found"


# --- Rule 9 -------------------------------------------------------------------------------
HIDDEN = {"score_hidden": True, "score": None, "high_disagreement": False}


def _blind(detail: dict[str, Any]) -> None:
    assert {key: detail[key] for key in HIDDEN} == HIDDEN
    assert detail["aggregate"] is None
    assert detail["evaluation_count"] == 0
    assert detail["evaluations"] == []


@pytest.mark.parametrize("kind", [AiRunKind.EVALUATE, AiRunKind.RESEARCH])
async def test_an_agent_never_sees_others_scores(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, kind: AiRunKind
) -> None:
    for evaluator, score in zip(crew.team.evaluators[:2], (1, 5), strict=True):
        await add_evaluator(
            db_session,
            crew.idea,
            evaluator,
            state=EvaluatorState.SUBMITTED,
            scores={c.name: score for c in crew.team.rubric},
        )
    from app.services.scoring import recompute_aggregates

    await recompute_aggregates(db_session, idea_ids=[crew.idea.id])
    await db_session.commit()
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    await open_run(db_session, crew.agent, crew.idea, kind)
    if kind is AiRunKind.RESEARCH:  # and an evaluate run, so it can submit too
        await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)

    before = (await agent.ok("get_idea", idea=crew.ref))["idea"]
    [listed] = (await agent.ok("search_ideas"))["items"]
    by_score = await agent.ok("search_ideas", sort="score")
    rubric = await agent.ok("get_rubric", idea=crew.ref)
    submitted = await agent.ok("submit_evaluation", **evaluation_args(crew, rubric))
    after = (await agent.ok("get_idea", idea=crew.ref))["idea"]
    [listed_after] = (await agent.ok("search_ideas"))["items"]

    _blind(before)
    _blind(after)
    for summary in (listed, listed_after, by_score["items"][0]):
        assert {key: summary[key] for key in HIDDEN} == HIDDEN
    # Its own evaluation, with its rationale and sources, stays visible to it.
    mine = after["my_evaluation"]
    assert submitted["evaluation"]["state"] == mine["state"] == "submitted"
    assert mine["scores"][0]["comment"].startswith("RATIONALE")
    assert [s["url"] for s in mine["scores"][0]["sources"]] == [
        f"https://example.org/{crew.ref}/1",
        f"https://example.org/{crew.ref}/2",
    ]
    # The evaluators' binary progress is fine (rule 2): nobody's draft or scores.
    assert {e["state"] for e in after["evaluators"]} <= {"invited", "submitted"}
