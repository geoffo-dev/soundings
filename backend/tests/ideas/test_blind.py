"""Blind evaluation on every surface (contract section 3.7, role matrix section 3).

One internal project; idea T has two submitted human evaluations that disagree, an
excluded AI evaluation, and three pending evaluators: one invited, one with a draft,
and the project admin (who also owns T). For each viewer the test walks every surface:
the list (rows, total, ``sort=score`` in both directions and its cursors, the
``high_disagreement`` filter), the board (cards and counts), the idea page, the
evaluations list, the activity feed, My work, owned ideas and search.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility
from app.models.idea import Idea
from app.models.user import User
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_idea, make_project, make_user
from tests.ideas.conftest import AsUser, assert_problem, ok

ALL5 = {"Value": 5, "Feasibility": 5, "Effort": 1, "Strategic fit": 5, "Risk": 1}  # adjusted 5
LOW = {"Value": 2, "Feasibility": 3, "Effort": 3, "Strategic fit": 3, "Risk": 3}
ALL2 = {"Value": 2, "Feasibility": 2, "Effort": 4, "Strategic fit": 2, "Risk": 4}  # adjusted 2
ALL1 = {"Value": 1, "Feasibility": 1, "Effort": 5, "Strategic fit": 1, "Risk": 5}  # adjusted 1
ALL4 = {"Value": 4, "Feasibility": 4, "Effort": 2, "Strategic fit": 4, "Risk": 2}  # adjusted 4

HIDDEN = ("pending", "drafting", "admin_pending")
SEEING = ("submitter", "viewer", "outsider", "platform")


@dataclass
class World:
    users: dict[str, User]
    slug: str
    target: Idea  # T: 3.9, flagged, pending evaluators
    high: Idea  # 5.0
    disputed: Idea  # 2.5, flagged, nobody pending
    low: Idea  # 2.0
    unscored: Idea


@pytest.fixture
async def world(db_session: AsyncSession, api: AsUser) -> World:
    names = ["pending", "drafting", "admin_pending", "submitter", "second", "viewer"]
    users = {name: await make_user(db_session, name.replace("_", " ").title()) for name in names}
    users["outsider"] = await make_user(db_session, "Internal Outsider")
    users["platform"] = await make_user(db_session, "Platform Admin", platform_admin=True)
    agent = await make_user(db_session, "Scout Agent", service_account=True)
    roles = {
        users["admin_pending"]: ProjectRole.ADMIN,
        users["viewer"]: ProjectRole.VIEWER,
        agent: ProjectRole.MEMBER,
        **{users[n]: ProjectRole.MEMBER for n in ("pending", "drafting", "submitter", "second")},
    }
    project = await make_project(
        db_session, key="BLND", visibility=ProjectVisibility.INTERNAL, members=roles
    )
    target = await make_idea(
        db_session,
        project,
        title="Target idea",
        status=IdeaStatus.EVALUATING,
        owner=users["admin_pending"],
    )
    await add_evaluator(db_session, target, users["pending"])
    await add_evaluator(db_session, target, users["drafting"], state=EvaluatorState.DRAFT)
    await add_evaluator(db_session, target, users["admin_pending"])
    await add_evaluator(
        db_session, target, users["second"], state=EvaluatorState.SUBMITTED, scores=LOW
    )
    await add_evaluator(
        db_session,
        target,
        agent,
        state=EvaluatorState.SUBMITTED,
        scores=ALL1,
        include_in_aggregate=False,
    )
    await add_evaluator(db_session, target, users["submitter"])
    high = await make_idea(db_session, project, title="High idea", owner=users["admin_pending"])
    await add_evaluator(
        db_session, high, users["second"], state=EvaluatorState.SUBMITTED, scores=ALL5
    )
    disputed = await make_idea(
        db_session, project, title="Disputed idea", status=IdeaStatus.EVALUATING
    )
    await add_evaluator(
        db_session, disputed, users["second"], state=EvaluatorState.SUBMITTED, scores=ALL1
    )
    await add_evaluator(
        db_session, disputed, users["submitter"], state=EvaluatorState.SUBMITTED, scores=ALL4
    )
    low = await make_idea(db_session, project, title="Low idea", status=IdeaStatus.SHORTLISTED)
    await add_evaluator(
        db_session, low, users["second"], state=EvaluatorState.SUBMITTED, scores=ALL2
    )
    unscored = await make_idea(db_session, project, title="Unscored idea")
    await recompute_aggregates(db_session, project_id=project.id)
    await db_session.commit()
    # The submitter submits through the API (an evaluation_submitted event on T).
    submitter = await api(users["submitter"])
    body = {
        "scores": [
            {"criterion_id": str(c["id"]), "score": ALL5[c["name"]]}
            for c in ok(await submitter.get(f"/projects/{project.slug}"))["rubric"]
        ],
        "recommendation": "go",
        "comment": "Secret opinion",
        "submit": True,
    }
    ok(await submitter.put(f"/ideas/{target.id}/evaluations/me", body))
    return World(users, project.slug, target, high, disputed, low, unscored)


def decode(cursor: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    return data


async def walk(client: Any, slug: str, **params: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """Every page with limit=1: the titles in order and every cursor, decoded."""
    titles: list[str] = []
    cursors: list[dict[str, Any]] = []
    cursor = None
    while True:
        extra: dict[str, str] = {"cursor": cursor} if cursor else {}
        page = ok(await client.get(f"/projects/{slug}/ideas", limit=1, **params, **extra))
        titles += [item["title"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return titles, cursors
        cursors.append(decode(cursor))


def assert_hidden_summary(item: dict[str, Any]) -> None:
    assert (item["score"], item["score_hidden"], item["high_disagreement"]) == (None, True, False)


def assert_visible_target(item: dict[str, Any]) -> None:
    assert item["score"] == {"overall": 3.9, "count": 2}
    assert (item["score_hidden"], item["high_disagreement"]) == (False, True)


SCORE_KEYS = ("score", "overall", "aggregate", "mean", "recommendation")


def assert_no_score_data(value: Any) -> None:
    text = json.dumps(value)
    assert "Secret opinion" not in text
    assert not any(f'"{key}"' in text for key in SCORE_KEYS), text


@pytest.mark.parametrize("who", HIDDEN + SEEING)
async def test_every_surface(api: AsUser, world: World, who: str) -> None:
    client = await api(world.users[who])
    hidden = who in HIDDEN
    target = str(world.target.id)

    # --- List rows, total and score order.
    page = ok(await client.get(f"/projects/{world.slug}/ideas", sort="-score"))
    rows = {item["title"]: item for item in page["items"]}
    assert page["total"] == 5
    if hidden:
        assert_hidden_summary(rows["Target idea"])
        expected_desc = ["High idea", "Disputed idea", "Low idea"]
        expected_asc = ["Low idea", "Disputed idea", "High idea"]
    else:
        assert_visible_target(rows["Target idea"])
        expected_desc = ["High idea", "Target idea", "Disputed idea", "Low idea"]
        expected_asc = ["Low idea", "Disputed idea", "Target idea", "High idea"]
    for other in ("High idea", "Disputed idea", "Low idea"):
        assert rows[other]["score_hidden"] is False
    for sort, expected in (("-score", expected_desc), ("score", expected_asc)):
        titles, cursors = await walk(client, world.slug, sort=sort)
        assert titles[: len(expected)] == expected
        assert set(titles[len(expected) :]) == (
            {"Target idea", "Unscored idea"} if hidden else {"Unscored idea"}
        )
        # Cursors carry the masked score only: never T's raw 3.9 for a pending evaluator.
        assert all(set(c) == {"sort", "v", "id"} for c in cursors)
        by_id = {c["id"]: c["v"] for c in cursors}
        if target in by_id:
            assert by_id[target] == (None if hidden else "3.9")
        if hidden:
            assert "3.9" not in json.dumps(cursors)

    # --- Score-derived filter, list and board.
    flagged = ok(await client.get(f"/projects/{world.slug}/ideas", high_disagreement="true"))
    assert {i["title"] for i in flagged["items"]} == (
        {"Disputed idea"} if hidden else {"Disputed idea", "Target idea"}
    )
    assert flagged["total"] == (1 if hidden else 2)
    board = ok(await client.get(f"/projects/{world.slug}/board", high_disagreement="true"))
    evaluating = next(c for c in board["columns"] if c["status"] == "evaluating")
    assert evaluating["count"] == (1 if hidden else 2)
    full_board = ok(await client.get(f"/projects/{world.slug}/board", sort="-score"))
    column = next(c for c in full_board["columns"] if c["status"] == "evaluating")
    card = next(i for i in column["items"] if i["id"] == target)
    if hidden:
        assert_hidden_summary(card)
        assert [i["title"] for i in column["items"]] == ["Disputed idea", "Target idea"]
    else:
        assert_visible_target(card)
        assert [i["title"] for i in column["items"]] == ["Target idea", "Disputed idea"]

    # --- The idea page.
    detail = ok(await client.get(f"/ideas/{target}"))
    states = {e["user"]["display_name"]: e["state"] for e in detail["evaluators"]}
    assert states["Drafting"] == ("draft" if who == "drafting" else "invited")  # drafts are private
    assert states["Second"] == states["Submitter"] == states["Scout Agent"] == "submitted"
    assert detail["evaluator_progress"] == {"submitted": 3, "total": 6}  # not score data
    if hidden:
        assert_hidden_summary(detail)
        assert detail["aggregate"] is None
    else:
        assert_visible_target(detail)
        assert detail["aggregate"]["overall"] == 3.9
        assert detail["aggregate"]["count"] == 2

    # --- Evaluations list.
    evaluations = ok(await client.get(f"/ideas/{target}/evaluations"))
    if hidden:
        assert evaluations == {"items": [], "score_hidden": True}
    else:
        assert evaluations["score_hidden"] is False
        assert len(evaluations["items"]) == 3  # two humans and the excluded AI evaluation

    # --- Activity, search and the evaluate sheet never carry other people's scores.
    feed = ok(await client.get(f"/ideas/{target}/activity"))
    assert [item["type"] for item in feed["items"]] == ["evaluation_submitted"]
    assert_no_score_data(feed)
    found = ok(await client.get("/search", q="Target"))
    assert [i["id"] for i in found["ideas"]] == [target]
    assert_no_score_data(found)
    mine = ok(await client.get(f"/ideas/{target}/evaluations/me"))
    if who == "drafting":
        assert mine["state"] == "draft"
    elif who in ("pending", "admin_pending"):
        assert (mine["state"], mine["scores"]) == ("invited", [])
    elif who != "submitter":
        assert mine is None

    # --- My work and owned ideas.
    work = ok(await client.get("/me/work"))
    for group in work["owned"]:
        for item in group["ideas"]:
            if item["id"] == target:
                assert_hidden_summary(item) if hidden else assert_visible_target(item)
    for entry in work["recent"]:
        if entry["idea"]["id"] == target:
            assert_hidden_summary(entry["idea"]) if hidden else assert_visible_target(entry["idea"])
            assert_no_score_data(entry["latest_activity"])
    due = [e["idea"]["id"] for e in work["evaluations_due"]]
    assert due == ([target] if hidden else [])
    assert_no_score_data(work["evaluations_due"])
    owned = ok(await client.get("/me/owned-ideas"))
    if who == "admin_pending":
        target_row = next(i for i in owned["items"] if i["id"] == target)
        assert_hidden_summary(target_row)
    if who in ("pending", "admin_pending"):
        assert work["evaluations_due"][0]["state"] == "invited"
    if who == "drafting":
        assert work["evaluations_due"][0]["state"] == "draft"


async def test_submitting_lifts_the_blind_immediately(api: AsUser, world: World) -> None:
    pending = await api(world.users["pending"])
    target = str(world.target.id)
    rubric = ok(await pending.get(f"/projects/{world.slug}"))["rubric"]
    body = {
        "scores": [{"criterion_id": c["id"], "score": LOW[c["name"]]} for c in rubric],
        "recommendation": "maybe",
        "submit": True,
    }

    ok(await pending.put(f"/ideas/{target}/evaluations/me", body))
    detail = ok(await pending.get(f"/ideas/{target}"))
    evaluations = ok(await pending.get(f"/ideas/{target}/evaluations"))

    assert detail["score_hidden"] is False
    # (5, 4, 4, 4, 4)... the adjusted means over three humans: Value 3, others 11/3 -> 3.5.
    assert detail["score"] == {"overall": 3.5, "count": 3}
    assert detail["aggregate"] is not None
    assert len(evaluations["items"]) == 4
    assert evaluations["score_hidden"] is False


async def test_pending_admin_cannot_remove_themselves_to_peek(api: AsUser, world: World) -> None:
    admin = await api(world.users["admin_pending"])
    target = str(world.target.id)
    admin_id = world.users["admin_pending"].id

    response = await admin.delete(f"/ideas/{target}/evaluators/{admin_id}")

    assert_problem(response, 403, "cannot_remove_self")
    assert_hidden_summary(ok(await admin.get(f"/ideas/{target}")))
    assert ok(await admin.get(f"/ideas/{target}/evaluations"))["items"] == []


async def test_closing_evaluation_does_not_lift_the_blind(api: AsUser, world: World) -> None:
    owner = await api(world.users["admin_pending"])
    target = str(world.target.id)

    ok(await owner.post(f"/ideas/{target}/evaluation/close"))
    detail = ok(await (await api(world.users["pending"])).get(f"/ideas/{target}"))
    work = ok(await (await api(world.users["pending"])).get("/me/work"))

    assert_hidden_summary(detail)
    assert work["evaluations_due"] == []  # nothing left to do, still blind


async def test_removing_a_pending_evaluator_releases_them(api: AsUser, world: World) -> None:
    owner = await api(world.users["admin_pending"])
    target = str(world.target.id)

    ok(await owner.delete(f"/ideas/{target}/evaluators/{world.users['drafting'].id}"))
    detail = ok(await (await api(world.users["drafting"])).get(f"/ideas/{target}"))

    assert_visible_target(detail)


async def test_demoted_pending_evaluators_stay_blind(
    api: AsUser, world: World, db_session: AsyncSession
) -> None:
    from app.models.project import ProjectMember

    member = await db_session.get(
        ProjectMember, (world.target.project_id, world.users["pending"].id)
    )
    assert member is not None
    member.role = ProjectRole.VIEWER
    await db_session.commit()

    detail = ok(await (await api(world.users["pending"])).get(f"/ideas/{world.target.id}"))

    assert_hidden_summary(detail)
    assert detail["permissions"]["can_evaluate"] is False
