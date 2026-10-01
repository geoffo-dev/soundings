"""Held ideas (contract-phase4 section 3.6; role matrix c12, c19), through the API: an
idea held for moderation or email confirmation is in no list, board, count, search,
tag list, My work or inbox for anyone; admins open one held for moderation by its link
(read-only: every permission false but can_delete) and nobody can open one held for
confirmation; writes on a held idea are 409 ``awaiting_moderation``."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import (
    HoldReason,
    NotificationMode,
    NotificationType,
    ProjectVisibility,
)
from app.models.idea import Idea, IdeaEvaluator, IdeaTag
from app.models.notification import Notification
from app.models.project import Project, Tag
from app.models.user import User
from tests.factories import make_idea
from tests.public.conftest import (
    AsUser,
    Team,
    assert_problem,
    make_public_idea,
    ok,
)

pytestmark = pytest.mark.usefixtures("form")

HELD = "HELD idea"


async def world(db: AsyncSession, settings: Settings, team: Team, user: User) -> dict[str, Idea]:
    """An internal project (so the outsider is an internal non-member) with one visible
    idea and two held ones, all owned by, assigned to, tagged and notified to ``user``
    (states the API would never allow for held ideas: the filters must still hold)."""
    await db.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    tag = Tag(id=uuid4(), project_id=team.project.id, name="returns")
    db.add(tag)
    await db.commit()
    visible = await make_idea(db, team.project, title="Visible idea")
    _, moderation = await make_public_idea(
        db, settings, team, title=f"{HELD} for review", held_for=HoldReason.MODERATION
    )
    _, verification = await make_public_idea(
        db,
        settings,
        team,
        title=f"{HELD} for confirmation",
        held_for=HoldReason.EMAIL_VERIFICATION,
        email="jo@example.org",
    )
    ideas = {"visible": visible, "moderation": moderation, "verification": verification}
    for n, idea in enumerate(ideas.values()):
        await db.execute(update(Idea).where(Idea.id == idea.id).values(owner_id=user.id))
        db.add(IdeaTag(idea_id=idea.id, tag_id=tag.id))
        db.add(IdeaEvaluator(idea_id=idea.id, user_id=user.id))
        db.add(
            Notification(
                id=uuid4(),
                user_id=user.id,
                type=NotificationType.STATUS_CHANGED,
                idea_id=idea.id,
                payload={
                    "from_status": "new",
                    "from_resolution": None,
                    "to_status": "new",
                    "to_resolution": None,
                },
                dedupe_key=f"test:{n}",
                email_mode=NotificationMode.OFF,
            )
        )
    await db.commit()
    return ideas


WHO = ["member", "viewer", "outsider", "admin", "platform"]


def person(team: Team, who: str) -> User:
    user: User = getattr(team, who)
    return user


@pytest.mark.parametrize("who", WHO)
async def test_held_ideas_are_listed_nowhere(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, who: str
) -> None:
    user = person(team, who)
    await world(db_session, settings, team, user)
    client = await api(user)
    slug = team.slug

    responses: dict[str, Any] = {
        "list": ok(await client.get(f"/projects/{slug}/ideas")),
        "board": ok(await client.get(f"/projects/{slug}/board")),
        "search": ok(await client.get("/search", q="idea")),
        "work": ok(await client.get("/me/work")),
        "owned": ok(await client.get("/me/owned-ideas", status="new")),
        "tags": ok(await client.get(f"/projects/{slug}/tags")),
        "project": ok(await client.get(f"/projects/{slug}")),
        "projects": ok(await client.get("/projects")),
        "inbox": ok(await client.get("/me/notifications")),
        "summary": ok(await client.get("/me/notifications/summary")),
    }

    for name, body in responses.items():
        assert HELD not in str(body), name
    assert responses["list"]["total"] == 1
    [new] = [c for c in responses["board"]["columns"] if c["status"] == "new"]
    assert new["count"] == 1
    assert [i["title"] for i in responses["search"]["ideas"]] == ["Visible idea"]
    assert [(t["name"], t["idea_count"]) for t in responses["tags"]] == [("returns", 1)]
    assert responses["project"]["idea_count"] == 1
    assert [i["title"] for i in responses["owned"]["items"]] == ["Visible idea"]
    assert [n["idea"]["title"] for n in responses["inbox"]["items"]] == ["Visible idea"]
    assert responses["summary"]["unread_count"] == 1


@pytest.mark.parametrize("who", ["member", "viewer", "outsider"])
async def test_an_idea_held_for_moderation_is_404_for_non_admins(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, who: str
) -> None:
    ideas = await world(db_session, settings, team, person(team, who))
    client = await api(person(team, who))
    held = ideas["moderation"]

    for path in (
        f"/ideas/{held.id}",
        f"/ideas/CUST-{held.number}",
        f"/ideas/{held.id}/activity",
        f"/ideas/{held.id}/evaluations",
    ):
        assert_problem(await client.get(path), 404, "not_found")


@pytest.mark.parametrize("who", ["admin", "platform"])
async def test_admins_open_an_idea_held_for_moderation_read_only(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, who: str
) -> None:
    ideas = await world(db_session, settings, team, person(team, who))
    client = await api(person(team, who))
    held = ideas["moderation"]

    body = ok(await client.get(f"/ideas/{held.id}"))

    assert body["title"] == f"{HELD} for review"
    assert body["submitted_by"] is None
    assert {k for k, v in body["permissions"].items() if v} == {"can_delete"}
    assert ok(await client.get(f"/ideas/{held.id}/activity"))


@pytest.mark.parametrize("who", WHO)
async def test_an_idea_held_for_confirmation_is_404_for_everyone(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, who: str
) -> None:
    ideas = await world(db_session, settings, team, person(team, who))
    client = await api(person(team, who))
    held = ideas["verification"]

    assert_problem(await client.get(f"/ideas/{held.id}"), 404, "not_found")
    assert_problem(await client.get(f"/ideas/CUST-{held.number}"), 404, "not_found")
    assert_problem(await client.delete(f"/ideas/{held.id}"), 404, "not_found")


WRITES: list[tuple[str, str, Any]] = [
    ("PATCH", "", {"title": "Edited"}),
    ("POST", "/status", {"status": "evaluating"}),
    ("PUT", "/owner", {"user_id": None}),
    ("POST", "/volunteer", None),
    ("POST", "/evaluators", {"user_ids": []}),
    ("PUT", "/evaluation/due-date", {"due_at": None}),
    ("POST", "/evaluation/close", None),
    ("PUT", "/vote", None),
    ("PUT", "/watch", None),
    ("POST", "/comments", {"body_md": "Looks like spam"}),
]


@pytest.mark.parametrize("who", ["admin", "platform"])
@pytest.mark.parametrize(("method", "suffix", "body"), WRITES)
async def test_idea_writes_on_an_idea_held_for_moderation_are_409(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    who: str,
    method: str,
    suffix: str,
    body: Any,
) -> None:
    ideas = await world(db_session, settings, team, person(team, who))
    client = await api(person(team, who))
    if body == {"user_ids": []}:
        body = {"user_ids": [str(team.evaluators[0].id)]}

    response = await client.http.request(
        method, f"/api/v1/ideas/{ideas['moderation'].id}{suffix}", json=body
    )

    if (method, suffix) == ("POST", "/volunteer") and who == "platform":
        # A platform admin without a project role can't volunteer anyway (c4, 422).
        assert response.status_code in (409, 422), response.text
    else:
        assert_problem(response, 409, "awaiting_moderation")


async def test_an_admin_may_delete_an_idea_held_for_moderation(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, held = await make_public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)

    response = await (await api(team.admin)).delete(f"/ideas/{held.id}")

    assert response.status_code == 204


async def test_a_released_idea_appears_in_new(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, held = await make_public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)
    member = await api(team.member)
    assert ok(await member.get(f"/projects/{team.slug}/ideas"))["total"] == 0

    await db_session.execute(update(Idea).where(Idea.id == held.id).values(held_for=None))
    await db_session.commit()

    listed = ok(await member.get(f"/projects/{team.slug}/ideas"))
    assert [i["title"] for i in listed["items"]] == ["Recycle packaging at the till"]
    assert ok(await member.get(f"/ideas/{held.id}"))["permissions"]["can_comment"] is True
