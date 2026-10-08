"""MCP and Phase 8 (contract-phase8 sections 2.4 and 3.11): ``get_idea`` shows the research
checklist and its answers, read only, to people and to agents (null while the project's
step is off); ``get_proposal`` lists the project's template sections, so clients learn the
keys there; ``propose_proposal_section`` with an unknown or removed key is the tool error
``unknown_section``; Research shows in ``search_ideas`` like any status; still ten tools."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AiRunKind, IdeaStatus, ProposalSectionKey, ResearchStep
from app.models.idea import Idea
from app.models.proposal import ProposalTemplateSection
from app.schemas.mcp import MCP_TOOLS
from tests.ai.helpers import make_agent, open_run
from tests.factories import make_idea, make_user
from tests.mcp.conftest import AsAgent, AsUser, Team, ok
from tests.research.conftest import answer, set_step

READ = ["read", "mcp"]
WRITE = ["read", "write", "mcp"]


def key_of(team: Team, idea: Idea) -> str:
    return f"{team.project.key}-{idea.number}"


def test_still_ten_tools() -> None:
    assert len(MCP_TOOLS) == 10


async def test_get_idea_shows_the_checklist_read_only(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH, owner=team.owner)
    await answer(db_session, idea, items[1], team.owner, "Le\u200bgal, 3 Oct: fine.")

    got = await (await as_agent(team.viewer, READ)).ok("get_idea", idea=key_of(team, idea))

    research = got["idea"]["research"]
    assert research["step"] == "before_evaluation"
    assert research["required_open"] == 1
    assert [(i["title"], i["required"]) for i in research["items"]] == [
        ("Not already being done elsewhere", True),
        ("Departments or teams consulted", True),
        ("Data protection considered", False),
    ]
    answered = research["items"][1]
    assert answered["answer"] == "Legal, 3 Oct: fine."  # invisible characters dropped
    assert answered["answered_by"]["display_name"] == "Olive Owner"
    assert research["items"][0]["answer"] is None
    assert got["idea"]["status"] == "research"


async def test_get_idea_research_is_null_while_the_step_is_off(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)

    got = await (await as_agent(team.member, READ)).ok("get_idea", idea=key_of(team, idea))

    assert got["idea"]["research"] is None


async def test_an_agent_reads_the_checklist_in_its_run(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH)
    await answer(db_session, idea, items[0], team.owner)
    bot = await make_user(db_session, "Research Agent", service_account=True)
    agent = await make_agent(db_session, [team.project], user=bot)
    run = await open_run(db_session, agent, idea, AiRunKind.RESEARCH)

    got = (
        await (await as_agent(bot, WRITE, [team.project]))
        .for_run(run)
        .ok("get_idea", idea=key_of(team, idea))
    )

    assert got["idea"]["research"]["items"][0]["answer"].startswith("Legal")


async def test_search_ideas_finds_research(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH)
    await make_idea(db_session, team.project)

    found = await (await as_agent(team.member, READ)).ok("search_ideas", status=["research"])

    assert [item["key"] for item in found["items"]] == [key_of(team, idea)]
    assert found["items"][0]["status"] == "research"


async def test_get_proposal_and_suggestions_follow_the_template(
    as_agent: AsAgent, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    ada = await api(team.admin)
    ok(
        await ada.put(
            f"/projects/{team.slug}/proposal-template",
            {
                "sections": [
                    {"key": "summary", "title": "Summary"},
                    {"title": "Carbon impact", "hint": "Tonnes of CO2e a year."},
                ]
            },
        )
    )
    ok(await (await api(team.owner)).post(f"/ideas/{key_of(team, idea)}/proposal"), 201)
    member = await as_agent(team.member, WRITE)
    ref = key_of(team, idea)

    proposal = await member.ok("get_proposal", idea=ref)
    created = await member.ok(
        "propose_proposal_section", idea=ref, section_key="carbon_impact", body_md="12 t."
    )
    removed = await member.fails(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="x"
    )
    unknown = await member.fails(
        "propose_proposal_section", idea=ref, section_key="nothing_here", body_md="x"
    )

    assert [(s["key"], s["title"], s["prompt"]) for s in proposal["proposal"]["sections"]] == [
        ("summary", "Summary", ""),
        ("carbon_impact", "Carbon impact", "Tonnes of CO2e a year."),
    ]
    assert created["suggestion"]["section_key"] == "carbon_impact"
    assert (removed, unknown) == ("unknown_section", "unknown_section")


async def test_an_agents_draft_of_a_section_removed_meanwhile_fails_cleanly(
    as_agent: AsAgent, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    ok(await (await api(team.owner)).post(f"/ideas/{key_of(team, idea)}/proposal"), 201)
    bot = await make_user(db_session, "Drafting Agent", service_account=True)
    agent = await make_agent(db_session, [team.project], user=bot)
    run = await open_run(
        db_session, agent, idea, AiRunKind.DRAFT_SECTION, section_key=ProposalSectionKey.MARKET
    )
    await db_session.execute(
        update(ProposalTemplateSection)
        .where(
            ProposalTemplateSection.project_id == team.project.id,
            ProposalTemplateSection.key == "market",
        )
        .values(archived_at=idea.created_at)
    )
    await db_session.commit()

    code = (
        await (await as_agent(bot, WRITE, [team.project]))
        .for_run(run)
        .fails(
            "propose_proposal_section", idea=key_of(team, idea), section_key="market", body_md="x"
        )
    )

    assert code == "unknown_section"
