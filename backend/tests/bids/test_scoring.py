"""Scoring, the comparison and the award (contract-phase10 section 8; the worked example of
section 8.1, through the API), and the AI assessment in and out of the totals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid import BidAiAssessment, BidAiScore
from app.models.enums import AiRunKind
from tests.ai.helpers import make_agent
from tests.bids.conftest import (
    Api,
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    call_url,
    ok,
    open_call,
    qualify,
    score_questions,
    sections_by_title,
    start,
    submit,
    to_assessing,
)

WORKED_TEMPLATE: dict[str, Any] = {
    "scale": ["0", "1", "2", "3", "4", "5"],
    "sections": [
        {
            "title": "Technical",
            "weight": 40,
            "questions": [
                {"text": "Q1", "type": "score", "weight": 2},
                {"text": "Q2", "type": "score", "weight": 1},
            ],
        },
        {
            "title": "Commercial",
            "weight": 40,
            "questions": [
                {"text": "Q3", "type": "price", "weight": 3},
                {"text": "Q4", "type": "score", "weight": 1},
            ],
        },
        {
            "title": "Delivery",
            "weight": 20,
            "questions": [{"text": "Q5", "type": "score", "weight": 1}],
        },
    ],
    "must_haves": [{"text": "Insurance certificate", "kind": "document"}],
}


async def ai_assessment(
    db: AsyncSession,
    crew: Crew,
    view: dict[str, Any],
    bid_id: str,
    scores: Mapping[str, Sequence[int]],
    *,
    included: bool = False,
) -> UUID:
    """An AI assessment of the bid (as the MCP tool will record it): ``scores`` by section
    title, one per score question in order."""
    agent = await make_agent(
        db, [crew.project], purposes=[AiRunKind.ASSESS_BID], display_name="Bid assessor"
    )
    assessment = BidAiAssessment(
        id=uuid4(), bid_id=UUID(bid_id), agent_id=agent.agent.id, included=included
    )
    db.add(assessment)
    await db.flush()
    sections = sections_by_title(view)
    for title, values in scores.items():
        for question, value in zip(score_questions(sections[title]), values, strict=True):
            db.add(
                BidAiScore(
                    ai_assessment_id=assessment.id,
                    question_id=UUID(question["id"]),
                    score=value,
                    rationale="Because the bid says so.",
                    evidence=[],
                )
            )
    await db.commit()
    return assessment.id


async def worked_example(crew: Crew, api: AsUser, db: AsyncSession) -> dict[str, Any]:
    """Section 8.1: bids A, B (qualified) and C (rejected, no insurance), scored."""
    admin = await api(crew.admin)
    ok(await admin.put(f"/projects/{crew.project.slug}/bid-template", WORKED_TEMPLATE))
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    a = await add_bid(owner, crew, "A Ltd", price="120000.00")
    b = await add_bid(owner, crew, "B Ltd", price="96000.00")
    c = await add_bid(owner, crew, "C Ltd", price="80000.00")
    await qualify(db, a["id"], crew.owner)
    await qualify(db, b["id"], crew.owner)
    ok(await owner.put(call_url(crew, f"/bids/{c['id']}/rejection"), {"reason": "No insurance."}))
    view = await assign(
        owner,
        crew,
        view,
        {
            "Technical": [crew.tech1, crew.tech2],
            "Commercial": [crew.commercial],
            "Delivery": [crew.delivery, crew.delivery_viewer],
        },
    )
    await to_assessing(owner, crew)
    sections = sections_by_title(view)
    marks: dict[str, dict[str, list[tuple[Any, Sequence[int]]]]] = {
        a["id"]: {
            "Technical": [(crew.tech1, [4, 4]), (crew.tech2, [5, 4])],
            "Commercial": [(crew.commercial, [4])],
            "Delivery": [(crew.delivery, [4]), (crew.delivery_viewer, [5])],
        },
        b["id"]: {
            "Technical": [(crew.tech1, [4, 3]), (crew.tech2, [2, 3])],
            "Commercial": [(crew.commercial, [3])],
            "Delivery": [(crew.delivery, [3]), (crew.delivery_viewer, [4])],
        },
    }
    clients: dict[UUID, Api] = {}
    for bid_id, by_section in marks.items():
        for title, entries in by_section.items():
            for user, values in entries:
                if user.id not in clients:
                    clients[user.id] = await api(user)
                await submit(clients[user.id], crew, bid_id, sections[title], values)
    return {"owner": owner, "view": view, "a": a, "b": b, "c": c}


def _row(comparison: dict[str, Any], bid: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in comparison["rows"] if row["bid"]["id"] == bid["id"])


def _sections(row: dict[str, Any], comparison: dict[str, Any]) -> dict[str, float | None]:
    titles = {s["id"]: s["title"] for s in comparison["sections"]}
    return {titles[cell["section_id"]]: cell["score"] for cell in row["sections"]}


async def test_the_worked_example(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    case = await worked_example(crew, api, db_session)
    owner: Api = case["owner"]

    comparison = ok(await owner.get(call_url(crew, "/comparison")))

    a, b, c = (_row(comparison, case[k]) for k in "abc")
    assert _sections(a, comparison) == {"Technical": 86.7, "Commercial": 80.0, "Delivery": 90.0}
    assert a["price_score"] == 4.0
    assert a["total"] == 84.7
    assert _sections(b, comparison) == {"Technical": 60.0, "Commercial": 90.0, "Delivery": 70.0}
    assert b["price_score"] == 5.0
    assert b["total"] == 74.0
    assert (a["rank"], b["rank"]) == (1, 2)
    assert not a["tied"]
    # C is out of everything, including the lowest price.
    assert (c["total"], c["rank"], c["price_score"]) == (None, None, None)
    assert {cell["score"] for cell in c["sections"]} == {None}
    assert comparison["lowest_price"] == "96000.00"
    assert [row["bid"]["bidder"] for row in comparison["rows"]] == ["A Ltd", "B Ltd", "C Ltd"]
    assert comparison["ranking_hidden"] is False
    assert comparison["complete"] is True
    assert comparison["progress"] == {"submitted": 10, "total": 10}
    # B's first question disagrees (4 and 2).
    tech = next(cell for cell in b["sections"] if cell["score"] == 60.0)
    assert tech["disagreement"] is True
    assert not any(cell["disagreement"] for cell in a["sections"])


async def test_had_c_not_been_rejected(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    case = await worked_example(crew, api, db_session)
    owner: Api = case["owner"]
    ok(await owner.delete(call_url(crew, f"/bids/{case['c']['id']}/rejection")))
    await qualify(db_session, case["c"]["id"], crew.owner)

    comparison = ok(await owner.get(call_url(crew, "/comparison")))

    assert comparison["lowest_price"] == "80000.00"
    assert _row(comparison, case["a"])["price_score"] == 3.33
    # C is scored now but nobody assessed it: no total, not ranked, after the ranked ones.
    c = _row(comparison, case["c"])
    assert (c["total"], c["rank"], c["price_score"]) == (None, None, 5.0)
    assert comparison["rows"][-1]["bid"]["bidder"] == "C Ltd"
    assert comparison["complete"] is False


async def test_the_ai_out_and_in(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    case = await worked_example(crew, api, db_session)
    owner: Api = case["owner"]
    assessment = await ai_assessment(
        db_session,
        crew,
        case["view"],
        case["b"]["id"],
        {"Technical": [3, 4], "Commercial": [4], "Delivery": [3]},
    )
    left_out = ok(await owner.get(call_url(crew, "/comparison")))
    assert _row(left_out, case["b"])["total"] == 74.0
    assert _row(left_out, case["b"])["ai_included"] is False

    url = call_url(crew, f"/bids/{case['b']['id']}/ai-assessments/{assessment}/include-in-totals")
    included = ok(await owner.put(url, {"include": True}))
    assert included["included"] is True

    comparison = ok(await owner.get(call_url(crew, "/comparison")))
    b = _row(comparison, case["b"])
    assert _sections(b, comparison) == {"Technical": 62.2, "Commercial": 92.5, "Delivery": 66.7}
    assert b["total"] == 75.2
    assert b["ai_included"] is True
    assert any(cell["disagreement"] for cell in b["sections"])  # Q1: 4 and 2 still
    listed = ok(await owner.get(call_url(crew, f"/bids/{case['b']['id']}/ai-assessments")))
    assert listed["items"][0]["included"] is True
    assert listed["can_include"] is True
    # Assessors don't list the AI's assessments (call managers only).
    tech = await api(crew.tech1)
    response = await tech.get(call_url(crew, f"/bids/{case['b']['id']}/ai-assessments"))
    assert_problem(response, 403, "forbidden")
    assert_problem(await tech.put(url, {"include": False}), 403, "forbidden")


async def test_the_award_keeps_the_numbers(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    case = await worked_example(crew, api, db_session)
    owner: Api = case["owner"]
    before = ok(await owner.get(call_url(crew, "/comparison")))

    view = ok(
        await owner.post(
            call_url(crew, "/award"), {"bid_id": case["a"]["id"], "reason": "Best value."}
        )
    )

    assert view["summary"]["status"] == "awarded"
    assert view["call"]["awarded_bid"]["id"] == case["a"]["id"]
    assert view["call"]["award_reason"] == "Best value."
    after = ok(await owner.get(call_url(crew, "/comparison")))
    statuses = {row["bid"]["bidder"]: row["bid"]["status"] for row in after["rows"]}
    assert statuses == {"A Ltd": "awarded", "B Ltd": "unsuccessful", "C Ltd": "rejected"}
    for key in ("a", "b"):
        old, new = _row(before, case[key]), _row(after, case[key])
        assert (new["total"], new["rank"], new["sections"]) == (
            old["total"],
            old["rank"],
            old["sections"],
        )
    # Read-only now.
    assert_problem(
        await owner.put(call_url(crew, f"/bids/{case['b']['id']}/rejection"), {"reason": "x"}),
        409,
        "bid_call_finished",
    )


async def test_award_refusals(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    case = await worked_example(crew, api, db_session)
    owner: Api = case["owner"]
    assert_problem(
        await owner.post(call_url(crew, "/award"), {"bid_id": case["c"]["id"]}), 409, "bid_rejected"
    )
    assert_problem(
        await owner.post(call_url(crew, "/award"), {"bid_id": str(uuid4())}), 404, "not_found"
    )
    for user in (crew.member, crew.tech1):
        response = await (await api(user)).post(
            call_url(crew, "/award"), {"bid_id": case["a"]["id"]}
        )
        assert_problem(response, 403, "forbidden")


async def test_only_a_qualified_bid_is_awarded_while_assessing(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Unchecked Ltd")
    assert_problem(
        await owner.post(call_url(crew, "/award"), {"bid_id": bid["id"]}),
        409,
        "bid_call_not_assessing",
    )
    await to_assessing(owner, crew)
    assert_problem(
        await owner.post(call_url(crew, "/award"), {"bid_id": bid["id"]}),
        409,
        "bid_not_qualified",
    )


async def test_equal_rounded_totals_share_a_rank(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    admin = await api(crew.admin)
    template = {
        "scale": ["0", "1", "2", "3", "4", "5"],
        "sections": [
            {"title": "Only", "weight": 100, "questions": [{"text": "Q", "type": "score"}]}
        ],
        "must_haves": [],
    }
    ok(await admin.put(f"/projects/{crew.project.slug}/bid-template", template))
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bids = [await add_bid(owner, crew, name) for name in ("One", "Two", "Three", "Four")]
    view = await assign(owner, crew, view, {"Only": [crew.tech1]})
    await to_assessing(owner, crew)
    only = sections_by_title(view)["Only"]
    tech = await api(crew.tech1)
    for bid, value in zip(bids, (5, 4, 4, 2), strict=True):
        await submit(tech, crew, bid["id"], only, value)

    comparison = ok(await owner.get(call_url(crew, "/comparison")))

    ranks = [(r["bid"]["bidder"], r["rank"], r["tied"]) for r in comparison["rows"]]
    assert ranks == [
        ("One", 1, False),
        ("Two", 2, True),
        ("Three", 2, True),
        ("Four", 4, False),
    ]
