"""Blind evaluation and holds through MCP (role matrix sections 3 and 6; contract-phase5
section 4.6, "Blind evaluation" and "Holds"). A pending evaluator's key gets no score
data from any tool, whatever its scopes or role, and an idea held for moderation or
email confirmation is not found through any tool, for everyone."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    EvaluatorState,
    HoldReason,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    Recommendation,
)
from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_idea, make_user
from tests.mcp.conftest import AsAgent, AsUser, Team, full_scores, ok

HIDDEN = {
    "score": None,
    "score_hidden": True,
    "high_disagreement": False,
}


def key_of(team: Team, idea: Idea) -> str:
    return f"{team.project.key}-{idea.number}"


async def agent_account(db: AsyncSession, team: Team) -> User:
    """An AI agent's service account, a member of the project (never admin, c4)."""
    agent = await make_user(db, "Research Agent", service_account=True)
    db.add(ProjectMember(project_id=team.project.id, user_id=agent.id, role=ProjectRole.MEMBER))
    await db.commit()
    return agent


@pytest.fixture
async def evaluated(db_session: AsyncSession, team: Team) -> Idea:
    """An idea in Evaluating with two submitted evaluations from people (scores far
    apart: high disagreement) and one from an AI agent (left out of the aggregate)."""
    idea = await make_idea(
        db_session, team.project, title="Refunds", status=IdeaStatus.EVALUATING, owner=team.owner
    )
    names = [criterion.name for criterion in team.rubric]
    await add_evaluator(
        db_session,
        idea,
        team.evaluators[1],
        state=EvaluatorState.SUBMITTED,
        scores=dict.fromkeys(names, 1),
        recommendation=Recommendation.NO,
    )
    await add_evaluator(
        db_session,
        idea,
        team.evaluators[2],
        state=EvaluatorState.SUBMITTED,
        scores=dict.fromkeys(names, 5),
        recommendation=Recommendation.GO,
    )
    agent = await agent_account(db_session, team)
    await add_evaluator(
        db_session, idea, agent, state=EvaluatorState.SUBMITTED, include_in_aggregate=False
    )
    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.commit()
    return idea


def assert_blind(summary: dict[str, Any], detail: dict[str, Any]) -> None:
    assert {k: summary[k] for k in HIDDEN} == HIDDEN
    assert {k: detail[k] for k in HIDDEN} == HIDDEN
    assert detail["aggregate"] is None
    assert detail["evaluation_count"] == 0
    assert detail["evaluations"] == []
    others = [e for e in detail["evaluators"] if e["state"] == "draft"]
    assert len(others) <= 1  # only your own row can say draft


def assert_sighted(summary: dict[str, Any], detail: dict[str, Any]) -> None:
    assert summary["score_hidden"] is detail["score_hidden"] is False
    assert summary["score"] == detail["score"] == {"overall": 3.0, "count": 2}
    assert summary["high_disagreement"] is detail["high_disagreement"] is True
    assert detail["aggregate"]["count"] == 2
    assert detail["evaluation_count"] == 3
    by_ai = {e["evaluator"]["is_ai"]: e for e in detail["evaluations"]}
    assert by_ai[True]["include_in_aggregate"] is False
    assert by_ai[False]["scores"][0]["score"] in (1, 5)


async def look(agent: Any, team: Team, idea: Idea) -> tuple[dict[str, Any], dict[str, Any]]:
    found = await agent.ok("search_ideas", query=key_of(team, idea))
    [summary] = found["items"]
    detail = (await agent.ok("get_idea", idea=key_of(team, idea)))["idea"]
    return summary, detail


@pytest.mark.parametrize("state", [EvaluatorState.INVITED, EvaluatorState.DRAFT])
async def test_a_pending_evaluators_key_gets_no_score_data(
    as_agent: AsAgent,
    team: Team,
    evaluated: Idea,
    db_session: AsyncSession,
    state: EvaluatorState,
) -> None:
    evaluator = team.evaluators[0]
    await add_evaluator(db_session, evaluated, evaluator, state=state, scores={})
    agent = await as_agent(evaluator)

    summary, detail = await look(agent, team, evaluated)

    assert_blind(summary, detail)
    assert summary["my_evaluation_state"] == detail["my_evaluation_state"] == state.value
    assert detail["my_evaluation"]["state"] == state.value
    states = {e["user"]["display_name"]: e["state"] for e in detail["evaluators"]}
    assert states["Eve Evaluator1"] == state.value
    assert states["Eve Evaluator2"] == states["Eve Evaluator3"] == "submitted"


