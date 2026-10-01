"""The public form (contract-phase4 section 3.5): JSON only, availability (c8), the
per-IP and per-project limits, email required, the honeypot, and the idea it creates.
ALTCHA itself: test_altcha.py."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.submission_tokens import tracking_token_hash, unseal_tracking_token
from app.config import Settings
from app.main import create_app
from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.enums import EmailType, HoldReason, IdeaStatus
from app.models.idea import Idea, IdeaWatcher
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project
from app.models.public import AltchaUsedChallenge, PublicSubmission
from tests.factories import make_project
from tests.public.conftest import (
    PUBLIC,
    VISITOR_IP,
    Form,
    Team,
    Visitor,
    assert_problem,
    send,
    solve,
    submission,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")


async def count(db: AsyncSession, model: Any) -> int:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0)


# --- JSON only (415 before anything else) ----------------------------------------------------
WRITES = [
    ("POST", "/projects/customer-innovation/submissions"),
    ("POST", "/track"),
    ("PUT", "/track/updates"),
    ("POST", "/track/verification-email"),
    ("POST", "/track/erase"),
    ("POST", "/verify-email"),
]


@pytest.mark.parametrize(("method", "path"), WRITES)
@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "text/plain",
        "text/plain;charset=UTF-8",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "application/jsonx",
        "application/problem+json",
    ],
)
async def test_public_writes_must_be_json(
    anon: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    content_type: str | None,
) -> None:
    """A cross-site no-cors request (text/plain, a form, no type at all) is refused
    before the body is read: 415, nothing happens, even with a valid JSON body."""
    headers = {} if content_type is None else {"content-type": content_type}
    body = b'{"title": "x", "summary": "y", "altcha": "AAAA", "token": "' + b"a" * 43 + b'"}'

    response = await anon.request(method, PUBLIC + path, content=body, headers=headers)

    assert_problem(response, 415, "unsupported_media_type")
    assert await count(db_session, AltchaUsedChallenge) == 0
    assert await count(db_session, Idea) == 0


async def test_415_comes_before_the_bodys_shape(anon: httpx.AsyncClient) -> None:
    response = await anon.post(
        f"{PUBLIC}/track", content=b"not json at all", headers={"content-type": "text/plain"}
    )

    assert_problem(response, 415, "unsupported_media_type")


async def test_json_with_a_charset_is_fine(anon: httpx.AsyncClient, team: Team) -> None:
    body = submission(altcha=await solve(anon, team.slug))
    response = await anon.post(
        f"{PUBLIC}/projects/{team.slug}/submissions",
        content=httpx.Request("POST", "/", json=body).content,
        headers={"content-type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 201, response.text


async def test_reads_need_no_content_type(anon: httpx.AsyncClient, team: Team) -> None:
    assert (await anon.get(f"{PUBLIC}/projects/{team.slug}")).status_code == 200


# --- Availability: c8, the same 404 for every reason ----------------------------------------
async def _not_found_body(client: httpx.AsyncClient, slug: str) -> list[tuple[int, Any]]:
    answers = []
    for method, path, body in [
        ("GET", f"/projects/{slug}", None),
        ("GET", f"/projects/{slug}/altcha", None),
        ("POST", f"/projects/{slug}/submissions", submission(altcha="AAAA")),
    ]:
        response = await client.request(method, PUBLIC + path, json=body)
        problem = response.json()
        problem.pop("instance", None)
        problem.pop("request_id", None)
        answers.append((response.status_code, problem))
    return answers


@pytest.mark.parametrize(
    "reason",
    [
        "form_off",
        "archived",
        "unknown",
        "reserved_slug",
        pytest.param("instance_off", marks=pytest.mark.settings(public_submission_enabled=False)),
    ],
)
async def test_an_unavailable_form_is_an_unknown_project(
    app: FastAPI,
    visitor: Visitor,
    team: Team,
    form: Form,
    db_session: AsyncSession,
    settings: Settings,
    reason: str,
) -> None:
    slug = team.slug
    if reason == "form_off":
        await form(public_submission_enabled=False)
    elif reason == "archived":
        await form(archived_at=utcnow())
    elif reason == "unknown":
        slug = "no-such-project"
    elif reason == "reserved_slug":
        # Only an older project can have one (new projects can't take it).
        project = await make_project(db_session, slug="ideas-old", key="OLD")
        await db_session.execute(
            update(Project).where(Project.id == project.id).values(slug="track")
        )
        await db_session.commit()
        await form(project)
        slug = "track"
    client = await visitor()
    reference = await _not_found_body(client, "never-existed")

    answers = await _not_found_body(client, slug)

    assert answers == reference
    assert {status for status, _ in answers} == {404}
    assert await count(db_session, Idea) == 0


async def test_the_public_project_shows_nothing_private(
    anon: httpx.AsyncClient, team: Team, form: Form
) -> None:
    await form(public_intro_md="Tell us how to **improve** the shop.")

    body = (await anon.get(f"{PUBLIC}/projects/{team.slug}")).json()

    assert body == {
        "slug": team.slug,
        "name": "Customer Innovation",
        "intro_md": "Tell us how to **improve** the shop.",
        "asks_for_email": True,
        "email_required": False,
        "moderated": True,
        "branding": {
            "app_name": "Soundings",
            "primary_color": "#1d5fa8",
            "accent_color": "#1d5fa8",
            "font": "inter",
            "logo_url": None,
            "favicon_url": None,
        },
    }


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_without_email_the_form_asks_for_no_address(
    anon: httpx.AsyncClient, team: Team, form: Form
) -> None:
    await form(public_require_email_verification=True)

    body = (await anon.get(f"{PUBLIC}/projects/{team.slug}")).json()

    assert (body["asks_for_email"], body["email_required"]) == (False, False)


# --- What a submission creates --------------------------------------------------------------
async def test_a_submission_creates_a_held_public_idea(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    response = await send(
        anon, team.slug, name="Jo Public", email="jo@example.org", wants_updates=True
    )

    assert response.status_code == 201, response.text
    receipt = response.json()
    token = receipt["tracking_token"]
    assert len(token) == 43
    assert receipt == {
        "tracking_token": token,
        "tracking_url": f"http://testserver/track#{token}",
        "held_for": "moderation",
        "email_sent": True,
    }
    row, idea = await submitted(db_session, token)
    assert (idea.status, idea.submitted_by_id, idea.held_for) == (
        IdeaStatus.NEW,
        None,
        HoldReason.MODERATION,
    )
    assert idea.number == 1
    assert idea.title == "Recycle packaging at the till"
    assert idea.description_md == "Bins by every till."
    assert (row.name, row.email, row.wants_updates, row.email_verified_at) == (
        "Jo Public",
        "jo@example.org",
        True,
        None,
    )
    assert (row.submitted_title, row.submitted_summary) == (idea.title, idea.summary)
    assert row.project_id == team.project.id
    # The token is kept only hashed and sealed.
    assert row.tracking_token_hash == tracking_token_hash(token)
    assert row.tracking_token_sealed is not None
    assert token not in row.tracking_token_sealed
    assert unseal_tracking_token(settings, row.tracking_token_sealed) == token
    # One event, no actor; no watchers; no notifications.
    events = list(
        await db_session.scalars(select(ActivityEvent).where(ActivityEvent.idea_id == idea.id))
    )
    assert [(e.type, e.actor_id) for e in events] == [("idea_created", None)]
    assert await count(db_session, IdeaWatcher) == 0
    assert await count(db_session, Notification) == 0
    # The confirmation email, naming its idea.
    [email] = list(await db_session.scalars(select(OutboundEmail)))
    assert (email.type, email.to_address, email.idea_id, email.payload) == (
        EmailType.SUBMISSION_RECEIVED,
        "jo@example.org",
        idea.id,
        {},
    )
    assert email.idempotency_key == f"submission_received:{row.id}:1"


@pytest.mark.parametrize(
    ("values", "held_for"),
    [
        ({"public_moderation_required": False}, None),
        ({"public_moderation_required": True}, "moderation"),
        ({"public_require_email_verification": True}, "email_verification"),
    ],
)
async def test_where_a_new_idea_waits(
    anon: httpx.AsyncClient,
    team: Team,
    form: Form,
    db_session: AsyncSession,
    values: dict[str, Any],
    held_for: str | None,
) -> None:
    await form(**values)

    receipt = (await send(anon, team.slug, email="jo@example.org")).json()

    assert receipt["held_for"] == held_for
    _, idea = await submitted(db_session)
    assert (idea.held_for.value if idea.held_for else None) == held_for


async def test_numbers_continue_the_projects_sequence(
    anon: httpx.AsyncClient, visitor: Visitor, team: Team, api: Any, db_session: AsyncSession
) -> None:
    internal = await (await api(team.member)).create_idea(team.slug)

    await send(anon, team.slug)

    _, idea = await submitted(db_session)
    assert idea.number == internal["number"] + 1


async def test_no_address_means_no_email(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    receipt = (await send(anon, team.slug, name="  ", email="")).json()

    assert receipt["email_sent"] is False
    row, _ = await submitted(db_session)
    assert (row.name, row.email) == (None, None)
    assert await count(db_session, OutboundEmail) == 0


async def test_updates_need_an_address(anon: httpx.AsyncClient, team: Team) -> None:
    response = await send(anon, team.slug, wants_updates=True)

    assert_problem(response, 422, "validation_error")


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_with_email_off_an_address_and_updates_are_dropped(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    """A form loaded before email was turned off still goes through, keeping neither."""
    response = await send(anon, team.slug, email="jo@example.org", wants_updates=True)

    assert response.status_code == 201, response.text
    assert response.json()["email_sent"] is False
    row, _ = await submitted(db_session)
    assert (row.email, row.wants_updates) == (None, False)
    assert await count(db_session, OutboundEmail) == 0


async def test_a_required_address_must_be_given(
    anon: httpx.AsyncClient, team: Team, form: Form, db_session: AsyncSession
) -> None:
    await form(public_require_email_verification=True)

    response = await send(anon, team.slug)

    assert_problem(response, 422, "email_required")
    assert await count(db_session, Idea) == 0
    assert await count(db_session, AltchaUsedChallenge) == 0  # checked before ALTCHA


# --- The honeypot ----------------------------------------------------------------------------
@pytest.mark.parametrize("website", ["https://spam.example", "x" * 5_000])
async def test_a_filled_honeypot_gets_a_lookalike_receipt_and_keeps_nothing(
    anon: httpx.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    website: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = await send(anon, team.slug, email="jo@example.org", website=website)

    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == {"tracking_token", "tracking_url", "held_for", "email_sent"}
    assert len(receipt["tracking_token"]) == 43
    assert receipt["held_for"] == "moderation"
    assert receipt["email_sent"] is True
    assert await count(db_session, Idea) == 0
    assert await count(db_session, PublicSubmission) == 0
    assert await count(db_session, OutboundEmail) == 0
    assert await count(db_session, AltchaUsedChallenge) == 1  # the solution is spent
    assert "public submission dropped (honeypot)" in caplog.messages
    # The fake token tracks nothing.
    tracked = await anon.post(f"{PUBLIC}/track", json={"token": receipt["tracking_token"]})
    assert tracked.status_code == 404


async def test_a_filled_honeypot_answers_like_a_real_submission(
    anon: httpx.AsyncClient, team: Team, form: Form, db_session: AsyncSession
) -> None:
    bad_challenge = await send(anon, team.slug, website="x", altcha="AAAA")
    assert_problem(bad_challenge, 422, "challenge_failed")

    await form(public_require_email_verification=True)
    assert_problem(await send(anon, team.slug, website="x"), 422, "email_required")


@pytest.mark.settings(public_submissions_per_project=1)
async def test_a_filled_honeypot_on_a_saturated_project_is_429(
    visitor: Visitor, team: Team
) -> None:
    assert (await send(await visitor("198.51.100.1"), team.slug)).status_code == 201

    response = await send(await visitor("198.51.100.2"), team.slug, website="x")

    assert_problem(response, 429, "too_many_attempts")
    assert int(response.headers["retry-after"]) > 3500


# --- Per-IP limit ----------------------------------------------------------------------------
async def test_the_eleventh_attempt_from_one_address_in_an_hour_is_refused(
    visitor: Visitor, team: Team, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Every attempt counts: failed challenges and honeypot hits too."""
    client = await visitor()
    for n in range(9):
        assert_problem(
            await send(client, team.slug, altcha="AAAA", title=f"Bot {n}"), 422, "challenge_failed"
        )
    assert (await send(client, team.slug, website="x")).status_code == 201
    caplog.set_level(logging.INFO)
    caplog.clear()

    response = await send(client, team.slug)

    assert_problem(response, 429, "too_many_attempts")
    assert 3500 < int(response.headers["retry-after"]) <= 3600
    assert "several ideas" in response.json()["detail"]
    assert await count(db_session, Idea) == 0
    refusals = [r for r in caplog.records if r.getMessage() == "public submission refused"]
    assert [(r.levelno, getattr(r, "reason", None)) for r in refusals] == [
        (logging.WARNING, "rate_limited")
    ]
    assert VISITOR_IP not in caplog.text
    # Another address is fine; the next refusal of this one is only INFO.
    assert (await send(await visitor("198.51.100.20"), team.slug)).status_code == 201
    assert (await send(client, team.slug)).status_code == 429
    later = [r for r in caplog.records if r.getMessage() == "public submission refused"]
    assert later[-1].levelno == logging.INFO


