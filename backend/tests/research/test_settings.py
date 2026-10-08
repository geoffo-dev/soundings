"""Project settings -> Research (contract-phase8 section 3.3): the step and the checklist,
replaced like the rubric; refusals while ideas are in Research; off keeps the checklist;
archive and restore keep answers; audit; who may read and change it."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.enums import IdeaStatus, ResearchStep
from app.models.research import ResearchAnswer, ResearchChecklistItem
from tests.api_keys.helpers import key_client, make_key
from tests.factories import make_idea
from tests.research.conftest import AsUser, Team, answer, assert_problem, ok, set_step

DEFAULTS = [
    {
        "title": "Not already being done elsewhere",
        "hint": "Search Soundings and ask around; note what you found.",
        "required": True,
    },
    {
        "title": "Departments or teams consulted",
        "hint": "Who you spoke to and what they said.",
        "required": True,
    },
    {
        "title": "Data protection considered",
        "hint": "Personal data involved, and who you checked with.",
        "required": False,
    },
]


def _url(team: Team) -> str:
    return f"/projects/{team.slug}/research"


async def _actions(db: AsyncSession) -> list[tuple[str, dict[str, Any]]]:
    rows = await db.execute(
        select(AuditLog.action, AuditLog.details)
        .where(AuditLog.action.like("project.research%"))
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    return [
        (action, {k: v for k, v in details.items() if not k.startswith("auth")})
        for action, details in rows
    ]


async def test_a_new_project_has_no_step_and_offers_the_default_checklist(
    api: AsUser, team: Team
) -> None:
    settings = ok(await (await api(team.member)).get(_url(team)))

    assert settings == {
        "step": "off",
        "items": [],
        "removed_items": [],
        "default_items": DEFAULTS,
        "ideas_in_research": 0,
    }


async def test_turning_the_step_on_with_the_default_checklist(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)

    settings = ok(await ada.put(_url(team), {"step": "before_evaluation", "items": DEFAULTS}))
    project = ok(await ada.get(f"/projects/{team.slug}"))

    assert settings["step"] == "before_evaluation"
    assert [(item["title"], item["required"], item["position"]) for item in settings["items"]] == [
        ("Not already being done elsewhere", True, 0),
        ("Departments or teams consulted", True, 1),
        ("Data protection considered", False, 2),
    ]
    assert project["research_step"] == "before_evaluation"
    assert project["lifecycle"] == [
        "new",
        "research",
        "evaluating",
        "shortlisted",
        "proposal",
        "closed",
    ]
    assert await _actions(db_session) == [
        (
            "project.research_step_change",
            {"rule": "project.edit_research", "from": "off", "to": "before_evaluation"},
        ),
        (
            "project.research_checklist_replace",
            {
                "rule": "project.edit_research",
                "added": 3,
                "restored": 0,
                "archived": 0,
                "deleted": 0,
                "changed": 0,
            },
        ),
    ]


async def test_before_proposal_puts_research_after_shortlisted(api: AsUser, team: Team) -> None:
    ada = await api(team.admin)

    ok(await ada.put(_url(team), {"step": "before_proposal", "items": DEFAULTS[:1]}))
    project = ok(await ada.get(f"/projects/{team.slug}"))
    board = ok(await ada.get(f"/projects/{team.slug}/board"))

    assert project["lifecycle"] == [
        "new",
        "evaluating",
        "shortlisted",
        "research",
        "proposal",
        "closed",
    ]
    assert [column["status"] for column in board["columns"]] == project["lifecycle"]
    assert board["columns"][3]["label"] == "Research"


async def test_a_step_needs_an_item(api: AsUser, team: Team) -> None:
    response = await (await api(team.admin)).put(
        _url(team), {"step": "before_evaluation", "items": []}
    )

    assert_problem(response, 422, "validation_error")


@pytest.mark.parametrize("to", ["off", "before_proposal"])
async def test_the_step_cant_change_while_ideas_are_in_research(
    api: AsUser, team: Team, db_session: AsyncSession, to: str
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    for _ in range(2):
        await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH)
    body = {"step": to, "items": [{"id": str(item.id), "title": item.title} for item in items]}
    ada = await api(team.admin)

    response = await ada.put(_url(team), body)
    settings = ok(await ada.get(_url(team)))

    problem = assert_problem(response, 409, "ideas_in_research")
    assert problem["idea_count"] == 2
    assert problem["detail"] == "2 ideas are in Research: move them to another status first."
    assert settings["step"] == "before_evaluation"
    assert settings["ideas_in_research"] == 2


async def test_the_checklist_can_change_while_ideas_are_in_research(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH)
    body = {
        "step": "before_evaluation",
        "items": [{"id": str(items[1].id), "title": "Teams consulted", "required": False}],
    }

    settings = ok(await (await api(team.admin)).put(_url(team), body))

    assert [(i["title"], i["required"]) for i in settings["items"]] == [("Teams consulted", False)]
    await db_session.refresh(idea)
    assert idea.status is IdeaStatus.RESEARCH  # changing the checklist never moves an idea


async def test_turning_the_step_off_keeps_the_checklist_and_answers(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await answer(db_session, idea, items[0], team.admin)
    ada = await api(team.admin)

    off = ok(await ada.put(_url(team), {"step": "off", "items": []}))
    research = ok(await ada.get(f"/ideas/{idea.id}/research"))
    on = ok(
        await ada.put(
            _url(team),
            {
                "step": "before_evaluation",
                "items": [{"id": str(item.id), "title": item.title} for item in items],
            },
        )
    )
    again = ok(await ada.get(f"/ideas/{idea.id}/research"))

    assert off["step"] == "off"
    assert [item["id"] for item in off["items"]] == [str(item.id) for item in items]  # kept
    assert research["items"] == []
    assert research["step"] == "off"
    assert [item["id"] for item in on["items"]] == [str(item.id) for item in items]
    assert again["items"][0]["answer"]["answer"].startswith("Legal")
    assert len(list(await db_session.scalars(select(ResearchAnswer)))) == 1


async def test_items_are_ignored_while_the_step_is_off(api: AsUser, team: Team) -> None:
    settings = ok(
        await (await api(team.admin)).put(
            _url(team),
            {
                "step": "off",
                "items": [{"id": "00000000-0000-0000-0000-000000000001", "title": "X"}],
            },
        )
    )

    assert settings["items"] == []


async def test_removing_an_answered_item_archives_it_and_restoring_brings_answers_back(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=IdeaStatus.RESEARCH)
    await answer(db_session, idea, items[0], team.owner)
    ada = await api(team.admin)
    keep = [{"id": str(items[1].id), "title": items[1].title}]

    removed = ok(await ada.put(_url(team), {"step": "before_evaluation", "items": keep}))
    hidden = ok(await ada.get(f"/ideas/{idea.id}/research"))
    restored = ok(
        await ada.put(
            _url(team),
            {
                "step": "before_evaluation",
                "items": [*keep, {"id": str(items[0].id), "title": items[0].title}],
            },
        )
    )
    shown = ok(await ada.get(f"/ideas/{idea.id}/research"))

    assert [item["title"] for item in removed["items"]] == [items[1].title]
    assert [(item["id"], item["answer_count"]) for item in removed["removed_items"]] == [
        (str(items[0].id), 1)
    ]
    # The unanswered optional item was deleted, not archived.
    assert (
        await db_session.scalar(
            select(ResearchChecklistItem.id).where(ResearchChecklistItem.id == items[2].id)
        )
        is None
    )
    assert [item["title"] for item in hidden["items"]] == [items[1].title]
    assert [item["title"] for item in restored["items"]] == [items[1].title, items[0].title]
    assert restored["removed_items"] == []
    assert shown["items"][1]["answer"] is not None
    actions = await _actions(db_session)
    assert actions[0] == (
        "project.research_checklist_replace",
        {
            "rule": "project.edit_research",
            "added": 0,
            "restored": 0,
            "archived": 1,
            "deleted": 1,
            "changed": 1,
        },
    )
    assert actions[1][1]["restored"] == 1


async def test_renaming_and_swapping_titles(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    body = {
        "step": "before_evaluation",
        "items": [
            {"id": str(items[1].id), "title": items[0].title},
            {"id": str(items[0].id), "title": items[1].title},
        ],
    }

    settings = ok(await (await api(team.admin)).put(_url(team), body))

    assert [(item["id"], item["title"]) for item in settings["items"]] == [
        (str(items[1].id), items[0].title),
        (str(items[0].id), items[1].title),
    ]


async def test_an_unknown_item_is_422(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    body = {
        "step": "before_evaluation",
        "items": [{"id": "00000000-0000-0000-0000-000000000001", "title": "X"}],
    }

    response = await (await api(team.admin)).put(_url(team), body)

    assert_problem(response, 422, "unknown_research_item")


async def test_nothing_changed_writes_no_audit(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    body = {
        "step": "before_evaluation",
        "items": [
            {"id": str(item.id), "title": item.title, "hint": item.hint, "required": item.required}
            for item in items
        ],
    }

    ok(await (await api(team.admin)).put(_url(team), body))

    assert await _actions(db_session) == []


@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("platform", 200),
        ("admin", 200),
        ("owner", 403),
        ("member", 403),
        ("viewer", 403),
        ("outsider", 404),
    ],
)
async def test_who_may_change_the_settings(api: AsUser, team: Team, who: str, status: int) -> None:
    response = await (await api(getattr(team, who))).put(
        _url(team), {"step": "before_evaluation", "items": DEFAULTS}
    )

    assert response.status_code == status, response.text


@pytest.mark.parametrize(("who", "status"), [("viewer", 200), ("outsider", 404)])
async def test_who_may_read_the_settings(api: AsUser, team: Team, who: str, status: int) -> None:
    response = await (await api(getattr(team, who))).get(_url(team))

    assert response.status_code == status, response.text


async def test_the_settings_work_in_an_archived_project(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)
    ok(await ada.patch(f"/projects/{team.slug}", {"archived": True}))

    settings = ok(await ada.put(_url(team), {"step": "before_proposal", "items": DEFAULTS}))

    assert settings["step"] == "before_proposal"


async def test_keys_read_but_never_change_the_settings(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    secret = await make_key(db_session, team.admin, scopes=["read", "write"])
    async with key_client(app, secret) as client:
        read = await client.get(f"/api/v1{_url(team)}")
        write = await client.put(
            f"/api/v1{_url(team)}", json={"step": "before_evaluation", "items": DEFAULTS}
        )

    assert read.status_code == 200
    assert_problem(write, 403, "insufficient_scope")
