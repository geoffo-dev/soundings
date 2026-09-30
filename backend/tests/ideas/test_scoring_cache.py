"""The cached aggregate on ``ideas`` (contract section 3.8): it always equals the pure
aggregate of the stored evaluations, also under concurrent submissions."""

from __future__ import annotations

import asyncio
import random  # seeded, for reproducible cases (not security)
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.scoring import Criterion, ScoredEvaluation, aggregate
from app.models.base import utcnow
from app.models.enums import EvaluatorState, ProjectRole, Recommendation
from app.models.idea import Idea
from app.services.scoring import recompute_aggregates
from tests.conftest import Login
from tests.factories import add_evaluator, criteria, make_idea, make_project, make_user
from tests.ideas.conftest import API, AsUser, Team, full_scores, ok


async def cached(db: AsyncSession, idea: Idea) -> tuple[Decimal | None, int, bool]:
    fresh = await db.get(Idea, idea.id, populate_existing=True)
    assert fresh is not None
    return fresh.aggregate_score, fresh.aggregate_count, fresh.high_disagreement


async def test_concurrent_submissions_all_count(
    login: Login, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    for user in team.evaluators:
        await add_evaluator(db_session, idea, user)
    clients = [await login(user) for user in team.evaluators]
    bodies = [
        {"scores": full_scores(team, value), "recommendation": "go", "submit": True}
        for value in (1, 3, 5)
    ]

    responses = await asyncio.gather(
        *(
            http.put(f"{API}/ideas/{idea.id}/evaluations/me", json=body)
            for http, body in zip(clients, bodies, strict=True)
        )
    )

    assert [r.status_code for r in responses] == [200, 200, 200]
    # Adjusted 1,1,5,1,5 / 3,3,3,3,3 / 5,5,1,5,1 -> every criterion averages 3.
    assert await cached(db_session, idea) == (Decimal("3.0"), 3, True)


async def test_cache_matches_the_pure_aggregate(api: AsUser, db_session: AsyncSession) -> None:
    rng = random.Random(42)  # noqa: S311
    people = [await make_user(db_session, f"Person {n}") for n in range(6)]
    project = await make_project(db_session, members=dict.fromkeys(people, ProjectRole.MEMBER))
    rubric = await criteria(db_session, project)
    for criterion in rubric:
        criterion.weight = Decimal(rng.randint(1, 1000)) / 100
    await db_session.commit()
    active = rubric[:1] + rubric[2:]  # Feasibility is archived after scoring: must not count
    expected: dict[Any, Any] = {}
    for n in range(12):
        idea = await make_idea(db_session, project, title=f"Idea {n}")
        included: list[ScoredEvaluation] = []
        for person in rng.sample(people, rng.randint(0, 5)):
            state = rng.choice(
                [EvaluatorState.INVITED, EvaluatorState.DRAFT, *[EvaluatorState.SUBMITTED] * 3]
            )
            scores = {c.name: rng.randint(1, 5) for c in rubric}
            include = rng.random() > 0.2
            recommendation = rng.choice(list(Recommendation))
            await add_evaluator(
                db_session,
                idea,
                person,
                state=state,
                scores=scores,
                recommendation=recommendation,
                include_in_aggregate=include,
            )
            if state is EvaluatorState.SUBMITTED and include:
                included.append(
                    ScoredEvaluation(
                        scores={c.id: scores[c.name] for c in rubric},
                        recommendation=recommendation,
                    )
                )
        result = aggregate([Criterion(c.id, c.weight, c.inverted) for c in active], included)
        expected[idea.id] = (
            (None, 0, False)
            if result is None
            else (result.overall, result.count, result.high_disagreement)
        )

    rubric[1].archived_at = utcnow()
    await recompute_aggregates(db_session, project_id=project.id)
    await db_session.commit()

    viewer = await api(people[0])
    page = ok(await viewer.get(f"/projects/{project.slug}/ideas", limit=50))
    for item in page["items"]:
        fresh = await db_session.get(Idea, item["id"], populate_existing=True)
        assert fresh is not None
        cached = (fresh.aggregate_score, fresh.aggregate_count, fresh.high_disagreement)
        assert cached == expected[fresh.id]
        if item["score_hidden"]:
            continue
        detail = ok(await viewer.get(f"/ideas/{item['id']}"))
        overall, count, flag = expected[fresh.id]
        if count:
            assert detail["aggregate"]["overall"] == float(overall)
            assert detail["aggregate"]["count"] == count
            assert detail["aggregate"]["high_disagreement"] is flag
            assert item["score"] == {"overall": float(overall), "count": count}
        else:
            assert detail["aggregate"] is None
            assert item["score"] is None
