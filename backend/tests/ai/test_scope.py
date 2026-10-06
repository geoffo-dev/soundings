"""c22, the run scope (contract-phase6 sections 3.5 and 10), for every MCP tool with and
without an open run: each of an agent's calls names its run (``run_id``) and reaches only
that run's idea, so two runs open at once can't reach each other, a run that ended stays
ended while a newer one is open, and nothing tells the agent which other ideas exist; and
rule 9: an agent never sees others' score data, before or after it submits, on evaluate
and research runs, and sees its own evaluation only in an evaluate run."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
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
from tests.ai.helpers import make_agent, open_run, run_row
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
@pytest.mark.parametrize("named", [True, False], ids=["run_id", "no_run_id"])
async def test_without_an_open_run_an_agent_can_do_nothing(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, state: str, named: bool
) -> None:
    run = None
    if state != "none":
        status = AiRunStatus.RUNNING if state == "cancel_requested" else AiRunStatus(state)
        run = await open_run(
            db_session,
            crew.agent,
            crew.idea,
            AiRunKind.EVALUATE,
            status=status,
            cancel_requested=state == "cancel_requested",
        )
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key).for_run(run if named else None)

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


async def test_an_open_run_needs_its_run_id(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    """H1: an open run doesn't open the key; only a call naming it does."""
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    unnamed = mcp_as(crew.agent.key)
    stranger = mcp_as(crew.agent.key).for_run(uuid4())

    for agent in (unnamed, stranger):
        assert (await agent.ok("list_projects"))["projects"] == []
        assert (await agent.ok("search_ideas"))["items"] == []
        refusals = {
            tool: await agent.fails(tool, **args) for tool, args in _calls(crew, crew.idea).items()
        }
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
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key).for_run(run)

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
    # Another idea or project, wherever it is: not this run's (never looked up, N1).
    assert await agent.fails("get_idea", idea=f"CUST-{sibling.number}") == "ai_run_not_active"
    assert await agent.fails("get_idea", idea=str(sibling.id)) == "ai_run_not_active"
    assert await agent.fails("get_rubric", project="other") == "ai_run_not_active"
    assert await agent.fails("get_idea", idea=f"OTH-{elsewhere.number}") == "ai_run_not_active"
    assert (await agent.ok("search_ideas", project="other"))["items"] == []
    # Its own idea by id or in another case works too.
    assert (await agent.ok("get_idea", idea=str(crew.idea.id)))["idea"]["key"] == crew.ref
    assert (await agent.ok("get_idea", idea=crew.ref.lower()))["idea"]["key"] == crew.ref
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
    run = await open_run(
        db_session, crew.agent, idea, AiRunKind.DRAFT_SECTION, section_key=ProposalSectionKey.RISKS
    )
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key).for_run(run)

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
    # Even naming the crew agent's open run: it isn't this account's.
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    agent = mcp_as(await make_key(bot, projects=[crew.team.project])).for_run(run)

    assert (await agent.ok("list_projects"))["projects"] == []
    assert (await agent.ok("search_ideas"))["items"] == []
    for tool, args in _calls(crew, crew.idea).items():
        assert await agent.fails(tool, **args) == EXPECTED_WITHOUT_RUN[tool], tool


