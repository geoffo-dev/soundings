"""Where the research step shows outside its panel (contract-phase8 sections 3.2 and 3.6):
the board's columns follow the project's lifecycle, cards carry the checklist's progress
only for an idea in Research or the status right before it (one statement per page, none
when no project on the page has the step on), My work's groups keep the canonical order,
``list_ideas?status=research`` and the Research label."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IdeaStatus, ResearchStep
from tests.factories import make_idea
from tests.research.conftest import AsUser, Team, answer, ok, set_step

S = IdeaStatus


@contextmanager
def recorded(app: FastAPI) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _research_statements(statements: list[str]) -> list[str]:
    return [s for s in statements if "research_checklist_items" in s]


async def test_board_columns_follow_the_lifecycle(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    olive = await api(team.owner)
    off = ok(await olive.get(f"/projects/{team.slug}/board"))
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    on = ok(await olive.get(f"/projects/{team.slug}/board"))

    assert [c["status"] for c in off["columns"]] == [
        "new",
        "evaluating",
        "shortlisted",
        "proposal",
        "closed",
    ]
    assert [c["status"] for c in on["columns"]] == [
        "new",
        "research",
        "evaluating",
        "shortlisted",
        "proposal",
        "closed",
    ]


@pytest.mark.parametrize(
    ("step", "status", "shown"),
    [
        (ResearchStep.BEFORE_EVALUATION, S.NEW, True),
        (ResearchStep.BEFORE_EVALUATION, S.RESEARCH, True),
        (ResearchStep.BEFORE_EVALUATION, S.EVALUATING, False),  # past Research
        (ResearchStep.BEFORE_EVALUATION, S.CLOSED, False),
        (ResearchStep.BEFORE_PROPOSAL, S.NEW, False),  # further back
        (ResearchStep.BEFORE_PROPOSAL, S.SHORTLISTED, True),
        (ResearchStep.BEFORE_PROPOSAL, S.RESEARCH, True),
        (ResearchStep.BEFORE_PROPOSAL, S.PROPOSAL, False),
        (ResearchStep.OFF, S.NEW, False),
    ],
)
async def test_cards_show_progress_only_in_research_or_the_status_before_it(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    status: IdeaStatus,
    shown: bool,
) -> None:
    items = await set_step(db_session, team.project, step)
    idea = await make_idea(db_session, team.project, status=status, owner=team.owner)
    await answer(db_session, idea, items[0], team.owner)
    await answer(db_session, idea, items[2], team.owner)
    olive = await api(team.owner)

    listed = ok(await olive.get(f"/projects/{team.slug}/ideas"))["items"][0]
    board = ok(await olive.get(f"/projects/{team.slug}/board"))
    card = next(c for column in board["columns"] for c in column["items"])
    detail = ok(await olive.get(f"/ideas/{idea.id}"))

    expected = {"answered": 2, "total": 3, "required_open": 1} if shown else None
    assert listed["research"] == expected
    assert card["research"] == expected
    assert detail["research"] == expected


async def test_one_statement_per_page_and_none_without_a_step(
    app: FastAPI, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    for status in (S.NEW, S.NEW, S.EVALUATING):
        await make_idea(db_session, team.project, status=status)
    olive = await api(team.owner)

    with recorded(app) as off:
        ok(await olive.get(f"/projects/{team.slug}/board"))
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    with recorded(app) as on:
        ok(await olive.get(f"/projects/{team.slug}/board"))
    with recorded(app) as listed:
        ok(await olive.get(f"/projects/{team.slug}/ideas"))

    assert _research_statements(off) == []
    assert len(_research_statements(on)) == 1
    assert len(_research_statements(listed)) == 1


async def test_list_filter_research(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    olive = await api(team.owner)
    empty = ok(await olive.get(f"/projects/{team.slug}/ideas", status="research"))
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH)

    found = ok(await olive.get(f"/projects/{team.slug}/ideas", status="research"))

    assert empty["items"] == []
    assert [item["id"] for item in found["items"]] == [str(idea.id)]
    assert found["items"][0]["status_label"] == "Research"


async def test_the_research_label_is_renameable(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH)
    ada = await api(team.admin)

    project = ok(
        await ada.patch(f"/projects/{team.slug}", {"status_labels": {"research": "Due diligence"}})
    )
    detail = ok(await ada.get(f"/ideas/{idea.id}"))
    board = ok(await ada.get(f"/projects/{team.slug}/board"))

    assert project["status_labels"]["research"] == "Due diligence"
    assert detail["status_label"] == "Due diligence"
    assert board["columns"][3]["label"] == "Due diligence"


async def test_my_work_groups_keep_the_canonical_order(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    for status in (S.PROPOSAL, S.RESEARCH, S.NEW, S.EVALUATING):
        await make_idea(db_session, team.project, status=status, owner=team.owner)

    work = ok(await (await api(team.owner)).get("/me/work"))

    assert [group["status"] for group in work["owned"]] == [
        "new",
        "research",
        "evaluating",
        "proposal",
    ]
