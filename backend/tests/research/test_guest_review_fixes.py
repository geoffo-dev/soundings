"""Phase 8b review fixes for the guest researcher (role matrix column R, table L).

* Guest review L1: ``last_activity_at`` must not time the events a guest's feed leaves out
  (an evaluation submitted, an evaluator invited): wherever the guest sees one of their
  ideas (the idea, MCP ``get_idea`` / ``search_ideas``, Similar ideas) it is the time of
  the newest event of their feed, and the guest's lists sort on that same value (⌘K's
  most recently active first, MCP ``sort=updated``), so polling them can't count or time
  the hidden events either.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.enums import IdeaStatus, ProjectRole
from app.models.idea import Idea
from app.schemas.activity import RESEARCH_GUEST_ACTIVITY_TYPES
from tests.factories import make_idea, make_project
from tests.mcp.conftest import AsAgent
from tests.research.conftest import AsUser, Team, assign, key_of, ok
from tests.research.test_guest_access import DUE, READ, Scene
from tests.research.test_guest_access import scene as scene


async def _guest_seen_at(db: AsyncSession, idea: Idea) -> datetime:
    """The newest event of the idea's guest feed."""
    found = await db.scalar(
        select(func.max(ActivityEvent.created_at)).where(
            ActivityEvent.idea_id == idea.id,
            ActivityEvent.type.in_(sorted(RESEARCH_GUEST_ACTIVITY_TYPES)),
        )
    )
    assert found is not None
    return found


async def _hidden_event(db: AsyncSession, idea: Idea, at: datetime) -> None:
    """An evaluation submitted at ``at`` (left out of the guest's feed), as the app records
    one: the event and ``ideas.last_activity_at``."""
    db.add(
        ActivityEvent(
            id=uuid4(),
            project_id=idea.project_id,
            idea_id=idea.id,
            actor_id=None,
            type="evaluation_submitted",
            payload={"evaluator_id": str(uuid4())},
            created_at=at,
        )
    )
    await db.execute(update(Idea).where(Idea.id == idea.id).values(last_activity_at=at))
    await db.commit()


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def test_last_activity_shows_the_guest_only_their_feed(
    api: AsUser, as_agent: AsAgent, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    seen = await _guest_seen_at(db_session, scene.idea)
    hidden = utcnow() + timedelta(minutes=5)
    await _hidden_event(db_session, scene.idea, hidden)
    guest = await api(scene.guest)
    agent = await as_agent(scene.guest, READ)

    detail = ok(await guest.get(f"/ideas/{scene.key}"))
    member = ok(await (await api(team.member)).get(f"/ideas/{scene.key}"))
    mcp_idea = (await agent.ok("get_idea", idea=scene.key))["idea"]
    (mcp_summary,) = (await agent.ok("search_ideas", query="refunds"))["items"]

    assert _at(member["last_activity_at"]) == hidden
    for someone in (team.admin, team.platform, team.owner):  # every column but R: the column
        seen_by = ok(await (await api(someone)).get(f"/ideas/{scene.key}"))
        assert _at(seen_by["last_activity_at"]) == hidden
    assert _at(detail["last_activity_at"]) == seen
    assert _at(mcp_idea["last_activity_at"]) == seen
    assert _at(mcp_summary["last_activity_at"]) == seen
    # What the guest sees still moves with what they can see: a comment.
    ok(await guest.post(f"/ideas/{scene.key}/comments", {"body_md": "Asked Legal."}), 201)
    after = ok(await guest.get(f"/ideas/{scene.key}"))
    assert seen < _at(after["last_activity_at"]) == await _guest_seen_at(db_session, scene.idea)


async def test_the_guests_lists_sort_on_what_they_see(
    api: AsUser, as_agent: AsAgent, scene: Scene, db_session: AsyncSession
) -> None:
    """Their own project's idea was active after the newest event the guest sees on the
    researched idea, and before its hidden one: it comes first in their lists."""
    theirs = await make_project(db_session, key="OWN", members={scene.guest: ProjectRole.MEMBER})
    own = await make_idea(db_session, theirs, title="Self-service refunds kiosk")
    seen = await _guest_seen_at(db_session, scene.idea)
    await db_session.execute(
        update(Idea).where(Idea.id == own.id).values(last_activity_at=seen + timedelta(minutes=1))
    )
    await _hidden_event(db_session, scene.idea, seen + timedelta(minutes=2))
    guest = await api(scene.guest)
    agent = await as_agent(scene.guest, READ)
    expected = [key_of(theirs, own), scene.key]

    # ⌘K: one or two letters list the most recently active matches first.
    short = ok(await guest.get("/search", q="se"))
    by_update = await agent.ok("search_ideas", sort="-updated")
    oldest_first = await agent.ok("search_ideas", sort="updated")
    paged = await agent.ok("search_ideas", sort="-updated", limit=1)
    rest = await agent.ok("search_ideas", sort="-updated", limit=1, cursor=paged["next_cursor"])

    assert [idea["key"] for idea in short["ideas"]] == expected
    assert [idea["key"] for idea in by_update["items"]] == expected
    assert [idea["key"] for idea in oldest_first["items"]] == expected[::-1]
    assert [idea["key"] for idea in paged["items"] + rest["items"]] == expected


async def test_similar_ideas_show_a_researched_ideas_guest_activity(
    api: AsUser, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    second = await make_idea(
        db_session,
        team.project,
        owner=team.owner,
        status=IdeaStatus.NEW,
        title="Self-service refunds portal for shops",
    )
    second_key = key_of(team.project, second)
    ok(await assign(await api(team.admin), second_key, scene.guest, DUE))
    seen = await _guest_seen_at(db_session, second)
    hidden = utcnow() + timedelta(minutes=5)
    await _hidden_event(db_session, second, hidden)

    similar = ok(await (await api(scene.guest)).get(f"/ideas/{scene.key}/similar-ideas"))
    admin_view = ok(await (await api(team.admin)).get(f"/ideas/{scene.key}/similar-ideas"))

    (item,) = [item for item in similar["items"] if item["key"] == second_key]
    (admin_item,) = [item for item in admin_view["items"] if item["key"] == second_key]
    assert _at(item["last_activity_at"]) == seen
    assert _at(admin_item["last_activity_at"]) == hidden
