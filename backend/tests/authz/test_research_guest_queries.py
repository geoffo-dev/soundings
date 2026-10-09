"""Phase 8b: the policy in SQL agrees with :func:`app.authz.authorize` for researchers
(contract-phase8b section 4.5, review M1): :func:`researched_ideas`, the project mask in
:func:`score_visible` and :func:`evaluation_visible`, with guest rows (R in a private
project, NMi + Rsr in an internal one, a stale owner who lost their role and researches
their own idea) and every way an assignment isn't live."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    Rule,
    authorize,
    evaluation_visible,
    idea_resource,
    listed_ideas,
    researched_ideas,
    researcher_live,
    score_visible,
    visible_aggregate_score,
)
from app.domain.principal import ApiKeyScope, Principal
from app.models.enums import (
    EvaluatorState,
    HoldReason,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    ResearchStep,
)
from app.models.idea import Idea
from app.models.project import Project
from app.models.user import User
from tests.factories import add_evaluator, make_idea, make_project, make_user, set_researcher


@dataclass
class World:
    users: dict[str, User]
    ideas: dict[str, Idea]
    projects: dict[str, Project]


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    names = ["guest", "insider", "stale", "member", "evaluator", "other", "outsider", "agent"]
    users = {name: await make_user(db_session, name.title()) for name in names}
    users["agent"].is_service_account = True
    await db_session.commit()
    step = ResearchStep.BEFORE_EVALUATION
    private = await make_project(
        db_session,
        key="PRV",
        research_step=step,
        members={
            users["member"]: ProjectRole.MEMBER,
            users["evaluator"]: ProjectRole.MEMBER,
            users["other"]: ProjectRole.MEMBER,
            users["agent"]: ProjectRole.MEMBER,
        },
    )
    internal = await make_project(
        db_session, key="INT", visibility=ProjectVisibility.INTERNAL, research_step=step
    )
    archived = await make_project(db_session, key="ARC", research_step=step, archived=True)
    off = await make_project(db_session, key="OFF")
    ideas: dict[str, Idea] = {}
    ideas["guest"] = await make_idea(db_session, private, title="Guest", status=IdeaStatus.RESEARCH)
    for name, state in [("evaluator", EvaluatorState.INVITED), ("other", EvaluatorState.SUBMITTED)]:
        await add_evaluator(db_session, ideas["guest"], users[name], state=state)
    await db_session.execute(
        update(Idea)
        .where(Idea.id == ideas["guest"].id)
        .values(aggregate_score=Decimal("4.0"), aggregate_count=1, high_disagreement=True)
    )
    ideas["stale"] = await make_idea(db_session, private, title="Stale", owner=users["stale"])
    ideas["member"] = await make_idea(
        db_session, private, title="Member", status=IdeaStatus.RESEARCH
    )
    ideas["plain"] = await make_idea(db_session, private, title="Plain")
    ideas["closed"] = await make_idea(db_session, private, title="Closed", status=IdeaStatus.CLOSED)
    ideas["held"] = await make_idea(db_session, private, title="Held")
    await db_session.execute(
        update(Idea).where(Idea.id == ideas["held"].id).values(held_for=HoldReason.MODERATION)
    )
    ideas["internal"] = await make_idea(db_session, internal, title="Internal")
    ideas["archived"] = await make_idea(db_session, archived, title="Archived")
    ideas["off"] = await make_idea(db_session, off, title="Off")
    ideas["agent"] = await make_idea(db_session, private, title="Agent's")
    for idea, who in [
        ("guest", "guest"),
        ("stale", "stale"),
        ("member", "member"),
        ("closed", "guest"),
        ("held", "guest"),
        ("internal", "insider"),
        ("archived", "guest"),
        ("off", "guest"),
        ("agent", "agent"),
    ]:
        await set_researcher(db_session, ideas[idea], users[who])
    return World(
        users=users,
        ideas=ideas,
        projects={"private": private, "internal": internal, "archived": archived, "off": off},
    )


def as_principal(user: User, scopes: set[ApiKeyScope] | None = None) -> Principal:
    if scopes is None:
        return Principal(user=user)
    return Principal(user=user, auth="api_key", scopes=frozenset(scopes))


WHO = ["guest", "insider", "stale", "member", "evaluator", "other", "outsider", "agent"]
EXPECTED = {
    "guest": {"Guest"},  # closed, held, archived, step off: not live
    "insider": {"Internal"},
    "stale": {"Stale"},
    "member": {"Member"},
    "evaluator": set(),
    "other": set(),
    "outsider": set(),
    "agent": set(),  # c23: never an agent
}


@pytest.mark.parametrize("who", WHO)
async def test_researched_ideas(db_session: AsyncSession, world: World, who: str) -> None:
    principal = as_principal(world.users[who])

    found = set(await db_session.scalars(select(Idea.title).where(researched_ideas(principal))))

    assert found == EXPECTED[who]


@pytest.mark.parametrize("who", WHO)
async def test_researched_ideas_agree_with_the_policy(
    db_session: AsyncSession, world: World, who: str
) -> None:
    principal = as_principal(world.users[who])
    rows = await db_session.execute(
        select(Idea, Project, researched_ideas(principal)).join(
            Project, Project.id == Idea.project_id
        )
    )

    for idea, project, in_sql in rows:
        resource = await idea_resource(db_session, principal, idea, project)
        live = researcher_live(principal, resource) and idea.held_for is None
        assert bool(in_sql) is live, (who, idea.title)  # NULL where nobody is assigned
        if in_sql:
            assert authorize(principal, Rule.IDEA_VIEW, resource).allowed, (who, idea.title)


@pytest.mark.parametrize("who", WHO)
async def test_score_and_evaluation_masks_match_the_policy(
    db_session: AsyncSession, world: World, who: str
) -> None:
    """Every idea a list may show a person (``listed_ideas | researched_ideas``): the SQL
    masks equal the policy's ``score.view_aggregate`` and ``evaluation.view_own``."""
    principal = as_principal(world.users[who])
    rows = await db_session.execute(
        select(Idea, Project, score_visible(principal), evaluation_visible(principal))
        .join(Project, Project.id == Idea.project_id)
        .where(or_(listed_ideas(principal), researched_ideas(principal)))
    )

    checked = 0
    for idea, project, scores_in_sql, evaluation_in_sql in rows:
        resource = await idea_resource(db_session, principal, idea, project)
        assert scores_in_sql is authorize(principal, Rule.SCORE_VIEW_AGGREGATE, resource).allowed
        assert evaluation_in_sql is authorize(principal, Rule.EVALUATION_VIEW_OWN, resource).allowed
        checked += 1
    assert checked or who in {"outsider", "evaluator", "other"} or not EXPECTED[who]


