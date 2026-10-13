"""Fixtures and helpers for the bid evaluation tests (Phase 10, contract-phase10).

``crew``: a **private** project (``TOOLS``) with an admin, the idea's owner (a member), a
plain member, a viewer, an outsider (no role), a platform admin without a role, and five
would-be assessors: two members for Technical, a member for Commercial (the price
section), a member and a viewer for Delivery. ``crew.idea`` is in Proposal with a proposal
(c27), owned by ``crew.owner``.

Helpers drive the real routes (``Api``) or, where the route belongs to a later part of the
build (documents), write rows straight in the database:

* ``start(api, crew)`` creates the call; ``open_call`` sets a deadline and opens it;
  ``add_bid`` enters a bid; ``assign(api, crew, call, {title: [users]})`` sets assessors;
  ``to_assessing`` closes it to new bids; ``submit`` saves (and submits) an assessment.
* ``qualify(db, bid_id)`` marks every must-have of a bid met (as a person would);
  ``attach(db, bid_id, must_have_id)`` links a document row to a must-have.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bids.service import refresh_status, sync_document_must_have
from app.models.base import utcnow
from app.models.bid import (
    Bid,
    BidCallMustHave,
    BidDocument,
    BidDocumentContent,
    BidMustHaveResult,
)
from app.models.enums import (
    BidDocumentType,
    ExtractionState,
    IdeaStatus,
    MustHaveResult,
    ProjectRole,
)
from app.models.idea import Idea
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.user import User
from tests.factories import make_idea, make_project, make_user
from tests.ideas.conftest import (  # noqa: F401 - fixtures and helpers
    API,
    Api,
    AsUser,
    api,
    assert_problem,
    ok,
)

__all__ = [
    "API",
    "Api",
    "AsUser",
    "Crew",
    "add_bid",
    "assert_problem",
    "assign",
    "attach",
    "bid_detail",
    "call_url",
    "must_haves",
    "ok",
    "open_call",
    "qualify",
    "result_of",
    "start",
    "submit",
    "to_assessing",
    "upload",
]


@dataclass
class Crew:
    project: Project
    admin: User
    owner: User
    member: User
    viewer: User
    outsider: User
    platform: User
    tech1: User
    tech2: User
    commercial: User
    delivery: User
    delivery_viewer: User
    idea: Idea

    @property
    def key(self) -> str:
        return f"{self.project.key}-{self.idea.number}"


async def proposal_for(db: AsyncSession, idea: Idea, user: User) -> None:
    db.add(Proposal(id=uuid4(), idea_id=idea.id, created_by_id=user.id))
    await db.commit()


@pytest.fixture
async def crew(db_session: AsyncSession) -> Crew:
    people = {
        name: await make_user(db_session, name)
        for name in (
            "Dave Admin",
            "Kenji Owner",
            "Max Member",
            "Zanele Viewer",
            "Otto Outsider",
            "Pat Platform",
            "Carol Tech",
            "Mateo Tech",
            "Priya Commercial",
            "Sven Delivery",
            "Vera Delivery",
        )
    }
    platform = people["Pat Platform"]
    platform.is_platform_admin = True
    await db_session.commit()
    roles = {
        people["Dave Admin"]: ProjectRole.ADMIN,
        people["Kenji Owner"]: ProjectRole.MEMBER,
        people["Max Member"]: ProjectRole.MEMBER,
        people["Zanele Viewer"]: ProjectRole.VIEWER,
        people["Carol Tech"]: ProjectRole.MEMBER,
        people["Mateo Tech"]: ProjectRole.MEMBER,
        people["Priya Commercial"]: ProjectRole.MEMBER,
        people["Sven Delivery"]: ProjectRole.MEMBER,
        people["Vera Delivery"]: ProjectRole.VIEWER,
    }
    project = await make_project(
        db_session, slug="internal-tools", key="TOOLS", name="Internal Tools", members=roles
    )
    idea = await make_idea(
        db_session,
        project,
        title="Data platform",
        status=IdeaStatus.PROPOSAL,
        owner=people["Kenji Owner"],
        submitted_by=people["Kenji Owner"],
    )
    await proposal_for(db_session, idea, people["Kenji Owner"])
    return Crew(
        project=project,
        admin=people["Dave Admin"],
        owner=people["Kenji Owner"],
        member=people["Max Member"],
        viewer=people["Zanele Viewer"],
        outsider=people["Otto Outsider"],
        platform=platform,
        tech1=people["Carol Tech"],
        tech2=people["Mateo Tech"],
        commercial=people["Priya Commercial"],
        delivery=people["Sven Delivery"],
        delivery_viewer=people["Vera Delivery"],
        idea=idea,
    )


def call_url(crew: Crew, suffix: str = "") -> str:
    return f"/ideas/{crew.key}/bid-call{suffix}"


def deadline(days: int = 14) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


async def start(who: Api, crew: Crew, **body: Any) -> dict[str, Any]:
    body.setdefault("title", "Data platform build")
    view: dict[str, Any] = ok(await who.post(call_url(crew), body), 201)
    return view


async def open_call(who: Api, crew: Crew, view: dict[str, Any] | None = None) -> dict[str, Any]:
    if view is None:
        view = ok(await who.get(call_url(crew)))
    call = view["call"]
    settings = {
        "title": call["title"],
        "description": call["description"],
        "currency": call["currency"],
        "deadline_at": deadline(),
        "ai_assessor_id": None,
    }
    ok(await who.put(call_url(crew), settings))
    opened: dict[str, Any] = ok(await who.post(call_url(crew, "/status"), {"status": "open"}))
    return opened


async def add_bid(who: Api, crew: Crew, bidder: str, **body: Any) -> dict[str, Any]:
    bid: dict[str, Any] = ok(
        await who.post(call_url(crew, "/bids"), {"bidder": bidder, **body}), 201
    )
    return bid


def sections_by_title(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["title"]: s for s in view["call"]["template"]["sections"]}


async def assign(
    who: Api,
    crew: Crew,
    view: dict[str, Any],
    people: Mapping[str, Iterable[User]],
    *,
    due_at: str | None = None,
) -> dict[str, Any]:
    sections = sections_by_title(view)
    body = {
        "sections": [
            {"section_id": s["id"], "user_ids": [str(u.id) for u in people.get(title, [])]}
            for title, s in sections.items()
        ],
        "due_at": due_at,
    }
    result: dict[str, Any] = ok(await who.put(call_url(crew, "/assessors"), body))
    return result


async def to_assessing(who: Api, crew: Crew) -> dict[str, Any]:
    result: dict[str, Any] = ok(await who.post(call_url(crew, "/status"), {"status": "assessing"}))
    return result


def score_questions(section: dict[str, Any]) -> list[dict[str, Any]]:
    return [q for q in section["questions"] if q["type"] == "score"]


async def submit(
    who: Api,
    crew: Crew,
    bid_id: str,
    section: dict[str, Any],
    scores: Iterable[int] | int,
    *,
    final: bool = True,
) -> dict[str, Any]:
    """Score the section's score questions in order (one value for all, or one each)."""
    questions = score_questions(section)
    values = [scores] * len(questions) if isinstance(scores, int) else list(scores)
    body = {
        "answers": [
            {"question_id": q["id"], "score": v} for q, v in zip(questions, values, strict=True)
        ],
        "submit": final,
    }
    result: dict[str, Any] = ok(
        await who.put(call_url(crew, f"/bids/{bid_id}/sections/{section['id']}/assessment"), body)
    )
    return result


