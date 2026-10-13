"""My work's "Bids to assess" and the sidebar's counts (contract-phase10 section 11):
progress only, calls being assessed, never closed ideas, archived projects or assignments
that fail c28 now."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from tests.bids.conftest import (
    AsUser,
    Crew,
    add_bid,
    assign,
    call_url,
    ok,
    open_call,
    sections_by_title,
    start,
    submit,
    to_assessing,
)


async def _setup(crew: Crew, api: AsUser, *, due: str | None) -> dict[str, Any]:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bids = [await add_bid(owner, crew, name, price="10.00") for name in ("One", "Two", "Three")]
    ok(await owner.put(call_url(crew, f"/bids/{bids[2]['id']}/rejection"), {"reason": "x"}))
    view = await assign(
        owner,
        crew,
        view,
        {"Technical": [crew.tech1], "Delivery": [crew.tech1, crew.delivery]},
        due_at=due,
    )
    await to_assessing(owner, crew)
    return {"view": view, "bids": bids}


async def test_bids_to_assess_and_counts(crew: Crew, api: AsUser) -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    case = await _setup(crew, api, due=yesterday)
    tech = await api(crew.tech1)
    technical = sections_by_title(case["view"])["Technical"]
    await submit(tech, crew, case["bids"][0]["id"], technical, 4)

    work = ok(await tech.get("/me/work"))

    assert len(work["bids_to_assess"]) == 1
    item = work["bids_to_assess"][0]
    assert item["idea"]["key"] == crew.key
    assert item["call"]["title"] == "Data platform build"
    assert [s["title"] for s in item["sections"]] == ["Technical", "Delivery"]
    assert item["overdue"] is True
    # 2 sections x 2 bids that aren't rejected, 1 submitted; never scores or bidders.
    assert item["progress"] == {"submitted": 1, "total": 4}
    assert "bidder" not in str(item)
    assert (work["counts"]["bid_assessments_due"], work["counts"]["bid_assessments_overdue"]) == (
        3,
        3,
    )
    counts = ok(await tech.get("/me/work/counts"))
    assert (counts["bid_assessments_due"], counts["bid_assessments_overdue"]) == (3, 3)
    other = ok(await (await api(crew.delivery)).get("/me/work/counts"))
    assert (other["bid_assessments_due"], other["bid_assessments_overdue"]) == (2, 2)
    # Nobody else owes anything.
    assert ok(await (await api(crew.owner)).get("/me/work"))["bids_to_assess"] == []


async def test_done_drafts_and_open_calls(crew: Crew, api: AsUser) -> None:
    case = await _setup(crew, api, due=None)
    delivery = await api(crew.delivery)
    section = sections_by_title(case["view"])["Delivery"]
    await submit(delivery, crew, case["bids"][0]["id"], section, 3, final=False)  # a draft owes

    work = ok(await delivery.get("/me/work"))
    assert work["bids_to_assess"][0]["progress"] == {"submitted": 0, "total": 2}
    assert work["bids_to_assess"][0]["overdue"] is False
    for bid in case["bids"][:2]:
        await submit(delivery, crew, bid["id"], section, 3)
    assert ok(await delivery.get("/me/work"))["bids_to_assess"] == []
    assert ok(await delivery.get("/me/work/counts"))["bid_assessments_due"] == 0


async def test_skipped_calls(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    await _setup(crew, api, due=None)
    tech = await api(crew.tech1)
    assert ok(await tech.get("/me/work/counts"))["bid_assessments_due"] == 4

    # A closed idea.
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status="closed", resolution="parked")
    )
    await db_session.commit()
    assert ok(await tech.get("/me/work/counts"))["bid_assessments_due"] == 0
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status="proposal", resolution=None)
    )
    # An archived project.
    await db_session.execute(
        update(Project).where(Project.id == crew.project.id).values(archived_at=datetime.now(UTC))
    )
    await db_session.commit()
    assert ok(await tech.get("/me/work"))["bids_to_assess"] == []
    await db_session.execute(
        update(Project).where(Project.id == crew.project.id).values(archived_at=None)
    )
    # Left the private project (c28 now).
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == crew.project.id, ProjectMember.user_id == crew.tech1.id
        )
    )
    await db_session.commit()
    assert ok(await tech.get("/me/work/counts"))["bid_assessments_due"] == 0
    assert ok(await tech.get("/me/work"))["bids_to_assess"] == []
