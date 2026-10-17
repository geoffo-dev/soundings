"""Phase 11's two submitter emails (contract-phase11 sections 7-8, ADR 0019): the tracking
link after the address's **first** confirmation (never in the confirmation email, never
twice, nothing retroactive), each team message to a confirmed address, both rendered at send
time in the project's branding, without ``Reply-To``, naming no person, and cancelled once
the submission was erased or the address changed."""

from __future__ import annotations

import html
import re
from email.message import EmailMessage
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email.delivery import Runtime
from app.models.enums import EmailStatus, EmailType, HoldReason
from app.models.notification import OutboundEmail
from app.models.public import PublicSubmission, SubmissionMessage
from tests.public.conftest import (
    PUBLIC,
    SMTP,
    AsUser,
    RecordingTransport,
    Team,
    make_public_idea,
    messages_url,
    ok,
    only,
    send,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    """With an operator Reply-To: the two new emails must leave it out (review S1)."""
    return {**SMTP, "altcha_cost": 1_000, "smtp_reply_to": "help@example.com"}


def text_of(message: EmailMessage) -> tuple[str, str]:
    plain = message.get_body(("plain",))
    rich = message.get_body(("html",))
    assert plain is not None
    assert rich is not None
    return str(plain.get_content()), str(rich.get_content())


async def emails_of(db: AsyncSession, type_: EmailType) -> list[OutboundEmail]:
    return list(
        await db.scalars(
            select(OutboundEmail)
            .where(OutboundEmail.type == type_)
            .order_by(OutboundEmail.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def confirmation_token(
    anon: httpx.AsyncClient, team: Team, db: AsyncSession, runtime: Runtime, transport: Any
) -> tuple[str, str]:
    """Submit with an address and read the confirmation link from the email sent."""
    receipt = ok(await send(anon, team.slug, email="jo@example.org"), 201)
    [email] = await emails_of(db, EmailType.SUBMISSION_RECEIVED)
    assert await delivery.send_email(runtime, email.id) == "sent"
    text, _ = text_of(transport.messages[-1])
    found = re.search(r"/verify#([A-Za-z0-9_.-]+)", text)
    assert found is not None
    return receipt["tracking_token"], found.group(1)


async def verify(anon: httpx.AsyncClient, token: str) -> dict[str, Any]:
    body: dict[str, Any] = ok(await anon.post(f"{PUBLIC}/verify-email", json={"token": token}))
    return body


# --- The tracking-link email (D1) --------------------------------------------------------------
async def test_the_first_confirmation_emails_the_tracking_link_once(
    anon: httpx.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    tracking, confirm = await confirmation_token(anon, team, db_session, runtime, transport)
    # Not at submission: the confirmation email carries no tracking link, but one sentence.
    assert await emails_of(db_session, EmailType.SUBMISSION_LINK) == []
    confirmation_text, confirmation_html = text_of(transport.messages[-1])
    assert "/track" not in confirmation_text + confirmation_html
    assert tracking not in confirmation_text + confirmation_html
    assert "Once you confirm, we'll email you a private link to follow your idea." in (
        confirmation_text
    )

    first = await verify(anon, confirm)
    again = await verify(anon, confirm)

    assert (first["tracking_link_emailed"], again["tracking_link_emailed"]) == (True, False)
    [email] = await emails_of(db_session, EmailType.SUBMISSION_LINK)
    row, idea = await submitted(db_session)
    assert (email.to_address, email.idea_id, email.payload) == ("jo@example.org", idea.id, {})
    assert email.idempotency_key == f"submission_link:{row.id}"

    assert await delivery.send_email(runtime, email.id) == "sent"
    message, _, recipient = transport.sent[-1]
    assert recipient == "jo@example.org"
    assert message["Subject"] == "Your link to follow your idea for Customer Innovation"
    assert message["Reply-To"] is None  # review S1
    assert message["List-Unsubscribe"] is None
    text, rich = text_of(message)
    assert f"See where your idea stands: http://testserver/track#{tracking}" in text
    assert f'href="http://testserver/track#{tracking}"' in rich
    assert (
        "Keep this link private: anyone who has it can see where your idea stands, reply to "
        "the team and delete your details." in text
    )
    assert "Recycle packaging at the till" in text  # the title as they sent it
    assert f"Stop emails about this idea: http://testserver/track#{tracking}" in text
    assert "Stop emails about this idea" in rich


async def test_a_resend_and_a_repeated_confirmation_send_no_link(
    anon: httpx.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    tracking, _ = await confirmation_token(anon, team, db_session, runtime, transport)
    ok(await anon.post(f"{PUBLIC}/track/verification-email", json={"token": tracking}), 202)

    assert await emails_of(db_session, EmailType.SUBMISSION_LINK) == []


async def test_an_address_confirmed_before_gets_no_link(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Nothing retroactive: a submission confirmed before this release (or by an earlier
    link) is confirmed again without a link email."""
    from app.auth.submission_tokens import make_confirmation_token
    from app.models.base import utcnow

    token, _ = await make_public_idea(db_session, settings, team, email="jo@example.org")
    row, _ = await submitted(db_session, token)
    await db_session.execute(
        update(PublicSubmission)
        .where(PublicSubmission.id == row.id)
        .values(email_verified_at=utcnow())
    )
    await db_session.commit()
    confirm = make_confirmation_token(settings, row.id, "jo@example.org", now=utcnow())

    assert (await verify(anon, confirm))["tracking_link_emailed"] is False
    assert await emails_of(db_session, EmailType.SUBMISSION_LINK) == []


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_without_email_no_link_is_queued(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    from app.auth.submission_tokens import make_confirmation_token
    from app.models.base import utcnow

    token, _ = await make_public_idea(db_session, settings, team, email="jo@example.org")
    row, _ = await submitted(db_session, token)
    confirm = make_confirmation_token(settings, row.id, "jo@example.org", now=utcnow())

    assert (await verify(anon, confirm))["tracking_link_emailed"] is False
    assert await emails_of(db_session, EmailType.SUBMISSION_LINK) == []


async def test_a_queued_link_is_cancelled_once_the_address_changed_or_details_are_gone(
    anon: httpx.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    tracking, confirm = await confirmation_token(anon, team, db_session, runtime, transport)
    await verify(anon, confirm)
    [email] = await emails_of(db_session, EmailType.SUBMISSION_LINK)
    await db_session.execute(update(PublicSubmission).values(email="someone@example.org"))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"

    # Erasing the details deletes the row outright (every submitter email).
    ok(await anon.post(f"{PUBLIC}/track/erase", json={"token": tracking}), 204)
    assert await emails_of(db_session, EmailType.SUBMISSION_LINK) == []


async def test_the_link_email_needs_the_sealed_token(
    team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Seeded submissions have no link: none can be emailed."""
    from uuid import uuid4

    from app.models.base import utcnow
    from app.public.emails import queue_link_email

    _, idea = await make_public_idea(db_session, settings, team, email="jo@example.org")
    seeded = PublicSubmission(
        id=uuid4(),
        idea_id=idea.id,
        project_id=team.project.id,
        email="jo@example.org",
        email_verified_at=utcnow(),
        tracking_token_sealed=None,
    )

    assert await queue_link_email(db_session, settings, seeded, now=utcnow()) is False
    assert await emails_of(db_session, EmailType.SUBMISSION_LINK) == []


# --- Team messages by email -------------------------------------------------------------------
async def test_a_team_message_reaches_a_confirmed_address_signed_by_the_team(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    tracking, idea = await make_public_idea(
        db_session,
        settings,
        team,
        email="sam@example.org",
        verified=True,
        owner=team.owner,
        title="Reusable delivery boxes",
    )
    body = "Hi Sam!\n<script>alert(1)</script> & **not bold**\n\nWhich stores?"

    sent = ok(await (await api(team.owner)).post(messages_url(idea), {"body": body}), 201)

    assert sent["emailed"] is True
    email = only(await emails_of(db_session, EmailType.SUBMISSION_MESSAGE))
    assert email.payload == {"message_id": sent["id"]}  # never the text
    assert (email.to_address, email.idea_id) == ("sam@example.org", idea.id)
    assert await delivery.send_email(runtime, email.id) == "sent"
    message, _, recipient = transport.sent[-1]
    assert recipient == "sam@example.org"
    assert message["Subject"] == "A message about your idea for Customer Innovation"
    assert message["Reply-To"] is None
    text, rich = text_of(message)
    # Plain text with its line breaks; escaped in HTML (no tag, no Markdown).
    assert "Hi Sam!\n<script>alert(1)</script> & **not bold**\n\nWhich stores?" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; **not bold**" in rich
    assert "<script>" not in rich
    assert "Hi Sam!<br>" in rich
    assert "The Customer Innovation team" in text
    assert 'About your idea "Reusable delivery boxes":' in text
    assert f"Reply: http://testserver/track#{tracking}" in text
    assert "Replies to this email aren't read: reply on your tracking page." in text
    assert "To stop all email about this idea, remove your email address" in text
    # Never a person: not the author's name or address.
    for person in (team.owner.display_name, team.owner.email, "Olive"):
        assert person not in text
        assert person not in html.unescape(rich)


async def test_message_emails_ignore_the_status_email_switch(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """``wants_updates`` is for automatic status emails; the address was given for the team
    to contact them."""
    _, idea = await make_public_idea(
        db_session, settings, team, email="sam@example.org", verified=True, wants_updates=False
    )

    ok(await (await api(team.admin)).post(messages_url(idea), {"body": "Hello"}), 201)

    assert len(await emails_of(db_session, EmailType.SUBMISSION_MESSAGE)) == 1


async def test_a_moderator_may_email_before_approving(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    runtime: Runtime,
) -> None:
    _, idea = await make_public_idea(
        db_session,
        settings,
        team,
        email="sam@example.org",
        verified=True,
        held_for=HoldReason.MODERATION,
    )
    ok(await (await api(team.admin)).post(messages_url(idea), {"body": "Which store?"}), 201)

    [email] = await emails_of(db_session, EmailType.SUBMISSION_MESSAGE)
    assert await delivery.send_email(runtime, email.id) == "sent"


async def test_a_message_email_is_cancelled_once_the_conversation_is_gone(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, runtime: Runtime
) -> None:
    _, idea = await make_public_idea(
        db_session, settings, team, email="sam@example.org", verified=True
    )
    ok(await (await api(team.admin)).post(messages_url(idea), {"body": "Hello"}), 201)
    [email] = await emails_of(db_session, EmailType.SUBMISSION_MESSAGE)
    await db_session.execute(delete(SubmissionMessage))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"
    [email] = await emails_of(db_session, EmailType.SUBMISSION_MESSAGE)
    assert email.status is EmailStatus.CANCELLED


async def test_a_message_email_is_cancelled_once_the_address_is_unconfirmed(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, runtime: Runtime
) -> None:
    _, idea = await make_public_idea(
        db_session, settings, team, email="sam@example.org", verified=True
    )
    ok(await (await api(team.admin)).post(messages_url(idea), {"body": "Hello"}), 201)
    [email] = await emails_of(db_session, EmailType.SUBMISSION_MESSAGE)
    await db_session.execute(update(PublicSubmission).values(email_verified_at=None))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"


async def test_the_other_emails_keep_the_operators_reply_to(
    anon: httpx.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    """Review S1 changes the two new types only."""
    await send(anon, team.slug, email="jo@example.org")
    [email] = await emails_of(db_session, EmailType.SUBMISSION_RECEIVED)

    assert await delivery.send_email(runtime, email.id) == "sent"

    assert transport.messages[-1]["Reply-To"] == "help@example.com"