async def qualify(db: AsyncSession, bid_id: str | UUID, by: User | None = None) -> None:
    """Every must-have of the bid met, as a person decided (documents need no file here)."""
    await db.execute(
        update(BidMustHaveResult)
        .where(BidMustHaveResult.bid_id == UUID(str(bid_id)))
        .values(
            result=MustHaveResult.MET,
            decided_at=utcnow(),
            decided_by_id=by.id if by is not None else None,
        )
    )
    bid = await db.get(Bid, UUID(str(bid_id)), populate_existing=True)
    assert bid is not None
    await refresh_status(db, bid)
    await db.commit()


async def attach(
    db: AsyncSession,
    bid_id: str | UUID,
    must_have_id: str | UUID | None = None,
    *,
    pricing: bool = False,
    name: str = "Form of tender.pdf",
) -> UUID:
    """A document row on the bid (as the upload route will write it), linked to a must-have."""
    bid = await db.get(Bid, UUID(str(bid_id)))
    assert bid is not None
    must = UUID(str(must_have_id)) if must_have_id is not None else None
    if must is not None:
        row = await db.get(BidCallMustHave, must)
        pricing = pricing or bool(row and row.pricing)
    document = BidDocument(
        id=uuid4(),
        bid_id=bid.id,
        call_id=bid.call_id,
        must_have_id=must,
        filename=name,
        type=BidDocumentType.PDF,
        content_type="application/pdf",
        size_bytes=4,
        sha256=uuid4().hex + uuid4().hex,
        pricing=pricing,
        extraction_state=ExtractionState.PENDING,
    )
    db.add(document)
    await db.flush()
    db.add(BidDocumentContent(document_id=document.id, data=b"%PDF"))
    if must is not None:
        await sync_document_must_have(db, bid.call_id, bid.id, must)
    await db.commit()
    return document.id


async def must_have_ids(db: AsyncSession, call_id: str) -> dict[str, UUID]:
    rows = await db.execute(
        select(BidCallMustHave.text, BidCallMustHave.id).where(
            BidCallMustHave.call_id == UUID(call_id)
        )
    )
    return dict(rows.all())


@pytest.fixture
def app_settings(app: FastAPI) -> Any:
    return app.state.settings


# --- Documents (Phase 10, part 2) -------------------------------------------------------------
async def upload(
    who: Api,
    crew: Crew,
    bid_id: str,
    data: bytes,
    filename: str = "Form of tender.pdf",
    *,
    headers: dict[str, str] | None = None,
    **params: Any,
) -> httpx.Response:
    query = {
        "filename": filename,
        **{k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()},
    }
    return await who.http.post(
        API + call_url(crew, f"/bids/{bid_id}/documents"),
        params=query,
        content=data,
        headers={"Content-Type": "application/octet-stream", **(headers or {})},
    )


def must_haves(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["text"]: m for m in view["call"]["template"]["must_haves"]}


async def bid_detail(who: Api, crew: Crew, bid_id: str) -> dict[str, Any]:
    detail: dict[str, Any] = ok(await who.get(call_url(crew, f"/bids/{bid_id}")))
    return detail


def result_of(detail: dict[str, Any], text: str) -> dict[str, Any]:
    return next(r for r in detail["must_have_results"] if r["must_have"]["text"] == text)
