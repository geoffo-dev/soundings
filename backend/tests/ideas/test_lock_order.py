"""Replacing the rubric while someone saves an evaluation (code review F2).

A rubric replacement locks the project row and then rewrites every idea's cached
aggregate; an evaluation save locks the idea row and then (a first submission's
activity event, the scores' foreign keys) needs the project row. Both must lock in
the same order, project then idea, or the pair deadlocks, the recompute overwrites
the idea with an aggregate read before the save committed, or a criterion the save
just scored is deleted under it.

These tests drive the service functions with two real sessions (as the routes do) and
pause the evaluation save between loading the idea and saving, while the rubric
replacement runs in the second session.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.authz import Rule, load_project
from app.config import Settings
from app.db import SessionMaker, create_engine, create_sessionmaker
from app.domain.principal import Principal
from app.models.enums import EvaluatorState, Recommendation
from app.models.evaluation import EvaluationScore
from app.models.idea import Idea
from app.models.project import RubricCriterion
from app.models.user import User
from app.schemas.evaluations import MyEvaluationIn
from app.schemas.rubric import RubricUpdate
from app.services import evaluations, ideas, projects
from app.services.scoring import active_criteria, recompute_aggregates
from tests.factories import add_evaluator, make_idea
from tests.ideas.conftest import Team

RUBRIC_APP = "p1-lock-order-rubric"


@pytest.fixture
async def rubric_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A second engine, so the rubric replacement's backend is easy to spot."""
    engine = create_engine(settings, application_name=RUBRIC_APP)
    yield engine
    await engine.dispose()


async def _replace_rubric(
    sessionmaker: SessionMaker, admin: User, slug: str, change: dict[str, dict[str, Any]]
) -> None:
    """``PUT /projects/{slug}/rubric`` as the route runs it; ``change`` maps criterion
    names to new field values, ``{"drop": ...}`` removes that criterion."""
    async with sessionmaker() as db:
        principal = Principal(user=admin)
        project, _ = await load_project(
            db, principal, slug, Rule.PROJECT_EDIT_RUBRIC, for_update=True
        )
        current = (await active_criteria(db, [project.id]))[project.id]
        items = [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "weight": float(c.weight),
                "inverted": c.inverted,
                "guidance": c.guidance,
            }
            | {k: v for k, v in change.get(c.name, {}).items() if k != "drop"}
            for c in current
            if "drop" not in change.get(c.name, {})
        ]
        await projects.replace_rubric(
            db, principal, project, RubricUpdate.model_validate({"criteria": items})
        )
        await db.commit()


async def _blocked_or_done(engine: AsyncEngine, task: asyncio.Task[None]) -> bool:
    """Wait until the rubric task waits on a lock (True) or finished (False)."""
    for _ in range(200):
        if task.done():
            return False
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE application_name = :app AND wait_event_type = 'Lock'"
                ),
                {"app": RUBRIC_APP},
            )
        if waiting:
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("the rubric replacement neither finished nor waited")


async def _cache_is_right(app: FastAPI, idea: Idea) -> tuple[Decimal | None, int]:
    """The cached aggregate, after checking a fresh recompute would not change it (in
    a new session: another one may hold criteria loaded before the change)."""
    async with app.state.sessionmaker() as db:
        before = await db.get(Idea, idea.id)
        assert before is not None
        cached = (before.aggregate_score, before.aggregate_count, before.high_disagreement)
        await recompute_aggregates(db, idea_ids=[idea.id])
        after = await db.get(Idea, idea.id, populate_existing=True)
        assert after is not None
        assert (after.aggregate_score, after.aggregate_count, after.high_disagreement) == cached
        await db.rollback()
    return cached[0], cached[1]


def _body(
    team: Team, score: int, *, submit: bool = True, only: str | None = None
) -> MyEvaluationIn:
    return MyEvaluationIn.model_validate(
        {
            "scores": [
                {"criterion_id": c.id, "score": score}
                for c in team.rubric
                if only is None or c.name == only
            ],
            "recommendation": "go" if submit else None,
            "submit": submit,
        }
    )


@pytest.fixture
async def scored(team: Team, db_session: AsyncSession) -> Idea:
    """An idea with two submitted evaluations and a third evaluator still to go."""
    idea = await make_idea(db_session, team.project, owner=team.owner)
    # Scores differ per criterion, so a weight change changes the aggregate.
    for evaluator, first in zip(team.evaluators[:2], (1, 3), strict=True):
        await add_evaluator(
            db_session,
            idea,
            evaluator,
            state=EvaluatorState.SUBMITTED,
            scores={c.name: 1 + (first + n) % 5 for n, c in enumerate(team.rubric)},
            recommendation=Recommendation.GO,
        )
    await add_evaluator(db_session, idea, team.evaluators[2])
    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.commit()
    return idea


