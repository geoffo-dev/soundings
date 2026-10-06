"""The nine tools (contract-phase5 sections 4.2-4.4 and 4.6, "Per tool"): happy paths,
the scope each needs, the owner's role in every column, the key's project restriction,
and the REST codes as structured tool errors. Writes behave exactly as their REST twins
(notifications, activity, audit entries naming the owner)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog, Comment
from app.models.base import utcnow
from app.models.enums import (
    AiRunKind,
    EvaluatorState,
    IdeaStatus,
    NotificationType,
    ProjectRole,
    ProjectVisibility,
    ProposalSectionKey,
    Recommendation,
)
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaTag, IdeaWatcher
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project, ProjectMember
from app.models.proposal import ProposalSuggestion
from app.models.public import PublicSubmission
from app.schemas.mcp import MCP_TEXT_LIMIT, MCP_TOOLS
from app.services.scoring import recompute_aggregates
from tests.ai.helpers import make_agent, open_run
from tests.factories import add_evaluator, make_idea, make_project, make_user
from tests.mcp.conftest import AsAgent, AsUser, Team, full_scores, ok

READ = ["read", "mcp"]
WRITE = ["read", "write", "mcp"]
EVALUATE = ["read", "evaluate", "mcp"]
NO_READ = ["mcp"]


def key_of(team: Team, idea: Idea) -> str:
    return f"{team.project.key}-{idea.number}"


async def internal(db: AsyncSession, team: Team) -> None:
    await db.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db.commit()


@pytest.fixture
async def other(db_session: AsyncSession, team: Team) -> Project:
    """Internal Tools: a second project where the member is also a member."""
    return await make_project(
        db_session,
        slug="internal-tools",
        key="TOOLS",
        name="Internal Tools",
        members={team.member: ProjectRole.MEMBER, team.admin: ProjectRole.ADMIN},
    )


# --- list_projects -------------------------------------------------------------------------
async def test_list_projects_lists_what_the_owner_sees_inside_the_key(
    as_agent: AsAgent, team: Team, other: Project, db_session: AsyncSession
) -> None:
    await make_idea(db_session, team.project)
    archived = await make_project(
        db_session, name="Old ideas", members={team.member: ProjectRole.MEMBER}, archived=True
    )

    everything = await (await as_agent(team.member)).ok("list_projects")
    with_archived = await (await as_agent(team.member, READ)).ok(
        "list_projects", include_archived=True
    )
    restricted = await (await as_agent(team.member, READ, [other])).ok("list_projects")

    assert [p["slug"] for p in everything["projects"]] == ["customer-innovation", "internal-tools"]
    cust = everything["projects"][0]
    assert cust == {
        "id": str(team.project.id),
        "slug": "customer-innovation",
        "key": "CUST",
        "name": "Customer Innovation",
        "description": "",
        "visibility": "private",
        "my_role": "member",
        "archived": False,
        "idea_count": 1,
        "can_create_ideas": True,
    }
    assert [p["slug"] for p in with_archived["projects"]] == [
        "customer-innovation",
        "internal-tools",
        archived.slug,
    ]
    assert with_archived["projects"][0]["can_create_ideas"] is False  # no write scope
    assert with_archived["projects"][2]["archived"] is True
    assert [p["slug"] for p in restricted["projects"]] == ["internal-tools"]


async def test_list_projects_needs_read(as_agent: AsAgent, team: Team) -> None:
    assert await (await as_agent(team.member, NO_READ)).fails("list_projects") == (
        "insufficient_scope"
    )


async def test_a_platform_admins_restricted_key_sees_only_its_projects(
    as_agent: AsAgent, team: Team, other: Project
) -> None:
    found = await (await as_agent(team.platform, READ, [team.project])).ok("list_projects")
    assert [p["slug"] for p in found["projects"]] == ["customer-innovation"]
    assert found["projects"][0]["my_role"] is None


# --- search_ideas ---------------------------------------------------------------------------
async def test_search_filters_like_the_list(
    as_agent: AsAgent, team: Team, other: Project, db_session: AsyncSession
) -> None:
    refunds = await make_idea(db_session, team.project, title="Self-service refunds")
    owned = await make_idea(
        db_session,
        team.project,
        title="Chat support",
        status=IdeaStatus.EVALUATING,
        owner=team.member,
    )
    tools = await make_idea(db_session, other, title="Refund tooling")
    agent = await as_agent(team.member, READ)

    by_text = await agent.ok("search_ideas", query="REFUND")
    by_key = await agent.ok("search_ideas", query=f"cust-{owned.number}")
    by_project = await agent.ok("search_ideas", project="internal-tools")
    by_status = await agent.ok("search_ideas", status=["evaluating"])
    mine = await agent.ok("search_ideas", owner="me")
    unowned = await agent.ok("search_ideas", owner="none", project=team.slug)

    def keys(found: dict[str, Any]) -> list[str]:
        return [item["key"] for item in found["items"]]

    assert sorted(keys(by_text)) == sorted([key_of(team, refunds), f"TOOLS-{tools.number}"])
    assert keys(by_key) == [key_of(team, owned)]
    assert keys(by_project) == [f"TOOLS-{tools.number}"]
    assert keys(by_status) == [key_of(team, owned)]
    assert keys(mine) == [key_of(team, owned)]
    assert keys(unowned) == [key_of(team, refunds)]
    item = by_key["items"][0]
    assert item["url"] == f"http://testserver/ideas/{key_of(team, owned)}"
    assert item["owner"] == {
        "id": str(team.member.id),
        "display_name": "Max Member",
        "is_ai": False,
    }
    assert item["via_public_form"] is False


async def test_search_pages_with_opaque_cursors(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    for n in range(5):
        await make_idea(db_session, team.project, title=f"Idea {n}")
    agent = await as_agent(team.member, READ)

    first = await agent.ok("search_ideas", limit=2, sort="title")
    second = await agent.ok("search_ideas", limit=2, sort="title", cursor=first["next_cursor"])
    last = await agent.ok("search_ideas", limit=2, sort="title", cursor=second["next_cursor"])
    foreign = await agent.fails("search_ideas", cursor="bm90IG91cnM")
    other_sort = await agent.fails("search_ideas", sort="-votes", cursor=first["next_cursor"])

    titles = [i["title"] for page in (first, second, last) for i in page["items"]]
    assert titles == [f"Idea {n}" for n in range(5)]
    assert last["next_cursor"] is None
    assert foreign == other_sort == "invalid_cursor"


async def test_search_inside_the_restriction_only(
    as_agent: AsAgent, team: Team, other: Project, db_session: AsyncSession
) -> None:
    await make_idea(db_session, team.project, title="Refunds")
    await make_idea(db_session, other, title="Refund tooling")
    agent = await as_agent(team.member, READ, [team.project])

    found = await agent.ok("search_ideas", query="refund")
    outside = await agent.fails("search_ideas", project="internal-tools")
    unknown = await agent.fails("search_ideas", project="no-such-project")

    assert [item["project"]["slug"] for item in found["items"]] == ["customer-innovation"]
    assert outside == unknown == "not_found"


async def test_awaiting_my_evaluation_lists_what_my_work_lists(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    due = await make_idea(db_session, team.project, title="Due", status=IdeaStatus.EVALUATING)
    drafted = await make_idea(db_session, team.project, title="Drafted")
    done = await make_idea(db_session, team.project, title="Done")
    closed = await make_idea(db_session, team.project, title="Closed", status=IdeaStatus.CLOSED)
    await make_idea(db_session, team.project, title="Not mine")
    await add_evaluator(db_session, due, evaluator)
    await add_evaluator(db_session, drafted, evaluator, state=EvaluatorState.DRAFT)
    await add_evaluator(db_session, done, evaluator, state=EvaluatorState.SUBMITTED)
    await add_evaluator(db_session, closed, evaluator)

    found = await (await as_agent(evaluator, EVALUATE)).ok(
        "search_ideas", awaiting_my_evaluation=True, sort="title"
    )

    assert [(i["title"], i["my_evaluation_state"]) for i in found["items"]] == [
        ("Drafted", "draft"),
        ("Due", "invited"),
    ]
    assert all(item["score_hidden"] for item in found["items"])


async def test_search_needs_read_and_flags_public_ideas(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    public = await make_idea(db_session, team.project, title="From the public")
    db_session.add(
        PublicSubmission(
            id=uuid4(),
            idea_id=public.id,
            project_id=team.project.id,
            name="Pat Public",
            submitted_title="From the public",
            submitted_summary="A short summary.",
        )
    )
    await db_session.commit()

    found = await (await as_agent(team.member, READ)).ok("search_ideas")
    detail = await (await as_agent(team.member, READ)).ok("get_idea", idea=key_of(team, public))
    refused = await (await as_agent(team.member, NO_READ)).fails("search_ideas")

    assert found["items"][0]["via_public_form"] is True
    assert detail["idea"]["via_public_form"] is True
    assert detail["idea"]["submitted_by"] is None
    assert "Pat Public" not in str(detail)
    assert refused == "insufficient_scope"


# --- get_idea -------------------------------------------------------------------------------
async def test_get_idea_returns_the_page_bounded(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(
        db_session,
        team.project,
        title="Refunds",
        owner=team.owner,
        submitted_by=team.member,
        tags=["Payments"],
    )
    authors = [team.member, team.owner, team.admin]
    for n in range(30):
        db_session.add(
            Comment(
                id=uuid4(),
                idea_id=idea.id,
                author_id=authors[n % 3].id,
                body_md=f"{n:02d}" + "x" * 9_998,
                created_at=utcnow() + timedelta(seconds=n),
            )
        )
    await db_session.commit()
    people = [await make_user(db_session, f"Rater {n}") for n in range(30)]
    for person in people:
        db_session.add(
            ProjectMember(project_id=team.project.id, user_id=person.id, role=ProjectRole.MEMBER)
        )
        await add_evaluator(
            db_session,
            idea,
            person,
            state=EvaluatorState.SUBMITTED,
            recommendation=Recommendation.MAYBE,
        )
    await db_session.execute(update(Evaluation).values(comment="y" * 3_000))
    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.commit()
    agent = await as_agent(team.viewer, READ)

    found = (await agent.ok("get_idea", idea=key_of(team, idea).lower()))["idea"]
    twenty = (await agent.ok("get_idea", idea=str(idea.id), comment_limit=20))["idea"]
    none = (await agent.ok("get_idea", idea=str(idea.id), comment_limit=0))["idea"]

    assert found["key"] == key_of(team, idea)
    assert found["owner"]["display_name"] == "Olive Owner"
    assert found["submitted_by"]["display_name"] == "Max Member"
    assert found["tags"] == ["Payments"]
    assert found["comment_count"] == 30
    assert [c["body_md"][:2] for c in found["comments"]] == [f"{n:02d}" for n in range(20, 30)]
    assert all(len(c["body_md"]) == MCP_TEXT_LIMIT and c["truncated"] for c in found["comments"])
    assert len(twenty["comments"]) == 20
    assert none["comments"] == []
    assert found["evaluation_count"] == 30
    assert len(found["evaluations"]) == 25
    assert all(e["truncated"] and len(e["comment"]) == MCP_TEXT_LIMIT for e in found["evaluations"])
    assert found["score_hidden"] is False
    assert found["score"]["count"] == 30
    assert found["aggregate"]["count"] == 30
    assert found["evaluators"][0]["state"] == "submitted"
    assert found["permissions"] == {
        "can_comment": False,  # a viewer
        "can_evaluate": False,
        "can_suggest_proposal_section": False,
    }
    assert found["my_evaluation"] is None
    assert found["has_proposal"] is False


@pytest.mark.parametrize(
    ("who", "visibility", "expected"),
    [
        ("platform", "private", "ok"),
        ("admin", "private", "ok"),
        ("member", "private", "ok"),
        ("viewer", "private", "ok"),
        ("outsider", "internal", "ok"),
        ("outsider", "private", "not_found"),
    ],
)
async def test_get_idea_for_every_column(
    as_agent: AsAgent,
    team: Team,
    db_session: AsyncSession,
    who: str,
    visibility: str,
    expected: str,
) -> None:
    idea = await make_idea(db_session, team.project)
    if visibility == "internal":
        await internal(db_session, team)
    agent = await as_agent(getattr(team, who), READ)

    result = await agent.call("get_idea", idea=key_of(team, idea))

    if expected == "ok":
        assert not result.is_error, result.structured_content
    else:
        assert result.structured_content["code"] == expected


async def test_get_idea_scope_and_restriction(
    as_agent: AsAgent, team: Team, other: Project, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    hidden = await make_idea(db_session, other)

    no_read = await (await as_agent(team.member, NO_READ)).fails(
        "get_idea", idea=key_of(team, idea)
    )
    outside = await (await as_agent(team.member, READ, [team.project])).fails(
        "get_idea", idea=f"TOOLS-{hidden.number}"
    )
    missing = await (await as_agent(team.member, READ)).fails("get_idea", idea="CUST-999")

    assert no_read == "insufficient_scope"
    assert outside == missing == "not_found"


# --- get_rubric and get_proposal -----------------------------------------------------------
async def test_get_rubric_by_project_or_idea(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    agent = await as_agent(team.member, READ)

    by_project = await agent.ok("get_rubric", project=team.slug)
    by_idea = await agent.ok("get_rubric", idea=key_of(team, idea))
    neither = await agent.fails("get_rubric")
    outsider = await (await as_agent(team.outsider, READ)).fails("get_rubric", project=team.slug)

    assert by_project == by_idea
    assert [c["id"] for c in by_project["criteria"]] == [str(c.id) for c in team.rubric]
    assert any(c["inverted"] for c in by_project["criteria"])
    assert all(c["guidance"] for c in by_project["criteria"])
    assert (by_project["score_min"], by_project["score_max"]) == (1, 5)
    assert by_project["recommendations"] == ["go", "maybe", "no"]
    assert by_project["project"]["key"] == "CUST"
    assert neither == "validation_error"
    assert outsider == "not_found"


async def test_get_proposal_before_and_after_it_starts(
    as_agent: AsAgent, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    agent = await as_agent(team.member)

    before = await agent.ok("get_proposal", idea=key_of(team, idea))
    ok(await (await api(team.owner)).post(f"/ideas/{key_of(team, idea)}/proposal"), 201)
    after = await agent.ok("get_proposal", idea=key_of(team, idea))
    viewer = await (await as_agent(team.viewer, READ)).ok("get_proposal", idea=key_of(team, idea))

    assert before["proposal"] is None
    assert before["can_suggest"] is False
    assert before["idea"]["status"] == "shortlisted"
    assert [s["key"] for s in after["proposal"]["sections"]][:2] == ["summary", "problem"]
    assert after["proposal"]["sections"][0]["version"] == 1
    assert after["can_suggest"] is True
    assert after["idea"]["status"] == "proposal"
    assert viewer["can_suggest"] is False


# --- create_idea ------------------------------------------------------------------------------
async def test_create_idea_is_rest_create_idea(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    agent = await as_agent(team.member, WRITE)

    created = await agent.ok(
        "create_idea",
        project=team.slug,
        title="  Self-service refunds  ",
        summary="Let customers refund without calling us.",
        tags=["Payments", "payments", "UX"],
    )

    ref = created["idea"]
    assert ref["key"] == "CUST-1"
    assert ref["title"] == "Self-service refunds"  # stripped
    assert ref["status"] == "new"
    assert ref["url"] == "http://testserver/ideas/CUST-1"
    idea = await db_session.scalar(select(Idea).where(Idea.number == 1))
    assert idea is not None
    assert idea.submitted_by_id == team.member.id
    tags = await db_session.scalar(
        select(func.count()).select_from(IdeaTag).where(IdeaTag.idea_id == idea.id)
    )
    assert tags == 2  # "Payments" and "payments" merged
    events = list(
        await db_session.scalars(select(ActivityEvent).where(ActivityEvent.idea_id == idea.id))
    )
    assert [(e.type, e.actor_id) for e in events] == [("idea_created", team.member.id)]


@pytest.mark.parametrize(
    ("who", "scopes", "code"),
    [
        ("member", READ, "insufficient_scope"),
        ("viewer", WRITE, "forbidden"),
        ("outsider", WRITE, "not_found"),
    ],
)
async def test_create_idea_refusals(
    as_agent: AsAgent, team: Team, who: str, scopes: list[str], code: str
) -> None:
    agent = await as_agent(getattr(team, who), scopes)
    assert await agent.fails("create_idea", project=team.slug, title="x", summary="y") == code


async def test_create_idea_in_an_archived_project_or_outside_the_key(
    as_agent: AsAgent, team: Team, other: Project, db_session: AsyncSession
) -> None:
    restricted = await as_agent(team.member, WRITE, [team.project])
    outside = await restricted.fails(
        "create_idea", project="internal-tools", title="x", summary="y"
    )
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=func.now())
    )
    await db_session.commit()
    archived = await restricted.fails("create_idea", project=team.slug, title="x", summary="y")

    assert outside == "not_found"
    assert archived == "project_archived"
    assert await db_session.scalar(select(func.count()).select_from(Idea)) == 0


# --- add_comment ------------------------------------------------------------------------------
async def test_add_comment_is_rest_create_comment(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    db_session.add(IdeaWatcher(idea_id=idea.id, user_id=team.owner.id))
    await db_session.commit()
    mention = f"@[Ada Admin](user:{team.admin.id})"

    created = await (await as_agent(team.member, WRITE)).ok(
        "add_comment", idea=key_of(team, idea), body_md=f"Looks good, {mention}"
    )

    comment = created["comment"]
    assert comment["body_md"] == f"Looks good, {mention}"
    assert comment["truncated"] is False
    assert comment["author"]["display_name"] == "Max Member"
    notified = {
        (n.user_id, n.type)
        for n in await db_session.scalars(
            select(Notification).where(Notification.idea_id == idea.id)
        )
    }
    assert (team.admin.id, NotificationType.MENTION) in notified
    assert (team.owner.id, NotificationType.COMMENT) in notified
    events = list(
        await db_session.scalars(select(ActivityEvent).where(ActivityEvent.idea_id == idea.id))
    )
    assert [(e.type, e.actor_id) for e in events] == [("comment", team.member.id)]


async def test_add_comment_refusals(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    ref = key_of(team, idea)

    viewer = await (await as_agent(team.viewer, WRITE)).fails("add_comment", idea=ref, body_md="x")
    read_only = await (await as_agent(team.member, READ)).fails(
        "add_comment", idea=ref, body_md="x"
    )
    empty = await (await as_agent(team.member, WRITE)).fails("add_comment", idea=ref, body_md="  ")

    assert viewer == "forbidden"
    assert read_only == "insufficient_scope"
    assert empty == "validation_error"


# --- submit_evaluation -------------------------------------------------------------------------
async def test_submit_evaluation_submits_by_default_and_counts(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, evaluator)
    agent = await as_agent(evaluator, EVALUATE)

    result = await agent.ok(
        "submit_evaluation",
        idea=key_of(team, idea),
        scores=full_scores(team, 4),
        recommendation="go",
        comment="Worth it.",
    )

    evaluation = result["evaluation"]
    assert evaluation["state"] == "submitted"
    assert evaluation["editable"] is True
    assert [s["criterion"] for s in evaluation["scores"]] == [c.name for c in team.rubric]
    assert result["idea"]["key"] == key_of(team, idea)
    row = await db_session.scalar(select(Evaluation).where(Evaluation.idea_id == idea.id))
    assert row is not None
    assert row.include_in_aggregate is True
    audited = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "evaluation.submit")
    )
    assert audited is not None
    assert audited.actor_id == evaluator.id
    assert audited.details["auth"] == "api_key"
    assert audited.details["api_key_id"]
    events = list(
        await db_session.scalars(select(ActivityEvent.type).where(ActivityEvent.idea_id == idea.id))
    )
    assert events == ["evaluation_submitted"]


async def test_a_misspelt_write_argument_is_refused_not_ignored(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    """Security review L2: ``sumbit=false`` must not quietly submit (the default) or save
    anything; read tools still ignore extra arguments."""
    evaluator = team.evaluators[0]
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, evaluator)
    agent = await as_agent(evaluator, EVALUATE)

    refused = await agent.call(
        "submit_evaluation",
        idea=key_of(team, idea),
        scores=full_scores(team, 4),
        recommendation="go",
        sumbit=False,
    )
    read = await agent.ok("get_idea", idea=key_of(team, idea), verbose=True)

    assert refused.is_error
    assert refused.structured_content["code"] == "validation_error"
    assert "sumbit" in refused.structured_content["message"]
    assert read["idea"]["my_evaluation"]["state"] == "invited"
    saved = await db_session.scalar(select(Evaluation).where(Evaluation.idea_id == idea.id))
    assert saved is None
    calls = list(
        await db_session.scalars(
            select(AuditLog).where(AuditLog.action == "mcp.call").order_by(AuditLog.created_at)
        )
    )
    assert [(c.details["tool"], c.details["decision"], c.details["code"]) for c in calls] == [
        ("submit_evaluation", "deny", "validation_error"),
        ("get_idea", "allow", None),
    ]


async def test_submit_evaluation_follows_the_phase1_rules(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, evaluator)
    ref = key_of(team, idea)
    agent = await as_agent(evaluator, EVALUATE)
    one = full_scores(team, 3)[:1]

    incomplete = await agent.call("submit_evaluation", idea=ref, scores=one, recommendation="go")
    unknown = await agent.fails(
        "submit_evaluation",
        idea=ref,
        scores=[{"criterion_id": str(uuid4()), "score": 3}],
        submit=False,
    )
    draft = await agent.ok("submit_evaluation", idea=ref, scores=one, submit=False)
    submitted = await agent.ok(
        "submit_evaluation", idea=ref, scores=full_scores(team, 5), recommendation="no"
    )
    back_to_draft = await agent.fails("submit_evaluation", idea=ref, scores=one, submit=False)
    edited = await agent.ok(
        "submit_evaluation", idea=ref, scores=full_scores(team, 2), recommendation="maybe"
    )

    assert incomplete.structured_content["code"] == "evaluation_incomplete"
    missing = incomplete.structured_content["message"]
    assert all(f"scores.{c.id}" in missing for c in team.rubric[1:])
    assert f"scores.{team.rubric[0].id}" not in missing
    assert unknown == "unknown_criterion"
    assert draft["evaluation"]["state"] == "draft"
    assert submitted["evaluation"]["state"] == "submitted"
    assert back_to_draft == "evaluation_already_submitted"
    assert edited["evaluation"]["recommendation"] == "maybe"


async def test_submit_evaluation_refusals(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, evaluator)
    ref = key_of(team, idea)
    body: dict[str, Any] = {"scores": full_scores(team), "recommendation": "go"}

    not_assigned = await (await as_agent(team.member)).fails("submit_evaluation", idea=ref, **body)
    no_scope = await (await as_agent(evaluator, WRITE)).fails("submit_evaluation", idea=ref, **body)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(evaluation_closed_at=func.now())
    )
    await db_session.commit()
    closed = await (await as_agent(evaluator, EVALUATE)).fails(
        "submit_evaluation", idea=ref, **body
    )

    assert not_assigned == "forbidden"
    assert no_scope == "insufficient_scope"
    assert closed == "evaluation_closed"


async def test_submit_evaluation_outside_the_restriction_is_not_found(
    as_agent: AsAgent, team: Team, other: Project, db_session: AsyncSession
) -> None:
    """Acceptance step 4: Carol may evaluate TOOLS-m in the app, not with this key."""
    evaluator = team.member
    idea = await make_idea(db_session, other, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, evaluator)
    agent = await as_agent(evaluator, EVALUATE, [team.project])

    found = await agent.fails("get_idea", idea=f"TOOLS-{idea.number}")
    submitted = await agent.fails(
        "submit_evaluation",
        idea=f"TOOLS-{idea.number}",
        scores=[{"criterion_id": str(uuid4()), "score": 3}],
        recommendation="go",
    )

    assert found == submitted == "not_found"


# --- propose_proposal_section ----------------------------------------------------------------
@pytest.fixture
async def proposal_idea(api: AsUser, team: Team, db_session: AsyncSession) -> Idea:
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    ok(await (await api(team.owner)).post(f"/ideas/{key_of(team, idea)}/proposal"), 201)
    return idea


async def test_propose_proposal_section_creates_a_pending_suggestion(
    as_agent: AsAgent, team: Team, proposal_idea: Idea, db_session: AsyncSession
) -> None:
    agent = await as_agent(team.member, WRITE)
    ref = key_of(team, proposal_idea)

    first = await agent.ok(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="  - Lock-in\n"
    )
    second = await agent.ok(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="- Lock-in\n- Cost\n"
    )

    assert first["suggestion"]["source"] == "mcp"
    assert first["suggestion"]["body_md"] == "  - Lock-in\n"  # verbatim, not stripped
    assert first["suggestion"]["status"] == "pending"
    assert first["replaced_suggestion_id"] is None
    assert second["replaced_suggestion_id"] == first["suggestion"]["id"]
    rows = list(await db_session.scalars(select(ProposalSuggestion)))
    assert sorted(row.status.value for row in rows) == ["discarded", "pending"]


async def test_an_agents_suggestion_is_ai(
    as_agent: AsAgent, team: Team, proposal_idea: Idea, db_session: AsyncSession
) -> None:
    agent_user = await make_user(db_session, "Research Agent", service_account=True)
    agent_row = await make_agent(db_session, [team.project], user=agent_user)
    # c22: an agent writes only through its open draft run's tool, for that section.
    run = await open_run(
        db_session,
        agent_row,
        proposal_idea,
        AiRunKind.DRAFT_SECTION,
        section_key=ProposalSectionKey.MARKET,
    )

    created = (
        await (await as_agent(agent_user, WRITE, [team.project]))
        .for_run(run)
        .ok(
            "propose_proposal_section",
            idea=key_of(team, proposal_idea),
            section_key="market",
            body_md="Mid-size retailers.",
        )
    )

    assert created["suggestion"]["source"] == "ai"
    assert created["suggestion"]["author"]["display_name"] == "Research Agent"


async def test_propose_proposal_section_refusals(
    as_agent: AsAgent, team: Team, proposal_idea: Idea, db_session: AsyncSession
) -> None:
    without = await make_idea(db_session, team.project, status=IdeaStatus.SHORTLISTED)
    ref = key_of(team, proposal_idea)
    member = await as_agent(team.member, WRITE)

    no_proposal = await member.call(
        "propose_proposal_section", idea=key_of(team, without), section_key="risks", body_md="x"
    )
    ahead = await member.fails(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="x", base_version=2
    )
    blank = await member.fails(
        "propose_proposal_section", idea=ref, section_key="risks", body_md=" "
    )
    viewer = await (await as_agent(team.viewer, WRITE)).fails(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="x"
    )
    read_only = await (await as_agent(team.member, READ)).fails(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="x"
    )
    await db_session.execute(
        update(Idea).where(Idea.id == proposal_idea.id).values(status=IdeaStatus.EVALUATING)
    )
    await db_session.commit()
    unavailable = await member.fails(
        "propose_proposal_section", idea=ref, section_key="risks", body_md="x"
    )

    assert no_proposal.structured_content == {
        "code": "not_found",
        "message": "This idea has no proposal yet.",
    }
    assert ahead == "validation_error"
    assert blank == "validation_error"
    assert viewer == "forbidden"
    assert read_only == "insufficient_scope"
    assert unavailable == "proposal_not_available"


# --- Every tool's scope, every write tool's columns -------------------------------------------
@pytest.fixture
async def everything(api: AsUser, team: Team, db_session: AsyncSession) -> dict[str, Any]:
    """An idea every tool can act on (Shortlisted, with a proposal, the member asked to
    evaluate it) and each tool's arguments for it."""
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    await add_evaluator(db_session, idea, team.member)
    ref = key_of(team, idea)
    ok(await (await api(team.owner)).post(f"/ideas/{ref}/proposal"), 201)
    return {
        "list_projects": {},
        "search_ideas": {},
        "get_idea": {"idea": ref},
        "get_rubric": {"idea": ref},
        "get_proposal": {"idea": ref},
        "create_idea": {"project": team.slug, "title": "New", "summary": "One line."},
        "add_comment": {"idea": ref, "body_md": "Hello"},
        "submit_evaluation": {
            "idea": ref,
            "scores": full_scores(team),
            "recommendation": "go",
        },
        "propose_proposal_section": {"idea": ref, "section_key": "risks", "body_md": "x"},
    }