async def test_people_never_write_research_notes(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, make_key: MakeKey
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    for who in (crew.team.owner, crew.team.admin, crew.team.platform):
        person = mcp_as(await make_key(who))
        assert await person.fails("add_research_note", idea=crew.ref, body_md="x") == "forbidden"
        # A run id means nothing for people (ignored): still forbidden.
        named = person.for_run(run)
        assert await named.fails("add_research_note", idea=crew.ref, body_md="x") == "forbidden"
        assert (await named.ok("get_idea", idea=crew.ref))["idea"]["key"] == crew.ref
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
    run = await open_run(db_session, crew.agent, crew.idea, kind)
    evaluate = run
    if kind is AiRunKind.RESEARCH:  # and an evaluate run, so it can submit too
        evaluate = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key).for_run(run)
    evaluating = mcp_as(crew.agent.key).for_run(evaluate)

    before = (await agent.ok("get_idea", idea=crew.ref))["idea"]
    [listed] = (await agent.ok("search_ideas"))["items"]
    by_score = await agent.ok("search_ideas", sort="score")
    rubric = await evaluating.ok("get_rubric", idea=crew.ref)
    submitted = await evaluating.ok("submit_evaluation", **evaluation_args(crew, rubric))
    after = (await agent.ok("get_idea", idea=crew.ref))["idea"]
    [listed_after] = (await agent.ok("search_ideas"))["items"]
    own = (await evaluating.ok("get_idea", idea=crew.ref))["idea"]

    _blind(before)
    _blind(after)
    _blind(own)
    for summary in (listed, listed_after, by_score["items"][0]):
        assert {key: summary[key] for key in HIDDEN} == HIDDEN
    # Its own evaluation, with its rationale and sources, stays visible to it: in its
    # evaluate run only (M1: a research or draft run's output could quote it to people
    # who are still blind). The state alone ("submitted") isn't score data.
    assert after["my_evaluation_state"] == "submitted"
    if kind is AiRunKind.RESEARCH:
        assert after["my_evaluation"] is None
    mine = own["my_evaluation"]
    assert submitted["evaluation"]["state"] == mine["state"] == "submitted"
    assert mine["scores"][0]["comment"].startswith("RATIONALE")
    assert [s["url"] for s in mine["scores"][0]["sources"]] == [
        f"https://example.org/{crew.ref}/1",
        f"https://example.org/{crew.ref}/2",
    ]
    # The evaluators' binary progress is fine (rule 2): nobody's draft or scores.
    assert {e["state"] for e in after["evaluators"]} <= {"invited", "submitted"}


@pytest.mark.parametrize("kind", [AiRunKind.RESEARCH, AiRunKind.DRAFT_SECTION])
async def test_an_agent_sees_its_own_scores_only_in_its_evaluate_run(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs, kind: AiRunKind
) -> None:
    """M1: after its evaluate run, a research or draft run on the same idea doesn't show
    the agent its own scores, so its note or draft can't pass them to pending evaluators."""
    if kind is AiRunKind.DRAFT_SECTION:
        crew.idea.status = IdeaStatus.SHORTLISTED
        await db_session.commit()
        ok(await (await api(crew.team.owner)).post(f"/ideas/{crew.ref}/proposal"), 201)
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    assert crew.agent.key is not None
    evaluate = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    evaluator = mcp_as(crew.agent.key).for_run(evaluate)
    rubric = await evaluator.ok("get_rubric", idea=crew.ref)
    await evaluator.ok("submit_evaluation", **evaluation_args(crew, rubric, score=5))
    evaluate.status = AiRunStatus.SUCCEEDED
    evaluate.finished_at = utcnow()
    await db_session.commit()
    later = await open_run(db_session, crew.agent, crew.idea, kind)
    agent = mcp_as(crew.agent.key).for_run(later)

    seen = (await agent.ok("get_idea", idea=crew.ref))["idea"]

    assert seen["my_evaluation"] is None
    assert seen["my_evaluation_state"] == "submitted"
    _blind(seen)


