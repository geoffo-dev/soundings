"""My work and owned ideas (contract section 3.10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility, Resolution
from app.models.idea import Idea
from app.models.project import ProjectMember
from app.schemas.work import EVALUATIONS_DUE_PAGE
from app.services.work import OWNED_GROUP_SIZE
from tests.factories import add_evaluator, make_idea, make_project
from tests.ideas.conftest import AsUser, Team, assert_problem, ok

NOW = datetime.now(UTC)


async def set_due(db: AsyncSession, idea: Idea, due: datetime | None) -> None:
    idea.evaluation_due_at = due
    db.add(idea)
    await db.commit()


async def test_empty_work(api: AsUser, team: Team) -> None:
    work = ok(await (await api(team.member)).get("/me/work"))

    assert work == {
        "counts": {
            "evaluations_due": 0,
            "evaluations_overdue": 0,
            "owned_open": 0,
            "research_to_do": 0,  # Phase 8b
            "research_overdue": 0,
        },
        "evaluations_due": [],
        "evaluations_due_next_cursor": None,
        "research_to_do": [],
        "research_to_do_next_cursor": None,
        "owned": [],
        "recent": [],
    }


async def test_evaluations_due(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    eve = team.evaluators[0]
    p = team.project
    later = await make_idea(db_session, p, title="Later", owner=team.owner)
    overdue = await make_idea(db_session, p, title="Overdue")
    undated = await make_idea(db_session, p, title="Undated")
    soon = await make_idea(db_session, p, title="Soon")
    drafted = await make_idea(db_session, p, title="Drafted")
    for idea, due in (
        (later, NOW + timedelta(days=9)),
        (overdue, NOW - timedelta(days=1)),
        (undated, None),
        (soon, NOW + timedelta(hours=3)),
        (drafted, NOW + timedelta(days=5)),
    ):
        await set_due(db_session, idea, due)
        state = EvaluatorState.DRAFT if idea is drafted else EvaluatorState.INVITED
        await add_evaluator(db_session, idea, eve, state=state)
    # Not due: submitted, evaluation closed, idea closed, archived project, someone else's.
    done = await make_idea(db_session, p, title="Done")
    await add_evaluator(db_session, done, eve, state=EvaluatorState.SUBMITTED)
    closed_eval = await make_idea(db_session, p, title="Closed evaluation")
    closed_eval.evaluation_closed_at = utcnow()
    await add_evaluator(db_session, closed_eval, eve)
    closed_idea = await make_idea(
        db_session, p, title="Closed idea", status=IdeaStatus.CLOSED, resolution=Resolution.PARKED
    )
    await add_evaluator(db_session, closed_idea, eve)
    archived = await make_project(db_session, archived=True, members={eve: ProjectRole.MEMBER})
    await add_evaluator(db_session, await make_idea(db_session, archived), eve)
    await add_evaluator(db_session, await make_idea(db_session, p), team.evaluators[1])

    work = ok(await (await api(eve)).get("/me/work"))

    due = work["evaluations_due"]
    assert [e["idea"]["title"] for e in due] == ["Overdue", "Soon", "Drafted", "Later", "Undated"]
    assert [e["overdue"] for e in due] == [True, False, False, False, False]
    assert [e["state"] for e in due] == ["invited", "invited", "draft", "invited", "invited"]
    first = due[0]
    assert set(first) == {"idea", "owner", "due_at", "overdue", "state"}
    assert first["idea"]["key"] == f"CUST-{overdue.number}"
    assert first["idea"]["project"]["slug"] == "customer-innovation"
    assert due[3]["owner"]["id"] == str(team.owner.id)
    assert due[4]["due_at"] is None
    assert work["counts"]["evaluations_due"] == 5
    assert work["counts"]["evaluations_overdue"] == 1


async def test_demoted_evaluators_owe_nothing(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    eve = team.evaluators[0]
    await add_evaluator(db_session, await make_idea(db_session, team.project), eve)
    member = await db_session.get(ProjectMember, (team.project.id, eve.id))
    assert member is not None
    member.role = ProjectRole.VIEWER
    await db_session.commit()

    work = ok(await (await api(eve)).get("/me/work"))

    assert work["evaluations_due"] == []


async def test_owned_groups(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    team.project.status_labels = {"new": "Inbox"}  # groups span projects: default labels
    db_session.add(team.project)
    await db_session.commit()
    other = await make_project(db_session, key="OPS", members={team.owner: ProjectRole.MEMBER})
    archived = await make_project(
        db_session, archived=True, members={team.owner: ProjectRole.MEMBER}
    )
    t0 = NOW - timedelta(days=1)
    for n in range(OWNED_GROUP_SIZE + 2):
        await make_idea(
            db_session,
            team.project if n % 2 else other,
            title=f"New {n}",
            owner=team.owner,
            last_activity_at=t0 + timedelta(minutes=n),
        )
    await make_idea(
        db_session,
        team.project,
        title="Shortlisted",
        owner=team.owner,
        status=IdeaStatus.SHORTLISTED,
    )
    await make_idea(db_session, other, title="Closed", owner=team.owner, status=IdeaStatus.CLOSED)
    await make_idea(db_session, archived, title="Archived", owner=team.owner)
    await make_idea(db_session, team.project, title="Not mine", owner=team.member)
    olive = await api(team.owner)

    work = ok(await olive.get("/me/work"))

    groups = work["owned"]
    assert [(g["status"], g["label"], g["count"]) for g in groups] == [
        ("new", "New", OWNED_GROUP_SIZE + 2),
        ("shortlisted", "Shortlisted", 1),
        ("closed", "Closed", 1),
    ]
    new = groups[0]
    assert len(new["ideas"]) == OWNED_GROUP_SIZE
    assert new["ideas"][0]["title"] == f"New {OWNED_GROUP_SIZE + 1}"  # most recently active
    assert groups[2]["next_cursor"] is None
    assert work["counts"]["owned_open"] == OWNED_GROUP_SIZE + 3
    more = ok(await olive.get("/me/owned-ideas", status="new", cursor=new["next_cursor"]))
    assert [i["title"] for i in more["items"]] == ["New 1", "New 0"]
    assert (more["next_cursor"], more["total"]) == (None, OWNED_GROUP_SIZE + 2)


async def test_owned_ideas_list(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    for n, status in enumerate((IdeaStatus.NEW, IdeaStatus.PROPOSAL, IdeaStatus.CLOSED)):
        await make_idea(
            db_session,
            team.project,
            title=f"Owned {n}",
            owner=team.owner,
            status=status,
            last_activity_at=NOW - timedelta(hours=n),
        )
    olive = await api(team.owner)

    everything = ok(await olive.get("/me/owned-ideas"))
    open_only = ok(await olive.get("/me/owned-ideas", status=["new", "proposal"], limit=1))

    assert [i["title"] for i in everything["items"]] == ["Owned 0", "Owned 1", "Owned 2"]
    assert everything["total"] == 3
    assert [i["title"] for i in open_only["items"]] == ["Owned 0"]
    assert open_only["total"] == 2
    rest = ok(
        await olive.get(
            "/me/owned-ideas", status=["new", "proposal"], cursor=open_only["next_cursor"]
        )
    )
    assert [i["title"] for i in rest["items"]] == ["Owned 1"]
    assert_problem(await olive.get("/me/owned-ideas", cursor="nope"), 400, "invalid_cursor")
    assert_problem(await olive.get("/me/owned-ideas", status="done"), 422, "validation_error")


async def test_ideas_you_can_no_longer_see_leave_my_work(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    await add_evaluator(db_session, idea, team.owner)
    member = await db_session.get(ProjectMember, (team.project.id, team.owner.id))
    await db_session.delete(member)
    await db_session.commit()

    work = ok(await (await api(team.owner)).get("/me/work"))

    assert work["owned"] == work["evaluations_due"] == work["recent"] == []


async def test_recent(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    internal = await make_project(
        db_session,
        key="INT",
        visibility=ProjectVisibility.INTERNAL,
        members={team.admin: ProjectRole.ADMIN},
    )
    await make_idea(db_session, internal, title="Internal, no role")
    for n in range(22):
        await make_idea(
            db_session, team.project, title=f"Idea {n}", last_activity_at=NOW - timedelta(hours=n)
        )
    max_ = await api(team.member)
    ok(await max_.post("/ideas/CUST-22/comments", {"body_md": "Bumped"}), 201)  # Idea 21

    recent = ok(await max_.get("/me/work"))["recent"]

    titles = [entry["idea"]["title"] for entry in recent]
    assert len(titles) == 20
    assert titles[:3] == ["Idea 21", "Idea 0", "Idea 1"]
    assert "Internal, no role" not in titles
    latest: dict[str, Any] = recent[0]["latest_activity"]
    assert latest["type"] == "comment"
    assert latest["comment"]["body_md"] == "Bumped"
    assert recent[1]["latest_activity"] is None  # made without events
    assert recent[0]["idea"]["comment_count"] == 1


# --- Phase 7 (contract-phase7 C1): the first 50 due, the rest page by page; counts alone -----
async def test_my_work_lists_the_first_50_due_and_pages_the_rest(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    eve = team.evaluators[0]
    p = team.project
    total = EVALUATIONS_DUE_PAGE + 7
    same_time = NOW + timedelta(days=2)  # ties on the due date: the id decides
    for n in range(total):
        idea = await make_idea(db_session, p, title=f"Due {n}")
        if n % 5 == 0:
            due: datetime | None = None
        elif n % 5 == 1:
            due = same_time
        else:
            due = NOW + timedelta(hours=n - 20)  # the first few are overdue
        await set_due(db_session, idea, due)
        await add_evaluator(db_session, idea, eve)
    http = await api(eve)

    work = ok(await http.get("/me/work"))
    every: list[dict[str, Any]] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        page = ok(await http.get("/me/evaluations-due", **params))
        assert set(page) == {"items", "next_cursor"}
        every += page["items"]
        cursor = page["next_cursor"]
        pages += 1
        if cursor is None:
            break
    counts = ok(await http.get("/me/work/counts"))

    assert len(work["evaluations_due"]) == EVALUATIONS_DUE_PAGE
    assert work["evaluations_due_next_cursor"] is not None
    assert pages == 3
    assert len(every) == total
    assert len({e["idea"]["id"] for e in every}) == total
    assert every[:EVALUATIONS_DUE_PAGE] == work["evaluations_due"]
    dated = [e["due_at"] for e in every if e["due_at"] is not None]
    assert dated == sorted(dated)
    assert all(e["due_at"] is None for e in every[len(dated) :])  # undated last
    overdue = sum(e["overdue"] for e in every)
    assert overdue > 0
    assert work["counts"]["evaluations_due"] == total
    assert work["counts"]["evaluations_overdue"] == overdue
    assert counts == work["counts"]
    rest = ok(await http.get("/me/evaluations-due", cursor=work["evaluations_due_next_cursor"]))
    assert rest["items"] == every[EVALUATIONS_DUE_PAGE:]
    assert rest["next_cursor"] is None


async def test_work_counts_match_my_work(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    eve = team.evaluators[0]
    late = await make_idea(db_session, team.project, title="Late", owner=eve)
    await set_due(db_session, late, NOW - timedelta(days=1))
    await add_evaluator(db_session, late, eve)
    await add_evaluator(db_session, await make_idea(db_session, team.project), eve)
    await make_idea(db_session, team.project, owner=eve, status=IdeaStatus.SHORTLISTED)
    await make_idea(
        db_session, team.project, owner=eve, status=IdeaStatus.CLOSED, resolution=Resolution.PARKED
    )
    http = await api(eve)

    counts = ok(await http.get("/me/work/counts"))
    work = ok(await http.get("/me/work"))

    assert counts == {
        "evaluations_due": 2,
        "evaluations_overdue": 1,
        "owned_open": 2,
        "research_to_do": 0,
        "research_overdue": 0,
    }
    assert work["counts"] == counts
    assert work["evaluations_due_next_cursor"] is None
    assert ok(await (await api(team.member)).get("/me/work/counts")) == {
        "evaluations_due": 0,
        "evaluations_overdue": 0,
        "owned_open": 0,
        "research_to_do": 0,
        "research_overdue": 0,
    }


async def test_evaluations_due_rejects_foreign_cursors(api: AsUser, team: Team) -> None:
    http = await api(team.evaluators[0])
    owned_cursor = "eyJpZCI6IjEiLCJzb3J0IjoiLXVwZGF0ZWQiLCJ2IjoiMjAyNi0xMC0wMSJ9"

    assert_problem(await http.get("/me/evaluations-due", cursor="nope"), 400, "invalid_cursor")
    assert_problem(
        await http.get("/me/evaluations-due", cursor=owned_cursor), 400, "invalid_cursor"
    )
    assert_problem(await http.get("/me/evaluations-due", limit=0), 422, "validation_error")