@pytest.mark.parametrize(
    # add_research_note is for agents during a research run only (tests/ai/test_scope.py).
    "tool",
    [tool.name for tool in MCP_TOOLS if tool.name != "add_research_note"],
)
async def test_every_tool_needs_its_scope(
    as_agent: AsAgent, team: Team, everything: dict[str, Any], tool: str
) -> None:
    spec = next(t for t in MCP_TOOLS if t.name == tool)
    others = [s for s in ("read", "write", "evaluate") if s != spec.scope.value]
    if spec.scope.value == "read":
        others = []  # write and evaluate always come with read
    without = await as_agent(team.member, [*others, "mcp"])
    with_it = await as_agent(team.member, [spec.scope.value, "read", "mcp"])

    refused = await without.fails(tool, **everything[tool])
    allowed = await with_it.call(tool, **everything[tool])

    assert refused == "insufficient_scope"
    assert not allowed.is_error, allowed.structured_content


WRITE_COLUMNS: dict[str, list[str]] = {
    # platform, admin, member (not the owner, not evaluating), viewer, NMi, NMp
    "create_idea": ["ok", "ok", "ok", "forbidden", "forbidden", "not_found"],
    "add_comment": ["ok", "ok", "ok", "forbidden", "forbidden", "not_found"],
    "propose_proposal_section": ["ok", "ok", "ok", "forbidden", "forbidden", "not_found"],
    "submit_evaluation": [
        "forbidden",
        "forbidden",
        "forbidden",
        "forbidden",
        "forbidden",
        "not_found",
    ],
}
COLUMNS = [
    ("platform", "private"),
    ("admin", "private"),
    ("evaluator", "private"),
    ("viewer", "private"),
    ("outsider", "internal"),
    ("outsider", "private"),
]


