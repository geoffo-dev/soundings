"""Phase 10 notifications (contract-phase10 section 11; role matrix 3a rule 5): "Asked to
assess bids" (``assessor_assigned``) and "Bid assessments complete" (``assessments_complete``)
end to end, with what the inbox and emails may say.

* "Asked to assess bids": to each person a request adds to sections (never the actor), one
  per request whatever the number of sections; the inbox item (the call, the sections they
  assess now, the due date); the email (subject, the Bids tab link, never a bidder, price or
  score); hidden and cancelled at send time once they no longer assess the call (removed,
  or gone from the private project, even as the idea's researcher).
* "Bid assessments complete": once nothing expected is outstanding (after the last
  submission, a rejection, an assessor removed), to the idea's owner and the call's creator
  only (not the actor), once per call, with counts only; never to someone who no longer
  manages the call.
* Preferences, the digest line and unsubscribe scoping for the bid types.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import (
    EmailStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
)
from app.models.notification import Notification, NotificationPreference
from app.models.project import ProjectMember
from app.models.user import User
from app.notifications.schedule import build_digests
from tests.bids.conftest import (
    Crew,
    add_bid,
    assign,
    call_url,
    open_call,
    qualify,
    sections_by_title,
    start,
    submit,
    to_assessing,
)
from tests.factories import set_researcher
from tests.notifications.conftest import (
    API,
    Api,
    AsUser,
    Outbox,
    RecordingTransport,
    ok,
    only,
)

ASSIGNED = NotificationType.ASSESSOR_ASSIGNED
COMPLETE = NotificationType.ASSESSMENTS_COMPLETE
DUE = "2026-12-11T17:00:00+00:00"
BIDDERS = ("Northwind Data Ltd", "Tessellate Software")
PRICES = ("120000", "120,000", "96000", "96,000")
SCORE_VALUE = re.compile(r"\b[0-5]\.[0-9]\b|\b\d{1,3}\.\d\s*%|total|ranking|rank\b", re.I)


async def _send_all(outbox: Outbox, runtime: Runtime) -> None:
    for email in await outbox.emails():
        if email.status is EmailStatus.QUEUED:
            await delivery.send_email(runtime, email.id)


def _bodies(message: Any) -> tuple[str, str, str]:
    html = message.get_body(("html",))
    text = message.get_body(("plain",))
    assert html is not None
    assert text is not None
    return str(message["Subject"]), html.get_content(), text.get_content()


def _no_bid_data(*bodies: str) -> None:
    """Role matrix 3a rule 5: no bidder, price or score in what a notification says."""
    for body in bodies:
        for bidder in BIDDERS:
            assert bidder not in body
        for price in PRICES:
            assert price not in body
        visible = re.sub(r"<[^>]*>", " ", re.sub(r"(?s)<(style|head)\b.*?</\1>", " ", body))
        assert not SCORE_VALUE.search(visible), SCORE_VALUE.search(visible)


async def _call_with_bids(crew: Crew, api: AsUser, db: AsyncSession) -> tuple[Api, dict[str, Any]]:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    for bidder, price in zip(BIDDERS, ("120000.00", "96000.00"), strict=True):
        bid = await add_bid(owner, crew, bidder, price=price)
        await qualify(db, bid["id"], crew.owner)
    return owner, view


def _technical_only(people: list[User]) -> dict[str, list[User]]:
    return {"Technical": people}


# --- "Asked to assess bids" ------------------------------------------------------------------
async def test_asked_to_assess_bids_end_to_end(
    crew: Crew,
    api: AsUser,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    owner, view = await _call_with_bids(crew, api, db_session)

    view = await assign(owner, crew, view, {"Technical": [crew.tech1, crew.owner]}, due_at=DUE)

    note = only(await outbox.notifications(crew.tech1.id, ASSIGNED))
    assert await outbox.notifications(crew.owner.id, ASSIGNED) == []  # never the actor
    assert note.actor_id == crew.owner.id
    assert note.idea_id == crew.idea.id
    assert note.email_mode is NotificationMode.IMMEDIATE
    assert note.dedupe_key.startswith(f"assessor_assigned:{view['call']['id']}:")
    assert set(note.payload) == {"call_id", "due_at"}
    items = ok(await (await api(crew.tech1)).get("/me/notifications"))["items"]
    (item,) = items
    assert item["type"] == "assessor_assigned"
    assert item["call"] == {
        "id": view["call"]["id"],
        "title": "Data platform build",
        "status": "open",
    }
    assert item["sections"] == ["Technical"]
    assert item["due_at"].startswith("2026-12-11T17:00:00")
    assert item["actor"]["id"] == str(crew.owner.id)

    await _send_all(outbox, runtime)
    subject, html, text = _bodies(only(transport.messages))
    assert subject == f'[{crew.key}] Please assess the bids for "Data platform build" by Fri 11 Dec'
    for body in (html, text):
        assert "Kenji Owner asked you to assess the bids" in body
        assert f"/ideas/{crew.key}?tab=bids" in body
        assert "Technical" in body
        assert "Due Fri 11 Dec" in body
        assert "You're assessing bids for" in body.replace("&#39;", "'")
    _no_bid_data(subject, html, text)

    # A second request adding them to another section: another one; a request that adds
    # nobody (the due date only): none.
    await assign(
        owner,
        crew,
        view,
        {"Technical": [crew.tech1, crew.owner], "Delivery": [crew.tech1]},
        due_at=DUE,
    )
    await assign(
        owner,
        crew,
        view,
        {"Technical": [crew.tech1, crew.owner], "Delivery": [crew.tech1]},
        due_at="2026-12-12T17:00:00+00:00",
    )
    assert len(await outbox.notifications(crew.tech1.id, ASSIGNED)) == 2
    items = ok(await (await api(crew.tech1)).get("/me/notifications"))["items"]
    assert [i["sections"] for i in items] == [["Technical", "Delivery"]] * 2


async def test_the_request_ends_with_the_assignment(
    crew: Crew,
    api: AsUser,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    owner, view = await _call_with_bids(crew, api, db_session)
    await assign(owner, crew, view, _technical_only([crew.tech1, crew.tech2]))
    member = await api(crew.tech1)
    summary = ok(await member.get("/me/notifications/summary"))
    assert summary["unread_count"] == 1

    # Removed before it was emailed: gone from the inbox and the email is cancelled.
    await assign(owner, crew, view, _technical_only([crew.tech2]))
    assert ok(await member.get("/me/notifications"))["items"] == []
    assert ok(await member.get("/me/notifications/summary"))["unread_count"] == 0

    # Mateo leaves the private project, though he researches the idea (column R): the
    # same (bid types never reach a guest researcher).
    await set_researcher(db_session, crew.idea, crew.tech2)
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == crew.project.id, ProjectMember.user_id == crew.tech2.id
        )
    )
    await db_session.commit()
    other = await api(crew.tech2)
    assert [
        i["type"] for i in ok(await other.get("/me/notifications"))["items"]
    ] == []  # nothing of the call
    await _send_all(outbox, runtime)
    assert transport.messages == []
    emails = await outbox.emails()
    assert [e.status for e in emails] == [EmailStatus.CANCELLED, EmailStatus.CANCELLED]


# --- "Bid assessments complete" ----------------------------------------------------------------
async def _assessing(
    crew: Crew, api: AsUser, db: AsyncSession, *, starter: User | None = None
) -> tuple[Api, dict[str, Any], list[dict[str, Any]]]:
    starter = starter or crew.owner
    manager = await api(starter)
    await start(manager, crew)
    view = await open_call(manager, crew)
    bids = []
    for bidder, price in zip(BIDDERS, ("120000.00", "96000.00"), strict=True):
        bid = await add_bid(manager, crew, bidder, price=price)
        await qualify(db, bid["id"], starter)
        bids.append(bid)
    view = await assign(
        manager,
        crew,
        view,
        {"Technical": [crew.tech1], "Delivery": [crew.delivery]},
        due_at=DUE,
    )
    await to_assessing(manager, crew)
    return manager, view, bids


async def test_complete_after_the_last_submission(
    crew: Crew,
    api: AsUser,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    admin, view, bids = await _assessing(crew, api, db_session, starter=crew.admin)
    sections = sections_by_title(view)
    tech, delivery = await api(crew.tech1), await api(crew.delivery)
    await submit(tech, crew, bids[0]["id"], sections["Technical"], 4)
    await submit(tech, crew, bids[1]["id"], sections["Technical"], 3)
    await submit(delivery, crew, bids[0]["id"], sections["Delivery"], 5)
    assert await outbox.notifications(type_=COMPLETE) == []
    await submit(delivery, crew, bids[1]["id"], sections["Delivery"], 2, final=False)
    assert await outbox.notifications(type_=COMPLETE) == []  # a draft isn't in

    await submit(delivery, crew, bids[1]["id"], sections["Delivery"], 2)

    notes = await outbox.notifications(type_=COMPLETE)
    # The idea's owner and the call's creator (an admin here); not the actor.
    assert sorted(n.user_id for n in notes) == sorted([crew.owner.id, crew.admin.id])
    for note in notes:
        assert note.actor_id == crew.delivery.id
        assert note.payload == {
            "call_id": view["call"]["id"],
            "bid_count": 2,
            "assessment_count": 4,
        }
        assert note.dedupe_key == f"assessments_complete:{view['call']['id']}"
    item = only(ok(await (await api(crew.owner)).get("/me/notifications"))["items"])
    assert item["type"] == "assessments_complete"
    assert (item["bid_count"], item["assessment_count"]) == (2, 4)
    assert item["call"]["status"] == "assessing"

    # Once per call: an edit after submitting sends nothing more.
    await submit(delivery, crew, bids[1]["id"], sections["Delivery"], 3)
    assert len(await outbox.notifications(type_=COMPLETE)) == 2

    await _send_all(outbox, runtime)
    messages = {str(m["To"]): m for m in transport.messages}
    subject, html, text = _bodies(messages[crew.owner.email])
    assert subject == f'[{crew.key}] All bid assessments are in for "Data platform build"'
    for body in (html, text):
        assert "2 assessments" not in body
        assert "4 assessments of 2 bids" in body
        assert f"/ideas/{crew.key}?tab=bids" in body
        assert "You're the owner of" in body.replace("&#39;", "'")
    _no_bid_data(subject, html, text)
    _, html, _ = _bodies(messages[crew.admin.email])
    assert "You started the call for bids on" in html.replace("&#39;", "'")
    del admin


async def test_complete_after_a_rejection(
    crew: Crew, api: AsUser, db_session: AsyncSession, outbox: Outbox
) -> None:
    owner, view, bids = await _assessing(crew, api, db_session)
    sections = sections_by_title(view)
    tech = await api(crew.tech1)
    for bid in bids:
        await submit(tech, crew, bid["id"], sections["Technical"], 4)
    delivery = await api(crew.delivery)
    await submit(delivery, crew, bids[0]["id"], sections["Delivery"], 4)
    assert await outbox.notifications(type_=COMPLETE) == []

    # Sven still owes the second bid: rejecting it leaves nothing outstanding.
    admin = await api(crew.admin)
    ok(
        await admin.put(
            call_url(crew, f"/bids/{bids[1]['id']}/rejection"), {"reason": "No insurance."}
        )
    )

    (note,) = await outbox.notifications(type_=COMPLETE)
    assert (note.user_id, note.actor_id) == (crew.owner.id, crew.admin.id)
    # Counts over the bids that aren't rejected (Carol's assessment of it isn't counted).
    assert (note.payload["bid_count"], note.payload["assessment_count"]) == (1, 2)
    assert "No insurance" not in str(note.payload)
    del owner


async def test_complete_when_the_last_pending_assessor_is_removed(
    crew: Crew, api: AsUser, db_session: AsyncSession, outbox: Outbox
) -> None:
    owner, view, bids = await _assessing(crew, api, db_session)
    sections = sections_by_title(view)
    with_vera = {"Technical": [crew.tech1], "Delivery": [crew.delivery, crew.delivery_viewer]}
    view = await assign(owner, crew, view, with_vera, due_at=DUE)
    for user, title in ((crew.tech1, "Technical"), (crew.delivery, "Delivery")):
        who = await api(user)
        for bid in bids:
            await submit(who, crew, bid["id"], sections[title], 4)
    assert await outbox.notifications(type_=COMPLETE) == []  # Vera owes both

    admin = await api(crew.admin)
    await assign(
        admin, crew, view, {"Technical": [crew.tech1], "Delivery": [crew.delivery]}, due_at=DUE
    )

    (note,) = await outbox.notifications(type_=COMPLETE)
    assert (note.user_id, note.actor_id) == (crew.owner.id, crew.admin.id)
    # Outstanding again (a new assessor), then complete again: still once per call.
    await assign(admin, crew, view, with_vera, due_at=DUE)
    await assign(
        admin, crew, view, {"Technical": [crew.tech1], "Delivery": [crew.delivery]}, due_at=DUE
    )
    assert [n.id for n in await outbox.notifications(type_=COMPLETE)] == [note.id]


async def test_complete_reaches_only_a_call_manager(
    crew: Crew, api: AsUser, db_session: AsyncSession, outbox: Outbox
) -> None:
    owner, view, bids = await _assessing(crew, api, db_session)
    sections = sections_by_title(view)
    for user, title in ((crew.tech1, "Technical"), (crew.delivery, "Delivery")):
        who = await api(user)
        for bid in bids:
            await submit(who, crew, bid["id"], sections[title], 4)
    assert len(await outbox.notifications(crew.owner.id, COMPLETE)) == 1
    me = await api(crew.owner)
    assert len(ok(await me.get("/me/notifications"))["items"]) == 1

    # The owner becomes a viewer: no longer a call manager, so the item is gone.
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.project_id == crew.project.id, ProjectMember.user_id == crew.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()
    assert ok(await me.get("/me/notifications"))["items"] == []
    del owner


# --- Preferences, the digest, unsubscribe -----------------------------------------------------
async def test_preferences_digest_and_unsubscribe(
    app: FastAPI,
    crew: Crew,
    api: AsUser,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    settings: Settings,
    client: httpx.AsyncClient,
) -> None:
    member = await api(crew.tech1)
    prefs = ok(await member.get("/me/notification-preferences"))
    modes = {row["type"]: row["mode"] for row in prefs["items"]}
    assert [row["type"] for row in prefs["items"]][-3:] == [
        "assessor_assigned",
        "assessment_reminder",
        "assessments_complete",
    ]
    assert {modes[t] for t in ("assessor_assigned", "assessment_reminder")} == {"immediate"}
    ok(await member.patch("/me/notification-preferences", {"assessor_assigned": "digest"}))

    owner, view = await _call_with_bids(crew, api, db_session)
    await assign(owner, crew, view, _technical_only([crew.tech1, crew.tech2]), due_at=DUE)
    assert await outbox.emails(crew.tech1.id) == []  # digest: nothing now
    # Mateo's immediate email was queued; he turns the type off before it goes: cancelled.
    db_session.add(
        NotificationPreference(user_id=crew.tech2.id, type=ASSIGNED, mode=NotificationMode.OFF)
    )
    await db_session.commit()
    any_hour = settings.model_copy(update={"digest_hour": 0})
    assert await build_digests(app.state.sessionmaker, any_hour, utcnow()) == 1
    await _send_all(outbox, runtime)
    by_to = {str(m["To"]): m for m in transport.messages}
    assert crew.tech2.email not in by_to  # turned off before the send: cancelled
    subject, html, text = _bodies(by_to[crew.tech1.email])
    assert subject.startswith("Soundings digest")
    assert (
        "Kenji Owner asked you to assess the bids in “Data platform build” (due Fri 11 Dec)" in text
    )
    _no_bid_data(html, text)

    # A "bid assessment requests" link turns off that type only.
    ok(await member.patch("/me/notification-preferences", {"assessor_assigned": "immediate"}))
    await assign(owner, crew, view, {"Delivery": [crew.tech1]}, due_at=DUE)
    transport.sent.clear()
    await _send_all(outbox, runtime)
    message = only(transport.messages)
    url = str(message["List-Unsubscribe"]).strip("<>")
    token = parse_qs(urlparse(url).query)["token"][0]
    ok(await client.post(f"{API}/unsubscribe", params={"token": token}))
    modes = {
        row["type"]: row["mode"]
        for row in ok(await member.get("/me/notification-preferences"))["items"]
    }
    assert modes["assessor_assigned"] == "off"
    assert modes["assessment_reminder"] == "immediate"
    assert modes["assessments_complete"] == "immediate"


async def test_payloads_never_carry_bid_data(
    crew: Crew, api: AsUser, db_session: AsyncSession, outbox: Outbox
) -> None:
    owner, view, bids = await _assessing(crew, api, db_session)
    sections = sections_by_title(view)
    for user, title in ((crew.tech1, "Technical"), (crew.delivery, "Delivery")):
        who = await api(user)
        for bid in bids:
            await submit(who, crew, bid["id"], sections[title], 4)
    notes = [n for n in await outbox.notifications() if n.type.value.startswith("assess")]
    assert {n.type for n in notes} == {ASSIGNED, COMPLETE}
    allowed = {"call_id", "due_at", "days_before", "bid_count", "assessment_count"}
    for note in notes:
        assert isinstance(note, Notification)
        assert set(note.payload) <= allowed
        _no_bid_data(str(note.payload))
    del owner