async def _save_during_rubric_change(
    app: FastAPI,
    engine: AsyncEngine,
    team: Team,
    idea: Idea,
    evaluator: User,
    body: MyEvaluationIn,
    change: dict[str, dict[str, Any]],
    *,
    save_first: bool = False,
) -> None:
    """Load the idea for the save, start the rubric replacement, let it run until it
    waits (or finishes), save, commit. ``save_first`` saves before the replacement
    starts (the scores are written but not committed while it runs)."""
    principal = Principal(user=evaluator)
    rubric_sessions = create_sessionmaker(engine)
    async with app.state.sessionmaker() as db:
        loaded = await ideas.load_idea(db, principal, str(idea.id), for_update=True)
        if save_first:
            await evaluations.save_my_evaluation(db, principal, loaded, body)
        task = asyncio.create_task(_replace_rubric(rubric_sessions, team.admin, team.slug, change))
        try:
            await _blocked_or_done(engine, task)
            if not save_first:
                await evaluations.save_my_evaluation(db, principal, loaded, body)
            await db.commit()
        finally:
            await asyncio.wait_for(task, timeout=15)


async def test_first_submission_during_a_rubric_change_does_not_deadlock(
    app: FastAPI,
    rubric_engine: AsyncEngine,
    team: Team,
    scored: Idea,
    db_session: AsyncSession,
) -> None:
    # Before the fix: the replacement held the project and waited for the idea; the
    # submission held the idea and its activity event waited for the project.
    await _save_during_rubric_change(
        app,
        rubric_engine,
        team,
        scored,
        team.evaluators[2],
        _body(team, 5),
        {team.rubric[0].name: {"weight": 9.5}},
    )

    _, count = await _cache_is_right(app, scored)
    assert count == 3


async def test_editing_a_submission_during_a_rubric_change_keeps_the_cache_right(
    app: FastAPI,
    rubric_engine: AsyncEngine,
    team: Team,
    scored: Idea,
    db_session: AsyncSession,
) -> None:
    # Before the fix: the replacement recomputed from the evaluations as they were
    # before the edit committed, then overwrote the idea's cached aggregate.
    before, _ = await _cache_is_right(app, scored)

    await _save_during_rubric_change(
        app,
        rubric_engine,
        team,
        scored,
        team.evaluators[1],
        _body(team, 1),  # all 1s now
        {team.rubric[0].name: {"weight": 9.5}},
        save_first=True,
    )

    after, count = await _cache_is_right(app, scored)
    assert count == 2
    assert after is not None
    assert before is not None
    assert after < before


async def test_a_criterion_scored_by_a_draft_during_its_removal_is_archived(
    app: FastAPI,
    rubric_engine: AsyncEngine,
    team: Team,
    db_session: AsyncSession,
) -> None:
    # Before the fix: the replacement deleted the (so far unscored) criterion and the
    # draft's deferred foreign key failed at commit.
    idea = await make_idea(db_session, team.project, owner=team.owner)
    await add_evaluator(db_session, idea, team.evaluators[0])
    dropped = team.rubric[-1]

    await _save_during_rubric_change(
        app,
        rubric_engine,
        team,
        idea,
        team.evaluators[0],
        _body(team, 3, submit=False, only=dropped.name),
        {dropped.name: {"drop": True}},
        save_first=True,
    )

    criterion = await db_session.get(RubricCriterion, dropped.id, populate_existing=True)
    assert criterion is not None
    assert criterion.archived_at is not None
    kept = await db_session.scalars(
        select(EvaluationScore.score).where(EvaluationScore.criterion_id == dropped.id)
    )
    assert list(kept) == [3]


async def test_a_save_waits_for_a_rubric_change_in_progress(
    app: FastAPI,
    rubric_engine: AsyncEngine,
    team: Team,
    scored: Idea,
    db_session: AsyncSession,
) -> None:
    """The other order: the replacement locked the project first; the save waits for
    it, then scores against the new rubric."""
    rubric_sessions = create_sessionmaker(rubric_engine)
    async with rubric_sessions() as db:
        principal = Principal(user=team.admin)
        project, _ = await load_project(
            db, principal, team.slug, Rule.PROJECT_EDIT_RUBRIC, for_update=True
        )

        async def submit() -> None:
            async with app.state.sessionmaker() as other:
                evaluator = Principal(user=team.evaluators[2])
                loaded = await ideas.load_idea(other, evaluator, str(scored.id), for_update=True)
                await evaluations.save_my_evaluation(other, evaluator, loaded, _body(team, 5))
                await other.commit()

        task = asyncio.create_task(submit())
        await asyncio.sleep(0.3)
        assert not task.done()  # waiting for the project row
        current = (await active_criteria(db, [project.id]))[project.id]
        items = [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "weight": 9.5 if n == 0 else float(c.weight),
                "inverted": c.inverted,
                "guidance": c.guidance,
            }
            for n, c in enumerate(current)
        ]
        await projects.replace_rubric(
            db, principal, project, RubricUpdate.model_validate({"criteria": items})
        )
        await db.commit()
        await asyncio.wait_for(task, timeout=15)

    _, count = await _cache_is_right(app, scored)
    assert count == 3


async def test_writes_to_different_ideas_of_a_project_do_not_wait_for_each_other(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    """The project lock is FOR KEY SHARE: idea writes don't serialise per project."""
    first = await make_idea(db_session, team.project)
    second = await make_idea(db_session, team.project)
    principal = Principal(user=team.admin)
    async with app.state.sessionmaker() as one, app.state.sessionmaker() as two:
        await ideas.load_idea(one, principal, str(first.id), for_update=True)
        loaded = await asyncio.wait_for(
            ideas.load_idea(two, principal, str(second.id), for_update=True), timeout=2
        )
        assert loaded.idea.id == second.id
        await two.rollback()
        await one.rollback()
