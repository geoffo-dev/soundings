"""Ideas and keys, editing, deleting, tags, votes and watching (contract sections 3.2
and 3.12): happy paths and every documented error code."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog, Comment
from app.models.base import utcnow
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility, Resolution
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaWatcher
from app.models.project import Project, Tag
from tests.conftest import Login
from tests.factories import add_evaluator, make_idea, make_project, make_user
from tests.ideas.conftest import AsUser, Team, assert_problem, ok


async def events(db: AsyncSession, idea_id: str) -> list[tuple[str, dict[str, Any]]]:
    rows = await db.execute(
        select(ActivityEvent.type, ActivityEvent.payload)
        .where(ActivityEvent.idea_id == idea_id)
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    return [(type_, payload) for type_, payload in rows]


# --- Create -----------------------------------------------------------------------------------
async def test_member_submits_an_idea(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    max_ = await api(team.member)

    idea = await max_.create_idea(
        team.slug,
        title="  Self-service refunds ",
        summary="Let customers refund.",
        description_md="## Why\nCalls cost money.",
        tags=["UX", "billing", "ux"],
    )

    assert idea["key"] == "CUST-1"
    assert idea["number"] == 1
    assert idea["title"] == "Self-service refunds"  # trimmed
    assert idea["project"] == {
        "id": str(team.project.id),
        "slug": "customer-innovation",
        "key": "CUST",
        "name": "Customer Innovation",
    }
    assert (idea["status"], idea["resolution"], idea["status_label"]) == ("new", None, "New")
    assert idea["owner"] is None
    assert idea["submitted_by"]["id"] == str(team.member.id)
    assert idea["submitted_by"]["initials"] == "MM"
    assert "email" not in idea["submitted_by"]
    assert idea["tags"] == ["billing", "UX"]  # merged, alphabetical
    assert idea["evaluators"] == []
    assert idea["evaluator_progress"] == {"submitted": 0, "total": 0}
    assert (idea["score"], idea["score_hidden"], idea["high_disagreement"]) == (None, False, False)
    assert idea["aggregate"] is None
    assert (idea["vote_count"], idea["has_voted"], idea["comment_count"]) == (0, False, 0)
    assert idea["watching"] is True  # the submitter watches
    assert idea["evaluation_due_at"] is None
    assert idea["evaluation_closed_at"] is None
    assert idea["evaluation_open"] is True
    assert idea["description_md"] == "## Why\nCalls cost money."
    assert idea["last_activity_at"] >= idea["created_at"]
    assert idea["permissions"] == {
        "can_change_status": False,
        "can_edit": True,
        "can_assign_owner": False,
        "can_release_owner": False,
        "can_volunteer": True,
        "can_invite_evaluators": False,
        "can_remove_evaluators": False,
        "can_evaluate": False,
        "can_close_evaluation": False,
        "can_comment": True,
        "can_vote": True,
        "can_delete": False,
        "can_answer_research": False,  # Phase 8: the project's research step is off
        "invite_blocked_by_research": False,
    }
    assert await events(db_session, idea["id"]) == [("idea_created", {})]


async def test_admin_permissions_on_a_new_idea(api: AsUser, team: Team) -> None:
    ada = await api(team.admin)

    idea = await ada.create_idea(team.slug)

    assert idea["permissions"] == {
        "can_change_status": True,
        "can_edit": True,
        "can_assign_owner": True,
        "can_release_owner": False,  # "step down" is for the owner
        "can_volunteer": True,
        "can_invite_evaluators": True,
        "can_remove_evaluators": True,
        "can_evaluate": False,  # only assigned evaluators
        "can_close_evaluation": True,
        "can_comment": True,
        "can_vote": True,
        "can_delete": True,
        "can_answer_research": False,  # Phase 8: the project's research step is off
        "invite_blocked_by_research": False,
    }


async def test_keys_are_numbered_per_project_and_never_reused(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    other = await make_project(db_session, key="OPS", members={team.admin: ProjectRole.ADMIN})
    ada = await api(team.admin)

    first = await ada.create_idea(team.slug)
    second = await ada.create_idea(team.slug)
    elsewhere = await ada.create_idea(other.slug)
    ok(await ada.delete(f"/ideas/{second['key']}"), 204)
    third = await ada.create_idea(team.slug)

    assert [first["key"], second["key"], elsewhere["key"], third["key"]] == [
        "CUST-1",
        "CUST-2",
        "OPS-1",
        "CUST-3",
    ]
    project = await db_session.get(Project, team.project.id, populate_existing=True)
    assert project is not None
    assert project.next_idea_number == 4


async def test_concurrent_submissions_get_distinct_numbers(login: Login, team: Team) -> None:
    clients = [await login(user) for user in (team.admin, team.member, *team.evaluators)]

    responses = await asyncio.gather(
        *(
            http.post(
                f"/api/v1/projects/{team.slug}/ideas",
                json={"title": f"Idea {n}", "summary": "Concurrent."},
            )
            for n in range(3)
            for http in clients
        )
    )

    assert all(response.status_code == 201 for response in responses)
    numbers = sorted(response.json()["number"] for response in responses)
    assert numbers == list(range(1, len(responses) + 1))


async def test_who_may_submit(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    body = {"title": "An idea", "summary": "Short."}
    path = f"/projects/{team.slug}/ideas"

    assert_problem(await (await api(team.viewer)).post(path, body), 403, "forbidden")
    assert_problem(await (await api(team.outsider)).post(path, body), 404, "not_found")
    # A platform admin without a role may submit (can_create_ideas).
    ok(await (await api(team.platform)).post(path, body), 201)
    team.project.archived_at = utcnow()
    db_session.add(team.project)
    await db_session.commit()
    assert_problem(await (await api(team.admin)).post(path, body), 409, "project_archived")


async def test_create_validation(api: AsUser, team: Team) -> None:
    max_ = await api(team.member)
    path = f"/projects/{team.slug}/ideas"

    for body in (
        {"title": "No summary"},
        {"title": "   ", "summary": "Blank title."},
        {"title": "Too many tags", "summary": "x", "tags": [f"t{n}" for n in range(11)]},
        {"title": "Bad tag", "summary": "x", "tags": ["a,b"]},
        {"title": "Unknown field", "summary": "x", "status": "closed"},
    ):
        assert_problem(await max_.post(path, body), 422, "validation_error")


async def test_tags_match_case_insensitively_and_keep_the_first_spelling(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    max_ = await api(team.member)

    await max_.create_idea(team.slug, tags=["UX"])
    second = await max_.create_idea(team.slug, tags=["ux", "Pricing"])

    assert second["tags"] == ["Pricing", "UX"]
    names = await db_session.scalars(
        select(Tag.name).where(Tag.project_id == team.project.id).order_by(Tag.name)
    )
    assert list(names) == ["Pricing", "UX"]
    listed = ok(await max_.get(f"/projects/{team.slug}/tags"))
    assert [(tag["name"], tag["idea_count"]) for tag in listed] == [("Pricing", 1), ("UX", 2)]


# --- Read -------------------------------------------------------------------------------------
async def test_get_by_id_or_key_in_any_case(api: AsUser, team: Team) -> None:
    max_ = await api(team.member)
    created = await max_.create_idea(team.slug)

    by_id = ok(await max_.get(f"/ideas/{created['id']}"))
    by_key = ok(await max_.get("/ideas/CUST-1"))
    by_lower = ok(await max_.get("/ideas/cust-1"))

    assert by_id == by_key == by_lower == created


async def test_missing_and_hidden_ideas_are_the_same_404(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await make_idea(db_session, team.project)
    otto = await api(team.outsider)

    hidden = assert_problem(await otto.get("/ideas/CUST-1"), 404, "not_found")
    missing = assert_problem(await otto.get("/ideas/CUST-99"), 404, "not_found")
    unknown_id = assert_problem(await otto.get(f"/ideas/{uuid4()}"), 404, "not_found")

    assert hidden["detail"] == missing["detail"] == unknown_id["detail"]


async def test_internal_projects_are_readable_by_everyone_signed_in(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    project = await make_project(
        db_session,
        key="INT",
        visibility=ProjectVisibility.INTERNAL,
        members={team.admin: ProjectRole.ADMIN},
    )
    idea = await make_idea(db_session, project, submitted_by=team.admin)

    seen = ok(await (await api(team.outsider)).get(f"/ideas/{idea.id}"))

    assert seen["key"] == "INT-1"
    assert seen["permissions"]["can_comment"] is False
    assert seen["permissions"]["can_vote"] is False


# --- Edit ------------------------------------------------------------------------------------
async def test_submitter_edits_while_new(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    max_ = await api(team.member)
    created = await max_.create_idea(team.slug, tags=["UX"])

    edited = ok(
        await max_.patch(
            "/ideas/CUST-1",
            {"title": "Refunds in one click", "summary": None, "tags": ["ux", "Billing"]},
        )
    )

    assert edited["title"] == "Refunds in one click"
    assert edited["summary"] == created["summary"]  # null = unchanged
    assert edited["tags"] == ["Billing", "UX"]
    assert (await events(db_session, created["id"]))[-1] == (
        "idea_edited",
        {"fields": ["title", "tags"]},
    )


async def test_edit_without_changes_emits_nothing(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    max_ = await api(team.member)
    created = await max_.create_idea(team.slug, tags=["UX"])

    unchanged = ok(
        await max_.patch(
            "/ideas/CUST-1", {"title": created["title"], "tags": ["ux"], "description_md": ""}
        )
    )

    assert unchanged["last_activity_at"] == created["last_activity_at"]
    assert [type_ for type_, _ in await events(db_session, created["id"])] == ["idea_created"]


async def test_who_may_edit(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, submitted_by=team.member, owner=team.owner)
    body = {"title": "Changed"}
    path = f"/ideas/{idea.id}"

    # Anyone else who can see it: not_submitter (also a viewer).
    assert_problem(await (await api(team.evaluators[0])).patch(path, body), 403, "not_submitter")
    assert_problem(await (await api(team.viewer)).patch(path, body), 403, "not_submitter")
    assert_problem(await (await api(team.outsider)).patch(path, body), 404, "not_found")
    # The owner edits while the idea is open; admins always.
    ok(await (await api(team.owner)).patch(path, {"title": "By the owner"}))
    ok(await (await api(team.admin)).patch(path, {"title": "By the admin"}))
    ok(await (await api(team.platform)).patch(path, {"title": "By the platform admin"}))

    # The submitter only while it is new.
    idea.status = IdeaStatus.EVALUATING
    db_session.add(idea)
    await db_session.commit()
    assert_problem(await (await api(team.member)).patch(path, body), 409, "idea_not_new")

    idea.status, idea.resolution = IdeaStatus.CLOSED, Resolution.PARKED
    db_session.add(idea)
    await db_session.commit()
    assert_problem(await (await api(team.owner)).patch(path, body), 409, "idea_closed")
    ok(await (await api(team.admin)).patch(path, {"title": "Admins may edit closed ideas"}))


async def test_edit_validation(api: AsUser, team: Team) -> None:
    max_ = await api(team.member)
    await max_.create_idea(team.slug)

    for body in ({"summary": ""}, {"summary": "   "}, {"title": ""}, {"owner": None}):
        assert_problem(await max_.patch("/ideas/CUST-1", body), 422, "validation_error")


async def test_archived_projects_are_read_only(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, submitted_by=team.admin)
    team.project.archived_at = utcnow()
    db_session.add(team.project)
    await db_session.commit()
    ada = await api(team.admin)

    detail = ok(await ada.get(f"/ideas/{idea.id}"))
    assert not any(detail["permissions"].values())
    for method, path, body in [
        ("patch", "", {"title": "x"}),
        ("delete", "", None),
        ("post", "/status", {"status": "evaluating"}),
        ("put", "/owner", {"user_id": str(team.owner.id)}),
        ("post", "/volunteer", None),
        ("post", "/evaluators", {"user_ids": [str(team.member.id)]}),
        ("put", "/evaluation/due-date", {"due_at": None}),
        ("post", "/evaluation/close", None),
        ("post", "/evaluation/reopen", None),
        ("put", "/vote", None),
        ("delete", "/vote", None),
        ("post", "/comments", {"body_md": "Hi"}),
    ]:
        call = getattr(ada, method)
        args = (f"/ideas/{idea.id}{path}",) if body is None else (f"/ideas/{idea.id}{path}", body)
        assert_problem(await call(*args), 409, "project_archived")
    # Watching still works.
    assert ok(await ada.put(f"/ideas/{idea.id}/watch")) == {"watching": True}


# --- Delete ----------------------------------------------------------------------------------
async def test_admin_deletes_an_idea_with_everything_under_it(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, submitted_by=team.member)
    await add_evaluator(db_session, idea, team.evaluators[0], state=EvaluatorState.SUBMITTED)
    db_session.add(Comment(id=uuid4(), idea_id=idea.id, author_id=team.member.id, body_md="Hi"))
    await db_session.commit()

    assert_problem(await (await api(team.member)).delete(f"/ideas/{idea.id}"), 403, "forbidden")
    response = await (await api(team.admin)).delete("/ideas/cust-1")

    assert response.status_code == 204
    assert response.content == b""
    assert_problem(await (await api(team.admin)).get(f"/ideas/{idea.id}"), 404, "not_found")
    assert await db_session.scalar(select(func.count()).select_from(Evaluation)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Comment)) == 0
    entry = await db_session.scalar(select(AuditLog).where(AuditLog.action == "idea.delete"))
    assert entry is not None
    assert (entry.actor_id, entry.target_id, entry.project_id) == (
        team.admin.id,
        idea.id,
        team.project.id,
    )


# --- Votes and watching ----------------------------------------------------------------------
async def test_votes_are_idempotent_and_emit_nothing(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, submitted_by=team.admin)
    max_, eve = await api(team.member), await api(team.evaluators[0])
    before = ok(await eve.get(f"/ideas/{idea.id}"))["last_activity_at"]

    assert ok(await max_.put(f"/ideas/{idea.id}/vote")) == {"vote_count": 1, "has_voted": True}
    assert ok(await max_.put("/ideas/CUST-1/vote")) == {"vote_count": 1, "has_voted": True}
    assert ok(await eve.put(f"/ideas/{idea.id}/vote")) == {"vote_count": 2, "has_voted": True}
    assert ok(await max_.delete(f"/ideas/{idea.id}/vote")) == {"vote_count": 1, "has_voted": False}
    assert ok(await max_.delete(f"/ideas/{idea.id}/vote")) == {"vote_count": 1, "has_voted": False}

    detail = ok(await eve.get(f"/ideas/{idea.id}"))
    assert (detail["vote_count"], detail["has_voted"]) == (1, True)
    assert detail["last_activity_at"] == before  # votes are not activity
    assert await events(db_session, str(idea.id)) == []


async def test_who_may_vote(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)

    assert_problem(await (await api(team.viewer)).put(f"/ideas/{idea.id}/vote"), 403, "forbidden")
    assert_problem(
        await (await api(team.viewer)).delete(f"/ideas/{idea.id}/vote"), 403, "forbidden"
    )
    assert_problem(await (await api(team.outsider)).put(f"/ideas/{idea.id}/vote"), 404, "not_found")
    # Votes are allowed in any status.
    idea.status, idea.resolution = IdeaStatus.CLOSED, Resolution.REJECTED
    db_session.add(idea)
    await db_session.commit()
    ok(await (await api(team.member)).put(f"/ideas/{idea.id}/vote"))


async def test_watching(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    vic = await api(team.viewer)

    assert ok(await vic.put(f"/ideas/{idea.id}/watch")) == {"watching": True}
    assert ok(await vic.put(f"/ideas/{idea.id}/watch")) == {"watching": True}
    assert ok(await vic.get(f"/ideas/{idea.id}"))["watching"] is True
    assert ok(await vic.delete(f"/ideas/{idea.id}/watch")) == {"watching": False}
    assert ok(await vic.delete(f"/ideas/{idea.id}/watch")) == {"watching": False}
    assert_problem(
        await (await api(team.outsider)).put(f"/ideas/{idea.id}/watch"), 404, "not_found"
    )
    assert await events(db_session, str(idea.id)) == []
    watchers = await db_session.scalar(select(func.count()).select_from(IdeaWatcher))
    assert watchers == 0


async def test_platform_admin_without_role_can_act(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    pat = await api(team.platform)

    detail = ok(await pat.get(f"/ideas/{idea.id}"))

    assert detail["permissions"]["can_change_status"] is True
    assert detail["permissions"]["can_volunteer"] is False  # c4: needs a real project role
    assert_problem(await pat.post(f"/ideas/{idea.id}/volunteer"), 422, "assignee_not_eligible")


async def test_ideas_of_removed_users_still_render(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ghost = await make_user(db_session, "Gone Person")
    idea = await make_idea(db_session, team.project, submitted_by=ghost)
    await db_session.delete(ghost)
    await db_session.commit()

    detail = ok(await (await api(team.member)).get(f"/ideas/{idea.id}"))

    assert detail["submitted_by"] is None
    assert await db_session.scalar(select(func.count()).select_from(Idea)) == 1