async def test_submitting_lifts_it_and_the_result_carries_none_either(
    as_agent: AsAgent, team: Team, evaluated: Idea, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    await add_evaluator(db_session, evaluated, evaluator)
    agent = await as_agent(evaluator)

    submitted = await agent.ok(
        "submit_evaluation",
        idea=key_of(team, evaluated),
        scores=full_scores(team, 3),
        recommendation="maybe",
    )
    summary, detail = await look(agent, team, evaluated)

    assert summary["score_hidden"] is False
    assert set(submitted) == {"idea", "evaluation"}
    assert set(submitted["evaluation"]) == {
        "state",
        "editable",
        "due_at",
        "recommendation",
        "comment",
        "scores",
        "submitted_at",
        "updated_at",
    }
    assert detail["score_hidden"] is False
    assert detail["evaluation_count"] == 3  # the others: yours is my_evaluation
    assert detail["aggregate"]["count"] == 3


async def test_a_project_admin_who_owes_an_evaluation_is_blind_too(
    as_agent: AsAgent, team: Team, evaluated: Idea, db_session: AsyncSession
) -> None:
    await add_evaluator(db_session, evaluated, team.admin)

    summary, detail = await look(await as_agent(team.admin), team, evaluated)

    assert_blind(summary, detail)


@pytest.mark.parametrize("who", ["viewer", "outsider", "platform", "owner"])
async def test_people_who_are_not_evaluators_see_the_scores(
    as_agent: AsAgent, team: Team, evaluated: Idea, db_session: AsyncSession, who: str
) -> None:
    if who == "outsider":
        await db_session.execute(
            update(Project)
            .where(Project.id == team.project.id)
            .values(visibility=ProjectVisibility.INTERNAL)
        )
        await db_session.commit()

    summary, detail = await look(
        await as_agent(getattr(team, who), ["read", "mcp"]), team, evaluated
    )

    assert_sighted(summary, detail)


async def test_sort_by_score_puts_the_hidden_idea_last(
    as_agent: AsAgent, team: Team, evaluated: Idea, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    await add_evaluator(db_session, evaluated, evaluator)
    low = await make_idea(db_session, team.project, title="Low", status=IdeaStatus.EVALUATING)
    await add_evaluator(
        db_session,
        low,
        team.evaluators[1],
        state=EvaluatorState.SUBMITTED,
        scores={criterion.name: 1 for criterion in team.rubric},
    )
    await recompute_aggregates(db_session, idea_ids=[low.id])
    await db_session.commit()
    agent = await as_agent(evaluator, ["read", "mcp"])

    ascending = await agent.ok("search_ideas", sort="score")
    descending = await agent.ok("search_ideas", sort="-score")

    assert [i["title"] for i in ascending["items"]] == ["Low", "Refunds"]
    assert [i["title"] for i in descending["items"]] == ["Low", "Refunds"]


async def test_a_service_account_evaluates_blind(
    as_agent: AsAgent, team: Team, evaluated: Idea, db_session: AsyncSession
) -> None:
    agent_user = await make_user(db_session, "Second Agent", service_account=True)
    db_session.add(
        ProjectMember(project_id=team.project.id, user_id=agent_user.id, role=ProjectRole.MEMBER)
    )
    await db_session.commit()
    await add_evaluator(db_session, evaluated, agent_user)
    agent = await as_agent(agent_user, ["read", "evaluate", "mcp"], [team.project])

    summary, detail = await look(agent, team, evaluated)
    submitted = await agent.ok(
        "submit_evaluation",
        idea=key_of(team, evaluated),
        scores=full_scores(team, 4),
        recommendation="go",
    )
    after = (await agent.ok("get_idea", idea=key_of(team, evaluated)))["idea"]

    assert_blind(summary, detail)
    assert submitted["evaluation"]["state"] == "submitted"
    assert after["score_hidden"] is False
    assert after["evaluation_count"] == 3  # the others: yours is my_evaluation


# --- Holds ------------------------------------------------------------------------------------
IDEA_TOOLS: list[tuple[str, dict[str, Any]]] = [
    ("get_idea", {}),
    ("get_rubric", {}),
    ("get_proposal", {}),
    ("add_comment", {"body_md": "Hello"}),
    ("submit_evaluation", {"scores": [], "submit": False}),
    ("propose_proposal_section", {"section_key": "risks", "body_md": "x"}),
]


@pytest.mark.parametrize("reason", [HoldReason.MODERATION, HoldReason.EMAIL_VERIFICATION])
@pytest.mark.parametrize("who", ["platform", "admin", "member"])
async def test_held_ideas_are_not_found_through_any_tool(
    as_agent: AsAgent,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    reason: HoldReason,
    who: str,
) -> None:
    held = await make_idea(db_session, team.project, title="Held public idea", owner=team.owner)
    await make_idea(db_session, team.project, title="Visible idea")
    user = getattr(team, who)
    await add_evaluator(db_session, held, team.member)
    await db_session.execute(update(Idea).where(Idea.id == held.id).values(held_for=reason))
    await db_session.commit()
    agent = await as_agent(user)

    for tool, arguments in IDEA_TOOLS:
        code = await agent.fails(tool, idea=key_of(team, held), **arguments)
        assert code == "not_found", tool
    listed = await agent.ok("search_ideas", query="idea")
    projects = await agent.ok("list_projects")

    assert [item["title"] for item in listed["items"]] == ["Visible idea"]
    if who != "platform":
        assert projects["projects"][0]["idea_count"] == 1
    if reason is HoldReason.MODERATION and who != "member":
        # REST still lets admins open it by its link (to moderate it); MCP never does.
        ok(await (await api(user)).get(f"/ideas/{key_of(team, held)}"))
