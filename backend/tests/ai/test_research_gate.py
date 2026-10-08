"""Phase 8 and AI runs (contract-phase8 sections 3.5 and 3.12): "Ask AI to evaluate" is
guarded like an evaluator invite (after c10, before the limit), says so up front
(``request_evaluation_blocked_by: research_incomplete``) and takes the admin's override;
"Draft with AI" uses the project's section keys (422 ``unknown_section`` after the 403s
and before the 409s); c7 lets a proposal step's Research draft too."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.ai import AiRun
from app.models.enums import IdeaStatus, ResearchStep
from app.models.idea import Idea, IdeaEvaluator
from tests.ai.conftest import AsUser, Crew, assert_problem, ok
from tests.factories import make_idea
from tests.research.conftest import answer_required, set_step


def _evaluate(crew: Crew) -> str:
    return f"/ideas/{crew.ref}/ai-runs/evaluation"


def _draft(crew: Crew) -> str:
    return f"/ideas/{crew.ref}/ai-runs/section-draft"


async def test_asking_ai_to_evaluate_is_guarded_like_the_first_invite(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await set_step(db_session, crew.team.project, ResearchStep.BEFORE_EVALUATION)
    olive = await api(crew.team.owner)

    runs = ok(await olive.get(f"/ideas/{crew.ref}/ai-runs"))
    refused = await olive.post(_evaluate(crew), {"agent_id": str(crew.agent.id)})

    assert runs["permissions"]["can_request_evaluation"] is False
    assert runs["permissions"]["request_evaluation_blocked_by"] == "research_incomplete"
    body = assert_problem(refused, 409, "research_incomplete")
    assert body["can_override"] is False
    assert await db_session.scalar(select(AiRun.id)) is None
    assert await db_session.scalar(select(IdeaEvaluator.user_id)) is None


async def test_an_admin_asks_anyway_and_an_answered_checklist_lets_it_through(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, crew.team.project, ResearchStep.BEFORE_EVALUATION)
    ada = await api(crew.team.admin)

    owner_anyway = await (await api(crew.team.owner)).post(
        _evaluate(crew), {"agent_id": str(crew.agent.id), "override_research": True}
    )
    anyway = await ada.post(
        _evaluate(crew), {"agent_id": str(crew.agent.id), "override_research": True}
    )
    [entry] = list(
        await db_session.scalars(
            select(AuditLog).where(AuditLog.action == "idea.research_override")
        )
    )

    assert_problem(owner_anyway, 403, "forbidden")
    assert ok(anyway, 201)["status"] == "queued"
    assert entry.details["operation"] == "request_ai_evaluation"

    # Another idea, answered first: no override needed.
    answered = await make_idea(db_session, crew.team.project, owner=crew.team.owner)
    await answer_required(db_session, answered, items, crew.team.owner)
    asked = await (await api(crew.team.owner)).post(
        f"/ideas/CUST-{answered.number}/ai-runs/evaluation", {"agent_id": str(crew.agent.id)}
    )
    assert ok(asked, 201)["status"] == "queued"


async def test_the_gate_comes_after_c10(api: AsUser, crew: Crew, db_session: AsyncSession) -> None:
    await set_step(db_session, crew.team.project, ResearchStep.BEFORE_EVALUATION)
    await db_session.execute(update(type(crew.agent.agent)).values(enabled=False))
    await db_session.commit()

    response = await (await api(crew.team.owner)).post(
        _evaluate(crew), {"agent_id": str(crew.agent.id)}
    )

    assert_problem(response, 409, "ai_unavailable")


@pytest.mark.parametrize("status", [IdeaStatus.SHORTLISTED, IdeaStatus.RESEARCH])
async def test_drafts_use_the_projects_sections(
    api: AsUser, crew: Crew, db_session: AsyncSession, status: IdeaStatus
) -> None:
    items = await set_step(db_session, crew.team.project, ResearchStep.BEFORE_PROPOSAL)
    await db_session.execute(update(Idea).where(Idea.id == crew.idea.id).values(status=status))
    await db_session.commit()
    await answer_required(db_session, crew.idea, items, crew.team.owner)
    ada = await api(crew.team.admin)
    ok(
        await ada.put(
            f"/projects/{crew.team.slug}/proposal-template",
            {"sections": [{"key": "summary", "title": "Summary"}, {"title": "Carbon impact"}]},
        )
    )
    ok(await ada.post(f"/ideas/{crew.ref}/proposal"), 201)  # moves it to Proposal
    await db_session.execute(update(Idea).where(Idea.id == crew.idea.id).values(status=status))
    await db_session.commit()  # c7: Research before a proposal step drafts too
    olive = await api(crew.team.owner)

    drafted = await olive.post(
        _draft(crew), {"agent_id": str(crew.agent.id), "section_key": "carbon_impact"}
    )
    removed = await olive.post(
        _draft(crew), {"agent_id": str(crew.agent.id), "section_key": "risks"}
    )
    member = await (await api(crew.team.member)).post(
        _draft(crew), {"agent_id": str(crew.agent.id), "section_key": "risks"}
    )

    assert ok(drafted, 201)["section_key"] == "carbon_impact"
    assert_problem(removed, 422, "unknown_section")
    assert_problem(member, 403, "forbidden")  # the 403 comes first


async def test_unknown_section_comes_before_the_409s(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status=IdeaStatus.SHORTLISTED)
    )
    await db_session.commit()
    olive = await api(crew.team.owner)
    ok(await olive.post(f"/ideas/{crew.ref}/proposal"), 201)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status=IdeaStatus.EVALUATING)
    )
    await db_session.commit()

    unknown = await olive.post(
        _draft(crew), {"agent_id": str(crew.agent.id), "section_key": "nothing_here"}
    )
    known = await olive.post(_draft(crew), {"agent_id": str(crew.agent.id), "section_key": "risks"})

    assert_problem(unknown, 422, "unknown_section")
    assert_problem(known, 409, "proposal_not_available")