async def test_a_guest_never_gets_the_score_in_sql(db_session: AsyncSession, world: World) -> None:
    guest = as_principal(world.users["guest"])

    score = await db_session.scalar(
        select(visible_aggregate_score(guest)).where(Idea.id == world.ideas["guest"].id)
    )

    assert score is None


@pytest.mark.parametrize("scopes", [{"read"}, {"read", "write"}])
async def test_a_key_needs_read(
    db_session: AsyncSession, world: World, scopes: set[ApiKeyScope]
) -> None:
    key = as_principal(world.users["guest"], scopes)
    no_read = as_principal(world.users["guest"], {"mcp"})

    assert set(await db_session.scalars(select(Idea.title).where(researched_ideas(key)))) == {
        "Guest"
    }
    assert not set(await db_session.scalars(select(Idea.title).where(researched_ideas(no_read))))


async def test_a_restricted_key_narrows_researched_ideas(
    db_session: AsyncSession, world: World
) -> None:
    user = world.users["guest"]
    here = Principal(
        user=user, auth="api_key", scopes=frozenset({"read"}),
        project_ids=frozenset({world.projects["private"].id}),
    )  # fmt: skip
    elsewhere = Principal(
        user=user, auth="api_key", scopes=frozenset({"read"}),
        project_ids=frozenset({world.projects["internal"].id}),
    )  # fmt: skip

    assert set(await db_session.scalars(select(Idea.title).where(researched_ideas(here)))) == {
        "Guest"
    }
    assert not set(await db_session.scalars(select(Idea.title).where(researched_ideas(elsewhere))))
