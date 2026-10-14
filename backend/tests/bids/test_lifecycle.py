"""The call for bids: starting it (c27), its settings, the lifecycle and its refusals,
cancelling, deleting (c30), the feed event and the audit (contract-phase10 section 3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
from app.models.bid import BidCall, BidCallSection
from app.models.enums import IdeaStatus
from app.models.idea import Idea
from app.models.project import Project
from tests.api_keys.helpers import ALL_SCOPES, key_client, make_key
from tests.bids.conftest import (
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    call_url,
    deadline,
    ok,
    open_call,
    qualify,
    sections_by_title,
    start,
    submit,
    to_assessing,
)
from tests.factories import make_idea


async def _actions(db: AsyncSession, idea: Idea) -> list[str]:
    rows = await db.scalars(
        select(AuditLog.action)
        .where(AuditLog.target_id == idea.id, AuditLog.action.like("bid%"))
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    return list(rows)


async def _feed(db: AsyncSession, idea: Idea) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(ActivityEvent)
        .where(ActivityEvent.idea_id == idea.id, ActivityEvent.type == "bid_call_changed")
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    return [event.payload for event in rows]


# --- Starting a call (c27) ---------------------------------------------------------------
async def test_the_owner_starts_a_draft_call_with_the_projects_template(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)

    view = await start(owner, crew, description="Supply and build the pilot.", currency="EUR")

    call = view["call"]
    assert view["summary"]["status"] == "draft"
    assert view["summary"]["bid_count"] == 0
    assert (call["title"], call["currency"], call["description"]) == (
        "Data platform build",
        "EUR",
        "Supply and build the pilot.",
    )
    titles = [(s["title"], s["weight"]) for s in call["template"]["sections"]]
    assert titles == [("Technical", 40), ("Commercial", 40), ("Delivery", 20)]
    assert [m["text"] for m in call["template"]["must_haves"]] == [
        "Signed form of tender",
        "Pricing schedule",
        "Insurance certificate",
        "Accepts our standard terms",
    ]
    assert call["template"]["price_question_id"] is not None
    assert call["template"]["locked"] is False
    assert view["permissions"]["can_manage_call"] is True
    assert view["permissions"]["can_create"] is False
    assert await _feed(db_session, crew.idea) == [
        {"call_id": call["id"], "from_status": None, "to_status": "draft"}
    ]
    assert await _actions(db_session, crew.idea) == ["bid_call.create"]


async def test_one_call_per_idea(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)

    assert_problem(await owner.post(call_url(crew), {"title": "Again"}), 409, "bid_call_exists")


async def test_a_call_needs_an_idea_in_proposal_with_a_proposal(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    admin = await api(crew.admin)
    shortlisted = await make_idea(
        db_session, crew.project, status=IdeaStatus.SHORTLISTED, owner=crew.owner
    )
    no_proposal = await make_idea(
        db_session, crew.project, status=IdeaStatus.PROPOSAL, owner=crew.owner
    )
    for idea in (shortlisted, no_proposal):
        response = await admin.post(f"/ideas/TOOLS-{idea.number}/bid-call", {"title": "Call"})
        assert_problem(response, 409, "bid_call_not_available")
    # The idea page says so: no "Start a call for bids" there.
    detail = ok(await admin.get(f"/ideas/TOOLS-{no_proposal.number}"))
    assert detail["permissions"]["can_create_bid_call"] is False
    assert detail["permissions"]["can_view_bid_call"] is True  # the rule; c27 is the service's
    assert detail["bid_call"] is None


async def test_who_may_start_one(crew: Crew, api: AsUser) -> None:
    for user in (crew.member, crew.viewer, crew.tech1):
        assert_problem(
            await (await api(user)).post(call_url(crew), {"title": "C"}), 403, "forbidden"
        )
    assert_problem(
        await (await api(crew.outsider)).post(call_url(crew), {"title": "C"}), 404, "not_found"
    )
    ok(await (await api(crew.platform)).post(call_url(crew), {"title": "By a platform admin"}), 201)


async def test_a_closed_idea_or_an_archived_project_refuses(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    admin = await api(crew.admin)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status="closed", resolution="parked")
    )
    await db_session.commit()
    assert_problem(await admin.post(call_url(crew), {"title": "C"}), 409, "idea_closed")
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status="proposal", resolution=None)
    )
    await db_session.execute(
        update(Project).where(Project.id == crew.project.id).values(archived_at=datetime.now(UTC))
    )
    await db_session.commit()
    assert_problem(await admin.post(call_url(crew), {"title": "C"}), 409, "project_archived")


# --- Who sees what of it -----------------------------------------------------------------
async def test_everyone_who_sees_the_idea_sees_the_summary_only(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)

    for user in (crew.member, crew.viewer):
        view = ok(await (await api(user)).get(call_url(crew)))
        assert view["summary"]["title"] == "Data platform build"
        assert view["call"] is None
        assert view["ai_agents"] == []
        assert view["permissions"]["can_view_bids"] is False
        detail = ok(await (await api(user)).get(f"/ideas/{crew.key}"))
        assert detail["bid_call"]["title"] == "Data platform build"
        assert detail["permissions"]["can_view_bid_call"] is True
        assert detail["permissions"]["can_create_bid_call"] is False
    assert_problem(await (await api(crew.outsider)).get(call_url(crew)), 404, "not_found")


async def test_no_call_yet_is_an_empty_view(crew: Crew, api: AsUser) -> None:
    owner = ok(await (await api(crew.owner)).get(call_url(crew)))
    member = ok(await (await api(crew.member)).get(call_url(crew)))

    assert owner["summary"] is None
    assert owner["call"] is None
    assert owner["permissions"]["can_create"] is True
    assert member["permissions"]["can_create"] is False
    detail = ok(await (await api(crew.owner)).get(f"/ideas/{crew.key}"))
    assert detail["permissions"]["can_create_bid_call"] is True
    assert detail["permissions"]["can_view_bid_call"] is True
    member_detail = ok(await (await api(crew.member)).get(f"/ideas/{crew.key}"))
    assert member_detail["permissions"]["can_view_bid_call"] is False  # nothing to show yet


# --- Settings and the lifecycle ----------------------------------------------------------
async def test_opening_needs_a_deadline(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)

    assert_problem(
        await owner.post(call_url(crew, "/status"), {"status": "open"}),
        409,
        "bid_call_deadline_required",
    )
    opened = await open_call(owner, crew)
    assert opened["summary"]["status"] == "open"
    assert [e["to_status"] for e in await _feed(db_session, crew.idea)] == ["draft", "open"]


def _settings(view: dict[str, Any], **changes: Any) -> dict[str, Any]:
    call = view["call"]
    body = {
        "title": call["title"],
        "description": call["description"],
        "currency": call["currency"],
        "deadline_at": call["deadline_at"],
        "ai_assessor_id": None,
    }
    body.update(changes)
    return body


async def test_the_deadline_rules(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)

    # An open call keeps a deadline.
    response = await owner.put(call_url(crew), _settings(view, deadline_at=None))
    assert_problem(response, 409, "bid_call_deadline_required")
    # It changes while open...
    later = deadline(30)
    view = ok(await owner.put(call_url(crew), _settings(view, deadline_at=later)))
    assert view["summary"]["deadline_at"] is not None
    # ...but not once assessing (late never flips); other settings still do.
    view = await to_assessing(owner, crew)
    response = await owner.put(call_url(crew), _settings(view, deadline_at=deadline(40)))
    assert_problem(response, 409, "bid_call_not_open")
    view = ok(await owner.put(call_url(crew), _settings(view, title="Renamed", currency="USD")))
    assert (view["call"]["title"], view["call"]["currency"]) == ("Renamed", "USD")


async def test_the_moves_and_their_refusals(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    assert_problem(
        await owner.post(call_url(crew, "/status"), {"status": "assessing"}),
        409,
        "invalid_bid_call_transition",
    )
    view = await open_call(owner, crew)
    assert_problem(
        await owner.post(call_url(crew, "/status"), {"status": "open"}),
        409,
        "invalid_bid_call_transition",
    )
    view = await to_assessing(owner, crew)
    # Back to open while nobody has submitted an assessment...
    view = ok(await owner.post(call_url(crew, "/status"), {"status": "open"}))
    assert view["summary"]["status"] == "open"
    bid = await add_bid(owner, crew, "Northwind Data Ltd")
    view = await assign(owner, crew, view, {"Technical": [crew.tech1]})
    await to_assessing(owner, crew)
    tech = sections_by_title(view)["Technical"]
    await submit(await api(crew.tech1), crew, bid["id"], tech, 4)
    # ...not after.
    assert_problem(
        await owner.post(call_url(crew, "/status"), {"status": "open"}),
        409,
        "assessments_submitted",
    )
    assert [e["to_status"] for e in await _feed(db_session, crew.idea)] == [
        "draft",
        "open",
        "assessing",
        "open",
        "assessing",
    ]
    statuses: list[str] = list(
        await db_session.scalars(
            select(AuditLog.details["to_status"].astext).where(
                AuditLog.action == "bid_call.status_change"
            )
        )
    )
    assert statuses == ["open", "assessing", "open", "assessing"]


async def test_members_and_assessors_cannot_move_it(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    await assign(owner, crew, view, {"Technical": [crew.tech1]})
    for user in (crew.member, crew.tech1):
        response = await (await api(user)).post(call_url(crew, "/status"), {"status": "open"})
        assert_problem(response, 403, "forbidden")


async def test_cancel_makes_it_read_only(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)

    view = ok(await owner.post(call_url(crew, "/cancellation"), {"reason": "Budget withdrawn."}))

    assert view["summary"]["status"] == "cancelled"
    assert view["call"]["cancel_reason"] == "Budget withdrawn."
    assert view["permissions"]["can_manage_call"] is False
    assert_problem(await owner.post(call_url(crew, "/cancellation"), {}), 409, "bid_call_finished")
    assert_problem(
        await owner.put(call_url(crew), _settings(view, title="X")), 409, "bid_call_finished"
    )
    assert_problem(
        await owner.post(call_url(crew, "/bids"), {"bidder": "Late Ltd"}), 409, "bid_call_finished"
    )
    # The reason is the call managers'.
    assessor_view = ok(await (await api(crew.member)).get(call_url(crew)))
    assert assessor_view["call"] is None
    assert (await _feed(db_session, crew.idea))[-1]["to_status"] == "cancelled"


async def test_closing_the_idea_makes_the_call_read_only_for_everyone(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Review M1 (contract section 3.1): closing the idea makes everything read-only, the
    assessors' writes too (409 ``idea_closed``, before the call's own state); reopening the
    idea lets the call go on where it stood."""
    owner = await api(crew.owner)
    view = await start(owner, crew)
    view = await open_call(owner, crew, view)
    bid = await add_bid(owner, crew, "Alpha Ltd")
    await qualify(db_session, bid["id"], crew.owner)
    view = await assign(owner, crew, view, {"Technical": [crew.tech1, crew.tech2]})
    await to_assessing(owner, crew)
    tech = sections_by_title(view)["Technical"]
    assessment = call_url(crew, f"/bids/{bid['id']}/sections/{tech['id']}/assessment")
    answers = [{"question_id": q["id"], "score": 4} for q in tech["questions"] if q["type"] == "score"]
    closed = {"status": "closed", "resolution": "parked"}
    ok(await owner.post(f"/ideas/{crew.key}/status", closed))

    tech1 = await api(crew.tech1)
    for submit_it in (True, False):
        response = await tech1.put(assessment, {"answers": answers, "submit": submit_it})
        assert_problem(response, 409, "idea_closed")
    for path, body in (
        ("/cancellation", {}),
        ("/award", {"bid_id": bid["id"]}),
        ("/status", {"status": "open"}),
    ):
        assert_problem(await owner.post(call_url(crew, path), body), 409, "idea_closed")

    ok(await owner.post(f"/ideas/{crew.key}/status", {"status": "proposal"}))
    ok(await tech1.put(assessment, {"answers": answers, "submit": True}))


