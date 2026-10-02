"""Fixtures for the public submission tests (contract-phase4 sections 3.5-3.9).

Every test runs with SMTP configured (nothing is sent unless a test runs the worker
with a recording transport) and the cheapest ALTCHA cost. The ``team`` project
("customer-innovation") has its public form on, moderated, without required email
confirmation; change it with ``await form(...)``.

* ``visitor(ip)``: an anonymous client whose address is ``ip`` (not a trusted proxy,
  so its own ``X-Forwarded-For`` is ignored).
* ``solve(client, slug)``: a solved ALTCHA payload for the form, fetched like the
  widget does.
* ``send(client, slug, **fields)``: solve and submit (``altcha=`` overrides).
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import altcha
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import Idea
from app.models.project import Project
from app.models.public import PublicSubmission
from tests.ideas.conftest import (  # noqa: F401 - fixtures
    API,
    Api,
    AsUser,
    Team,
    api,
    assert_problem,
    ok,
    team,
)
from tests.notifications.conftest import (  # noqa: F401 - fixtures
    SMTP,
    Clock,
    Outbox,
    RecordingTransport,
    clock,
    jobs,
    only,
    outbox,
    runtime,
    transport,
)

__all__ = [
    "API",
    "PUBLIC",
    "SMTP",
    "VISITOR_IP",
    "Api",
    "AsUser",
    "Clock",
    "Form",
    "Outbox",
    "RecordingTransport",
    "Team",
    "Visitor",
    "assert_problem",
    "challenge_for",
    "make_public_idea",
    "ok",
    "only",
    "payload_for",
    "send",
    "solve",
    "submission",
    "submitted",
]

PUBLIC = f"{API}/public"
VISITOR_IP = "203.0.113.10"


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {**SMTP, "altcha_cost": 1_000}


Visitor = Callable[..., Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def visitor(app: FastAPI) -> AsyncIterator[Visitor]:
    clients: list[httpx.AsyncClient] = []

    async def make(ip: str = VISITOR_IP) -> httpx.AsyncClient:
        asgi = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(ip, 4711))
        http = httpx.AsyncClient(transport=asgi, base_url="http://testserver")
        clients.append(http)
        return http

    yield make
    for http in clients:
        await http.aclose()


@pytest.fixture
async def anon(visitor: Visitor) -> httpx.AsyncClient:
    return await visitor()


Form = Callable[..., Awaitable[Project]]


@pytest.fixture
async def form(db_session: AsyncSession, team: Team) -> Form:  # noqa: F811 - the fixture
    async def configure(project: Project | None = None, **values: Any) -> Project:
        target = project or team.project
        values = {
            "public_submission_enabled": True,
            "public_moderation_required": True,
            "public_require_email_verification": False,
            **values,
        }
        await db_session.execute(update(Project).where(Project.id == target.id).values(**values))
        await db_session.commit()
        refreshed = await db_session.get(Project, target.id, populate_existing=True)
        assert refreshed is not None
        return refreshed

    await configure()
    return configure


def payload_for(challenge: dict[str, Any], *, counter: int | None = None) -> str:
    """Solve ``challenge`` (the widget's JSON) and encode the payload as the widget does."""
    parsed = altcha.Challenge.from_dict(challenge)
    solution = altcha.solve_challenge(parsed)
    assert solution is not None
    if counter is not None:
        solution = altcha.Solution(counter=counter, derived_key=solution.derived_key)
    return base64.b64encode(
        json.dumps(altcha.Payload(parsed, solution).to_dict()).encode()
    ).decode()


async def challenge_for(client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
    response = await client.get(f"{PUBLIC}/projects/{slug}/altcha")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def solve(client: httpx.AsyncClient, slug: str) -> str:
    return payload_for(await challenge_for(client, slug))


def submission(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Recycle packaging at the till",
        "summary": "Let customers hand back packaging when they pay.",
        "description_md": "Bins by every till.",
    }
    body.update(fields)
    return body


async def send(client: httpx.AsyncClient, slug: str, **fields: Any) -> httpx.Response:
    body = submission(**fields)
    if "altcha" not in body:
        body["altcha"] = await solve(client, slug)
    return await client.post(f"{PUBLIC}/projects/{slug}/submissions", json=body)


async def submitted(db: AsyncSession, token: str | None = None) -> tuple[PublicSubmission, Idea]:
    """The only (or the token's) public submission and its idea, fresh from the database."""
    from app.auth.submission_tokens import tracking_token_hash

    statement = (
        select(PublicSubmission, Idea)
        .join(Idea, Idea.id == PublicSubmission.idea_id)
        .execution_options(populate_existing=True)
    )
    if token is not None:
        statement = statement.where(
            PublicSubmission.tracking_token_hash == tracking_token_hash(token)
        )
    rows = (await db.execute(statement)).all()
    assert len(rows) == 1, rows
    return rows[0][0], rows[0][1]


async def make_public_idea(
    db: AsyncSession,
    settings: Any,
    team: Team,  # noqa: F811 - the fixture's value
    *,
    title: str = "Recycle packaging at the till",
    held_for: Any = None,
    email: str | None = None,
    verified: bool = False,
    wants_updates: bool = False,
    project: Project | None = None,
) -> tuple[str, Idea]:
    """A public idea and its submission written straight to the database (as
    ``app.public.submit`` would, without the form, its limits or ALTCHA). Returns the
    tracking token and the idea."""
    from uuid import uuid4

    from app.auth.submission_tokens import (
        new_tracking_token,
        seal_tracking_token,
        tracking_token_hash,
    )
    from app.models.base import utcnow
    from tests.factories import make_idea

    target = project or team.project
    idea = await make_idea(db, target, title=title, summary="As sent.")
    idea.held_for = held_for
    token = new_tracking_token()
    db.add(
        PublicSubmission(
            id=uuid4(),
            idea_id=idea.id,
            project_id=target.id,
            email=email,
            email_verified_at=utcnow() if verified else None,
            wants_updates=wants_updates,
            tracking_token_hash=tracking_token_hash(token),
            tracking_token_sealed=seal_tracking_token(settings, token),
            submitted_title=title,
            submitted_summary="As sent.",
            reached_team_at=None if held_for is not None else utcnow(),
        )
    )
    await db.commit()
    return token, idea
