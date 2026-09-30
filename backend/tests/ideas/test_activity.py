"""Comments (contract section 3.12) and the activity feed (3.13)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.idea import IdeaWatcher
from tests.factories import make_idea, make_user
from tests.ideas.conftest import AsUser, Team, assert_problem, ok


# --- Comments --------------------------------------------------------------------------------
async def test_comment_lifecycle(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(
        db_session, team.project, last_activity_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    max_ = await api(team.member)

    created = ok(
        await max_.post(f"/ideas/{idea.id}/comments", {"body_md": "  **Love** it.  "}), 201
    )

    assert created["type"] == "comment"
    assert created["idea_id"] == str(idea.id)
    assert created["actor"]["id"] == str(team.member.id)
    assert created["comment"] == {
        "id": created["comment"]["id"],
        "body_md": "**Love** it.",
        "edited_at": None,
        "deleted": False,
        "can_edit": True,
        "can_delete": True,
    }
    detail = ok(await max_.get(f"/ideas/{idea.id}"))
    assert detail["comment_count"] == 1
    assert detail["watching"] is True  # commenters watch
    assert detail["last_activity_at"] == created["created_at"]

    comment_id = created["comment"]["id"]
    edited = ok(await max_.patch(f"/comments/{comment_id}", {"body_md": "Love it!"}))
    assert edited["id"] == created["id"]  # the same feed item
    assert edited["comment"]["body_md"] == "Love it!"
    assert edited["comment"]["edited_at"] is not None

    response = await max_.delete(f"/comments/{comment_id}")
    assert response.status_code == 204
    feed = ok(await max_.get(f"/ideas/{idea.id}/activity"))
    [item] = feed["items"]
    assert item["comment"] == {
        "id": comment_id,
        "body_md": "",
        "edited_at": edited["comment"]["edited_at"],
        "deleted": True,
        "can_edit": False,
        "can_delete": False,
    }
    assert ok(await max_.get(f"/ideas/{idea.id}"))["comment_count"] == 0
    assert_problem(await max_.patch(f"/comments/{comment_id}", {"body_md": "x"}), 404, "not_found")
    assert_problem(await max_.delete(f"/comments/{comment_id}"), 404, "not_found")
    # Editing and deleting are not events.
    types = await db_session.scalars(
        select(ActivityEvent.type).where(ActivityEvent.idea_id == idea.id)
    )
    assert list(types) == ["comment"]


async def test_who_may_comment(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    path = f"/ideas/{idea.id}/comments"

    assert_problem(await (await api(team.viewer)).post(path, {"body_md": "Hi"}), 403, "forbidden")
    assert_problem(await (await api(team.outsider)).post(path, {"body_md": "Hi"}), 404, "not_found")
    for body in ({"body_md": ""}, {"body_md": "   "}, {}, {"body_md": "x" * 10_001}):
        assert_problem(await (await api(team.member)).post(path, body), 422, "validation_error")
    ok(await (await api(team.platform)).post(path, {"body_md": "From the platform admin"}), 201)
    team.project.archived_at = utcnow()
    db_session.add(team.project)
    await db_session.commit()
    assert_problem(
        await (await api(team.admin)).post(path, {"body_md": "Hi"}), 409, "project_archived"
    )


async def test_only_authors_edit_and_admins_also_delete(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    created = ok(
        await (await api(team.member)).post(f"/ideas/{idea.id}/comments", {"body_md": "Mine"}), 201
    )
    comment_id = created["comment"]["id"]
    path = f"/comments/{comment_id}"

    # How others see it.
    admin_view = ok(await (await api(team.admin)).get(f"/ideas/{idea.id}/activity"))["items"][0]
    viewer_view = ok(await (await api(team.viewer)).get(f"/ideas/{idea.id}/activity"))["items"][0]
    assert (admin_view["comment"]["can_edit"], admin_view["comment"]["can_delete"]) == (False, True)
    assert (viewer_view["comment"]["can_edit"], viewer_view["comment"]["can_delete"]) == (
        False,
        False,
    )

    for user in (team.admin, team.evaluators[0], team.viewer):
        assert_problem(
            await (await api(user)).patch(path, {"body_md": "Hijacked"}), 403, "not_author"
        )
    for user in (team.evaluators[0], team.viewer):
        assert_problem(await (await api(user)).delete(path), 403, "not_author")
    assert_problem(await (await api(team.outsider)).patch(path, {"body_md": "x"}), 404, "not_found")
    assert_problem(await (await api(team.outsider)).delete(path), 404, "not_found")
    assert_problem(
        await (await api(team.member)).patch(path, {"body_md": ""}), 422, "validation_error"
    )
    # Admins moderate.
    assert (await (await api(team.admin)).delete(path)).status_code == 204


async def test_comments_in_archived_projects_are_read_only(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    max_ = await api(team.member)
    created = ok(await max_.post(f"/ideas/{idea.id}/comments", {"body_md": "Mine"}), 201)
    team.project.archived_at = utcnow()
    db_session.add(team.project)
    await db_session.commit()
    path = f"/comments/{created['comment']['id']}"

    assert_problem(await max_.patch(path, {"body_md": "Edit"}), 409, "project_archived")
    assert_problem(await max_.delete(path), 409, "project_archived")
    item = ok(await max_.get(f"/ideas/{idea.id}/activity"))["items"][0]
    assert (item["comment"]["can_edit"], item["comment"]["can_delete"]) == (False, False)


# --- The feed --------------------------------------------------------------------------------
async def test_feed_items_resolve_people_and_values(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)
    idea = await (await api(team.member)).create_idea(team.slug, tags=["UX"])
    path = f"/ideas/{idea['id']}"
    eve = team.evaluators[0]
    due = datetime(2026, 10, 7, 17, tzinfo=UTC)
    ok(await (await api(team.member)).patch(path, {"summary": "Sharper.", "tags": ["Billing"]}))
    ok(await ada.put(f"{path}/owner", {"user_id": str(team.owner.id)}))
    ok(await ada.post(f"{path}/status", {"status": "evaluating"}))
    ok(await ada.post(f"{path}/evaluators", {"user_ids": [str(eve.id)], "due_at": due.isoformat()}))
    ok(await ada.delete(f"{path}/evaluators/{eve.id}"))
    ok(await ada.post(f"{path}/evaluation/close"))
    ok(await ada.post(f"{path}/evaluation/reopen"))
    ok(await ada.post(f"{path}/comments", {"body_md": "Go for it"}), 201)
    ok(await ada.post(f"{path}/status", {"status": "closed", "resolution": "accepted"}))

    feed = ok(await (await api(team.viewer)).get(f"{path}/activity"))

    items = feed["items"]
    assert feed["next_cursor"] is None
    assert [i["type"] for i in items] == [
        "status_changed",
        "comment",
        "evaluation_reopened",
        "evaluation_closed",
        "evaluator_removed",
        "due_date_changed",
        "evaluator_added",
        "status_changed",
        "owner_changed",
        "idea_edited",
        "idea_created",
    ]  # newest first
    by_type: dict[str, dict[str, Any]] = {}
    for item in reversed(items):
        by_type.setdefault(item["type"], item)
    assert by_type["idea_created"]["actor"]["id"] == str(team.member.id)
    assert by_type["idea_edited"]["fields"] == ["summary", "tags"]
    owner = by_type["owner_changed"]
    assert (owner["from_owner"], owner["to_owner"]["id"], owner["volunteered"]) == (
        None,
        str(team.owner.id),
        False,
    )
    assert owner["to_owner"]["display_name"] == "Olive Owner"
    assert "email" not in owner["to_owner"]
    moved = by_type["status_changed"]
    assert (moved["from_status"], moved["to_status"], moved["to_resolution"]) == (
        "new",
        "evaluating",
        None,
    )
    assert items[0]["to_resolution"] == "accepted"
    assert by_type["evaluator_added"]["evaluator"]["id"] == str(eve.id)
    assert by_type["evaluator_removed"]["evaluator"]["id"] == str(eve.id)
    changed = by_type["due_date_changed"]
    assert changed["from_due_at"] is None
    assert datetime.fromisoformat(changed["to_due_at"]) == due
    assert all(set(i) >= {"id", "idea_id", "created_at", "actor", "type"} for i in items)


async def test_feed_pages_newest_first(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    max_ = await api(team.member)
    for n in range(5):
        ok(await max_.post(f"/ideas/{idea.id}/comments", {"body_md": f"Comment {n}"}), 201)

    bodies: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = ok(await max_.get(f"/ideas/{idea.id}/activity", **params))
        bodies += [item["comment"]["body_md"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert bodies == [f"Comment {n}" for n in reversed(range(5))]
    for bad in ("garbage", "eyJ0IjogIm5vcGUiLCAiaWQiOiAxfQ"):
        response = await max_.get(f"/ideas/{idea.id}/activity", cursor=bad)
        assert_problem(response, 400, "invalid_cursor")
    assert_problem(
        await (await api(team.outsider)).get(f"/ideas/{idea.id}/activity"), 404, "not_found"
    )


async def test_feed_survives_removed_users(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ghost = await make_user(db_session, "Gone Person")
    idea = await make_idea(db_session, team.project, owner=ghost)
    ada = await api(team.admin)
    ok(await ada.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.owner.id)}))
    await db_session.delete(ghost)
    await db_session.commit()

    [item] = ok(await ada.get(f"/ideas/{idea.id}/activity"))["items"]

    assert (item["from_owner"], item["to_owner"]["id"]) == (None, str(team.owner.id))
    watchers = set(await db_session.scalars(select(IdeaWatcher.user_id)))
    assert watchers == {team.owner.id}
