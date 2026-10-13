"""Bid access as a table (role matrix table M, contract-phase10 sections 2.1 and 10): every
bid route of this part x every kind of principal, with sessions and API keys.

One call, being assessed, with a qualified bid (``good``) and a rejected one (``bad``);
Technical is assessed by ``tech1``, Commercial (the price section) by ``commercial``; an
AI assessment of ``good`` is on record; ``outsider`` is the idea's guest researcher (no role
in the private project). Each principal's answers are collected in one pass and compared
with the table, so a mismatch names the route and the principal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AiRunKind, ResearchStep
from app.models.project import Project
from tests.ai.helpers import make_agent
from tests.api_keys.helpers import key_client, make_key
from tests.bids.conftest import (
    API,
    AsUser,
    Crew,
    add_bid,
    assign,
    call_url,
    ok,
    open_call,
    qualify,
    sections_by_title,
    start,
    to_assessing,
)
from tests.bids.test_scoring import ai_assessment
from tests.factories import set_researcher


@dataclass
class World:
    crew: Crew
    view: dict[str, Any]
    good: dict[str, Any]
    bad: dict[str, Any]
    ai: str


@pytest.fixture
async def world(crew: Crew, api: AsUser, db_session: AsyncSession) -> World:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    good = await add_bid(owner, crew, "Good Ltd", price="100.00")
    bad = await add_bid(owner, crew, "Bad Ltd", price="90.00")
    await qualify(db_session, good["id"], crew.owner)
    ok(await owner.put(call_url(crew, f"/bids/{bad['id']}/rejection"), {"reason": "No cert."}))
    view = await assign(
        owner, crew, view, {"Technical": [crew.tech1], "Commercial": [crew.commercial]}
    )
    await to_assessing(owner, crew)
    ai = await ai_assessment(db_session, crew, view, good["id"], {"Technical": [3, 3]})
    await db_session.execute(
        update(Project)
        .where(Project.id == crew.project.id)
        .values(research_step=ResearchStep.BEFORE_PROPOSAL)
    )
    await db_session.commit()
    await set_researcher(db_session, crew.idea, crew.outsider)
    return World(crew, view, good, bad, str(ai))


def _reads(w: World) -> dict[str, tuple[str, str]]:
    sections = sections_by_title(w.view)
    tech, commercial = sections["Technical"]["id"], sections["Commercial"]["id"]
    good, bad = w.good["id"], w.bad["id"]
    return {
        "get_bid_template": ("GET", f"/projects/{w.crew.project.slug}/bid-template"),
        "get_bid_call": ("GET", call_url(w.crew)),
        "list_bids": ("GET", call_url(w.crew, "/bids")),
        "get_bid": ("GET", call_url(w.crew, f"/bids/{good}")),
        "get_bid (rejected)": ("GET", call_url(w.crew, f"/bids/{bad}")),
        "get_bid (unknown)": ("GET", call_url(w.crew, f"/bids/{uuid4()}")),
        "get_bid_comparison": ("GET", call_url(w.crew, "/comparison")),
        "get_my_bid_assessment (Technical)": (
            "GET",
            call_url(w.crew, f"/bids/{good}/sections/{tech}/assessment"),
        ),
        "get_my_bid_assessment (Commercial)": (
            "GET",
            call_url(w.crew, f"/bids/{good}/sections/{commercial}/assessment"),
        ),
        "list_bid_section_assessments (Technical)": (
            "GET",
            call_url(w.crew, f"/bids/{good}/sections/{tech}/assessments"),
        ),
        "list_bid_ai_assessments": ("GET", call_url(w.crew, f"/bids/{good}/ai-assessments")),
    }


# fmt: off
#             template call bids  bid  rejected unknown compare mine(T) mine(C) section(T) ai
READS: dict[str, tuple[int, ...]] = {
    "owner":      (200, 200, 200, 200, 200, 404, 200, 403, 403, 200, 200),
    "admin":      (200, 200, 200, 200, 200, 404, 200, 403, 403, 200, 200),
    "platform":   (200, 200, 200, 200, 200, 404, 200, 403, 403, 200, 200),
    "tech1":      (200, 200, 200, 200, 404, 404, 403, 200, 403, 200, 403),
    "commercial": (200, 200, 200, 200, 404, 404, 403, 403, 200, 403, 403),
    "member":     (200, 200, 403, 403, 403, 403, 403, 403, 403, 403, 403),
    "viewer":     (200, 200, 403, 403, 403, 403, 403, 403, 403, 403, 403),
    "outsider":   (404, 404, 404, 404, 404, 404, 404, 404, 404, 404, 404),  # guest researcher
}
# fmt: on


async def _answers(http: httpx.AsyncClient, requests: dict[str, tuple[str, str]]) -> list[int]:
    return [
        (await http.request(method, API + path)).status_code for method, path in requests.values()
    ]


@pytest.mark.parametrize("who", sorted(READS))
async def test_reads(world: World, api: AsUser, who: str) -> None:
    user = getattr(world.crew, who)
    http = (await api(user)).http

    got = await _answers(http, _reads(world))

    expected = READS[who]
    mismatches = [
        (name, want, have)
        for name, want, have in zip(_reads(world), expected, got, strict=True)
        if want != have
    ]
    assert mismatches == []


async def test_a_pending_assessor_reads_hidden_scores_only(world: World, api: AsUser) -> None:
    sections = sections_by_title(world.view)
    url = call_url(
        world.crew, f"/bids/{world.good['id']}/sections/{sections['Technical']['id']}/assessments"
    )

    hidden = ok(await (await api(world.crew.tech1)).get(url))

    assert hidden["hidden"] is True
    assert hidden["assessments"] == hidden["ai"] == hidden["questions"] == []


async def test_anonymous_is_401_everywhere(world: World, client: httpx.AsyncClient) -> None:
    got = await _answers(client, _reads(world))

    assert set(got) == {401}


def _writes(w: World) -> dict[str, tuple[str, str, Any]]:
    sections = w.view["call"]["template"]["sections"]
    tech = sections_by_title(w.view)["Technical"]
    good = w.good["id"]
    must = w.view["call"]["template"]["must_haves"][0]["id"]
    return {
        "replace_bid_template": (
            "PUT",
            f"/projects/{w.crew.project.slug}/bid-template",
            {
                "scale": list("012345"),
                "sections": [
                    {"title": "A", "weight": 100, "questions": [{"text": "Q", "type": "score"}]}
                ],
                "must_haves": [],
            },
        ),
        "create_bid_call": ("POST", call_url(w.crew), {"title": "Another"}),
        "update_bid_call": (
            "PUT",
            call_url(w.crew),
            {
                "title": "T",
                "description": "",
                "currency": "GBP",
                "deadline_at": w.view["call"]["deadline_at"],
                "ai_assessor_id": None,
            },
        ),
        "change_bid_call_status": ("POST", call_url(w.crew, "/status"), {"status": "open"}),
        "cancel_bid_call": ("POST", call_url(w.crew, "/cancellation"), {}),
        "delete_bid_call": ("DELETE", call_url(w.crew), None),
        "replace_bid_call_template": (
            "PUT",
            call_url(w.crew, "/template"),
            {
                "scale": list("012345"),
                "sections": [
                    {"title": "A", "weight": 100, "questions": [{"text": "Q", "type": "score"}]}
                ],
                "must_haves": [],
            },
        ),
        "set_bid_assessors": (
            "PUT",
            call_url(w.crew, "/assessors"),
            {
                "sections": [{"section_id": s["id"], "user_ids": []} for s in sections],
                "due_at": None,
            },
        ),
        "award_bid_call": ("POST", call_url(w.crew, "/award"), {"bid_id": good}),
        "create_bid": ("POST", call_url(w.crew, "/bids"), {"bidder": "New"}),
        "update_bid": (
            "PUT",
            call_url(w.crew, f"/bids/{good}"),
            {"bidder": "X", "received_at": w.good["received_at"]},
        ),
        "delete_bid": ("DELETE", call_url(w.crew, f"/bids/{good}"), None),
        "reject_bid": ("PUT", call_url(w.crew, f"/bids/{good}/rejection"), {"reason": "x"}),
        "reinstate_bid": ("DELETE", call_url(w.crew, f"/bids/{good}/rejection"), None),
        "decide_must_have": (
            "PUT",
            call_url(w.crew, f"/bids/{good}/must-haves/{must}"),
            {"result": None},
        ),
        "save_my_bid_assessment": (
            "PUT",
            call_url(w.crew, f"/bids/{good}/sections/{tech['id']}/assessment"),
            {"answers": [], "submit": False},
        ),
        "set_bid_ai_inclusion": (
            "PUT",
            call_url(w.crew, f"/bids/{good}/ai-assessments/{w.ai}/include-in-totals"),
            {"include": True},
        ),
    }


# Everything a member, a viewer or an assessor of another section may not do: 403; a guest
# researcher: 404 (nothing of the call); the save is the Technical assessor's own (200).
# fmt: off
WRITES_DENIED: dict[str, dict[str, int]] = {
    "member":     {},
    "viewer":     {},
    "commercial": {"save_my_bid_assessment": 403},
    "tech1":      {"save_my_bid_assessment": 200},
    "outsider":   {},
}
# fmt: on


@pytest.mark.parametrize("who", sorted(WRITES_DENIED))
async def test_writes_are_the_managers(world: World, api: AsUser, who: str) -> None:
    http = (await api(getattr(world.crew, who))).http
    default = 404 if who == "outsider" else 403
    mismatches = []
    for name, (method, path, body) in _writes(world).items():
        want = WRITES_DENIED[who].get(name, default)
        if name == "replace_bid_template" and who != "outsider":
            want = 403
        response = await http.request(method, API + path, json=body)
        if response.status_code != want:
            mismatches.append((name, want, response.status_code))
    assert mismatches == []


# --- API keys ---------------------------------------------------------------------------------
# fmt: off
KEY_READS: dict[str, tuple[int, ...]] = {
    # The owner's key with one scope: read reads, write/evaluate keys carry read in practice.
    "read":     (200, 200, 200, 200, 200, 404, 200, 403, 403, 200, 200),
    "mcp":      (403, 403, 403, 403, 403, 403, 403, 403, 403, 403, 403),
}
# fmt: on


@pytest.mark.parametrize("scope", sorted(KEY_READS))
async def test_a_managers_key_reads_with_read(
    world: World, app: FastAPI, db_session: AsyncSession, scope: str
) -> None:
    key = await make_key(db_session, world.crew.owner, scopes=[scope])
    async with key_client(app, key) as http:
        got = await _answers(http, _reads(world))

    assert got == list(KEY_READS[scope])


async def test_keys_and_session_only_writes(
    world: World, app: FastAPI, db_session: AsyncSession
) -> None:
    session_only = {
        "replace_bid_template",
        "delete_bid_call",
        "cancel_bid_call",
        "set_bid_assessors",
        "award_bid_call",
        "delete_bid",
        "reject_bid",
        "reinstate_bid",
    }
    everything = await make_key(db_session, world.crew.owner)
    read_only = await make_key(db_session, world.crew.owner, scopes=["read"])
    writes = _writes(world)
    async with key_client(app, everything) as http:
        for name in sorted(session_only):
            method, path, body = writes[name]
            response = await http.request(method, API + path, json=body)
            assert (name, response.status_code) == (name, 403)
            assert response.json()["code"] == "insufficient_scope"
        # A write key reaches the rule (and its state conditions).
        method, path, body = writes["create_bid"]
        assert (await http.request(method, API + path, json=body)).json()["code"] == (
            "bid_call_not_open"
        )
    async with key_client(app, read_only) as http:
        method, path, body = writes["create_bid"]
        response = await http.request(method, API + path, json=body)
        assert response.json()["code"] == "insufficient_scope"


async def test_an_assessors_key_assesses_with_evaluate(
    world: World, app: FastAPI, db_session: AsyncSession
) -> None:
    method, path, body = _writes(world)["save_my_bid_assessment"]
    for scopes, status in ((["read"], 403), (["read", "evaluate"], 200)):
        key = await make_key(db_session, world.crew.tech1, scopes=scopes)
        async with key_client(app, key) as http:
            response = await http.request(method, API + path, json=body)
        assert response.status_code == status, response.text


async def test_an_agents_key_never_reaches_rest(
    world: World, app: FastAPI, db_session: AsyncSession
) -> None:
    agent = await make_agent(
        db_session, [world.crew.project], purposes=[AiRunKind.ASSESS_BID], key=True
    )
    assert agent.key is not None
    async with key_client(app, agent.key) as http:
        for method, path in _reads(world).values():
            response = await http.request(method, API + path)
            assert response.status_code == 403
            assert response.json()["code"] == "insufficient_scope"