@pytest.mark.parametrize("tool", sorted(WRITE_COLUMNS))
@pytest.mark.parametrize("column", range(len(COLUMNS)))
async def test_write_tools_for_every_column(
    as_agent: AsAgent,
    team: Team,
    everything: dict[str, Any],
    db_session: AsyncSession,
    tool: str,
    column: int,
) -> None:
    who, visibility = COLUMNS[column]
    if visibility == "internal":
        await internal(db_session, team)
    user = team.evaluators[1] if who == "evaluator" else getattr(team, who)
    agent = await as_agent(user)

    result = await agent.call(tool, **everything[tool])

    expected = WRITE_COLUMNS[tool][column]
    if expected == "ok":
        assert not result.is_error, result.structured_content
    else:
        assert result.structured_content["code"] == expected


async def test_the_evaluator_overlay_and_a_demoted_evaluator(
    as_agent: AsAgent, team: Team, everything: dict[str, Any], db_session: AsyncSession
) -> None:
    agent = await as_agent(team.member, EVALUATE)
    assert not (await agent.call("submit_evaluation", **everything["submit_evaluation"])).is_error
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.member.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    demoted = await agent.fails("submit_evaluation", **everything["submit_evaluation"])

    assert demoted == "forbidden"  # live: the key acts with the owner's role now


@pytest.mark.settings(
    smtp_host="smtp.invalid", smtp_port=2525, smtp_security="none", smtp_from="s@example.com"
)
async def test_a_write_through_mcp_queues_email_like_the_app(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    """The call's unit of work carries the settings, so the before-commit fan-out writes
    the outbox row (and its send job) as a REST request would."""
    idea = await make_idea(db_session, team.project)
    mention = f"@[Ada Admin](user:{team.admin.id})"

    await (await as_agent(team.member, WRITE)).ok(
        "add_comment", idea=key_of(team, idea), body_md=f"Have a look, {mention}"
    )

    queued = list(await db_session.scalars(select(OutboundEmail)))
    assert [(email.recipient_user_id, email.type.value) for email in queued] == [
        (team.admin.id, "mention")
    ]
