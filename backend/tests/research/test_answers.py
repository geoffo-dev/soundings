"""An idea's research (contract-phase8 sections 3.4 and 3.6): reading the checklist (every
column, pending evaluators included: no score data), answering and clearing it
(``idea.answer_research``: the owner and admins; c5; archived and held ideas; the step
off), the answer's rules (plain text, invisible characters, who and when), and keys
(write scope; an agent's key never answers)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluatorState, HoldReason, IdeaStatus, ProjectRole, ResearchStep
from app.models.idea import Idea
from app.models.project import ProjectMember
from app.models.research import ResearchAnswer, ResearchChecklistItem
from tests.api_keys.helpers import key_client, make_key
from tests.factories import add_evaluator, make_idea, make_user
from tests.research.conftest import AsUser, Team, answer, assert_problem, ok, set_step

TEXT = "Legal (contracts team), 3 Oct: fine if we keep the standard terms."


async def _ready(
    db: AsyncSession, team: Team, status: IdeaStatus = IdeaStatus.RESEARCH
) -> tuple[Idea, list[ResearchChecklistItem]]:
    items = await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db, team.project, status=status, owner=team.owner)
    return idea, items


def _item_url(idea: Idea, item: ResearchChecklistItem) -> str:
    return f"/ideas/{idea.id}/research/items/{item.id}"


# --- Reading --------------------------------------------------------------------------------
async def test_the_research_panel(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea, items = await _ready(db_session, team)
    await answer(db_session, idea, items[0], team.owner)

    panel = ok(await (await api(team.owner)).get(f"/ideas/{idea.id}/research"))

    assert panel["step"] == "before_evaluation"
    assert panel["gate_status"] == "evaluating"
    assert [(item["title"], item["required"]) for item in panel["items"]] == [
        ("Not already being done elsewhere", True),
        ("Departments or teams consulted", True),
        ("Data protection considered", False),
    ]
    first = panel["items"][0]["answer"]
    assert first["answer"] == TEXT
    assert first["answered_by"]["id"] == str(team.owner.id)
    assert first["updated_at"] == first["answered_at"]
    assert panel["items"][1]["answer"] is None
    assert panel["progress"] == {"answered": 1, "total": 3, "required_open": 1}
    assert panel["blocking"] is True
    assert panel["permissions"] == {
        "can_answer": True,
        "can_override": False,
        # Phase 8b: the owner assigns (people with a role: the project is private).
        "can_assign": True,
        "can_assign_outside_researcher": False,
        "can_hand_back": False,
    }


@pytest.mark.parametrize(
    ("who", "status", "can_answer"),
    [
        ("platform", 200, True),
        ("admin", 200, True),
        ("owner", 200, True),
        ("member", 200, False),
        ("viewer", 200, False),
        ("outsider", 404, False),
    ],
)
async def test_who_reads_the_checklist(
    api: AsUser, team: Team, db_session: AsyncSession, who: str, status: int, can_answer: bool
) -> None:
    idea, _ = await _ready(db_session, team)

    response = await (await api(getattr(team, who))).get(f"/ideas/{idea.id}/research")

    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["permissions"]["can_answer"] is can_answer


async def test_pending_evaluators_read_the_answers(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team, IdeaStatus.EVALUATING)
    await answer(db_session, idea, items[1], team.owner)
    evaluator = team.evaluators[0]
    await add_evaluator(db_session, idea, evaluator, state=EvaluatorState.INVITED)

    panel = ok(await (await api(evaluator)).get(f"/ideas/{idea.id}/research"))

    assert panel["items"][1]["answer"]["answer"] == TEXT
    assert panel["blocking"] is False  # past Research


async def test_while_the_step_is_off_the_panel_is_empty(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    await answer(db_session, idea, items[0], team.owner)
    await set_step(db_session, team.project, ResearchStep.OFF)

    panel = ok(await (await api(team.owner)).get(f"/ideas/{idea.id}/research"))

    assert panel == {
        "step": "off",
        "gate_status": None,
        "items": [],
        "progress": {"answered": 0, "total": 0, "required_open": 0},
        "blocking": False,
        "permissions": {
            "can_answer": False,
            "can_override": False,
            "can_assign": False,
            "can_assign_outside_researcher": False,
            "can_hand_back": False,
        },
        # Phase 8b: nothing assigned while the step is off.
        "gate_status_label": None,
        "assignment": {
            "researcher": None,
            "researcher_in_project": False,
            "assigned_at": None,
            "due_at": None,
            "overdue": False,
        },
    }


async def test_a_closed_idea_never_blocks(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, _ = await _ready(db_session, team, IdeaStatus.CLOSED)

    panel = ok(await (await api(team.admin)).get(f"/ideas/{idea.id}/research"))

    assert panel["blocking"] is False
    assert panel["progress"]["required_open"] == 2
    assert panel["permissions"]["can_answer"] is False  # c5


# --- Answering ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("platform", 200),
        ("admin", 200),
        ("owner", 200),
        ("member", 403),
        ("viewer", 403),
        ("outsider", 404),
    ],
)
async def test_who_answers(
    api: AsUser, team: Team, db_session: AsyncSession, who: str, status: int
) -> None:
    idea, items = await _ready(db_session, team)

    response = await (await api(getattr(team, who))).put(
        _item_url(idea, items[0]), {"answer": TEXT}
    )

    assert response.status_code == status, response.text


async def test_a_demoted_owner_cannot_answer(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    response = await (await api(team.owner)).put(_item_url(idea, items[0]), {"answer": TEXT})

    assert_problem(response, 403, "forbidden")


async def test_answering_records_who_and_when(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    url = _item_url(idea, items[0])

    first = ok(await (await api(team.owner)).put(url, {"answer": TEXT}))
    same = ok(await (await api(team.admin)).put(url, {"answer": TEXT}))
    edited = ok(
        await (await api(team.admin)).put(url, {"answer": "  Legal: fine.\nFinance: fine.  "})
    )

    one, two, three = (panel["items"][0]["answer"] for panel in (first, same, edited))
    assert one["answered_by"]["id"] == str(team.owner.id)
    assert two == one  # identical text changes nothing
    assert three["answer"] == "Legal: fine.\nFinance: fine."  # ends trimmed, breaks kept
    assert three["answered_by"]["id"] == str(team.owner.id)
    assert (three["answered_at"], three["updated_by"]["id"]) == (
        one["answered_at"],
        str(team.admin.id),
    )
    assert three["updated_at"] > one["updated_at"]
    assert first["progress"]["answered"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "\u200b",  # a lone zero-width space
        "\u202e\u202c",  # bidi controls
        " \u2060\ufeff ",  # word joiner, BOM
        "",
        "   ",
        "x" * 2001,
        "Legal\x00",
    ],
)
async def test_answers_need_visible_text(
    api: AsUser, team: Team, db_session: AsyncSession, text: str
) -> None:
    idea, items = await _ready(db_session, team)

    response = await (await api(team.owner)).put(_item_url(idea, items[0]), {"answer": text})

    assert_problem(response, 422, "validation_error")
    assert await db_session.scalar(select(ResearchAnswer.answer)) is None


async def test_invisible_characters_are_removed_from_stored_answers(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)

    ok(
        await (await api(team.owner)).put(
            _item_url(idea, items[0]), {"answer": "Le\u200bgal\u202e ok \u2066fine\u2069"}
        )
    )

    assert await db_session.scalar(select(ResearchAnswer.answer)) == "Legal ok fine"


async def test_an_invisible_answer_never_satisfies_the_gate(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    olive = await api(team.owner)
    for item in items[:2]:
        await olive.put(_item_url(idea, item), {"answer": "\u200b"})

    response = await olive.post(f"/ideas/{idea.id}/status", {"status": "evaluating"})

    assert_problem(response, 409, "research_incomplete")


async def test_clearing_is_idempotent(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea, items = await _ready(db_session, team)
    await answer(db_session, idea, items[0], team.owner)
    olive = await api(team.owner)

    cleared = ok(await olive.delete(_item_url(idea, items[0])))
    again = ok(await olive.delete(_item_url(idea, items[0])))

    assert cleared["items"][0]["answer"] is None
    assert again == cleared


async def test_only_active_items_of_the_ideas_project(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    other = await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH)
    await db_session.execute(
        update(ResearchChecklistItem)
        .where(ResearchChecklistItem.id == items[2].id)
        .values(archived_at=idea.created_at)
    )
    await db_session.commit()
    elsewhere = await set_step(
        db_session,
        await _other_project(db_session, team),
        ResearchStep.BEFORE_EVALUATION,
    )
    olive = await api(team.owner)

    archived = await olive.put(_item_url(idea, items[2]), {"answer": TEXT})
    foreign = await olive.put(_item_url(idea, elsewhere[0]), {"answer": TEXT})
    unknown = await olive.put(
        f"/ideas/{idea.id}/research/items/00000000-0000-0000-0000-000000000001", {"answer": TEXT}
    )

    assert_problem(archived, 404, "not_found")
    assert_problem(foreign, 404, "not_found")
    assert_problem(unknown, 404, "not_found")
    assert other.id != idea.id


async def _other_project(db: AsyncSession, team: Team) -> Any:
    from tests.factories import make_project

    return await make_project(db, members={team.owner: ProjectRole.ADMIN})


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("closed", "idea_closed"),
        ("archived", "project_archived"),
        ("moderation", "awaiting_moderation"),
        ("step_off", "research_step_off"),
    ],
)
async def test_answering_is_refused(
    api: AsUser, team: Team, db_session: AsyncSession, change: str, code: str
) -> None:
    idea, items = await _ready(db_session, team)
    if change == "closed":
        await db_session.execute(
            update(Idea)
            .where(Idea.id == idea.id)
            .values(status=IdeaStatus.CLOSED, resolution="parked")
        )
    elif change == "archived":
        ok(await (await api(team.admin)).patch(f"/projects/{team.slug}", {"archived": True}))
    elif change == "moderation":
        await db_session.execute(
            update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
        )
    else:
        await set_step(db_session, team.project, ResearchStep.OFF)
    await db_session.commit()

    put = await (await api(team.admin)).put(_item_url(idea, items[0]), {"answer": TEXT})
    delete = await (await api(team.admin)).delete(_item_url(idea, items[0]))

    assert_problem(put, 409, code)
    assert_problem(delete, 409, code)


async def test_answers_are_not_activity_or_audit(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    from app.models.activity import ActivityEvent, AuditLog

    idea, items = await _ready(db_session, team)
    before = idea.last_activity_at

    ok(await (await api(team.owner)).put(_item_url(idea, items[0]), {"answer": TEXT}))

    await db_session.refresh(idea)
    assert idea.last_activity_at == before
    assert await db_session.scalar(select(ActivityEvent.id)) is None
    assert (
        await db_session.scalar(select(AuditLog.id).where(AuditLog.action.like("%research%")))
        is None
    )


# --- Keys -------------------------------------------------------------------------------------
async def test_keys_answer_with_the_write_scope(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    writer = await make_key(db_session, team.owner, scopes=["read", "write"])
    reader = await make_key(db_session, team.owner, scopes=["read"])
    url = f"/api/v1{_item_url(idea, items[0])}"

    async with key_client(app, reader) as client:
        read = await client.get(f"/api/v1/ideas/{idea.id}/research")
        refused = await client.put(url, json={"answer": TEXT})
    async with key_client(app, writer) as client:
        answered = await client.put(url, json={"answer": TEXT})
        cleared = await client.delete(url)

    assert read.status_code == 200
    assert_problem(refused, 403, "insufficient_scope")
    assert answered.status_code == 200, answered.text
    assert cleared.status_code == 200


async def test_an_agents_key_never_answers(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _ready(db_session, team)
    bot = await make_user(db_session, "Research Agent", service_account=True)
    db_session.add(
        ProjectMember(project_id=team.project.id, user_id=bot.id, role=ProjectRole.ADMIN)
    )
    await db_session.commit()
    secret = await make_key(db_session, bot, scopes=["read", "write", "mcp"])

    async with key_client(app, secret) as client:
        refused = await client.put(f"/api/v1{_item_url(idea, items[0])}", json={"answer": TEXT})
        read = await client.get(f"/api/v1/ideas/{idea.id}/research")

    assert_problem(refused, 403, "insufficient_scope")  # c22: REST is never an agent's
    assert_problem(read, 403, "insufficient_scope")