# --- H1: two runs open at once ------------------------------------------------------------
async def test_two_open_runs_of_one_agent_never_reach_each_other(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    """The review's H1: one agent serves CUST (internal) and TOOLS (private), with an
    evaluate run open on a TOOLS idea and a research run on a CUST idea. Text planted in
    the CUST idea can't make the research run read the TOOLS idea and copy it into CUST's
    feed: every call names its run and reaches only that run's idea."""
    team = crew.team
    tools = await make_project(db_session, slug="tools", key="TOOLS", name="Tools")
    secret = await make_idea(db_session, tools, title="Private tooling plan")
    agent_row = await make_agent(
        db_session, [team.project, tools], key=True, creator=team.platform, name="two-projects"
    )
    assert agent_row.key is not None
    await add_evaluator(db_session, secret, agent_row.user)
    on_tools = await open_run(db_session, agent_row, secret, AiRunKind.EVALUATE)
    on_cust = await open_run(db_session, agent_row, crew.idea, AiRunKind.RESEARCH)
    research = mcp_as(agent_row.key).for_run(on_cust)
    evaluate = mcp_as(agent_row.key).for_run(on_tools)
    tools_ref = f"TOOLS-{secret.number}"

    # The research run (on CUST) sees CUST's idea only.
    assert [p["slug"] for p in (await research.ok("list_projects"))["projects"]] == [team.slug]
    assert [i["key"] for i in (await research.ok("search_ideas"))["items"]] == [crew.ref]
    assert (await research.ok("search_ideas", project="tools"))["items"] == []
    assert await research.fails("get_idea", idea=tools_ref) == "ai_run_not_active"
    assert await research.fails("get_idea", idea=str(secret.id)) == "ai_run_not_active"
    assert await research.fails("get_rubric", project="tools") == "ai_run_not_active"
    # The evaluate run (on TOOLS) can't write into CUST, nor read it.
    assert await evaluate.fails("add_research_note", idea=crew.ref, body_md="x") == (
        "ai_run_not_active"
    )
    assert await evaluate.fails("get_idea", idea=crew.ref) == "ai_run_not_active"
    assert [i["key"] for i in (await evaluate.ok("search_ideas"))["items"]] == [tools_ref]
    # Each still does its own work.
    assert (await research.ok("get_idea", idea=crew.ref))["idea"]["key"] == crew.ref
    assert (await evaluate.ok("get_idea", idea=tools_ref))["idea"]["key"] == tools_ref
    note = await research.ok("add_research_note", idea=crew.ref, body_md="On CUST only.")
    assert note["idea"]["key"] == crew.ref


async def test_a_run_that_ended_stays_ended_while_a_newer_one_is_open(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    """An agent task that outlives its run (kagent-adk 0.10.2 can't cancel) can't act
    through a newer run on the same idea: its calls name the run that ended."""
    ended = await open_run(
        db_session, crew.agent, crew.idea, AiRunKind.RESEARCH, status=AiRunStatus.TIMED_OUT
    )
    newer = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    assert crew.agent.key is not None
    late = mcp_as(crew.agent.key).for_run(ended)

    assert await late.fails("get_idea", idea=crew.ref) == "ai_run_not_active"
    assert await late.fails("add_research_note", idea=crew.ref, body_md="Late.") == (
        "ai_run_not_active"
    )
    assert (await late.ok("search_ideas"))["items"] == []
    assert (await run_row(db_session, newer.id)).activity_event_id is None


async def test_an_agent_cant_tell_which_other_ideas_exist(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    """N1: with or without a run, another idea that exists and one that doesn't get the
    same answer (the reference is compared with the run's idea, never looked up)."""
    sibling = await make_idea(db_session, crew.team.project, title="Sibling idea")
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    assert crew.agent.key is not None
    for agent in (mcp_as(crew.agent.key), mcp_as(crew.agent.key).for_run(run)):
        for tool in ("get_idea", "get_proposal", "add_research_note", "submit_evaluation"):
            extra: dict[str, dict[str, Any]] = {
                "get_idea": {},
                "get_proposal": {},
                "add_research_note": {"body_md": "x"},
                "submit_evaluation": {"scores": [], "submit": False},
            }
            args = extra[tool]
            existing = await agent.fails(tool, idea=f"CUST-{sibling.number}", **args)
            missing = await agent.fails(tool, idea="CUST-999999", **args)
            assert existing == missing == "ai_run_not_active", tool
        assert await agent.fails("get_rubric", project="no-such-project") == "ai_run_not_active"
        assert await agent.fails("create_idea", project="no-such", title="T", summary="S") == (
            "forbidden"
        )
        assert await agent.fails("add_comment", idea="CUST-999999", body_md="x") == "forbidden"
