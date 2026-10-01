"""The two submitter emails (contract-phase4 section 3.8), through the Phase 3 outbox
and worker: the confirmation email is fixed text with the confirmation and tracking
links; status emails go only to an opted-in, confirmed submitter and show only what
they sent; both are re-checked when sent."""

from __future__ import annotations

import html
import re
from email.message import EmailMessage
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType, HoldReason
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.public import PublicSubmission
from tests.public.conftest import (
    PUBLIC,
    AsUser,
    Outbox,
    RecordingTransport,
    Team,
    ok,
    only,
    send,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")

SPAM_TITLE = "CHEAP PILLS at pills.example"
SPAM_SUMMARY = "Visit pills.example for discount pills today"
SPAM_NAME = "Pill Seller"


def body_of(message: EmailMessage) -> str:
    parts = []
    for kind in ("plain", "html"):
        part = message.get_body((kind,))
        assert part is not None
        parts.append(html.unescape(str(part.get_content())))
    return "\n".join(parts)


async def emails_of(db: AsyncSession, type_: EmailType) -> list[OutboundEmail]:
    return list(
        await db.scalars(
            select(OutboundEmail)
            .where(OutboundEmail.type == type_)
            .order_by(OutboundEmail.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def test_the_confirmation_email_is_fixed_text_with_both_links(
    anon: httpx.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    receipt = ok(
        await send(
            anon,
            team.slug,
            title=SPAM_TITLE,
            summary=SPAM_SUMMARY,
            description_md="More at pills.example",
            name=SPAM_NAME,
            email="victim@example.org",
            wants_updates=True,
        ),
        201,
    )
    [email] = await emails_of(db_session, EmailType.SUBMISSION_RECEIVED)

    assert await delivery.send_email(runtime, email.id) == "sent"

    message, _, recipient = only(transport.sent)
    assert recipient == "victim@example.org"
    assert message["Subject"] == "Confirm your idea for Customer Innovation"
    assert message["List-Unsubscribe"] is None
    assert message["Auto-Submitted"] == "auto-generated"
    text = body_of(message)
    for typed in ("pills", "Pill Seller", "CHEAP", "discount"):
        assert typed.lower() not in text.lower()
    assert "Someone sent an idea to Customer Innovation" in text
    assert "If this wasn't you, ignore this email" in text
    assert f"http://testserver/track#{receipt['tracking_token']}" in text
    confirm = re.search(r"http://testserver/verify#([A-Za-z0-9_.-]+)", text)
    assert confirm is not None
    # The link confirms the address (posted on the Confirm click).
    verified = ok(await anon.post(f"{PUBLIC}/verify-email", json={"token": confirm.group(1)}))
    assert verified["title"] == SPAM_TITLE  # the confirmation page may show what they sent
    row, _ = await submitted(db_session)
    assert row.email_verified_at is not None


async def test_a_confirmation_email_is_cancelled_once_the_address_is_confirmed(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, runtime: Runtime
) -> None:
    await send(anon, team.slug, email="jo@example.org")
    [email] = await emails_of(db_session, EmailType.SUBMISSION_RECEIVED)
    await db_session.execute(update(PublicSubmission).values(email_verified_at=utcnow()))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"

    [email] = await emails_of(db_session, EmailType.SUBMISSION_RECEIVED)
    assert email.status is EmailStatus.CANCELLED


async def test_a_queued_email_to_a_forgotten_address_is_cancelled(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, runtime: Runtime
) -> None:
    await send(anon, team.slug, email="jo@example.org")
    [email] = await emails_of(db_session, EmailType.SUBMISSION_RECEIVED)
    await db_session.execute(update(PublicSubmission).values(email=None))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"


async def opted_in(
    anon: httpx.AsyncClient,
    team: Team,
    db: AsyncSession,
    *,
    verified: bool = True,
    wants_updates: bool = True,
) -> tuple[str, Idea]:
    receipt = ok(
        await send(anon, team.slug, email="jo@example.org", wants_updates=wants_updates), 201
    )
    row, idea = await submitted(db)
    await db.execute(
        update(PublicSubmission)
        .where(PublicSubmission.id == row.id)
        .values(email_verified_at=utcnow() if verified else None)
    )
    await db.execute(update(Idea).where(Idea.id == idea.id).values(held_for=None))  # approved
    await db.execute(
        update(OutboundEmail).values(status="sent", sent_at=utcnow(), next_attempt_at=None)
    )
    await db.commit()
    return receipt["tracking_token"], idea


async def move(api: AsUser, team: Team, idea: Idea, status: str, **extra: Any) -> None:
    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/status", {"status": status, **extra}))


async def test_status_emails_go_to_an_opted_in_confirmed_submitter(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
    outbox: Outbox,
) -> None:
    token, idea = await opted_in(anon, team, db_session)
    ok(
        await (await api(team.admin)).patch(
            f"/ideas/{idea.id}", {"title": "Internal rename", "summary": "Team notes"}
        )
    )

    await move(api, team, idea, "evaluating")

    [email] = await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)
    assert (email.to_address, email.idea_id, email.recipient_user_id) == (
        "jo@example.org",
        idea.id,
        None,
    )
    assert email.payload == {
        "from_status": "new",
        "from_resolution": None,
        "to_status": "evaluating",
        "to_resolution": None,
    }
    assert await delivery.send_email(runtime, email.id) == "sent"
    message = only(transport.messages)
    assert message["Subject"] == 'Your idea "Recycle packaging at the till" is now Evaluating'
    assert message["List-Unsubscribe"] is None
    text = body_of(message)
    assert "Internal rename" not in text
    assert "Team notes" not in text
    assert "Olive" not in text
    assert f"http://testserver/track#{token}" in text
    assert "Stop these emails" in text
    # No in-app notification row for the submitter (there is no user).
    assert all(n.user_id != idea.submitted_by_id for n in await outbox.notifications())


async def test_closing_shows_the_resolutions_label(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    _, idea = await opted_in(anon, team, db_session)

    await move(api, team, idea, "closed", resolution="accepted")

    [email] = await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)
    assert await delivery.send_email(runtime, email.id) == "sent"
    assert only(transport.messages)["Subject"].endswith("is now Accepted")


@pytest.mark.parametrize(
    ("verified", "wants_updates"), [(False, True), (True, False)], ids=["unconfirmed", "opted-out"]
)
async def test_no_status_email_without_a_confirmed_opt_in(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    verified: bool,
    wants_updates: bool,
) -> None:
    _, idea = await opted_in(anon, team, db_session, verified=verified, wants_updates=wants_updates)

    await move(api, team, idea, "evaluating")

    assert await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED) == []


async def test_turning_updates_off_cancels_a_queued_status_email(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, runtime: Runtime
) -> None:
    token, idea = await opted_in(anon, team, db_session)
    await move(api, team, idea, "evaluating")
    ok(await anon.put(f"{PUBLIC}/track/updates", json={"token": token, "wants_updates": False}))
    [email] = await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)

    assert await delivery.send_email(runtime, email.id) == "cancelled"

    [email] = await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)
    assert email.last_error == "Not sent: turned off by the recipient"


async def test_erasing_deletes_the_submitters_emails(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    _, idea = await opted_in(anon, team, db_session)
    await move(api, team, idea, "evaluating")
    assert len(await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)) == 1

    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/erase"))

    remaining = await db_session.scalars(
        select(OutboundEmail).where(OutboundEmail.idea_id == idea.id)
    )
    assert list(remaining) == []
    await move(api, team, idea, "shortlisted")
    assert await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED) == []


async def test_internal_ideas_get_no_submitter_email(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await (await api(team.member)).create_idea(team.slug)

    ok(await (await api(team.admin)).post(f"/ideas/{idea['id']}/status", {"status": "evaluating"}))

    assert await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED) == []


async def test_a_status_email_for_an_idea_held_again_is_cancelled(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, runtime: Runtime
) -> None:
    _, idea = await opted_in(anon, team, db_session)
    await move(api, team, idea, "evaluating")
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()
    [email] = await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)

    assert await delivery.send_email(runtime, email.id) == "cancelled"
