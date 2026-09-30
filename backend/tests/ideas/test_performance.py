"""The list and the board stay fast at 10k ideas (SPEC section 12, contract section 3.9).

Slow: excluded from the default run; ``make -C backend test-slow`` runs it. It seeds
one project with 10,000 ideas (tags, owners, a quarter of them evaluated by three
evaluators, one of whom is still pending, so blind masking is in every query),
recomputes every aggregate, then times each list and board request through the
whole app and asserts p95 < 150 ms. It also checks that the default orders are
served by the keyset indexes rather than a sequential scan of ``ideas``.

Before timing, the startup heap is frozen (``gc.freeze()``): otherwise a full
garbage collection of the ~160k objects the app imports (~80 ms on this machine)
lands on whichever request triggers it, whatever that request does. Serving
processes should do the same after startup (requested for ``app/main.py``).
"""

from __future__ import annotations

import gc
import json
import time
from collections.abc import Awaitable, Callable
from statistics import quantiles
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.enums import ProjectRole
from app.services.board import (
    IdeaFilter,
    Sort,
    board_statement,
    idea_filter_clauses,
    page_statement,
)
from app.services.scoring import recompute_aggregates
from tests.factories import criteria, make_project, make_user
from tests.ideas.conftest import API, ok

pytestmark = pytest.mark.slow

IDEAS = 10_000
RUNS = 40
BUDGET_MS = 150.0

SEED = """
INSERT INTO ideas (id, project_id, number, title, summary, description_md, status,
                   resolution, owner_id, submitted_by_id, last_activity_at, created_at,
                   updated_at, vote_count, aggregate_count, high_disagreement)
SELECT gen_random_uuid(), :project, n,
       'Idea ' || n || ' about '
           || (ARRAY['refunds','pricing','chat','kiosks','billing'])[1 + n % 5],
       'Summary ' || md5(n::text),
       '',
       (ARRAY['new','evaluating','shortlisted','proposal','closed'])[1 + n % 5],
       CASE WHEN n % 5 = 4 THEN (ARRAY['accepted','rejected','parked'])[1 + n % 3] END,
       CASE WHEN n % 3 = 0 THEN CAST(:owner AS uuid) END,
       CAST(:owner AS uuid),
       now() - n * interval '1 minute',
       now() - n * interval '1 minute',
       now(),
       n % 7, 0, false
FROM generate_series(1, :ideas) AS n
"""
TAGS = """
INSERT INTO tags (id, project_id, name, created_at)
SELECT gen_random_uuid(), :project, 'tag-' || t, now() FROM generate_series(0, 19) AS t
"""
IDEA_TAGS = """
INSERT INTO idea_tags (idea_id, tag_id)
SELECT i.id, t.id FROM ideas i JOIN tags t ON t.project_id = i.project_id
WHERE i.project_id = :project
  AND (t.name = 'tag-' || (i.number % 20) OR t.name = 'tag-' || (i.number * 7 % 20))
"""
EVALUATORS = """
INSERT INTO idea_evaluators (idea_id, user_id, invited_at)
SELECT i.id, u.id, now() FROM ideas i CROSS JOIN unnest(CAST(:users AS uuid[])) AS u(id)
WHERE i.project_id = :project AND i.number % :every = 0
"""
EVALUATIONS = """
INSERT INTO evaluations (id, idea_id, evaluator_id, status, recommendation, comment,
                         submitted_at, include_in_aggregate, created_at, updated_at)
SELECT gen_random_uuid(), ie.idea_id, ie.user_id, 'submitted', 'go', '', now(), true, now(), now()
FROM idea_evaluators ie JOIN ideas i ON i.id = ie.idea_id
WHERE i.project_id = :project AND ie.user_id = ANY(CAST(:users AS uuid[]))
"""
SCORES = """
INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, comment)
SELECT e.id, c.id, 1 + (abs(hashtext(e.id::text || c.id::text)) % 5), ''
FROM evaluations e JOIN ideas i ON i.id = e.idea_id
JOIN rubric_criteria c ON c.project_id = i.project_id AND c.archived_at IS NULL
WHERE i.project_id = :project
"""
COMMENTS = """
INSERT INTO comments (id, idea_id, author_id, body_md, created_at, updated_at)
SELECT gen_random_uuid(), i.id, CAST(:owner AS uuid), 'A comment', now(), now()
FROM ideas i WHERE i.project_id = :project AND i.number % 10 = 0
"""


def p95_ms(samples: list[float]) -> float:
    return quantiles(samples, n=20)[18] * 1000


async def timed(call: Callable[[], Awaitable[httpx.Response]]) -> list[float]:
    for _ in range(3):  # warm up caches and the connection pool
        assert (await call()).status_code == 200
    samples = []
    for _ in range(RUNS):
        start = time.perf_counter()
        response = await call()
        samples.append(time.perf_counter() - start)
        assert response.status_code == 200, response.text
    return samples


async def plan(db: AsyncSession, statement: Any) -> dict[str, Any]:
    dialect = db.get_bind().dialect
    sql = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    result = await db.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"))
    document: dict[str, Any] = result.scalar_one()[0]["Plan"]
    return document


def nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node.get("Plans", []):
        found += nodes(child)
    return found


