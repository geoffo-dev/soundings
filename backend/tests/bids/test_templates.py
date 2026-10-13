"""Bid evaluation templates (contract-phase10 section 4): the project's default and the
call's own copy, its lock and what a change does."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.bid import BidAiAssessment, BidAiScore, BidMustHaveResult, BidTemplate
from app.models.enums import MustHaveResult
from app.schemas.bids import DEFAULT_BID_TEMPLATE
from tests.bids.conftest import (
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
    sections_by_title,
    start,
    submit,
    to_assessing,
)
from tests.factories import make_user

TEMPLATE = DEFAULT_BID_TEMPLATE.model_dump(mode="json")


def _project_template(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(json.dumps(TEMPLATE))
    body.update(changes)
    return body


# --- The project's default ------------------------------------------------------------------
async def test_every_project_has_the_default(crew: Crew, api: AsUser) -> None:
    member = ok(await (await api(crew.member)).get(f"/projects/{crew.project.slug}/bid-template"))
    admin = ok(await (await api(crew.admin)).get(f"/projects/{crew.project.slug}/bid-template"))

    assert [s["title"] for s in member["sections"]] == ["Technical", "Commercial", "Delivery"]
    assert member["scale"] == list(DEFAULT_BID_TEMPLATE.scale)
    assert member["can_edit"] is False
    assert admin["can_edit"] is True
    assert member["must_haves"][1] == {
        "text": "Pricing schedule",
        "kind": "document",
        "pricing": True,
    }


async def test_a_new_project_gets_the_default_row(api: AsUser, db_session: AsyncSession) -> None:
    platform = await make_user(db_session, "Pat Platform", platform_admin=True)
    http = await api(platform)
    body = {"slug": "new-one", "key": "NEW", "name": "New one", "visibility": "private"}
    created = ok(await http.post("/projects", body), 201)

    row = await db_session.get(BidTemplate, UUID(created["id"]))
    assert row is not None
    assert row.template == TEMPLATE


async def test_admins_replace_it_and_it_is_audited(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    admin = await api(crew.admin)
    body = _project_template(
        sections=[
            {
                "title": "Quality",
                "weight": 70,
                "questions": [{"text": "How good?", "type": "score", "weight": 2}],
            },
            {
                "title": "Cost",
                "weight": 30,
                "questions": [
                    {"text": "Price", "type": "price"},
                    {"text": "Clear pricing?", "type": "score"},
                    {"text": "Anything else?", "type": "comment"},
                ],
            },
        ],
        must_haves=[{"text": "Insurance", "kind": "document"}],
    )

    saved = ok(await admin.put(f"/projects/{crew.project.slug}/bid-template", body))

    assert [(s["title"], s["weight"]) for s in saved["sections"]] == [("Quality", 70), ("Cost", 30)]
    assert saved["sections"][1]["questions"][2]["weight"] == 0
    assert saved["updated_by"]["id"] == str(crew.admin.id)
    action = await db_session.scalar(
        select(AuditLog.action).where(AuditLog.action == "project.bid_template_replace")
    )
    assert action == "project.bid_template_replace"
    # The owner of an idea isn't a project admin: 403; a member too.
    for user in (crew.owner, crew.member):
        response = await (await api(user)).put(f"/projects/{crew.project.slug}/bid-template", body)
        assert_problem(response, 403, "forbidden")


async def test_titles_collide_under_postgres_lower(crew: Crew, api: AsUser) -> None:
    """Python's casefold and Postgres's lower() differ: "İ" folds apart in Python but the
    call's unique lower(title) index would collide; the service refuses it first."""
    admin = await api(crew.admin)
    body = _project_template()
    body["sections"][0]["title"] = "İdea"
    body["sections"][1]["title"] = "i̇dea"

    response = await admin.put(f"/projects/{crew.project.slug}/bid-template", body)

    assert_problem(response, 422, "validation_error")


# --- The call's copy --------------------------------------------------------------------------
def _copy(view: dict[str, Any]) -> dict[str, Any]:
    """The call's template as a request (ids kept)."""
    template = view["call"]["template"] if "call" in view else view
    return {
        "scale": template["scale"],
        "sections": [
            {
                "id": s["id"],
                "title": s["title"],
                "guidance": s["guidance"],
                "weight": s["weight"],
                "questions": [
                    {
                        "id": q["id"],
                        "text": q["text"],
                        "guidance": q["guidance"],
                        "type": q["type"],
                        "weight": q["weight"],
                    }
                    for q in s["questions"]
                ],
            }
            for s in template["sections"]
        ],
        "must_haves": [
            {"id": m["id"], "text": m["text"], "kind": m["kind"], "pricing": m["pricing"]}
            for m in template["must_haves"]
        ],
    }


