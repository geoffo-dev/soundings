"""Phase 1 acceptance through the HTTP API (QA; docs/test-plans/phase-1.md, AC-API-*).

SPEC section 13, Phase 1: *create a project, submit an idea, assign an owner, have
three evaluators score it blind, see the aggregate and ranking.*

Everything goes through the real app (dev login, session cookie, CSRF header) against
Postgres. It complements the backend's own ``tests/ideas/test_acceptance.py`` with:

* a rubric edited through the API: weights (2, 1, 1) and an inverted criterion;
* the aggregate checked against the contract's formula, including half-up rounding
  (2.25 -> 2.3, where Python's ``round`` gives 2.2);
* each evaluator blind on every surface until the response to their own submission,
  checked by walking every JSON payload for the idea, not by reading chosen fields;
* ``sort=score`` keyset cursors, decoded, never carrying a hidden score;
* the ranking in both directions for a viewer and for an internal non-member, on the
  list and on the board.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.conftest import Login
from tests.factories import make_user

API = "/api/v1"

# Rubric after the admin edits it: Value (weight 2), Effort (weight 1, inverted: lower is
# better), Reach (weight 1, new).
RUBRIC = [
    {"name": "Value", "weight": 2.0, "inverted": False},
    {"name": "Effort", "weight": 1.0, "inverted": True},
    {"name": "Reach", "weight": 1.0, "inverted": False},
]
EVALUATORS = ("Eve", "Fay", "Gus")
SCORES = {
    "Eve": {"Value": 4, "Effort": 2, "Reach": 3},
    "Fay": {"Value": 5, "Effort": 4, "Reach": 3},
    "Gus": {"Value": 2, "Effort": 3, "Reach": 3},
}
RECOMMENDATIONS = {"Eve": "go", "Fay": "go", "Gus": "no"}
# Value mean 11/3; Effort adjusted (6 - s) 4, 2, 3 -> 3; Reach 3.
# Overall = (2 * 11/3 + 3 + 3) / 4 = 3.333 -> 3.3. Value spreads 2..5 -> disagreement.
EXPECTED_OVERALL = 3.3
# The runner-up, one evaluation: Value 2, Effort 4 (-> 2), Reach 3:
# (2 * 2 + 2 + 3) / 4 = 2.25 -> 2.3 rounded half-up.
RUNNER_UP_SCORES = {"Value": 2, "Effort": 4, "Reach": 3}
RUNNER_UP_OVERALL = 2.3
PRIVATE_COMMENT = "{name}'s private reasoning about refunds"


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, f"{response.request.url}: {response.text}"
    return response.json() if response.content else None


class Client:
    """A signed-in client (dev login) with the CSRF header on writes."""

    def __init__(self, http: httpx.AsyncClient, user: User) -> None:
        self.http = http
        self.user = user

    async def get(self, path: str, **params: Any) -> Any:
        return ok(await self.http.get(API + path, params=params))

    async def send(self, method: str, path: str, body: Any = None, status: int = 200) -> Any:
        return ok(await self.http.request(method, API + path, json=body), status)


def walk(payload: Any) -> Iterator[dict[str, Any]]:
    """Every JSON object in ``payload``, depth first."""
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from walk(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from walk(item)


def assert_blind(payload: Any, idea: dict[str, Any], submitted: list[str]) -> int:
    """No object describing ``idea`` in ``payload`` carries score data, and no submitted
    evaluator's private comment appears. Returns how many such objects were seen."""
    text = json.dumps(payload)
    for name in submitted:
        assert PRIVATE_COMMENT.format(name=name) not in text
    seen = 0
    for obj in walk(payload):
        if obj.get("id") != idea["id"] and obj.get("key") != idea["key"]:
            continue
        seen += 1
        if "score" in obj:
            assert obj["score"] is None, obj
        if "score_hidden" in obj:
            assert obj["score_hidden"] is True, obj
        if "high_disagreement" in obj:
            assert obj["high_disagreement"] is False, obj
        if "aggregate" in obj:
            assert obj["aggregate"] is None, obj
    return seen


def decode_cursor(cursor: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))


def numbers_in(cursor: dict[str, Any]) -> list[Any]:
    """Values in a decoded cursor that are, or spell, a number (scores are "3.4")."""
    found: list[Any] = []
    for value in cursor.values():
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int | float):
            found.append(value)
        elif isinstance(value, str):
            try:
                float(value)
            except ValueError:
                continue
            found.append(value)
    return found


