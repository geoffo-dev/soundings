"""Phase 7 performance check at full scale (docs/test-plans/performance.md).

Slow: ``make -C backend test-slow`` (or ``uv run pytest -m slow tests/perf -s``) seeds the
demo story plus the large data set once for the module (``seed_large``: 10k ideas in Big
Ideas + 2k elsewhere, 50 people, ~30k evaluations, ~31k comments, ~120k feed events,
~20k notifications; about a minute), then checks, through the whole app:

* **no N+1 queries:** every list's SQL statement count is the same for a page of 5 and
  a page of 50-100 (list, board, feed, inbox, audit log, owned ideas, moderation,
  admin users), and the same for an idea with 3 and with 5 evaluators;
* **a statement budget per request** (``STATEMENT_BUDGET``): the counts this phase
  measured, so a new per-row query or an extra round trip fails here first;
* **service times:** p95 of 20 calls of each read one at a time, against the 150 ms
  read budget (writes: 250 ms). My work is over budget on a loaded machine (xfail
  until it is reworked; see the test plan, bottleneck B1).

Concurrency (20 people at once) needs a real server: ``tests/perf/load.py`` against
``e2e/perf/stack.sh up``.
"""

from __future__ import annotations

import asyncio
import gc
import json
import time
from collections.abc import AsyncIterator, Iterator
from statistics import quantiles
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import create_engine, create_sessionmaker
from app.models.user import User
from app.seed.runner import seed_demo_data
from tests.perf.seed_large import BIG_SLUG, PENDING_EMAIL, seed_large

pytestmark = pytest.mark.slow

API = "/api/v1"
RUNS = 20
READ_BUDGET_MS = 150.0
WRITE_BUDGET_MS = 250.0

# SQL statements per request measured in Phase 7 (session lookup included). A higher
# count is a regression: a new per-row query or round trip. Lower it when you remove one.
STATEMENT_BUDGET: dict[str, int] = {
    "auth.me": 1,
    "projects.list": 2,
    "project.get": 6,
    "project.members": 4,
    "project.tags": 4,
    "list": 7,
    "board": 7,
    "search": 3,
    "idea.get": 14,  # the most for one row: see the test plan (B6)
    "idea.activity": 7,
    "idea.evaluations": 7,
    "idea.ai_runs": 7,
    "evaluation.me": 6,
    "me.work": 17,  # owner with ideas in all five statuses: one page query per group
    "me.owned_ideas": 7,
    "notifications.list": 3,
    "notifications.summary": 2,
    "admin.audit": 5,
    "admin.users": 2,
    "moderation": 5,
}


@pytest.fixture(autouse=True)
def _isolate_database() -> None:
    """Overrides the conftest's per-test truncation: this module seeds once
    (``big_instance``) and empties the database when it is done."""


@pytest.fixture(scope="module")
def big_instance(database_url: str, truncate_tables: Any) -> Iterator[dict[str, int]]:
    from tests.conftest import make_settings

    settings = make_settings(database_url=database_url, environment="test")

    async def seed() -> dict[str, int]:
        engine = create_engine(settings)
        try:
            async with create_sessionmaker(engine)() as db:
                await seed_demo_data(db)
                await db.commit()
                counts = await seed_large(db)
            async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
                await conn.execute(text("VACUUM ANALYZE"))
            return counts
        finally:
            await engine.dispose()

    truncate_tables()
    started = time.perf_counter()
    counts = asyncio.run(seed())
    counts["seed_seconds"] = round(time.perf_counter() - started)
    print(json.dumps({"seeded": counts}))  # noqa: T201
    yield counts
    truncate_tables()


@pytest.fixture
async def perf_app(big_instance: dict[str, int], settings: Settings) -> AsyncIterator[FastAPI]:
    from app.main import create_app

    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


class Counter:
    """SQL statements sent on the app's engine (requests here run one at a time)."""

    def __init__(self, app: FastAPI) -> None:
        self.count = 0
        engine = app.state.engine.sync_engine

        def before(*_: Any) -> None:
            self.count += 1

        event.listen(engine, "before_cursor_execute", before)