async def test_editing_the_copy_keeps_ids_and_adds_results(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Northwind Data Ltd")
    body = _copy(view)
    tech = body["sections"][0]
    tech["title"] = "Technical fit"
    tech["questions"].append({"text": "Is it accessible?", "type": "score", "weight": 1})
    body["sections"][2]["questions"].pop()  # the team question goes
    body["must_haves"].append({"text": "References", "kind": "confirmation"})
    body["must_haves"] = [m for m in body["must_haves"] if m["text"] != "Insurance certificate"]

    template = ok(await owner.put(call_url(crew, "/template"), body))

    assert template["sections"][0]["id"] == view["call"]["template"]["sections"][0]["id"]
    assert template["sections"][0]["title"] == "Technical fit"
    assert len(template["sections"][0]["questions"]) == 4
    assert len(template["sections"][2]["questions"]) == 1
    assert [m["text"] for m in template["must_haves"]] == [
        "Signed form of tender",
        "Pricing schedule",
        "Accepts our standard terms",
        "References",
    ]
    results = dict(
        (
            await db_session.execute(
                select(BidMustHaveResult.must_have_id, BidMustHaveResult.result).where(
                    BidMustHaveResult.bid_id == UUID(bid["id"])
                )
            )
        ).all()
    )
    by_text = {m["text"]: UUID(m["id"]) for m in template["must_haves"]}
    assert results[by_text["References"]] is MustHaveResult.UNCHECKED
    assert len(results) == 4


async def test_swapping_titles_and_moving_the_price_question(crew: Crew, api: AsUser) -> None:
    """Unique lower(title) and one price question per call hold at the end, not between."""
    owner = await api(crew.owner)
    view = await start(owner, crew)
    body = _copy(view)
    first, second = body["sections"][0], body["sections"][1]
    first["title"], second["title"] = second["title"], first["title"]
    price = next(q for q in second["questions"] if q["type"] == "price")
    second["questions"].remove(price)
    first["questions"].append(price)  # the same question, now in the first section

    template = ok(await owner.put(call_url(crew, "/template"), body))

    assert [s["title"] for s in template["sections"][:2]] == ["Commercial", "Technical"]
    assert template["price_question_id"] == price["id"]
    assert template["sections"][0]["has_price"] is True
    assert template["sections"][1]["has_price"] is False


async def test_unknown_or_foreign_ids_are_refused(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    for path in (("sections", 0, "id"), ("must_haves", 0, "id")):
        body = _copy(view)
        body[path[0]][path[1]][path[2]] = str(uuid4())
        response = await owner.put(call_url(crew, "/template"), body)
        assert_problem(response, 422, "unknown_template_item")
    body = _copy(view)
    body["sections"][0]["questions"][0]["id"] = str(uuid4())
    assert_problem(await owner.put(call_url(crew, "/template"), body), 422, "unknown_template_item")


async def test_a_persons_submission_locks_the_copy(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Northwind Data Ltd")
    view = await assign(owner, crew, view, {"Technical": [crew.tech1]})
    await to_assessing(owner, crew)
    tech = sections_by_title(view)["Technical"]
    # A draft doesn't lock it.
    await submit(await api(crew.tech1), crew, bid["id"], tech, 3, final=False)
    ok(await owner.put(call_url(crew, "/template"), _copy(view)))
    await submit(await api(crew.tech1), crew, bid["id"], tech, 3)

    response = await owner.put(call_url(crew, "/template"), _copy(view))

    assert_problem(response, 409, "bid_call_template_locked")
    again = ok(await owner.get(call_url(crew)))
    assert again["call"]["template"]["locked"] is True
    assert again["permissions"]["can_edit_template"] is False


async def test_a_change_deletes_the_ai_assessments_but_a_resave_doesnt(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    from tests.bids.test_scoring import ai_assessment

    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Northwind Data Ltd")
    await ai_assessment(db_session, crew, view, bid["id"], {"Technical": [4, 4]})

    ok(await owner.put(call_url(crew, "/template"), _copy(view)))  # nothing changed
    assert await db_session.scalar(select(func.count()).select_from(BidAiAssessment)) == 1

    body = _copy(view)
    body["sections"][0]["guidance"] = "Read the requirements first."
    ok(await owner.put(call_url(crew, "/template"), body))
    assert await db_session.scalar(select(func.count()).select_from(BidAiAssessment)) == 0
    assert await db_session.scalar(select(func.count()).select_from(BidAiScore)) == 0


async def test_removing_a_must_have_unlinks_its_documents(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Northwind Data Ltd")
    musts = await must_have_ids(db_session, view["call"]["id"])
    document = await attach(db_session, bid["id"], musts["Insurance certificate"])
    body = _copy(view)
    body["must_haves"] = [m for m in body["must_haves"] if m["text"] != "Insurance certificate"]

    ok(await owner.put(call_url(crew, "/template"), body))

    from app.models.bid import BidDocument

    row = await db_session.get(BidDocument, document, populate_existing=True)
    assert row is not None
    assert row.must_have_id is None


async def test_assessors_dont_edit_the_copy(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    await assign(owner, crew, view, {"Technical": [crew.tech1]})

    response = await (await api(crew.tech1)).put(call_url(crew, "/template"), _copy(view))

    assert_problem(response, 403, "forbidden")
