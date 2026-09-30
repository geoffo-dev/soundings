"""The policy in SQL (app.authz.queries) and the loaders, against real Postgres.

The SQL filters must agree with :func:`app.authz.authorize` for every principal and
idea; roles come from the ``project_effective_roles`` view.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    Rule,
    admin_count,
    authorize,
    effective_role_of,
    effective_roles_of,
    evaluator_state,
    idea_resource,
    score_visible,
    viewable_ideas,
    visible_aggregate_score,
    visible_high_disagreement,
    visible_projects,
)
from app.domain.principal import ApiKeyScope, Principal
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility
from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from app.models.user import User
from tests.factories import add_evaluator, make_idea, make_project, make_user


@dataclass
class World:
    users: dict[str, User]
    projects: dict[str, Project]
    ideas: dict[str, Idea]


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    """Two projects and an archived one; one idea with evaluators in every state."""
    names = [
        "platform", "admin", "member", "viewer", "outsider", "pending", "drafting",
        "submitted", "other", "admin_pending", "demoted_pending",
    ]  # fmt: skip
    users = {name: await make_user(db_session, name.title()) for name in names}
    users["platform"].is_platform_admin = True
    await db_session.commit()
    members = {
        users["admin"]: ProjectRole.ADMIN,
        users["member"]: ProjectRole.MEMBER,
        users["viewer"]: ProjectRole.VIEWER,
        users["pending"]: ProjectRole.MEMBER,
        users["drafting"]: ProjectRole.MEMBER,
        users["submitted"]: ProjectRole.MEMBER,
        users["other"]: ProjectRole.MEMBER,
        users["admin_pending"]: ProjectRole.ADMIN,
        users["demoted_pending"]: ProjectRole.VIEWER,
    }
    private = await make_project(db_session, slug="private", key="PRV", members=members)
    internal = await make_project(
        db_session,
        slug="internal",
        key="INT",
        visibility=ProjectVisibility.INTERNAL,
        members={users["admin"]: ProjectRole.ADMIN},
    )
    archived = await make_project(
        db_session, slug="archived", key="ARC", members={users["member"]: ProjectRole.MEMBER}
    )
    scored = await make_idea(db_session, private, title="Scored", status=IdeaStatus.EVALUATING)
    for name, state in [
        ("pending", EvaluatorState.INVITED),
        ("drafting", EvaluatorState.DRAFT),
        ("submitted", EvaluatorState.SUBMITTED),
        ("other", EvaluatorState.SUBMITTED),
        ("admin_pending", EvaluatorState.INVITED),
        ("demoted_pending", EvaluatorState.INVITED),
    ]:
        scores = {"Value": 5 if name == "submitted" else 1}
        await add_evaluator(db_session, scored, users[name], state=state, scores=scores)
    await db_session.execute(
        update(Idea)
        .where(Idea.id == scored.id)
        .values(aggregate_score=Decimal("3.0"), aggregate_count=2, high_disagreement=True)
    )
    unscored = await make_idea(db_session, private, title="Unscored")
    lower = await make_idea(db_session, private, title="Lower")
    await db_session.execute(
        update(Idea).where(Idea.id == lower.id).values(aggregate_score=Decimal("2.0"))
    )
    open_idea = await make_idea(db_session, internal, title="Internal idea")
    old = await make_idea(db_session, archived, title="Archived idea")
    await db_session.commit()
    return World(
        users=users,
        projects={"private": private, "internal": internal, "archived": archived},
        ideas={
            "scored": scored,
            "unscored": unscored,
            "lower": lower,
            "internal": open_idea,
            "archived": old,
        },
    )


def as_principal(
    user: User, *, scopes: set[ApiKeyScope] | None = None, projects: set[UUID] | None = None
) -> Principal:
    if scopes is None:
        return Principal(user=user)
    return Principal(
        user=user,
        auth="api_key",
        scopes=frozenset(scopes),
        project_ids=None if projects is None else frozenset(projects),
    )


async def visible_project_slugs(db: AsyncSession, principal: Principal | None) -> set[str]:
    return set(await db.scalars(select(Project.slug).where(visible_projects(principal))))


async def viewable_titles(db: AsyncSession, principal: Principal | None) -> set[str]:
    return set(await db.scalars(select(Idea.title).where(viewable_ideas(principal))))


ALL_IDEAS = {"Scored", "Unscored", "Lower", "Internal idea", "Archived idea"}
PRIVATE_IDEAS = {"Scored", "Unscored", "Lower"}


@pytest.mark.parametrize(
    ("who", "projects", "ideas"),
    [
        ("platform", {"private", "internal", "archived"}, ALL_IDEAS),
        ("admin", {"private", "internal"}, PRIVATE_IDEAS | {"Internal idea"}),
        ("member", {"private", "internal", "archived"}, ALL_IDEAS),
        ("viewer", {"private", "internal"}, PRIVATE_IDEAS | {"Internal idea"}),
        ("outsider", {"internal"}, {"Internal idea"}),
    ],
)
async def test_visible_projects_and_ideas(
    db_session: AsyncSession, world: World, who: str, projects: set[str], ideas: set[str]
) -> None:
    principal = as_principal(world.users[who])

    assert await visible_project_slugs(db_session, principal) == projects
    assert await viewable_titles(db_session, principal) == ideas


async def test_anonymous_sees_nothing(db_session: AsyncSession, world: World) -> None:
    assert await visible_project_slugs(db_session, None) == set()
    assert await viewable_titles(db_session, None) == set()


async def test_api_key_narrowing(db_session: AsyncSession, world: World) -> None:
    platform = world.users["platform"]
    internal_only = as_principal(
        platform, scopes={"read"}, projects={world.projects["internal"].id}
    )
    write_only = as_principal(platform, scopes={"write"})

    assert await visible_project_slugs(db_session, internal_only) == {"internal"}
    assert await viewable_titles(db_session, internal_only) == {"Internal idea"}
    assert await visible_project_slugs(db_session, write_only) == set()  # listing needs read


async def test_removing_a_membership_removes_access_immediately(
    db_session: AsyncSession, world: World
) -> None:
    viewer = as_principal(world.users["viewer"])
    await db_session.execute(
        delete(ProjectMember).where(ProjectMember.user_id == world.users["viewer"].id)
    )
    await db_session.commit()

    assert await visible_project_slugs(db_session, viewer) == {"internal"}


# --- Blind evaluation in SQL agrees with the policy -----------------------------------------
@pytest.mark.parametrize(
    "who",
    [
        "platform", "admin", "member", "viewer", "outsider", "pending", "drafting",
        "submitted", "other", "admin_pending", "demoted_pending",
    ],
)  # fmt: skip
async def test_score_visible_matches_the_policy(
    db_session: AsyncSession, world: World, who: str
) -> None:
    principal = as_principal(world.users[who])
    rows = await db_session.execute(
        select(Idea, Project, score_visible(principal))
        .join(Project, Project.id == Idea.project_id)
        .where(viewable_ideas(principal))
    )

    checked = 0
    for idea, project, visible_in_sql in rows:
        resource = await idea_resource(db_session, principal, idea, project)
        decision = authorize(principal, Rule.SCORE_VIEW_AGGREGATE, resource)
        others = authorize(principal, Rule.EVALUATION_VIEW_OTHERS, resource)
        assert visible_in_sql is decision.allowed is others.allowed, (who, idea.title)
        checked += 1
    assert checked


@pytest.mark.parametrize(
    ("who", "hidden"),
    [
        ("pending", True),  # invited, nothing saved
        ("drafting", True),  # a draft is not a submission
        ("admin_pending", True),  # no role lifts it
        ("demoted_pending", True),  # a demoted evaluator stays blind
        ("submitted", False),
        ("other", False),
        ("admin", False),
        ("viewer", False),
        ("platform", False),
    ],
)
async def test_masked_score_columns(
    db_session: AsyncSession, world: World, who: str, hidden: bool
) -> None:
    principal = as_principal(world.users[who])
    score, flag = (
        await db_session.execute(
            select(visible_aggregate_score(principal), visible_high_disagreement(principal)).where(
                Idea.id == world.ideas["scored"].id
            )
        )
    ).one()

    assert (score, flag) == ((None, False) if hidden else (Decimal("3.0"), True))


async def test_hidden_scores_sort_with_the_unscored(db_session: AsyncSession, world: World) -> None:
    async def titles(principal: Principal) -> list[str]:
        masked = visible_aggregate_score(principal)
        rows = await db_session.scalars(
            select(Idea.title)
            .where(Idea.project_id == world.projects["private"].id)
            .order_by(masked.desc().nulls_last(), Idea.title)
        )
        return list(rows)

    assert await titles(as_principal(world.users["member"])) == ["Scored", "Lower", "Unscored"]
    # For a pending evaluator the idea sorts as if it had no score (after every scored one).
    assert await titles(as_principal(world.users["pending"])) == ["Lower", "Scored", "Unscored"]


# --- Loaders --------------------------------------------------------------------------------
async def test_loaders_read_roles_from_the_view(db_session: AsyncSession, world: World) -> None:
    private = world.projects["private"]
    users = world.users

    assert await effective_role_of(db_session, users["admin"].id, private.id) is ProjectRole.ADMIN
    assert await effective_role_of(db_session, users["outsider"].id, private.id) is None
    assert await effective_roles_of(
        db_session, private.id, [users["viewer"].id, users["outsider"].id, users["viewer"].id]
    ) == {users["viewer"].id: ProjectRole.VIEWER, users["outsider"].id: None}
    assert await admin_count(db_session, private.id) == 2


async def test_evaluator_state(db_session: AsyncSession, world: World) -> None:
    idea = world.ideas["scored"]
    users = world.users

    assert await evaluator_state(db_session, idea.id, users["pending"].id) is EvaluatorState.INVITED
    assert await evaluator_state(db_session, idea.id, users["drafting"].id) is EvaluatorState.DRAFT
    assert (
        await evaluator_state(db_session, idea.id, users["submitted"].id)
        is EvaluatorState.SUBMITTED
    )
    assert await evaluator_state(db_session, idea.id, users["member"].id) is None


async def test_idea_resource_facts(db_session: AsyncSession, world: World) -> None:
    principal = as_principal(world.users["drafting"])
    idea, project = world.ideas["scored"], world.projects["private"]

    resource = await idea_resource(db_session, principal, idea, project)

    assert resource.role is ProjectRole.MEMBER
    assert resource.idea is not None
    assert resource.idea.my_evaluation is EvaluatorState.DRAFT
    assert resource.idea.pending_evaluator
    assert resource.project is not None
    assert resource.project.visibility is ProjectVisibility.PRIVATE
    with pytest.raises(ValueError, match="another project"):
        await idea_resource(db_session, principal, idea, world.projects["internal"])