async def test_list_and_board_at_10k_ideas(
    db_session: AsyncSession, login: Callable[[Any], Awaitable[httpx.AsyncClient]]
) -> None:
    admin = await make_user(db_session, "Ada Admin")
    owner = await make_user(db_session, "Olive Owner")
    evaluators = [await make_user(db_session, f"Evaluator {n}") for n in range(3)]
    pending = evaluators[2]  # assigned to 1,250 of the 2,500 evaluated ideas, never submits
    project = await make_project(
        db_session,
        slug="big",
        key="BIG",
        members={
            admin: ProjectRole.ADMIN,
            owner: ProjectRole.MEMBER,
            **dict.fromkeys(evaluators, ProjectRole.MEMBER),
        },
    )
    params = {"project": project.id, "owner": owner.id, "ideas": IDEAS}
    await db_session.execute(text(SEED), params)
    await db_session.execute(
        text("UPDATE projects SET next_idea_number = :next WHERE id = :project"),
        {"next": IDEAS + 1, "project": project.id},
    )
    await db_session.execute(text(TAGS), {"project": project.id})
    await db_session.execute(text(IDEA_TAGS), {"project": project.id})
    # Two evaluators submit on every 4th idea; the pending one is assigned to every 8th.
    submitters = [str(user.id) for user in evaluators[:2]]
    for users, every in ((submitters, 4), ([str(pending.id)], 8)):
        values = {"project": project.id, "users": users, "every": every}
        await db_session.execute(text(EVALUATORS), values)
    await db_session.execute(text(EVALUATIONS), {"project": project.id, "users": submitters})
    await db_session.execute(text(SCORES), {"project": project.id})
    await db_session.execute(text(COMMENTS), {"project": project.id, "owner": owner.id})
    await db_session.commit()
    assert len(await criteria(db_session, project)) == 5
    started = time.perf_counter()
    await recompute_aggregates(db_session, project_id=project.id)  # like a rubric change
    await db_session.commit()
    recompute_s = time.perf_counter() - started
    await db_session.execute(text("ANALYZE"))
    await db_session.commit()

    gc.collect()
    gc.freeze()  # see the module docstring
    viewer = await login(pending)
    first = ok(await viewer.get(f"{API}/projects/big/ideas", params={"sort": "-score"}))
    assert first["total"] == IDEAS
    hidden = [i for i in first["items"] if i["score_hidden"]]
    assert not hidden  # pending ideas sort with the unscored, after every visible score
    second_page = {"sort": "-score", "cursor": first["next_cursor"]}
    scenarios: dict[str, tuple[httpx.AsyncClient, str, dict[str, Any]]] = {
        "list -updated": (viewer, "ideas", {}),
        "list -score": (viewer, "ideas", {"sort": "-score"}),
        "list -score page 2": (viewer, "ideas", second_page),
        "list score": (viewer, "ideas", {"sort": "score"}),
        "list title": (viewer, "ideas", {"sort": "title"}),
        "list votes": (viewer, "ideas", {"sort": "-votes"}),
        "list status": (viewer, "ideas", {"status": ["evaluating", "proposal"]}),
        "list tags+owner": (viewer, "ideas", {"tag": ["tag-3", "tag-7"], "owner": str(owner.id)}),
        "list q": (viewer, "ideas", {"q": "pricing"}),
        "list key": (viewer, "ideas", {"q": "big-4242"}),
        "list disagreement": (viewer, "ideas", {"high_disagreement": "true"}),
        "list needs evaluators": (viewer, "ideas", {"needs_evaluators": "true"}),
        "board": (viewer, "board", {}),
        "board -score": (viewer, "board", {"sort": "-score"}),
        "board filtered": (viewer, "board", {"tag": ["tag-1"], "q": "refunds"}),
    }
    admin_client = await login(admin)
    scenarios["board (admin)"] = (admin_client, "board", {})
    results: dict[str, float] = {}
    for name, (client, what, query) in scenarios.items():
        url = f"{API}/projects/big/{what}"

        def call(client: httpx.AsyncClient = client, url: str = url, query: Any = query) -> Any:
            return client.get(url, params=query)

        results[name] = p95_ms(await timed(call))
    report = {name: round(ms, 1) for name, ms in results.items()}
    print(json.dumps({"p95_ms": report, "recompute_10k_s": round(recompute_s, 2)}, indent=2))  # noqa: T201
    gc.unfreeze()
    slow = {name: ms for name, ms in report.items() if ms >= BUDGET_MS}
    assert not slow, slow

    # Query plans: the default list order and each board column walk the keyset indexes.
    principal = Principal(user=pending)
    where = idea_filter_clauses(principal, project, IdeaFilter())
    listed = page_statement(principal, where, Sort("-updated"), cursor=None, limit=50)
    board = board_statement(principal, where, Sort("-updated"), limit=50)
    for statement, index in (
        (listed, "ix_ideas_project_id_last_activity_at"),
        (board, "ix_ideas_project_id_status_last_activity_at"),
    ):
        document = await plan(db_session, statement)
        used = {n.get("Index Name") for n in nodes(document)}
        assert index in used, json.dumps(document)[:2000]
        seq = [
            n
            for n in nodes(document)
            if n["Node Type"] == "Seq Scan" and n.get("Relation Name") == "ideas"
        ]
        assert not seq, json.dumps(document)[:2000]
