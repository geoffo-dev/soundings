"""Bids and their must-haves (contract-phase10 section 5): entering and editing, the
must-have flags (missing documents, confirmations, a person's decision), reject and
reinstate, and what an assessor sees of a bid (no contacts, notes, reasons, rejected bids;
prices and pricing documents only for the price section)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bids.service import sync_document_must_have
from app.models.activity import AuditLog
from app.models.bid import Bid, BidDocument
from tests.bids.conftest import (
    bid_detail,
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    attach,
    call_url,
    must_have_ids,
    ok,
    open_call,
    qualify,
    start,
    to_assessing,
)


async def _ready(crew: Crew, api: AsUser) -> tuple[Any, dict[str, Any]]:
    owner = await api(crew.owner)
    await start(owner, crew)
    return owner, await open_call(owner, crew)


def _state(detail: dict[str, Any], text: str) -> dict[str, Any]:
    return next(s for s in detail["must_have_results"] if s["must_have"]["text"] == text)


# --- Entering bids -----------------------------------------------------------------------
async def test_entering_a_bid(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner, _ = await _ready(crew, api)

    bid = await add_bid(
        owner,
        crew,
        "Northwind Data Ltd",
        contact_name="Ada Price",
        contact_email="ada@northwind.example",
        price="120000.00",
        notes="By email.",
    )

    assert bid["status"] == "received"
    assert bid["price"] == "120000.00"
    assert bid["late"] is False
    assert bid["must_haves"] == {"met": 0, "not_met": 0, "missing": 3, "unchecked": 1}
    assert bid["contact_email"] == "ada@northwind.example"
    assert bid["entered_by"]["id"] == str(crew.owner.id)
    actions = await db_session.scalars(
        select(AuditLog.action).where(AuditLog.action == "bid.create")
    )
    assert list(actions) == ["bid.create"]


async def test_bids_only_while_open(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    assert_problem(
        await owner.post(call_url(crew, "/bids"), {"bidder": "Early"}), 409, "bid_call_not_open"
    )
    await open_call(owner, crew)
    await to_assessing(owner, crew)
    assert_problem(
        await owner.post(call_url(crew, "/bids"), {"bidder": "Late"}), 409, "bid_call_not_open"
    )


async def test_a_late_bid_is_marked_not_refused(crew: Crew, api: AsUser) -> None:
    owner, view = await _ready(crew, api)
    call = view["call"]
    settings = {
        "title": call["title"],
        "description": call["description"],
        "currency": call["currency"],
        "deadline_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "ai_assessor_id": None,
    }
    ok(await owner.put(call_url(crew), settings))

    bid = await add_bid(owner, crew, "Late Ltd")

    assert bid["late"] is True


async def test_no_price_without_a_price_question(crew: Crew, api: AsUser) -> None:
    admin = await api(crew.admin)
    template = {
        "scale": ["0", "1", "2", "3", "4", "5"],
        "sections": [
            {"title": "Only", "weight": 100, "questions": [{"text": "Q", "type": "score"}]}
        ],
        "must_haves": [],
    }
    ok(await admin.put(f"/projects/{crew.project.slug}/bid-template", template))
    owner, _ = await _ready(crew, api)

    response = await owner.post(call_url(crew, "/bids"), {"bidder": "X", "price": "10.00"})

    assert_problem(response, 422, "price_not_asked")
    # Without must-haves a bid qualifies at once.
    assert (await add_bid(owner, crew, "Y"))["status"] == "qualified"


async def test_at_most_fifty_bids(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner, view = await _ready(crew, api)
    call_id = UUID(view["call"]["id"])
    db_session.add_all(Bid(id=uuid4(), call_id=call_id, bidder=f"B{n}") for n in range(50))
    await db_session.commit()

    response = await owner.post(call_url(crew, "/bids"), {"bidder": "Fifty-first"})

    assert_problem(response, 409, "too_many_bids")


async def test_editing_keeps_received_at(crew: Crew, api: AsUser) -> None:
    owner, _ = await _ready(crew, api)
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    bid = await add_bid(owner, crew, "Northwind", received_at=old)
    body = {
        "bidder": "Northwind Data Ltd",
        "contact_name": "",
        "contact_email": None,
        "received_at": bid["received_at"],
        "price": "100.00",
        "notes": "",
    }

    updated = ok(await owner.put(call_url(crew, f"/bids/{bid['id']}"), body))

    assert updated["bidder"] == "Northwind Data Ltd"
    assert updated["received_at"] == bid["received_at"]
    too_old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    response = await owner.put(
        call_url(crew, f"/bids/{bid['id']}"), {**body, "received_at": too_old}
    )
    assert_problem(response, 422, "validation_error")


async def test_deleting_a_bid_while_open(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner, _ = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Gone Ltd")
    keep = await add_bid(owner, crew, "Kept Ltd")

    assert (await owner.delete(call_url(crew, f"/bids/{bid['id']}"))).status_code == 204
    await to_assessing(owner, crew)
    assert_problem(
        await owner.delete(call_url(crew, f"/bids/{keep['id']}")), 409, "bid_call_not_open"
    )
    assert await db_session.get(Bid, UUID(bid["id"])) is None


async def test_another_calls_bid_is_404_and_a_members_403_reveals_nothing(
    crew: Crew, api: AsUser
) -> None:
    owner, _ = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Northwind")
    member = await api(crew.member)

    real = await member.get(call_url(crew, f"/bids/{bid['id']}"))
    unknown = await member.get(call_url(crew, f"/bids/{uuid4()}"))

    assert_problem(real, 403, "forbidden")
    assert_problem(unknown, 403, "forbidden")
    assert_problem(await owner.get(call_url(crew, f"/bids/{uuid4()}")), 404, "not_found")


# --- Must-haves --------------------------------------------------------------------------
async def test_documents_flag_and_meet_their_must_haves(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Northwind")
    musts = await must_have_ids(db_session, view["call"]["id"])

    await attach(db_session, bid["id"], musts["Signed form of tender"])
    detail = ok(await owner.get(call_url(crew, f"/bids/{bid['id']}")))

    form = _state(detail, "Signed form of tender")
    assert form["result"] == "met"
    assert form["automatic"] is True
    assert len(form["document_ids"]) == 1
    assert _state(detail, "Insurance certificate")["result"] == "missing"
    assert detail["permissions"]["reject_suggested"] is True


async def test_a_document_must_have_cant_be_met_without_a_file(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Northwind")
    musts = await must_have_ids(db_session, view["call"]["id"])
    url = call_url(crew, f"/bids/{bid['id']}/must-haves/{musts['Insurance certificate']}")

    assert_problem(await owner.put(url, {"result": "met"}), 409, "document_missing")
    state = ok(await owner.put(url, {"result": "not_met", "note": "Expired."}))
    assert (state["result"], state["automatic"], state["note"]) == ("not_met", False, "Expired.")
    state = ok(await owner.put(url, {"result": None}))
    assert (state["result"], state["automatic"]) == ("missing", True)


async def test_confirmations_and_qualifying(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Northwind")
    musts = await must_have_ids(db_session, view["call"]["id"])
    for text in ("Signed form of tender", "Pricing schedule", "Insurance certificate"):
        await attach(db_session, bid["id"], musts[text], name=f"{text}.pdf")
    url = call_url(crew, f"/bids/{bid['id']}/must-haves/{musts['Accepts our standard terms']}")

    ok(await owner.put(url, {"result": "met"}))

    detail = ok(await owner.get(call_url(crew, f"/bids/{bid['id']}")))
    assert detail["status"] == "qualified"
    assert detail["permissions"]["reject_suggested"] is False
    ok(await owner.put(url, {"result": None}))
    assert ok(await owner.get(call_url(crew, f"/bids/{bid['id']}")))["status"] == "received"


async def test_losing_the_last_file_makes_it_missing_again(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Northwind")
    musts = await must_have_ids(db_session, view["call"]["id"])
    must = musts["Insurance certificate"]
    document = await attach(db_session, bid["id"], must)
    url = call_url(crew, f"/bids/{bid['id']}/must-haves/{must}")
    ok(await owner.put(url, {"result": "met"}))  # a person's met

    await db_session.execute(delete(BidDocument).where(BidDocument.id == document))
    await sync_document_must_have(db_session, UUID(view["call"]["id"]), UUID(bid["id"]), must)
    await db_session.commit()
    assert (
        _state(ok(await owner.get(call_url(crew, f"/bids/{bid['id']}"))), "Insurance certificate")[
            "result"
        ]
        == "missing"
    )

    # A person's not met stays when the file goes.
    document = await attach(db_session, bid["id"], must)
    ok(await owner.put(url, {"result": "not_met"}))
    await db_session.execute(delete(BidDocument).where(BidDocument.id == document))
    await sync_document_must_have(db_session, UUID(view["call"]["id"]), UUID(bid["id"]), must)
    await db_session.commit()
    detail = ok(await owner.get(call_url(crew, f"/bids/{bid['id']}")))
    assert _state(detail, "Insurance certificate")["result"] == "not_met"


# --- Reject and reinstate ----------------------------------------------------------------
async def test_reject_and_reinstate_keep_the_last_rejection(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, _ = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Quillfield Systems")
    url = call_url(crew, f"/bids/{bid['id']}/rejection")

    rejected = ok(await owner.put(url, {"reason": "No insurance certificate provided."}))
    assert rejected["status"] == "rejected"
    assert rejected["rejection"]["reason"] == "No insurance certificate provided."
    again = ok(await owner.put(url, {"reason": "Still no insurance."}))
    assert again["rejection"]["reason"] == "Still no insurance."

    reinstated = ok(await owner.delete(url))
    assert reinstated["status"] == "received"
    assert reinstated["rejection"]["reason"] == "Still no insurance."
    assert reinstated["rejection"]["reinstated_at"] is not None
    assert ok(await owner.delete(url))["status"] == "received"  # idempotent
    actions = list(
        await db_session.scalars(
            select(AuditLog.action)
            .where(AuditLog.action.in_(["bid.reject", "bid.reinstate"]))
            .order_by(AuditLog.created_at)
        )
    )
    assert actions == ["bid.reject", "bid.reject", "bid.reinstate"]
    # No reason's text in the audit.
    details: list[Any] = list(
        await db_session.scalars(select(AuditLog.details).where(AuditLog.action == "bid.reject"))
    )
    assert all("insurance" not in str(d).lower() for d in details)


async def test_a_reason_is_needed_and_keys_cannot_reject(crew: Crew, api: AsUser) -> None:
    owner, _ = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Quillfield Systems")
    url = call_url(crew, f"/bids/{bid['id']}/rejection")

    assert_problem(await owner.put(url, {"reason": "   "}), 422, "validation_error")
    assert_problem(await (await api(crew.member)).put(url, {"reason": "x"}), 403, "forbidden")


# --- What an assessor sees ---------------------------------------------------------------
async def test_assessors_see_bids_without_contacts_notes_or_rejected_ones(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view = await _ready(crew, api)
    northwind = await add_bid(
        owner,
        crew,
        "Northwind",
        contact_name="Ada",
        contact_email="ada@northwind.example",
        notes="Call Ada.",
        price="120000.00",
    )
    quill = await add_bid(owner, crew, "Quillfield")
    ok(await owner.put(call_url(crew, f"/bids/{quill['id']}/rejection"), {"reason": "No cert."}))
    await assign(owner, crew, view, {"Technical": [crew.tech1], "Commercial": [crew.commercial]})
    tech = await api(crew.tech1)

    listed = ok(await tech.get(call_url(crew, "/bids")))

    assert [b["bidder"] for b in listed["items"]] == ["Northwind"]
    item = listed["items"][0]
    assert (item["contact_name"], item["contact_email"], item["notes"]) == ("", None, "")
    assert (item["price"], item["price_hidden"]) == (None, True)
    assert item["rejection"] is None
    assert [s["section"]["title"] for s in item["my_sections"]] == ["Technical"]
    assert item["my_progress"] == {"submitted": 0, "total": 1}
    assert_problem(await tech.get(call_url(crew, f"/bids/{quill['id']}")), 404, "not_found")
    # The price section's assessor sees the price.
    commercial = ok(
        await (await api(crew.commercial)).get(call_url(crew, f"/bids/{northwind['id']}"))
    )
    assert (commercial["price"], commercial["price_hidden"]) == ("120000.00", False)
    # The call's view: the template and assessors, no reasons, no AI agents to ask.
    call = ok(await tech.get(call_url(crew)))
    assert call["call"]["template"]["sections"][0]["assessors"][0]["user"]["id"] == str(
        crew.tech1.id
    )
    assert call["permissions"]["can_see_prices"] is False
    assert call["permissions"]["assess_section_ids"] == [
        call["call"]["template"]["sections"][0]["id"]
    ]


async def test_pricing_documents_are_restricted(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Northwind")
    musts = await must_have_ids(db_session, view["call"]["id"])
    await attach(db_session, bid["id"], musts["Pricing schedule"], name="Prices.xlsx")
    await attach(db_session, bid["id"], musts["Signed form of tender"], name="Form.pdf")
    await assign(owner, crew, view, {"Technical": [crew.tech1], "Commercial": [crew.commercial]})

    tech = ok(await (await api(crew.tech1)).get(call_url(crew, f"/bids/{bid['id']}")))
    commercial = ok(await (await api(crew.commercial)).get(call_url(crew, f"/bids/{bid['id']}")))

    assert [d["filename"] for d in tech["documents"]] == ["Form.pdf"]
    assert (tech["document_count"], tech["restricted_document_count"]) == (1, 1)
    pricing = _state(tech, "Pricing schedule")
    assert (pricing["result"], pricing["document_ids"], pricing["restricted_document_count"]) == (
        "met",
        [],
        1,
    )
    assert {d["filename"] for d in commercial["documents"]} == {"Prices.xlsx", "Form.pdf"}
    assert commercial["restricted_document_count"] == 0
    # Deciding a pricing must-have: managers only (an assessor can't decide anything anyway).
    url = call_url(crew, f"/bids/{bid['id']}/must-haves/{musts['Pricing schedule']}")
    assert_problem(await (await api(crew.tech1)).put(url, {"result": None}), 403, "forbidden")


async def test_a_pricing_must_haves_decision_is_for_price_viewers_only(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Review ACC-1 (role matrix 3a rule 4): the note on a pricing must-have is where a
    manager writes about the price, so only ``bid.view_price`` reads it (and who decided
    it, when); the others keep the result and "present (restricted)"."""
    owner, view = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Tessellate Software", price="96000.00")
    musts = await must_have_ids(db_session, view["call"]["id"])
    await attach(db_session, bid["id"], musts["Pricing schedule"], name="Prices.xlsx")
    await assign(
        owner,
        crew,
        view,
        {"Technical": [crew.tech1], "Commercial": [crew.commercial], "Delivery": [crew.delivery]},
    )
    note = "Schedule total 96,000 GBP excludes licences; real price about 141,000 GBP"
    url = call_url(crew, f"/bids/{bid['id']}/must-haves/{musts['Pricing schedule']}")
    ok(await owner.put(url, {"result": "not_met", "note": note}))

    for user in (crew.tech1, crew.delivery):
        state = _state(await bid_detail(await api(user), crew, bid["id"]), "Pricing schedule")
        assert state["result"] == "not_met", user.display_name
        assert (state["note"], state["decided_by"], state["decided_at"]) == ("", None, None)
        assert state["automatic"] is False
        assert state["restricted_document_count"] == 1
    for user in (crew.owner, crew.admin, crew.platform, crew.commercial):
        state = _state(await bid_detail(await api(user), crew, bid["id"]), "Pricing schedule")
        assert state["note"] == note, user.display_name
        assert state["decided_by"]["id"] == str(crew.owner.id)


async def test_rejected_bids_stay_with_managers(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, _ = await _ready(crew, api)
    bid = await add_bid(owner, crew, "Quillfield")
    await qualify(db_session, bid["id"], crew.owner)
    ok(await owner.put(call_url(crew, f"/bids/{bid['id']}/rejection"), {"reason": "x"}))

    listed = ok(await owner.get(call_url(crew, "/bids")))

    assert [b["status"] for b in listed["items"]] == ["rejected"]
    assert listed["items"][0]["rejection"]["reason"] == "x"
