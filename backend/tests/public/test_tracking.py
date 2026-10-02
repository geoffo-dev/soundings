"""Tracking and confirmation links (contract-phase4 sections 3.7-3.9): what the
tracking page shows (and never shows), status emails on or off, the confirmation
email again, the submitter erasing their details, and confirming the address."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.submission_tokens import email_digest, make_confirmation_token
from app.config import Settings
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import EmailType, HoldReason
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.public import ConfirmationEmailSend, PublicSubmission
from app.public import retention
from tests.public.conftest import (
    PUBLIC,
    AsUser,
    Form,
    Team,
    Visitor,
    assert_problem,
    make_public_idea,
    ok,
    send,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")

PRIVATE_FIELDS = {
    "owner", "evaluators", "comments", "score", "aggregate_score", "tags", "key", "number",
    "description_md", "submitted_by", "email", "permissions", "votes", "watching",
}  # fmt: skip


async def receipt(client: httpx.AsyncClient, slug: str, **fields: Any) -> dict[str, Any]:
    response = await send(client, slug, **fields)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def track(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(f"{PUBLIC}/track", json={"token": token})


async def approve(db: AsyncSession, idea: Idea) -> None:
    """What approve_submission does to the idea (backend's route; c19 lifts)."""
    await db.execute(update(Idea).where(Idea.id == idea.id).values(held_for=None))
    await db.commit()


def all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in all_keys(v)}
    if isinstance(value, list):
        return {k for item in value for k in all_keys(item)}
    return set()


# --- The tracking page -----------------------------------------------------------------------
async def test_the_tracking_page_shows_the_submitters_own_words_and_status(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    sent = await receipt(anon, team.slug, name="Jo", email="jo@example.org", wants_updates=True)

    body = ok(await track(anon, sent["tracking_token"]))

    assert body == {
        "project": {"slug": team.slug, "name": "Customer Innovation"},
        "title": "Recycle packaging at the till",
        "summary": "Let customers hand back packaging when they pay.",
        "submitted_at": body["submitted_at"],
        "held_for": "moderation",
        "status": "new",
        "resolution": None,
        "status_label": "New",
        "history": [],
        "email_hint": "j•••@example.org",
        "email_verified": False,
        "wants_updates": True,
        "can_resend_verification": True,
        "branding": body["branding"],
    }
    assert not all_keys(body) & PRIVATE_FIELDS


async def test_after_the_team_edits_the_idea_the_page_shows_what_was_sent(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    sent = await receipt(anon, team.slug)
    _, idea = await submitted(db_session)
    await approve(db_session, idea)
    admin = await api(team.admin)
    ok(
        await admin.patch(
            f"/ideas/{idea.id}",
            {"title": "Internal: till recycling", "summary": "Owner notes", "description_md": "x"},
        )
    )
    ok(await admin.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.owner.id)}))
    ok(await admin.post(f"/ideas/{idea.id}/comments", {"body_md": "Secret internal note"}), 201)
    ok(await admin.post(f"/ideas/{idea.id}/status", {"status": "evaluating"}))

    body = ok(await track(anon, sent["tracking_token"]))

    assert body["title"] == "Recycle packaging at the till"
    assert body["summary"] == "Let customers hand back packaging when they pay."
    assert (body["status"], body["status_label"], body["held_for"]) == (
        "evaluating",
        "Evaluating",
        None,
    )
    assert [(h["status"], h["status_label"]) for h in body["history"]] == [
        ("evaluating", "Evaluating")
    ]
    text = str(body)
    for private in ("Internal", "Owner notes", "Secret internal note", "Olive", "CUST"):
        assert private not in text
    assert not all_keys(body) & PRIVATE_FIELDS


