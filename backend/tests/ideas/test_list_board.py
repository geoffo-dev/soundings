"""The list and the board (contract section 3.9): filters, sorts, keyset cursors,
totals, board columns and the summary fields."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Comment
from app.models.base import utcnow
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, Resolution
from app.models.idea import Idea, IdeaVote
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_idea, make_project
from tests.ideas.conftest import Api, AsUser, Team, assert_problem, ok

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)


async def titles(client: Api, slug: str, **params: Any) -> list[str]:
    page = ok(await client.get(f"/projects/{slug}/ideas", **params))
    return [item["title"] for item in page["items"]]


async def walk(client: Api, slug: str, limit: int = 2, **params: Any) -> list[str]:
    found: list[str] = []
    cursor = None
    while True:
        extra: dict[str, str] = {"cursor": cursor} if cursor else {}
        page = ok(await client.get(f"/projects/{slug}/ideas", limit=limit, **params, **extra))
        found += [item["title"] for item in page["items"]]
        assert len(page["items"]) <= limit
        cursor = page["next_cursor"]
        if cursor is None:
            return found


@pytest.fixture
async def ideas(team: Team, db_session: AsyncSession) -> dict[str, Idea]:
    """Seven ideas with distinct statuses, owners, tags, votes, times and scores."""
    p = team.project

    async def idea(title: str, minutes: int, **kwargs: Any) -> Idea:
        return await make_idea(
            db_session, p, title=title, last_activity_at=T0 + timedelta(minutes=minutes), **kwargs
        )

    made = {
        "alpha": await idea("alpha", 5, tags=["UX"], owner=team.owner, summary="Refunds by chat"),
        "Bravo": await idea("Bravo", 1, tags=["Billing"], status=IdeaStatus.EVALUATING),
        "charlie": await idea("charlie", 7, owner=team.member, status=IdeaStatus.SHORTLISTED),
        "Delta": await idea("Delta", 3, tags=["UX", "Billing"], status=IdeaStatus.PROPOSAL),
        "echo": await idea("echo", 2, status=IdeaStatus.CLOSED, resolution=Resolution.ACCEPTED),
        "foxtrot": await idea("foxtrot", 6, status=IdeaStatus.CLOSED, resolution=Resolution.PARKED),
        "golf 100%_off": await idea("golf 100%_off", 4, owner=team.owner),
    }
    # Created in the order above; votes 0..; scores on three ideas.
    for n, name in enumerate(["Bravo", "Delta", "charlie"]):
        for voter in [team.member, team.owner, team.admin][: n + 1]:
            db_session.add(IdeaVote(idea_id=made[name].id, user_id=voter.id))
        made[name].vote_count = n + 1
    await db_session.commit()
    eve1, eve2 = team.evaluators[:2]
    await add_evaluator(
        db_session, made["Bravo"], eve1, state=EvaluatorState.SUBMITTED, scores={"Value": 5}
    )
    await add_evaluator(
        db_session, made["Delta"], eve1, state=EvaluatorState.SUBMITTED, scores={"Value": 2}
    )
    await add_evaluator(db_session, made["Delta"], eve2)
    await add_evaluator(
        db_session, made["alpha"], eve2, state=EvaluatorState.SUBMITTED, scores={"Value": 4}
    )
    await add_evaluator(db_session, made["echo"], eve2)  # closed: never "needs evaluators"
    await recompute_aggregates(db_session, project_id=p.id)
    await db_session.commit()
    return made


# --- Filters ---------------------------------------------------------------------------------
async def test_default_order_is_most_recently_active(
    api: AsUser, team: Team, ideas: dict[str, Idea]
) -> None:
    client = await api(team.viewer)

    page = ok(await client.get(f"/projects/{team.slug}/ideas"))

    assert [i["title"] for i in page["items"]] == [
        "charlie", "foxtrot", "alpha", "golf 100%_off", "Delta", "echo", "Bravo"
    ]  # fmt: skip
    assert page["total"] == 7
    assert page["next_cursor"] is None


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": ["new"]}, {"alpha", "golf 100%_off"}),
        ({"status": ["evaluating", "proposal"]}, {"Bravo", "Delta"}),
        ({"status": ["closed"], "resolution": ["parked"]}, {"foxtrot"}),
        ({"resolution": ["accepted", "parked"]}, {"echo", "foxtrot"}),
        ({"status": ["new"], "resolution": ["parked"]}, set()),
        ({"owner": "none"}, {"Bravo", "Delta", "echo", "foxtrot"}),
        ({"tag": ["ux"]}, {"alpha", "Delta"}),
        ({"tag": ["UX", "billing"]}, {"alpha", "Bravo", "Delta"}),
        ({"tag": ["nope"]}, set()),
        ({"needs_evaluators": "true"}, {"charlie", "golf 100%_off"}),
        ({"high_disagreement": "true"}, set()),
        ({"q": "REFUND"}, {"alpha"}),  # in the summary, any case
        ({"q": "HA"}, {"alpha", "charlie"}),
        ({"q": "100%_"}, {"golf 100%_off"}),  # LIKE wildcards are literal
        ({"q": "%"}, {"golf 100%_off"}),
        ({"q": "cust-3"}, {"charlie"}),  # the idea's key
        ({"q": "OPS-3"}, set()),
        ({"owner": "none", "status": ["closed"], "tag": ["billing"]}, set()),
        ({"owner": "none", "tag": ["billing"]}, {"Bravo", "Delta"}),
    ],
)
async def test_filters(
    api: AsUser, team: Team, ideas: dict[str, Idea], params: dict[str, Any], expected: set[str]
) -> None:
    client = await api(team.member)

    page = ok(await client.get(f"/projects/{team.slug}/ideas", **params))

    assert {i["title"] for i in page["items"]} == expected
    assert page["total"] == len(expected)


async def test_owner_filter(api: AsUser, team: Team, ideas: dict[str, Idea]) -> None:
    olive = await api(team.owner)

    mine = await titles(olive, team.slug, owner="me")
    theirs = await titles(olive, team.slug, owner=str(team.member.id))
    nobody = await titles(olive, team.slug, owner=str(uuid4()))

    assert set(mine) == {"alpha", "golf 100%_off"}
    assert theirs == ["charlie"]
    assert nobody == []
    assert_problem(
        await olive.get(f"/projects/{team.slug}/ideas", owner="someone"), 422, "validation_error"
    )


async def test_high_disagreement_filter(
    api: AsUser, team: Team, ideas: dict[str, Idea], db_session: AsyncSession
) -> None:
    await add_evaluator(
        db_session,
        ideas["Bravo"],
        team.evaluators[2],
        state=EvaluatorState.SUBMITTED,
        scores={"Value": 1},
    )
    await recompute_aggregates(db_session, idea_ids=[ideas["Bravo"].id])
    await db_session.commit()

    assert await titles(await api(team.viewer), team.slug, high_disagreement="true") == ["Bravo"]


# --- Sorts and cursors -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("updated", ["Bravo", "echo", "Delta", "golf 100%_off", "alpha", "foxtrot", "charlie"]),
        ("-updated", ["charlie", "foxtrot", "alpha", "golf 100%_off", "Delta", "echo", "Bravo"]),
        ("created", ["alpha", "Bravo", "charlie", "Delta", "echo", "foxtrot", "golf 100%_off"]),
        ("-created", ["golf 100%_off", "foxtrot", "echo", "Delta", "charlie", "Bravo", "alpha"]),
        ("title", ["alpha", "Bravo", "charlie", "Delta", "echo", "foxtrot", "golf 100%_off"]),
        ("-title", ["golf 100%_off", "foxtrot", "echo", "Delta", "charlie", "Bravo", "alpha"]),
        ("-votes", ["charlie", "Delta", "Bravo"]),  # then the zero-vote ideas, by id
        ("votes", ["Bravo", "Delta", "charlie"]),  # after the zero-vote ideas
        ("-score", ["Bravo", "alpha", "Delta"]),  # 5, 4, 2, then unscored
        ("score", ["Delta", "alpha", "Bravo"]),  # 2, 4, 5, then unscored
    ],
)
async def test_sorts_page_through_every_idea_exactly_once(
    api: AsUser, team: Team, ideas: dict[str, Idea], sort: str, expected: list[str]
) -> None:
    client = await api(team.member)

    everything = await walk(client, team.slug, sort=sort)
    one_page = await titles(client, team.slug, sort=sort)

    assert everything == one_page
    assert sorted(everything) == sorted(ideas)
    if sort == "votes":
        assert everything[-3:] == expected
    else:
        assert everything[: len(expected)] == expected
    if sort in ("score", "-score", "votes", "-votes"):
        # Ties (no score, no votes) break on id in the sort's direction.
        tail = everything[len(expected) :] if sort != "votes" else everything[:-3]
        ids = [str(ideas[title].id) for title in tail]
        assert ids == sorted(ids, reverse=sort.startswith("-"))


async def test_filtered_pages_keep_the_filters(
    api: AsUser, team: Team, ideas: dict[str, Idea]
) -> None:
    client = await api(team.member)

    assert await walk(client, team.slug, limit=1, sort="title", status=["closed", "new"]) == [
        "alpha", "echo", "foxtrot", "golf 100%_off"
    ]  # fmt: skip


async def test_ties_on_the_sort_value_do_not_skip_or_repeat(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    same = utcnow()
    for n in range(7):
        await make_idea(db_session, team.project, title="Same", last_activity_at=same)
        await make_idea(db_session, team.project, title=f"Other {n}", last_activity_at=same)
    client = await api(team.member)

    for sort in ("-updated", "title", "-votes", "score"):
        everything = ok(await client.get(f"/projects/{team.slug}/ideas", sort=sort, limit=200))
        walked = await walk(client, team.slug, limit=3, sort=sort)
        assert walked == [i["title"] for i in everything["items"]]


async def test_bad_cursors(api: AsUser, team: Team, ideas: dict[str, Idea]) -> None:
    client = await api(team.member)
    path = f"/projects/{team.slug}/ideas"
    cursor = ok(await client.get(path, sort="title", limit=1))["next_cursor"]

    def forged(values: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")

    someone = str(uuid4())
    for sort, bad in (
        ("title", "not-a-cursor"),
        ("title", forged(["title"])),  # type: ignore[arg-type]
        ("title", forged({"sort": "title", "v": 5, "id": someone})),
        ("title", forged({"sort": "title", "v": "x", "id": "nope"})),
        ("title", forged({"sort": "title", "v": "x"})),
        ("-updated", forged({"sort": "-updated", "v": "yesterday", "id": someone})),
        ("-updated", forged({"sort": "-updated", "v": "2026-09-01T12:00:00", "id": someone})),
        ("-updated", forged({"sort": "-updated", "v": None, "id": someone})),
        ("-score", forged({"sort": "-score", "v": "high", "id": someone})),
        ("-score", forged({"sort": "-score", "v": 4.5, "id": someone})),
        ("votes", forged({"sort": "votes", "v": "3", "id": someone})),
        ("votes", forged({"sort": "votes", "v": True, "id": someone})),
    ):
        response = await client.get(path, sort=sort, cursor=bad)
        assert_problem(response, 400, "invalid_cursor")
    # A cursor from another sort is foreign.
    assert_problem(await client.get(path, sort="-title", cursor=cursor), 400, "invalid_cursor")
    for limit in (0, 201):
        assert_problem(await client.get(path, limit=limit), 422, "validation_error")
    assert_problem(await client.get(path, sort="rank"), 422, "validation_error")
    assert_problem(await client.get(path, status="done"), 422, "validation_error")


@pytest.mark.parametrize(
    ("sort", "value"),
    [
        # Cursors are not signed: values the column can't hold must not reach PostgreSQL
        # (code review F4: numeric overflow was a 500).
        ("-score", "1e999999"),
        ("-score", "1e131072"),
        ("score", "-1e131072"),
        ("-score", "0.9"),
        ("-score", "5.1"),
        ("-score", "Infinity"),
        ("votes", 10**40),
        ("-votes", 2**31),
        ("votes", -1),
        ("-updated", "0001-01-01T00:00:00+05:00"),
        ("-created", "9999-12-31T23:59:00-05:00"),
    ],
)
async def test_cursor_values_out_of_range_are_invalid(
    api: AsUser, team: Team, ideas: dict[str, Idea], sort: str, value: object
) -> None:
    client = await api(team.member)
    raw = json.dumps({"sort": sort, "v": value, "id": str(uuid4())})
    cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    response = await client.get(f"/projects/{team.slug}/ideas", sort=sort, cursor=cursor)

    assert_problem(response, 400, "invalid_cursor")


@pytest.mark.parametrize(
    ("sort", "value"),
    [("-score", "5"), ("score", "1.0"), ("-score", "3.5"), ("votes", 2**31 - 1), ("votes", 0)],
)
async def test_cursor_values_at_the_edges_are_valid(
    api: AsUser, team: Team, ideas: dict[str, Idea], sort: str, value: object
) -> None:
    client = await api(team.member)
    raw = json.dumps({"sort": sort, "v": value, "id": str(uuid4())})
    cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    ok(await client.get(f"/projects/{team.slug}/ideas", sort=sort, cursor=cursor))


async def test_activity_cursor_out_of_range_is_invalid(
    api: AsUser, team: Team, ideas: dict[str, Idea]
) -> None:
    client = await api(team.member)
    for when in ("0001-01-01T00:00:00+05:00", "9999-12-31T23:59:00-05:00"):
        raw = json.dumps({"t": when, "id": str(uuid4())})
        cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        response = await client.get(f"/ideas/{ideas['alpha'].id}/activity", cursor=cursor)
        assert_problem(response, 400, "invalid_cursor")


async def test_list_needs_view_access(api: AsUser, team: Team, ideas: dict[str, Idea]) -> None:
    otto = await api(team.outsider)

    assert_problem(await otto.get(f"/projects/{team.slug}/ideas"), 404, "not_found")
    assert_problem(await otto.get(f"/projects/{team.slug}/board"), 404, "not_found")
    assert_problem(await otto.get("/projects/no-such-project/ideas"), 404, "not_found")
    assert len(await titles(await api(team.platform), team.slug)) == 7


async def test_summary_fields(
    api: AsUser, team: Team, ideas: dict[str, Idea], db_session: AsyncSession
) -> None:
    delta = ideas["Delta"]
    db_session.add_all(
        [
            Comment(id=uuid4(), idea_id=delta.id, author_id=team.member.id, body_md="One"),
            Comment(id=uuid4(), idea_id=delta.id, author_id=team.member.id, body_md="Two"),
            Comment(
                id=uuid4(),
                idea_id=delta.id,
                author_id=team.member.id,
                body_md="",
                deleted_at=utcnow(),
            ),
        ]
    )
    await db_session.commit()
    olive = await api(team.owner)

    page = ok(await olive.get(f"/projects/{team.slug}/ideas", q="Delta"))

    [item] = page["items"]
    assert set(item) == {
        "id", "key", "number", "project", "title", "status", "resolution", "status_label",
        "summary", "owner", "tags", "evaluator_progress", "score", "score_hidden",
        "high_disagreement", "vote_count", "has_voted", "comment_count", "created_at",
        "last_activity_at", "permissions", "research", "researcher",
    }  # fmt: skip
    assert item["researcher"] is None  # Phase 8b: nobody assigned (and the step is off)
    assert item["research"] is None  # Phase 8: the project has no research step
    assert item["key"] == "CUST-4"
    assert item["tags"] == ["Billing", "UX"]
    assert item["evaluator_progress"] == {"submitted": 1, "total": 2}
    assert item["score"] == {"overall": 2.0, "count": 1}
    assert (item["vote_count"], item["has_voted"]) == (2, True)
    assert item["comment_count"] == 2
    assert item["last_activity_at"] == (T0 + timedelta(minutes=3)).isoformat().replace(
        "+00:00", "Z"
    )
    assert item["permissions"] == {"can_change_status": False}


# --- Board -----------------------------------------------------------------------------------
async def test_board_columns(
    api: AsUser, team: Team, ideas: dict[str, Idea], db_session: AsyncSession
) -> None:
    team.project.status_labels = {"shortlisted": "Short list", "parked": "On ice"}
    db_session.add(team.project)
    await db_session.commit()
    client = await api(team.admin)

    board = ok(await client.get(f"/projects/{team.slug}/board", limit=1))

    columns = board["columns"]
    assert [(c["status"], c["label"], c["count"]) for c in columns] == [
        ("new", "New", 2),
        ("evaluating", "Evaluating", 1),
        ("shortlisted", "Short list", 1),
        ("proposal", "Proposal", 1),
        ("closed", "Closed", 2),
    ]
    assert [[i["title"] for i in c["items"]] for c in columns] == [
        ["alpha"], ["Bravo"], ["charlie"], ["Delta"], ["foxtrot"]
    ]  # fmt: skip
    assert [c["resolution_counts"] for c in columns[:4]] == [None] * 4
    assert columns[4]["resolution_counts"] == {"accepted": 1, "rejected": 0, "parked": 1}
    assert columns[4]["items"][0]["status_label"] == "On ice"
    assert columns[1]["next_cursor"] is None
    assert columns[0]["items"][0]["permissions"] == {"can_change_status": True}
    # "Load more" of a column is list_ideas with status=<column> and the column's cursor.
    for column, rest in ((0, ["golf 100%_off"]), (4, ["echo"])):
        more = ok(
            await client.get(
                f"/projects/{team.slug}/ideas",
                status=columns[column]["status"],
                cursor=columns[column]["next_cursor"],
                limit=1,
            )
        )
        assert [i["title"] for i in more["items"]] == rest
        assert more["next_cursor"] is None


async def test_board_filters_and_sort(api: AsUser, team: Team, ideas: dict[str, Idea]) -> None:
    client = await api(team.owner)

    board = ok(await client.get(f"/projects/{team.slug}/board", owner="me", sort="title"))
    by_tag = ok(await client.get(f"/projects/{team.slug}/board", tag="billing", sort="-score"))
    unowned = ok(await client.get(f"/projects/{team.slug}/board", needs_evaluators="true"))

    assert [(c["count"], [i["title"] for i in c["items"]]) for c in board["columns"]] == [
        (2, ["alpha", "golf 100%_off"]), (0, []), (0, []), (0, []), (0, [])
    ]  # fmt: skip
    assert [c["count"] for c in by_tag["columns"]] == [0, 1, 0, 1, 0]
    assert [c["count"] for c in unowned["columns"]] == [1, 0, 1, 0, 0]
    assert unowned["columns"][4]["resolution_counts"] == {"accepted": 0, "rejected": 0, "parked": 0}
    assert_problem(
        await client.get(f"/projects/{team.slug}/board", limit=201), 422, "validation_error"
    )


async def test_empty_board(api: AsUser, team: Team) -> None:
    board = ok(await (await api(team.member)).get(f"/projects/{team.slug}/board"))

    assert [c["count"] for c in board["columns"]] == [0] * 5
    assert all(c["items"] == [] and c["next_cursor"] is None for c in board["columns"])


async def test_archived_project_lists_still_work(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    project = await make_project(
        db_session, archived=True, members={team.member: ProjectRole.MEMBER}
    )
    await make_idea(db_session, project, owner=team.member)
    client = await api(team.member)

    page = ok(await client.get(f"/projects/{project.slug}/ideas"))
    board = ok(await client.get(f"/projects/{project.slug}/board"))

    assert page["total"] == 1
    assert page["items"][0]["permissions"] == {"can_change_status": False}
    assert board["columns"][0]["count"] == 1