async def client_for(app: FastAPI, email: str) -> httpx.AsyncClient:
    db: AsyncSession
    async with app.state.sessionmaker() as db:
        user = await db.scalar(select(User).where(User.email == email))
    assert user is not None, email
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    response = await http.post(f"{API}/auth/dev/login", json={"user_id": str(user.id)})
    assert response.status_code == 200, response.text
    http.headers["X-CSRF-Token"] = http.cookies["soundings_csrf"]
    return http


async def statements(
    counter: Counter, http: httpx.AsyncClient, url: str, **params: Any
) -> tuple[int, httpx.Response]:
    await http.get(f"{API}{url}", params=params or None)  # warm caches (branding, plans)
    before = counter.count
    response = await http.get(f"{API}{url}", params=params or None)
    assert response.status_code == 200, (url, response.text[:300])
    return counter.count - before, response


async def first_key(http: httpx.AsyncClient, url: str, **params: Any) -> str:
    body = (await http.get(f"{API}{url}", params=params)).json()
    items = body["items"] if isinstance(body, dict) else body
    return str(items[0]["key"])


async def idea_with_evaluators(http: httpx.AsyncClient, count: int) -> str:
    """An evaluating Big Ideas idea with exactly ``count`` evaluators."""
    cursor = None
    for _ in range(20):
        params: dict[str, Any] = {"status": "evaluating", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        body = (await http.get(f"{API}/projects/{BIG_SLUG}/ideas", params=params)).json()
        for item in body["items"]:
            if item["evaluator_progress"]["total"] == count:
                return str(item["key"])
        cursor = body["next_cursor"]
    raise AssertionError(f"no idea with {count} evaluators")


async def test_no_n_plus_one_queries_at_10k(perf_app: FastAPI) -> None:
    counter = Counter(perf_app)
    alice = await client_for(perf_app, "alice@example.com")
    pat = await client_for(perf_app, PENDING_EMAIL)
    owner = await client_for(perf_app, "perf07@example.com")
    pages = {
        "list": (alice, f"/projects/{BIG_SLUG}/ideas", 10, 100),
        "list (pending evaluator)": (pat, f"/projects/{BIG_SLUG}/ideas", 10, 100),
        "board": (alice, f"/projects/{BIG_SLUG}/board", 5, 50),
        "idea.activity": (alice, "/ideas/BIG-9900/activity", 5, 50),
        "notifications.list": (pat, "/me/notifications", 5, 50),
        "admin.audit": (alice, "/admin/audit", 5, 100),
        "me.owned_ideas": (owner, "/me/owned-ideas", 5, 50),
        "moderation": (alice, "/projects/customer-innovation/moderation", 1, 50),
        "admin.users": (alice, "/admin/users", 5, 50),
    }
    found: dict[str, tuple[int, int]] = {}
    for name, (http, url, small, large) in pages.items():
        few, _ = await statements(counter, http, url, limit=small)
        many, response = await statements(counter, http, url, limit=large)
        body = response.json()
        rows = body.get("items", body.get("columns", [])) if isinstance(body, dict) else body
        assert rows, (name, "nothing listed: the test would prove nothing")
        found[name] = (few, many)
    three = await idea_with_evaluators(alice, 3)
    five = await idea_with_evaluators(alice, 5)
    found["idea.evaluations (3 vs 5 evaluators)"] = (
        (await statements(counter, alice, f"/ideas/{three}/evaluations"))[0],
        (await statements(counter, alice, f"/ideas/{five}/evaluations"))[0],
    )
    found["me.work (few vs 1,000 due)"] = (
        (await statements(counter, owner, "/me/work"))[0],
        (await statements(counter, pat, "/me/work"))[0],
    )
    print(json.dumps({"statements (small, large)": found}, indent=2))  # noqa: T201
    grows = {name: counts for name, counts in found.items() if counts[1] > counts[0]}
    assert not grows, grows


async def test_statements_per_request_stay_within_budget(perf_app: FastAPI) -> None:
    counter = Counter(perf_app)
    alice = await client_for(perf_app, "alice@example.com")
    pat = await client_for(perf_app, PENDING_EMAIL)
    due = (await pat.get(f"{API}/me/work")).json()["evaluations_due"][0]["idea"]["key"]
    calls: dict[str, tuple[httpx.AsyncClient, str, dict[str, Any]]] = {
        "auth.me": (alice, "/auth/me", {}),
        "projects.list": (alice, "/projects", {}),
        "project.get": (alice, f"/projects/{BIG_SLUG}", {}),
        "project.members": (alice, f"/projects/{BIG_SLUG}/members", {}),
        "project.tags": (alice, f"/projects/{BIG_SLUG}/tags", {}),
        "list": (pat, f"/projects/{BIG_SLUG}/ideas", {"limit": 100, "sort": "-score"}),
        "board": (pat, f"/projects/{BIG_SLUG}/board", {"limit": 50}),
        "search": (pat, "/search", {"q": "pricing"}),
        "idea.get": (pat, "/ideas/BIG-9900", {}),
        "idea.activity": (pat, "/ideas/BIG-9900/activity", {"limit": 50}),
        "idea.evaluations": (alice, "/ideas/BIG-9900/evaluations", {}),
        "idea.ai_runs": (alice, "/ideas/BIG-9900/ai-runs", {"limit": 20}),
        "evaluation.me": (pat, f"/ideas/{due}/evaluations/me", {}),
        "me.work": (pat, "/me/work", {}),
        "me.owned_ideas": (alice, "/me/owned-ideas", {"limit": 50}),
        "notifications.list": (pat, "/me/notifications", {"limit": 30}),
        "notifications.summary": (pat, "/me/notifications/summary", {}),
        "admin.audit": (alice, "/admin/audit", {"limit": 50}),
        "admin.users": (alice, "/admin/users", {"limit": 50}),
        "moderation": (alice, "/projects/customer-innovation/moderation", {"limit": 50}),
    }
    measured = {}
    for name, (http, url, params) in calls.items():
        measured[name] = (await statements(counter, http, url, **params))[0]
    print(json.dumps({"statements per request": measured}, indent=2))  # noqa: T201
    over = {
        name: (count, STATEMENT_BUDGET[name])
        for name, count in measured.items()
        if count > STATEMENT_BUDGET[name]
    }
    assert not over, over


def p95_ms(samples: list[float]) -> float:
    return quantiles(samples, n=20)[18] * 1000


async def service_times(perf_app: FastAPI) -> dict[str, float]:
    alice = await client_for(perf_app, "alice@example.com")
    pat = await client_for(perf_app, PENDING_EMAIL)
    due = (await pat.get(f"{API}/me/work")).json()["evaluations_due"][0]["idea"]["key"]
    calls: dict[str, tuple[httpx.AsyncClient, str, dict[str, Any]]] = {
        "projects.list": (pat, "/projects", {}),
        "project.get": (pat, f"/projects/{BIG_SLUG}", {}),
        "project.members": (pat, f"/projects/{BIG_SLUG}/members", {}),
        "project.tags": (pat, f"/projects/{BIG_SLUG}/tags", {}),
        "list": (pat, f"/projects/{BIG_SLUG}/ideas", {"limit": 100}),
        "list -score": (pat, f"/projects/{BIG_SLUG}/ideas", {"limit": 100, "sort": "-score"}),
        "list q": (pat, f"/projects/{BIG_SLUG}/ideas", {"limit": 100, "q": "pricing"}),
        "board": (pat, f"/projects/{BIG_SLUG}/board", {"limit": 50}),
        "board -score": (pat, f"/projects/{BIG_SLUG}/board", {"limit": 50, "sort": "-score"}),
        "search": (pat, "/search", {"q": "pricing"}),
        "search (2 letters)": (pat, "/search", {"q": "pr"}),
        "idea.get": (pat, "/ideas/BIG-9900", {}),
        "idea.activity": (pat, "/ideas/BIG-9900/activity", {"limit": 50}),
        "idea.evaluations": (alice, "/ideas/BIG-9900/evaluations", {}),
        "evaluation.me": (pat, f"/ideas/{due}/evaluations/me", {}),
        "notifications.list": (pat, "/me/notifications", {"limit": 30}),
        "admin.audit": (alice, "/admin/audit", {"limit": 50}),
        "me.work (1,000 due)": (pat, "/me/work", {}),
        "me.work (owner)": (alice, "/me/work", {}),
    }
    results: dict[str, float] = {}
    gc.collect()
    for name, (http, url, params) in calls.items():
        for _ in range(3):
            await http.get(f"{API}{url}", params=params or None)
        samples = []
        for _ in range(RUNS):
            started = time.perf_counter()
            response = await http.get(f"{API}{url}", params=params or None)
            samples.append(time.perf_counter() - started)
            assert response.status_code == 200, (name, response.text[:200])
        results[name] = round(p95_ms(samples), 1)
    return results


async def test_reads_are_within_budget_one_at_a_time(perf_app: FastAPI) -> None:
    results = await service_times(perf_app)
    print(json.dumps({"p95_ms (one request at a time)": results}, indent=2))  # noqa: T201
    over = {
        name: ms
        for name, ms in results.items()
        if ms >= READ_BUDGET_MS and not name.startswith("me.work")
    }
    assert not over, over


@pytest.mark.xfail(
    reason="B1: GET /me/work builds every evaluation due and four owned groups (~100-200 ms "
    "at 10k ideas); the sidebar fetches it on every load. Delete this mark once it is fast.",
    strict=False,
)
async def test_my_work_is_within_budget_one_at_a_time(perf_app: FastAPI) -> None:
    pat = await client_for(perf_app, PENDING_EMAIL)
    samples = []
    for n in range(RUNS + 3):
        started = time.perf_counter()
        response = await pat.get(f"{API}/me/work")
        if n >= 3:
            samples.append(time.perf_counter() - started)
        assert response.status_code == 200
    assert p95_ms(samples) < READ_BUDGET_MS / 2  # headroom for 20 people at once


async def test_writes_are_within_budget_one_at_a_time(perf_app: FastAPI) -> None:
    pat = await client_for(perf_app, PENDING_EMAIL)
    alice = await client_for(perf_app, "alice@example.com")
    due = (await pat.get(f"{API}/me/work")).json()["evaluations_due"][0]["idea"]["key"]
    project = (await alice.get(f"{API}/projects/{BIG_SLUG}")).json()
    criteria = [c["id"] for c in project["rubric"]]
    samples: dict[str, list[float]] = {}

    async def timed(name: str, call: Any) -> httpx.Response:
        started = time.perf_counter()
        response: httpx.Response = await call
        samples.setdefault(name, []).append(time.perf_counter() - started)
        assert response.status_code < 300, (name, response.status_code, response.text[:200])
        return response

    for n in range(RUNS):
        key = f"BIG-{100 + n * 37}"
        await timed(
            "comment.create",
            alice.post(f"{API}/ideas/{key}/comments", json={"body_md": "A perf check comment."}),
        )
        await timed("idea.vote", alice.put(f"{API}/ideas/{key}/vote"))
        await timed("idea.unvote", alice.delete(f"{API}/ideas/{key}/vote"))
        draft = {"scores": [{"criterion_id": criteria[0], "score": 1 + n % 5}], "submit": False}
        await timed(
            "evaluation.save_draft", pat.put(f"{API}/ideas/{due}/evaluations/me", json=draft)
        )
        made = await timed(
            "idea.create",
            alice.post(
                f"{API}/projects/{BIG_SLUG}/ideas",
                json={"title": f"Perf idea {n}", "summary": "From test_perf_large."},
            ),
        )
        await timed(
            "idea.update",
            alice.patch(f"{API}/ideas/{made.json()['key']}", json={"summary": "Edited."}),
        )
    results = {name: round(p95_ms(values), 1) for name, values in samples.items()}
    print(json.dumps({"write p95_ms (one at a time)": results}, indent=2))  # noqa: T201
    over = {name: ms for name, ms in results.items() if ms >= WRITE_BUDGET_MS}
    assert not over, over