async def score_cursors(client: Client, slug: str) -> list[tuple[str, Any]]:
    """Walks ``sort=-score`` one idea per page; (key of the page's idea, its cursor)."""
    pages: list[tuple[str, Any]] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {"sort": "-score", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = await client.get(f"/projects/{slug}/ideas", **params)
        cursor = page["next_cursor"]
        pages.append((page["items"][0]["key"], decode_cursor(cursor) if cursor else None))
        if cursor is None:
            break
    return pages


async def assert_blind_everywhere(
    client: Client, slug: str, idea: dict[str, Any], submitted: list[str]
) -> None:
    """What a pending evaluator of ``idea`` sees while ``submitted`` have submitted."""
    key = idea["key"]
    detail = await client.get(f"/ideas/{key}")
    assert (detail["score"], detail["aggregate"], detail["score_hidden"]) == (None, None, True)
    # Who has submitted is not score data: it stays visible.
    assert detail["evaluator_progress"] == {"submitted": len(submitted), "total": 3}
    assert assert_blind(detail, idea, submitted) >= 1

    evaluations = await client.get(f"/ideas/{key}/evaluations")
    assert evaluations == {"items": [], "score_hidden": True}

    surfaces: list[Any] = [
        await client.get(f"/projects/{slug}/ideas", sort="-score"),
        await client.get(f"/projects/{slug}/ideas", sort="score"),
        await client.get(f"/projects/{slug}/board", sort="-score"),
        await client.get(f"/ideas/{key}/activity"),
        await client.get("/me/work"),
        await client.get("/search", q=key),
    ]
    for payload in surfaces:
        assert_blind(payload, idea, submitted)
    listed, _, board, _, work, found = surfaces
    assert assert_blind(listed, idea, submitted) == 1
    assert assert_blind(board, idea, submitted) == 1
    assert [e["idea"]["key"] for e in work["evaluations_due"]] == [key]
    assert found["ideas"][0]["key"] == key
    # The disagreement filter never matches an idea whose scores are hidden from you.
    flagged = await client.get(f"/projects/{slug}/ideas", high_disagreement="true")
    assert key not in [i["key"] for i in flagged["items"]]

    # sort=score keyset cursors are unsigned base64 JSON: the cursor issued right after
    # the hidden idea must hold the masked (null) score, never the cached aggregate.
    for page_key, cursor in await score_cursors(client, slug):
        if page_key == key and cursor is not None:
            assert None in cursor.values(), cursor
            assert numbers_in(cursor) == [], cursor


@pytest.fixture
async def people(db_session: AsyncSession) -> dict[str, User]:
    names = ("Ada", "Max", "Olive", *EVALUATORS, "Vic", "Nia")
    users = {name: await make_user(db_session, f"{name} Tester") for name in names}
    users["Root"] = await make_user(db_session, "Root Admin", platform_admin=True)
    return users


async def test_phase_1_acceptance_through_the_api(people: dict[str, User], login: Login) -> None:
    async def as_(name: str) -> Client:
        return Client(await login(people[name]), people[name])

    root = await as_("Root")

    # AC-API-01: a platform admin creates an internal project with Ada as its admin;
    # Ada adds the team and tailors the rubric.
    project = await root.send(
        "POST",
        "/projects",
        {
            "name": "Refunds",
            "slug": "refunds",
            "key": "REF",
            "visibility": "internal",
            "admin_user_id": str(people["Ada"].id),
        },
        201,
    )
    slug = project["slug"]
    assert project["my_role"] is None  # the creator is not the admin here
    ada = await as_("Ada")
    for name in ("Max", "Olive", *EVALUATORS):
        await ada.send("POST", f"/projects/{slug}/members", {"user_id": str(people[name].id)}, 201)
    viewer = {"user_id": str(people["Vic"].id), "role": "viewer"}
    await ada.send("POST", f"/projects/{slug}/members", viewer, 201)

    current = {c["name"]: c["id"] for c in (await ada.get(f"/projects/{slug}"))["rubric"]}
    rubric = await ada.send(
        "PUT",
        f"/projects/{slug}/rubric",
        {"criteria": [{**c, "id": current.get(str(c["name"]))} for c in RUBRIC]},
    )
    assert [(c["name"], c["weight"], c["inverted"]) for c in rubric["criteria"]] == [
        ("Value", 2.0, False),
        ("Effort", 1.0, True),
        ("Reach", 1.0, False),
    ]
    criterion = {c["name"]: c["id"] for c in rubric["criteria"]}
    assert criterion["Value"] == current["Value"]  # kept, not recreated

    # AC-API-02: Max, a member, submits the idea (and two more to rank against).
    max_ = await as_("Max")
    idea = await max_.send(
        "POST",
        f"/projects/{slug}/ideas",
        {"title": "Refunds without a phone call", "summary": "Start a refund in the app."},
        201,
    )
    assert (idea["key"], idea["status"], idea["owner"]) == ("REF-1", "new", None)
    runner_up = await max_.send(
        "POST", f"/projects/{slug}/ideas", {"title": "Refund bot", "summary": "Chat."}, 201
    )
    unscored = await max_.send(
        "POST", f"/projects/{slug}/ideas", {"title": "Refund kiosk", "summary": "Stores."}, 201
    )

    # AC-API-03: Ada assigns Olive as the owner; Olive moves it to Evaluating.
    detail = await ada.send(
        "PUT", f"/ideas/{idea['key']}/owner", {"user_id": str(people["Olive"].id)}
    )
    assert detail["owner"]["id"] == str(people["Olive"].id)
    olive = await as_("Olive")
    detail = await olive.send("POST", f"/ideas/{idea['key']}/status", {"status": "evaluating"})
    assert detail["status"] == "evaluating"

    # AC-API-04: Olive invites three evaluators with a due date.
    due = (datetime.now(UTC) + timedelta(days=10)).replace(microsecond=0)
    invite = {"user_ids": [str(people[n].id) for n in EVALUATORS], "due_at": due.isoformat()}
    detail = await olive.send("POST", f"/ideas/{idea['key']}/evaluators", invite)
    assert [e["user"]["id"] for e in detail["evaluators"]] == invite["user_ids"]
    assert {e["state"] for e in detail["evaluators"]} == {"invited"}
    assert datetime.fromisoformat(detail["evaluation_due_at"]) == due
    assert detail["evaluator_progress"] == {"submitted": 0, "total": 3}

    # AC-API-05: each evaluator is blind until their own submission, and sees
    # everything in the very next response.
    submitted: list[str] = []
    for name in EVALUATORS:
        client = await as_(name)
        await assert_blind_everywhere(client, slug, idea, submitted)
        draft = {"scores": [{"criterion_id": criterion["Value"], "score": 1}], "submit": False}
        mine = await client.send("PUT", f"/ideas/{idea['key']}/evaluations/me", draft)
        assert mine["state"] == "draft"
        await assert_blind_everywhere(client, slug, idea, submitted)  # a draft lifts nothing

        final = {
            "scores": [{"criterion_id": criterion[c], "score": s} for c, s in SCORES[name].items()],
            "recommendation": RECOMMENDATIONS[name],
            "comment": PRIVATE_COMMENT.format(name=name),
            "submit": True,
        }
        mine = await client.send("PUT", f"/ideas/{idea['key']}/evaluations/me", final)
        assert mine["state"] == "submitted"
        submitted.append(name)

        detail = await client.get(f"/ideas/{idea['key']}")
        assert detail["score_hidden"] is False
        assert detail["aggregate"]["count"] == len(submitted)
        visible = await client.get(f"/ideas/{idea['key']}/evaluations")
        assert visible["score_hidden"] is False
        assert [e["evaluator"]["id"] for e in visible["items"]] == [
            str(people[n].id) for n in submitted
        ]
        work = await client.get("/me/work")
        assert work["evaluations_due"] == []
        # The owner (not an evaluator) sees the aggregate grow with each submission.
        assert (await olive.get(f"/ideas/{idea['key']}"))["score"]["count"] == len(submitted)

    # The runner-up: one evaluation, which exercises half-up rounding (2.25 -> 2.3).
    await ada.send(
        "POST", f"/ideas/{runner_up['key']}/evaluators", {"user_ids": [str(people["Fay"].id)]}
    )
    fay = await as_("Fay")
    body = {
        "scores": [{"criterion_id": criterion[c], "score": s} for c, s in RUNNER_UP_SCORES.items()],
        "recommendation": "maybe",
        "submit": True,
    }
    await fay.send("PUT", f"/ideas/{runner_up['key']}/evaluations/me", body)

    # AC-API-06: the aggregate, as a viewer sees it.
    vic = await as_("Vic")
    detail = await vic.get(f"/ideas/{idea['key']}")
    aggregate = detail["aggregate"]
    assert (aggregate["overall"], aggregate["count"]) == (EXPECTED_OVERALL, 3)
    assert aggregate["high_disagreement"] is True
    assert aggregate["recommendations"] == {"go": 2, "maybe": 0, "no": 1}
    stats = {c["name"]: c for c in aggregate["criteria"]}
    # Per-criterion statistics are raw (as scored), inverted or not.
    assert {n: (s["mean"], s["min"], s["max"], s["spread"]) for n, s in stats.items()} == {
        "Value": (3.7, 2, 5, 3),
        "Effort": (3.0, 2, 4, 2),
        "Reach": (3.0, 3, 3, 0),
    }
    assert {n: (s["weight"], s["inverted"]) for n, s in stats.items()} == {
        "Value": (2.0, False),
        "Effort": (1.0, True),
        "Reach": (1.0, False),
    }
    assert detail["score"] == {"overall": EXPECTED_OVERALL, "count": 3}
    assert (await vic.get(f"/ideas/{runner_up['key']}"))["score"] == {
        "overall": RUNNER_UP_OVERALL,
        "count": 1,
    }
    evaluations = await vic.get(f"/ideas/{idea['key']}/evaluations")
    assert len(evaluations["items"]) == 3
    assert {e["comment"] for e in evaluations["items"]} == {
        PRIVATE_COMMENT.format(name=n) for n in EVALUATORS
    }

    # AC-API-07: the ranking, for the viewer and for an internal non-member, in both
    # directions; unscored ideas come last either way.
    nia = await as_("Nia")
    expected = {
        "-score": [
            (idea["key"], {"overall": EXPECTED_OVERALL, "count": 3}),
            (runner_up["key"], {"overall": RUNNER_UP_OVERALL, "count": 1}),
            (unscored["key"], None),
        ],
        "score": [
            (runner_up["key"], {"overall": RUNNER_UP_OVERALL, "count": 1}),
            (idea["key"], {"overall": EXPECTED_OVERALL, "count": 3}),
            (unscored["key"], None),
        ],
    }
    for client in (vic, nia):
        for sort, ranking in expected.items():
            page = await client.get(f"/projects/{slug}/ideas", sort=sort)
            assert [(i["key"], i["score"]) for i in page["items"]] == ranking
            assert page["total"] == 3
        flagged = await client.get(f"/projects/{slug}/ideas", high_disagreement="true")
        assert [i["key"] for i in flagged["items"]] == [idea["key"]]
        # Paging one idea at a time gives the same order (the cursor carries the score).
        assert [key for key, _ in await score_cursors(client, slug)] == [
            key for key, _ in expected["-score"]
        ]
    board = await vic.get(f"/projects/{slug}/board", sort="-score")
    columns = {c["status"]: c for c in board["columns"]}
    assert [(i["key"], i["score"]) for i in columns["evaluating"]["items"]] == [
        (idea["key"], {"overall": EXPECTED_OVERALL, "count": 3})
    ]
    assert [(i["key"], i["score"]) for i in columns["new"]["items"]] == [
        (runner_up["key"], {"overall": RUNNER_UP_OVERALL, "count": 1}),
        (unscored["key"], None),
    ]

    # Closing evaluation keeps the aggregate and the ranking.
    await olive.send("POST", f"/ideas/{idea['key']}/evaluation/close")
    detail = await vic.get(f"/ideas/{idea['key']}")
    assert (detail["evaluation_open"], detail["aggregate"]["overall"]) == (False, EXPECTED_OVERALL)


async def test_a_pending_admin_evaluator_stays_blind_and_cannot_remove_themselves(
    people: dict[str, User], login: Login
) -> None:
    """AC-API-08: no role lifts the blind — the project admin owes an evaluation, two
    others have submitted, evaluation is closed; they still see nothing and can't get
    out of it by removing themselves."""
    root = Client(await login(people["Root"]), people["Root"])
    project = await root.send(
        "POST",
        "/projects",
        {"name": "Blind", "slug": "blind", "key": "BL", "admin_user_id": str(people["Ada"].id)},
        201,
    )
    slug = project["slug"]
    ada = Client(await login(people["Ada"]), people["Ada"])
    for name in ("Eve", "Fay"):
        await ada.send("POST", f"/projects/{slug}/members", {"user_id": str(people[name].id)}, 201)
    idea = await ada.send(
        "POST", f"/projects/{slug}/ideas", {"title": "Blind idea", "summary": "Shh."}, 201
    )
    user_ids = [str(people[n].id) for n in ("Ada", "Eve", "Fay")]
    await ada.send("POST", f"/ideas/{idea['key']}/evaluators", {"user_ids": user_ids})
    rubric = (await ada.get(f"/projects/{slug}"))["rubric"]
    for name, value in (("Eve", 5), ("Fay", 1)):
        client = Client(await login(people[name]), people[name])
        body = {
            "scores": [{"criterion_id": c["id"], "score": value} for c in rubric],
            "recommendation": "go",
            "comment": PRIVATE_COMMENT.format(name=name),
            "submit": True,
        }
        await client.send("PUT", f"/ideas/{idea['key']}/evaluations/me", body)
    await ada.send("POST", f"/ideas/{idea['key']}/evaluation/close")

    detail = await ada.get(f"/ideas/{idea['key']}")
    assert (detail["score"], detail["aggregate"], detail["score_hidden"]) == (None, None, True)
    assert detail["evaluation_open"] is False
    assert assert_blind(await ada.get(f"/projects/{slug}/ideas"), idea, ["Eve", "Fay"]) == 1
    assert await ada.get(f"/ideas/{idea['key']}/evaluations") == {
        "items": [],
        "score_hidden": True,
    }
    response = await ada.http.delete(f"{API}/ideas/{idea['key']}/evaluators/{people['Ada'].id}")
    assert response.status_code == 403
    assert response.json()["code"] == "cannot_remove_self"
    assert (await ada.get(f"/ideas/{idea['key']}"))["score_hidden"] is True