async def test_a_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored(
    visitor: Visitor, team: Team
) -> None:
    client = await visitor()
    for n in range(10):
        response = await client.post(
            f"{PUBLIC}/projects/{team.slug}/submissions",
            json=submission(altcha="AAAA"),
            headers={"X-Forwarded-For": f"198.51.100.{n}"},
        )
        assert_problem(response, 422, "challenge_failed")

    response = await client.post(
        f"{PUBLIC}/projects/{team.slug}/submissions",
        json=submission(altcha="AAAA"),
        headers={"X-Forwarded-For": "198.51.100.99"},
    )

    assert_problem(response, 429, "too_many_attempts")


@pytest.mark.settings(trusted_proxies=["10.0.0.0/8"])
async def test_behind_the_ingress_the_forwarded_client_is_the_key(
    visitor: Visitor, team: Team
) -> None:
    ingress = await visitor("10.42.0.7")
    for _ in range(10):
        response = await ingress.post(
            f"{PUBLIC}/projects/{team.slug}/submissions",
            json=submission(altcha="AAAA"),
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        assert_problem(response, 422, "challenge_failed")

    same = await ingress.post(
        f"{PUBLIC}/projects/{team.slug}/submissions",
        json=submission(altcha="AAAA"),
        headers={"X-Forwarded-For": "198.51.100.1"},
    )
    other = await ingress.post(
        f"{PUBLIC}/projects/{team.slug}/submissions",
        json=submission(altcha="AAAA"),
        headers={"X-Forwarded-For": "198.51.100.2"},
    )

    assert_problem(same, 429, "too_many_attempts")
    assert_problem(other, 422, "challenge_failed")


@pytest.mark.settings(public_submissions_per_ip=1)
async def test_ipv6_clients_count_per_64(visitor: Visitor, team: Team) -> None:
    assert (await send(await visitor("2001:db8:1:2::10"), team.slug)).status_code == 201

    response = await send(await visitor("2001:db8:1:2::99"), team.slug)

    assert_problem(response, 429, "too_many_attempts")
    assert (await send(await visitor("2001:db8:1:3::10"), team.slug)).status_code == 201


async def test_an_unavailable_form_does_not_count_against_the_address(
    visitor: Visitor, team: Team
) -> None:
    client = await visitor()
    for _ in range(12):
        response = await client.post(
            f"{PUBLIC}/projects/no-such-form/submissions", json=submission(altcha="AAAA")
        )
        assert response.status_code == 404

    assert (await send(client, team.slug)).status_code == 201


# --- Per-project limit (in the database, across replicas) ----------------------------------
@pytest.mark.settings(public_submissions_per_project=2)
async def test_the_per_project_limit_holds_across_replicas(
    app: FastAPI, visitor: Visitor, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    second = create_app(settings)
    async with second.router.lifespan_context(second):
        transport = httpx.ASGITransport(app=second, client=("198.51.100.50", 1))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as other:
            assert (await send(await visitor("198.51.100.1"), team.slug)).status_code == 201
            assert (await send(other, team.slug)).status_code == 201

            refused_here = await send(await visitor("198.51.100.2"), team.slug)
            refused_there = await send(other, team.slug)

    assert_problem(refused_here, 429, "too_many_attempts")
    assert_problem(refused_there, 429, "too_many_attempts")
    assert 3500 < int(refused_here.headers["retry-after"]) <= 3600
    assert await count(db_session, Idea) == 2
    # The refused solutions stay spent (a solution is accepted once).
    assert await count(db_session, AltchaUsedChallenge) == 4


@pytest.mark.settings(public_submissions_per_project=1)
async def test_the_per_project_window_is_an_hour(
    visitor: Visitor, team: Team, db_session: AsyncSession
) -> None:
    assert (await send(await visitor("198.51.100.1"), team.slug)).status_code == 201
    await db_session.execute(
        update(PublicSubmission).values(created_at=utcnow() - timedelta(minutes=61))
    )
    await db_session.commit()

    assert (await send(await visitor("198.51.100.2"), team.slug)).status_code == 201


@pytest.mark.settings(public_submissions_per_project=1)
async def test_the_limit_is_per_project(
    visitor: Visitor, team: Team, form: Form, db_session: AsyncSession
) -> None:
    other = await form(await make_project(db_session, slug="other-form", key="OTH"))
    assert (await send(await visitor("198.51.100.1"), team.slug)).status_code == 201

    assert (await send(await visitor("198.51.100.2"), other.slug)).status_code == 201


# --- Privacy in logs -------------------------------------------------------------------------
async def test_logs_hold_no_token_address_name_or_text(
    anon: httpx.AsyncClient, team: Team, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    response = await send(
        anon, team.slug, name="Jo Secretname", email="jo.private@example.org", wants_updates=True
    )
    token = response.json()["tracking_token"]
    await anon.post(f"{PUBLIC}/track", json={"token": token})

    for secret in (token, "jo.private", "Secretname", "Recycle packaging", VISITOR_IP):
        assert secret not in caplog.text


@pytest.mark.settings(public_submissions_per_project=1)
async def test_the_challenge_is_checked_before_the_per_project_limit(
    visitor: Visitor, team: Team
) -> None:
    assert (await send(await visitor("198.51.100.1"), team.slug)).status_code == 201

    response = await send(await visitor("198.51.100.2"), team.slug, altcha="AAAA")

    assert_problem(response, 422, "challenge_failed")