async def test_closed_ideas_show_the_resolutions_label(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    sent = await receipt(anon, team.slug)
    _, idea = await submitted(db_session)
    await approve(db_session, idea)
    ok(
        await (await api(team.admin)).post(
            f"/ideas/{idea.id}/status", {"status": "closed", "resolution": "accepted"}
        )
    )

    body = ok(await track(anon, sent["tracking_token"]))

    assert (body["status"], body["resolution"], body["status_label"]) == (
        "closed",
        "accepted",
        "Accepted",
    )
    assert body["history"][-1]["status_label"] == "Accepted"


async def test_unknown_and_erased_tokens_are_the_same_404(
    anon: httpx.AsyncClient, team: Team
) -> None:
    sent = await receipt(anon, team.slug)
    assert (
        await anon.post(f"{PUBLIC}/track/erase", json={"token": sent["tracking_token"]})
    ).status_code == 204

    erased = await track(anon, sent["tracking_token"])
    unknown = await track(anon, "A" * 43)

    assert_problem(erased, 404, "not_found")
    assert_problem(unknown, 404, "not_found")
    assert erased.json()["detail"] == unknown.json()["detail"]


async def test_a_deleted_idea_is_404(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    sent = await receipt(anon, team.slug)
    _, idea = await submitted(db_session)
    await db_session.delete(await db_session.get(Idea, idea.id))
    await db_session.commit()

    assert_problem(await track(anon, sent["tracking_token"]), 404, "not_found")


@pytest.mark.settings(public_submission_enabled=False)
async def test_tracking_is_off_with_the_instance_switch(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, _ = await make_public_idea(db_session, settings, team)

    assert_problem(await track(anon, token), 404, "not_found")


async def test_tracking_still_works_after_the_form_is_turned_off(
    anon: httpx.AsyncClient, team: Team, form: Form
) -> None:
    sent = await receipt(anon, team.slug)
    await form(public_submission_enabled=False)

    assert (await track(anon, sent["tracking_token"])).status_code == 200


async def test_the_token_is_stored_only_hashed_and_sealed(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    sent = await receipt(anon, team.slug, email="jo@example.org")
    token = sent["tracking_token"]

    rows = await db_session.execute(select(PublicSubmission))
    for row in rows.scalars():
        for column in PublicSubmission.__table__.columns:
            assert token not in str(getattr(row, column.key))
    for email in await db_session.scalars(select(OutboundEmail)):
        assert token not in str(email.payload)


async def test_link_requests_are_throttled_per_address(visitor: Visitor, team: Team) -> None:
    client = await visitor("198.51.100.77")
    for _ in range(60):
        assert (await track(client, "B" * 43)).status_code == 404

    response = await track(client, "B" * 43)

    assert_problem(response, 429, "too_many_attempts")
    assert int(response.headers["retry-after"]) >= 1
    assert (await track(await visitor("198.51.100.78"), "B" * 43)).status_code == 404


# --- Status emails on or off -----------------------------------------------------------------
async def test_updates_can_be_turned_on_and_off(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    sent = await receipt(anon, team.slug, email="jo@example.org")
    token = sent["tracking_token"]

    on = ok(await anon.put(f"{PUBLIC}/track/updates", json={"token": token, "wants_updates": True}))
    again = ok(
        await anon.put(f"{PUBLIC}/track/updates", json={"token": token, "wants_updates": True})
    )
    off = ok(
        await anon.put(f"{PUBLIC}/track/updates", json={"token": token, "wants_updates": False})
    )

    assert (on["wants_updates"], again["wants_updates"], off["wants_updates"]) == (
        True,
        True,
        False,
    )
    row, _ = await submitted(db_session)
    assert row.wants_updates is False


async def test_updates_need_an_address_on_file(anon: httpx.AsyncClient, team: Team) -> None:
    sent = await receipt(anon, team.slug)

    response = await anon.put(
        f"{PUBLIC}/track/updates", json={"token": sent["tracking_token"], "wants_updates": True}
    )

    assert_problem(response, 409, "no_email")
    off = await anon.put(
        f"{PUBLIC}/track/updates", json={"token": sent["tracking_token"], "wants_updates": False}
    )
    assert off.status_code == 200


# --- The confirmation email again ------------------------------------------------------------
async def confirmation_emails(db: AsyncSession) -> list[OutboundEmail]:
    return list(
        await db.scalars(
            select(OutboundEmail)
            .where(OutboundEmail.type == EmailType.SUBMISSION_RECEIVED)
            .order_by(OutboundEmail.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def test_the_confirmation_email_can_be_sent_three_times_a_day(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    token = (await receipt(anon, team.slug, email="jo@example.org"))["tracking_token"]
    url = f"{PUBLIC}/track/verification-email"

    first = await anon.post(url, json={"token": token})
    second = await anon.post(url, json={"token": token})
    third = await anon.post(url, json={"token": token})

    assert (first.status_code, second.status_code) == (202, 202)
    assert second.json()["can_resend_verification"] is False
    assert_problem(third, 429, "too_many_attempts")
    assert 86_000 < int(third.headers["retry-after"]) <= 86_400
    emails = await confirmation_emails(db_session)
    assert [e.idempotency_key.rsplit(":", 1)[1] for e in emails if e.idempotency_key] == [
        "1",
        "2",
        "3",
    ]
    # A day later it may be sent again.
    await db_session.execute(
        update(OutboundEmail).values(created_at=utcnow() - timedelta(hours=25))
    )
    await db_session.commit()
    assert (await anon.post(url, json={"token": token})).status_code == 202


async def test_resend_refusals(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    url = f"{PUBLIC}/track/verification-email"
    without = (await receipt(anon, team.slug))["tracking_token"]
    assert_problem(await anon.post(url, json={"token": without}), 409, "no_email")

    with_email = (await receipt(anon, team.slug, email="kim@example.org", title="Two"))[
        "tracking_token"
    ]
    row, _ = await submitted(db_session, with_email)
    await db_session.execute(
        update(PublicSubmission)
        .where(PublicSubmission.id == row.id)
        .values(email_verified_at=utcnow())
    )
    await db_session.commit()
    assert_problem(await anon.post(url, json={"token": with_email}), 409, "already_verified")


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_resend_needs_email_on(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, _ = await make_public_idea(db_session, settings, team, email="jo@example.org")

    response = await anon.post(f"{PUBLIC}/track/verification-email", json={"token": token})

    assert_problem(response, 409, "smtp_not_configured")


async def test_the_per_address_limit_counts_sub_addresses_and_resends_silently(
    visitor: Visitor, team: Team, db_session: AsyncSession
) -> None:
    """jo@x, Jo+1@x and a resend make three; the fourth is accepted without an email,
    and nothing says so (email_sent stays true)."""
    one = await receipt(await visitor("198.51.100.1"), team.slug, email="jo@example.org")
    await receipt(await visitor("198.51.100.2"), team.slug, email="Jo+1@Example.org", title="B")
    resent = await (await visitor("198.51.100.3")).post(
        f"{PUBLIC}/track/verification-email", json={"token": one["tracking_token"]}
    )
    assert resent.status_code == 202
    assert len(await confirmation_emails(db_session)) == 3

    fourth = await receipt(
        await visitor("198.51.100.4"), team.slug, email="jo+spam@example.org", title="C"
    )

    assert fourth["email_sent"] is True
    assert len(await confirmation_emails(db_session)) == 3
    other = await receipt(
        await visitor("198.51.100.5"), team.slug, email="kim@example.org", title="D"
    )
    assert other["email_sent"] is True
    assert len(await confirmation_emails(db_session)) == 4


async def test_erasing_or_rejecting_does_not_reset_the_per_address_limit(
    visitor: Visitor, team: Team, db_session: AsyncSession, api: AsUser
) -> None:
    """Code review M1: submit, then erase the details (or have the idea rejected), five
    times: the same address got five confirmation emails in a minute, because both
    delete the outbox rows the limit counted. It counts its own rows now."""
    admin = await api(team.platform)
    queued = 0
    for n in range(5):
        client = await visitor(f"198.51.100.{n + 1}")
        sent = await receipt(client, team.slug, email="victim@example.org", title=f"T{n}")
        queued += len(await confirmation_emails(db_session))
        if n % 2:
            erased = await client.post(
                f"{PUBLIC}/track/erase", json={"token": sent["tracking_token"]}
            )
            assert erased.status_code == 204
        else:
            _, idea = await submitted(db_session, sent["tracking_token"])
            rejected = await admin.post(f"/ideas/{idea.id}/submission/reject")
            assert rejected.status_code == 204
        assert await confirmation_emails(db_session) == []

    assert queued == 3


@pytest.mark.parametrize(
    "addresses",
    [
        ["v.ictim@gmail.com", "Victim+1@googlemail.com", "vic.tim@GMAIL.com", "victim@gmail.com"],
        ["jo-a@yahoo.com", "jo@yahoo.com", "JO-b@yahoo.com", "jo-c@yahoo.com"],
    ],
    ids=["gmail-dots", "yahoo-keywords"],
)
async def test_the_per_address_limit_folds_provider_variants(
    visitor: Visitor, team: Team, db_session: AsyncSession, addresses: list[str]
) -> None:
    """Code review L1: Gmail ignores dots (and googlemail.com is gmail.com); Yahoo's
    disposable base-keyword addresses reach one inbox."""
    for n, address in enumerate(addresses):
        client = await visitor(f"198.51.100.{n + 1}")
        assert (await receipt(client, team.slug, email=address, title=f"T{n}"))["email_sent"]

    assert len(await confirmation_emails(db_session)) == 3


async def test_the_limit_keeps_a_keyed_hash_not_the_address_and_forgets_it_after_a_day(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    await receipt(anon, team.slug, email="Victim+news@Example.org")
    [send] = list(await db_session.scalars(select(ConfirmationEmailSend)))

    assert re.fullmatch(r"[0-9a-f]{64}", send.address_key)
    assert send.address_key != hashlib.sha256(b"victim@example.org").hexdigest()
    assert await retention.cleanup(db_session, utcnow() + timedelta(hours=23)) is not None
    assert await db_session.scalar(select(func.count()).select_from(ConfirmationEmailSend)) == 1
    await retention.cleanup(db_session, utcnow() + timedelta(hours=25))
    assert await db_session.scalar(select(func.count()).select_from(ConfirmationEmailSend)) == 0


# --- Erasing my details ----------------------------------------------------------------------
async def test_the_submitter_can_erase_their_details(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    sent = await receipt(anon, team.slug, name="Jo", email="jo@example.org", wants_updates=True)
    row, idea = await submitted(db_session)
    await db_session.execute(
        update(OutboundEmail).values(status="sent", sent_at=utcnow(), next_attempt_at=None)
    )
    await db_session.commit()

    response = await anon.post(f"{PUBLIC}/track/erase", json={"token": sent["tracking_token"]})

    assert response.status_code == 204
    erased = await db_session.get(PublicSubmission, row.id, populate_existing=True)
    assert erased is not None
    assert (erased.name, erased.email, erased.email_verified_at, erased.wants_updates) == (
        None,
        None,
        None,
        False,
    )
    assert (erased.tracking_token_hash, erased.tracking_token_sealed) == (None, None)
    assert (erased.submitted_title, erased.submitted_summary) == (None, None)
    assert erased.erased_at is not None
    assert erased.erased_by_id is None
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 0
    kept = await db_session.get(Idea, idea.id, populate_existing=True)
    assert kept is not None
    assert kept.title == "Recycle packaging at the till"
    [entry] = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "submission.erase"))
    )
    assert (entry.actor_id, entry.target_id, entry.details) == (
        None,
        idea.id,
        {"reason": "submitter"},
    )
    assert "jo@example.org" not in str(entry.details)
    # The link stops working at once: a second call is 404.
    again = await anon.post(f"{PUBLIC}/track/erase", json={"token": sent["tracking_token"]})
    assert_problem(again, 404, "not_found")
    assert sent["tracking_token"] not in caplog.text


# --- Confirming the address ------------------------------------------------------------------
def confirmation_token(settings: Settings, row: PublicSubmission, **kwargs: Any) -> str:
    assert row.email is not None
    return make_confirmation_token(settings, row.id, row.email, now=kwargs.get("now", utcnow()))


async def verify(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(f"{PUBLIC}/verify-email", json={"token": token})


@pytest.mark.parametrize(
    ("moderated", "after"), [(True, "moderation"), (False, None)], ids=["moderated", "open"]
)
async def test_confirming_releases_an_idea_held_for_it(
    anon: httpx.AsyncClient,
    team: Team,
    form: Form,
    db_session: AsyncSession,
    settings: Settings,
    moderated: bool,
    after: str | None,
) -> None:
    await form(public_require_email_verification=True, public_moderation_required=moderated)
    await receipt(anon, team.slug, email="jo@example.org")
    row, idea = await submitted(db_session)
    assert idea.held_for is HoldReason.EMAIL_VERIFICATION
    before = idea.last_activity_at

    body = ok(await verify(anon, confirmation_token(settings, row)))

    assert body["held_for"] == after
    assert body["title"] == "Recycle packaging at the till"
    assert body["project"] == {"slug": team.slug, "name": "Customer Innovation"}
    assert set(body) == {"project", "title", "held_for", "branding"}
    row, idea = await submitted(db_session)
    assert row.email_verified_at is not None
    assert (idea.held_for.value if idea.held_for else None) == after
    assert idea.last_activity_at >= before
    # Idempotent.
    assert ok(await verify(anon, confirmation_token(settings, row)))["held_for"] == after


async def test_confirming_still_works_after_the_form_is_turned_off(
    anon: httpx.AsyncClient, team: Team, form: Form, db_session: AsyncSession, settings: Settings
) -> None:
    await receipt(anon, team.slug, email="jo@example.org")
    row, _ = await submitted(db_session)
    await form(public_submission_enabled=False)

    assert (await verify(anon, confirmation_token(settings, row))).status_code == 200


async def test_invalid_confirmation_tokens_are_404(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    await receipt(anon, team.slug, email="jo@example.org")
    row, _ = await submitted(db_session)
    good = confirmation_token(settings, row)
    body, mac = good.split(".")
    other_key = settings.model_copy(
        update={"secret_key": __import__("pydantic").SecretStr("x" * 40)}
    )

    for token in [
        confirmation_token(settings, row, now=utcnow() - timedelta(days=3, seconds=1)),  # expired
        f"{body}.{mac[:-2]}AA",  # tampered signature
        f"{body[:-2]}AA.{mac}",  # tampered payload
        make_confirmation_token(other_key, row.id, "jo@example.org", now=utcnow()),  # other key
        make_confirmation_token(settings, uuid4(), "jo@example.org", now=utcnow()),  # unknown
        make_confirmation_token(settings, row.id, "kim@example.org", now=utcnow()),  # other address
        "a" * 20,
        "a.b.c.d.e.f.g.h.i.j.k",
    ]:
        assert_problem(await verify(anon, token), 404, "not_found")

    row, _ = await submitted(db_session)
    assert row.email_verified_at is None


async def test_a_confirmation_link_is_spent_when_the_details_are_erased(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    sent = await receipt(anon, team.slug, email="jo@example.org")
    row, _ = await submitted(db_session)
    token = confirmation_token(settings, row)
    await anon.post(f"{PUBLIC}/track/erase", json={"token": sent["tracking_token"]})

    assert_problem(await verify(anon, token), 404, "not_found")


async def test_the_address_digest_is_case_insensitive() -> None:
    assert email_digest("Jo@Example.org") == email_digest("jo@example.org")
    assert len(email_digest("jo@example.org")) == 16


async def test_a_confirmed_idea_reaches_the_team(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    form: Form,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Held for confirmation it is in no list (nor by its link, for anyone); once
    confirmed in an unmoderated project it is in New for the team."""
    await form(public_require_email_verification=True, public_moderation_required=False)
    await receipt(anon, team.slug, email="jo@example.org")
    row, idea = await submitted(db_session)
    member, admin = await api(team.member), await api(team.admin)
    assert ok(await member.get(f"/projects/{team.slug}/ideas"))["total"] == 0
    assert_problem(await admin.get(f"/ideas/{idea.id}"), 404, "not_found")

    ok(await verify(anon, confirmation_token(settings, row)))

    listed = ok(await member.get(f"/projects/{team.slug}/ideas"))
    assert [i["title"] for i in listed["items"]] == ["Recycle packaging at the till"]
    detail = ok(await member.get(f"/ideas/{idea.id}"))
    assert (detail["held_for"], detail["via_public_form"], detail["submitted_by"]) == (
        None,
        True,
        None,
    )