async def test_deleting_a_call(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    await open_call(owner, crew)

    # Open (or assessing): cancel first.
    assert_problem(await owner.delete(call_url(crew)), 409, "bid_call_active")
    ok(await owner.post(call_url(crew, "/cancellation"), {}))
    assert (await owner.delete(call_url(crew))).status_code == 204

    assert await db_session.scalar(select(BidCall).where(BidCall.idea_id == crew.idea.id)) is None
    assert "bid_call.delete" in await _actions(db_session, crew.idea)
    # The idea is free for a new call, and the feed's old events read the call as gone.
    await start(owner, crew)
    feed = ok(await owner.get(f"/ideas/{crew.key}/activity"))
    bid_events = [item for item in feed["items"] if item["type"] == "bid_call_changed"]
    assert {item["call"] is None for item in bid_events} == {True, False}


async def test_an_awarded_call_is_deleted_by_a_platform_admin_only(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Northwind Data Ltd")
    await qualify(db_session, bid["id"], crew.owner)
    await to_assessing(owner, crew)
    ok(await owner.post(call_url(crew, "/award"), {"bid_id": bid["id"]}))

    for user in (crew.owner, crew.admin):
        assert_problem(await (await api(user)).delete(call_url(crew)), 409, "bid_call_active")
    assert (await (await api(crew.platform)).delete(call_url(crew))).status_code == 204


async def test_a_draft_call_is_deleted_also_on_a_closed_idea(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status="closed", resolution="parked")
    )
    await db_session.commit()

    assert_problem(
        await owner.post(call_url(crew, "/status"), {"status": "open"}), 409, "idea_closed"
    )
    assert (await owner.delete(call_url(crew))).status_code == 204


async def test_deleting_and_deciding_need_a_session(
    crew: Crew, api: AsUser, app: FastAPI, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    key = await make_key(db_session, crew.owner, scopes=ALL_SCOPES)
    async with key_client(app, key) as http:
        for method, path, body in (
            ("DELETE", call_url(crew), None),
            ("POST", call_url(crew, "/cancellation"), {}),
            ("POST", call_url(crew, "/award"), {"bid_id": str(UUID(int=1))}),
        ):
            response = await http.request(method, "/api/v1" + path, json=body)
            assert_problem(response, 403, "insufficient_scope")
        # Managing through a write key is allowed.
        response = await http.post("/api/v1" + call_url(crew, "/status"), json={"status": "open"})
        assert_problem(response, 409, "bid_call_deadline_required")


async def test_bid_writes_never_touch_the_ideas_activity(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    await open_call(owner, crew)
    before = await db_session.scalar(
        select(Idea.last_activity_at)
        .where(Idea.id == crew.idea.id)
        .execution_options(populate_existing=True)
    )
    await add_bid(owner, crew, "Northwind Data Ltd")
    await add_bid(owner, crew, "Tessellate Software")
    after = await db_session.scalar(
        select(Idea.last_activity_at)
        .where(Idea.id == crew.idea.id)
        .execution_options(populate_existing=True)
    )
    assert after == before


async def test_the_call_copies_the_template_and_later_changes_dont_touch_it(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    admin = await api(crew.admin)
    view = await start(admin, crew)
    template = ok(await admin.get(f"/projects/{crew.project.slug}/bid-template"))
    body = {
        "scale": template["scale"],
        "sections": [
            {
                "title": "Everything",
                "weight": 100,
                "questions": [{"text": "Good?", "type": "score"}],
            }
        ],
        "must_haves": [],
    }
    ok(await admin.put(f"/projects/{crew.project.slug}/bid-template", body))

    again = ok(await admin.get(call_url(crew)))
    assert again["call"]["template"] == view["call"]["template"]
    count = await db_session.scalar(
        select(BidCallSection.id).where(BidCallSection.call_id == UUID(view["call"]["id"])).limit(1)
    )
    assert count is not None
    assert datetime.now(UTC) - timedelta(minutes=5) < datetime.fromisoformat(
        again["call"]["created_at"]
    )


async def test_the_feed_event_reaches_viewers_not_a_guest_researcher(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    from app.models.enums import ResearchStep
    from tests.factories import set_researcher

    owner = await api(crew.owner)
    view = await start(owner, crew)
    await db_session.execute(
        update(Project)
        .where(Project.id == crew.project.id)
        .values(research_step=ResearchStep.BEFORE_PROPOSAL)
    )
    await db_session.commit()
    await set_researcher(db_session, crew.idea, crew.outsider)

    viewer_feed = ok(await (await api(crew.viewer)).get(f"/ideas/{crew.key}/activity"))
    guest_feed = ok(await (await api(crew.outsider)).get(f"/ideas/{crew.key}/activity"))

    [event] = [i for i in viewer_feed["items"] if i["type"] == "bid_call_changed"]
    assert event["call"] == {
        "id": view["call"]["id"],
        "title": "Data platform build",
        "status": "draft",
    }
    assert (event["from_status"], event["to_status"]) == (None, "draft")
    assert all(i["type"] != "bid_call_changed" for i in guest_feed["items"])
    guest_detail = ok(await (await api(crew.outsider)).get(f"/ideas/{crew.key}"))
    assert guest_detail["bid_call"] is None
