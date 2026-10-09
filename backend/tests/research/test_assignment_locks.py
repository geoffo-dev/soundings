"""Phase 8b lock order (contract-phase8b section 3.5, review S4), with two real sessions.

* An assignment and a deactivation of the same person serialise on the person's user
  row: never an inactive researcher, whichever commits first.
* Deactivating a researcher (projects ``FOR KEY SHARE`` by id, then the ideas
  ``FOR UPDATE`` by id) against ``replace_rubric`` on the same project (the project
  ``FOR UPDATE``, then its ideas) doesn't deadlock.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.authz import Rule, load_project
from app.config import Settings
from app.db import SessionMaker, create_engine, create_sessionmaker
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.enums import IdeaStatus, ResearchStep
from app.models.idea import Idea
from app.models.user import User
from app.schemas.admin_users import AdminUserUpdate
from app.schemas.research import ResearchAssignmentUpdate
from app.schemas.rubric import RubricUpdate
from app.services import admin_users, ideas, projects, research_assignment
from app.services.scoring import active_criteria
from tests.factories import make_idea
from tests.research.conftest import Team, set_step

OTHER_APP = "p8b-lock-order-other"


@pytest.fixture
async def other_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings, application_name=OTHER_APP)
    yield engine
    await engine.dispose()


async def _waits(engine: AsyncEngine, task: asyncio.Task[None]) -> bool:
    """Until the other session waits on a lock (True) or finished (False)."""
    for _ in range(200):
        if task.done():
            return False
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE application_name = :app AND wait_event_type = 'Lock'"
                ),
                {"app": OTHER_APP},
            )
        if waiting:
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("the other session neither finished nor waited")


async def _deactivate(sessions: SessionMaker, platform: User, target: User) -> None:
    async with sessions() as db:
        principal = Principal(user=platform)
        user = await admin_users.get_user(db, target.id)
        await admin_users.update_user(db, principal, user, AdminUserUpdate(is_active=False))
        await db.commit()


async def _assign(sessions: SessionMaker, admin: User, idea: Idea, researcher: User) -> None:
    async with sessions() as db:
        principal = Principal(user=admin)
        loaded = await ideas.load_idea(db, principal, str(idea.id), for_update=True)
        await research_assignment.set_assignment(
            db,
            principal,
            loaded.idea,
            loaded.project,
            loaded.resource,
            ResearchAssignmentUpdate(researcher_id=researcher.id, due_at=None),
        )
        await db.commit()


async def _researcher(db: AsyncSession, idea: Idea) -> object:
    row = await db.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    return row.researcher_id


async def test_an_assignment_committing_first_is_then_cleared(
    app: FastAPI, other_engine: AsyncEngine, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, owner=team.owner)
    principal = Principal(user=team.admin)
    async with app.state.sessionmaker() as db:
        loaded = await ideas.load_idea(db, principal, str(idea.id), for_update=True)
        await research_assignment.set_assignment(
            db,
            principal,
            loaded.idea,
            loaded.project,
            loaded.resource,
            ResearchAssignmentUpdate(researcher_id=team.outsider.id, due_at=None),
        )
        task = asyncio.create_task(
            _deactivate(create_sessionmaker(other_engine), team.platform, team.outsider)
        )
        assert await _waits(other_engine, task)  # on the user row we hold FOR SHARE
        await db.commit()
    await asyncio.wait_for(task, timeout=15)

    assert await _researcher(db_session, idea) is None


async def test_a_deactivation_committing_first_makes_the_assignment_422(
    app: FastAPI, other_engine: AsyncEngine, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, owner=team.owner)
    principal = Principal(user=team.platform)
    async with app.state.sessionmaker() as db:
        user = await admin_users.get_user(db, team.outsider.id)
        await admin_users.update_user(db, principal, user, AdminUserUpdate(is_active=False))
        task = asyncio.create_task(
            _assign(create_sessionmaker(other_engine), team.admin, idea, team.outsider)
        )
        assert await _waits(other_engine, task)
        await db.commit()
    with pytest.raises(ProblemError) as refused:
        await asyncio.wait_for(task, timeout=15)

    assert (refused.value.status, refused.value.code) == (422, "researcher_not_eligible")
    assert await _researcher(db_session, idea) is None


async def _replace_rubric(sessions: SessionMaker, admin: User, slug: str) -> None:
    async with sessions() as db:
        principal = Principal(user=admin)
        project, _ = await load_project(
            db, principal, slug, Rule.PROJECT_EDIT_RUBRIC, for_update=True
        )
        current = (await active_criteria(db, [project.id]))[project.id]
        body = RubricUpdate.model_validate(
            {
                "criteria": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "description": c.description,
                        "weight": float(c.weight) + 0.5,
                        "inverted": c.inverted,
                        "guidance": c.guidance,
                    }
                    for c in current
                ]
            }
        )
        await projects.replace_rubric(db, principal, project, body)
        await db.commit()


@pytest.mark.parametrize("deactivation_first", [True, False])
async def test_deactivation_and_a_rubric_change_dont_deadlock(
    app: FastAPI,
    other_engine: AsyncEngine,
    team: Team,
    db_session: AsyncSession,
    deactivation_first: bool,
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    made = [
        await make_idea(db_session, team.project, owner=team.owner, status=IdeaStatus.RESEARCH)
        for _ in range(3)
    ]
    for idea in made:
        await db_session.execute(
            update(Idea)
            .where(Idea.id == idea.id)
            .values(
                researcher_id=team.member.id,
                research_assigned_at=utcnow() - timedelta(days=1),
            )
        )
    await db_session.commit()
    other = create_sessionmaker(other_engine)
    if deactivation_first:
        async with app.state.sessionmaker() as db:
            user = await admin_users.get_user(db, team.member.id)
            await admin_users.update_user(
                db, Principal(user=team.platform), user, AdminUserUpdate(is_active=False)
            )
            task = asyncio.create_task(_replace_rubric(other, team.admin, team.slug))
            await _waits(other_engine, task)
            await db.commit()
    else:
        principal = Principal(user=team.admin)
        async with app.state.sessionmaker() as db:
            project, _ = await load_project(
                db, principal, team.slug, Rule.PROJECT_EDIT_RUBRIC, for_update=True
            )
            task = asyncio.create_task(_deactivate(other, team.platform, team.member))
            await _waits(other_engine, task)
            current = (await active_criteria(db, [project.id]))[project.id]
            await projects.replace_rubric(
                db,
                principal,
                project,
                RubricUpdate.model_validate(
                    {
                        "criteria": [
                            {
                                "id": c.id,
                                "name": c.name,
                                "description": c.description,
                                "weight": float(c.weight) + 1,
                                "inverted": c.inverted,
                                "guidance": c.guidance,
                            }
                            for c in current
                        ]
                    }
                ),
            )
            await db.commit()
    await asyncio.wait_for(task, timeout=15)

    for idea in made:
        assert await _researcher(db_session, idea) is None
