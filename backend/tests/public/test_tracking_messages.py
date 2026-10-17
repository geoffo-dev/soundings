"""Phase 11: the submitter's side (contract-phase11 sections 2.1, 3 and 5): the
conversation on the tracking page, the reply route (token checks, ``can_reply`` and each
``reply_blocked``, the throttles, JSON only, the body rules) and "Remove my email address"
(``forget_submission_email``, review M2)."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType, HoldReason, NotificationType
from app.models.idea import Idea
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project
from app.models.public import PublicSubmission, SubmissionMessage
from tests.public.conftest import (
    PUBLIC,
    AsUser,
    Team,
    Visitor,
    add_message,
    assert_problem,
    make_public_idea,
    messages_url,
    ok,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")

REPLY = "The two in the city centre see the most deliveries."


async def public_idea(
    db: AsyncSession, settings: Settings, team: Team, **values: Any
) -> tuple[str, Idea]:
    values.setdefault("email", "sam@example.org")
    values.setdefault("verified", True)
    values.setdefault("owner", team.owner)
    return await make_public_idea(db, settings, team, **values)


async def track(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(f"{PUBLIC}/track", json={"token": token})


async def reply(client: httpx.AsyncClient, token: str, body: str = REPLY) -> httpx.Response:
    return await client.post(f"{PUBLIC}/track/messages", json={"token": token, "body": body})


async def forget(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(f"{PUBLIC}/track/forget-email", json={"token": token})


async def team_writes(api: AsUser, team: Team, idea: Idea, body: str = "Which stores?") -> None:
    ok(await (await api(team.owner)).post(messages_url(idea), {"body": body}), 201)


# --- The conversation on the tracking page ------------------------------------------------------
async def test_the_page_shows_the_conversation_once_the_team_writes(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    before = ok(await track(anon, token))
    assert (before["messages"], before["can_reply"], before["reply_blocked"]) == (
        [],
        False,
        "awaiting_team",
    )
    assert before["team_messages_emailed"] is True

    await team_writes(api, team, idea, "Thanks, Sam! Which stores?")
    page = ok(await track(anon, token))

    [message] = page["messages"]
    assert set(message) == {"id", "direction", "body", "created_at"}  # no author: no people
    assert (message["direction"], message["body"]) == ("team", "Thanks, Sam! Which stores?")
    assert (page["can_reply"], page["reply_blocked"]) == (True, None)
    assert "Olive" not in json.dumps(page)


async def test_a_reply_comes_back_with_the_page(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    await team_writes(api, team, idea)

    page = ok(await reply(anon, token), 201)

    assert [(m["direction"], m["body"]) for m in page["messages"]] == [
        ("team", "Which stores?"),
        ("submitter", REPLY),
    ]
    listed = ok(await (await api(team.owner)).get(messages_url(idea)))
    assert listed["items"][0]["direction"] == "submitter"
    assert listed["items"][0]["author"] is None


async def test_the_public_never_starts_a_conversation(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, _ = await public_idea(db_session, settings, team)

    assert_problem(await reply(anon, token), 409, "awaiting_team")
    count = await db_session.scalar(select(func.count()).select_from(SubmissionMessage))
    assert count == 0


async def test_ten_replies_follow_each_team_message(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Review S6: the 11th reply since the team's latest message waits for the team."""
    token, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.admin, at=utcnow() - timedelta(days=2))
    await add_message(db_session, idea, "submitter", count=10, at=utcnow() - timedelta(days=2))

    assert_problem(await reply(anon, token), 409, "awaiting_team")
    page = ok(await track(anon, token))
    assert (page["can_reply"], page["reply_blocked"]) == (False, "awaiting_team")

    await team_writes(api, team, idea)
    ok(await reply(anon, token), 201)


async def test_ten_replies_a_day(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    oldest = utcnow() - timedelta(hours=22)
    await add_message(db_session, idea, author=team.admin, at=oldest - timedelta(minutes=1))
    await add_message(db_session, idea, "submitter", count=5, at=oldest)
    await add_message(db_session, idea, author=team.admin, at=oldest + timedelta(minutes=1))
    await add_message(db_session, idea, "submitter", count=5, at=oldest + timedelta(minutes=2))
    page = ok(await track(anon, token))
    assert (page["can_reply"], page["reply_blocked"]) == (False, "daily_limit")

    refused = await reply(anon, token)

    assert_problem(refused, 429, "too_many_attempts")
    assert 7100 <= int(refused.headers["Retry-After"]) <= 7200
    assert "replied 10 times today" in refused.json()["detail"]


async def test_a_full_conversation_takes_no_replies(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    old = utcnow() - timedelta(days=5)
    await add_message(db_session, idea, "submitter", count=99, at=old)
    await add_message(db_session, idea, author=team.admin, at=old + timedelta(minutes=1))

    assert_problem(await reply(anon, token), 409, "conversation_full")
    page = ok(await track(anon, token))
    assert len(page["messages"]) == 100  # review C1: all of them are shown
    assert page["reply_blocked"] == "conversation_full"


async def test_an_archived_project_takes_no_replies(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.admin)
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()

    assert_problem(await reply(anon, token), 409, "project_archived")
    page = ok(await track(anon, token))
    assert (len(page["messages"]), page["reply_blocked"]) == (1, "project_archived")


async def test_a_moderator_may_ask_and_the_submitter_answer_while_held(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)
    ok(await (await api(team.admin)).post(messages_url(idea), {"body": "Which store?"}), 201)

    ok(await reply(anon, token), 201)

    # No notification while held (in nobody's inbox); the queue says "They replied".
    assert await db_session.scalar(select(func.count()).select_from(Notification)) == 0
    queue = ok(await (await api(team.admin)).get(f"/projects/{team.slug}/moderation"))
    assert queue["items"][0]["submission"]["messages"]["last_direction"] == "submitter"


async def test_one_submissions_page_shows_only_its_own_conversation(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    other_token, _ = await public_idea(db_session, settings, team, title="Another idea")
    await team_writes(api, team, idea, "Only for the first submitter")

    other = ok(await track(anon, other_token))

    assert other["messages"] == []
    assert "Only for the first" not in json.dumps(other)
    assert_problem(await reply(anon, other_token), 409, "awaiting_team")
    assert len(ok(await track(anon, token))["messages"]) == 1


# --- Tokens, content type, body ----------------------------------------------------------------
async def test_unknown_and_erased_tokens_are_404(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    await team_writes(api, team, idea)
    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/erase"))

    assert_problem(await reply(anon, token), 404, "not_found")
    assert_problem(await reply(anon, "A" * 43), 404, "not_found")
    assert_problem(await forget(anon, token), 404, "not_found")


@pytest.mark.settings(public_submission_enabled=False)
async def test_every_token_is_404_while_public_submission_is_off(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.admin)

    assert_problem(await reply(anon, token), 404, "not_found")
    assert_problem(await forget(anon, token), 404, "not_found")


@pytest.mark.parametrize("route", ["track/messages", "track/forget-email"])
async def test_writes_must_be_json(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings, route: str
) -> None:
    token, _ = await public_idea(db_session, settings, team)

    response = await anon.post(
        f"{PUBLIC}/{route}",
        content=json.dumps({"token": token, "body": REPLY}),
        headers={"content-type": "text/plain"},
    )

    assert_problem(response, 415, "unsupported_media_type")


@pytest.mark.parametrize("body", ["", "  ", "⠀", "a\x00b", "tag \U000e0041", "x" * 4_001])
async def test_replies_that_show_nothing_or_hide_something_are_422(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    body: str,
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    await team_writes(api, team, idea)

    assert_problem(await reply(anon, token, body), 422, "validation_error")


async def test_a_reply_is_stored_as_plain_text(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    await team_writes(api, team, idea)

    page = ok(await reply(anon, token, "<b>Hi</b>\r\nsee https://evil.example\u2029bye"), 201)

    assert page["messages"][-1]["body"] == "<b>Hi</b>\nsee https://evil.example\nbye"


# --- Throttles ------------------------------------------------------------------------------
async def test_30_replies_an_hour_from_one_address(
    visitor: Visitor, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Every attempt past the token counts (here 409s: the team hasn't written)."""
    token, _ = await public_idea(db_session, settings, team)
    client = await visitor("198.51.100.20")
    for _ in range(30):
        assert_problem(await reply(client, token), 409, "awaiting_team")

    refused = await reply(client, token)

    assert_problem(refused, 429, "too_many_attempts")
    assert int(refused.headers["Retry-After"]) > 3000
    # Another address isn't held back; unknown tokens aren't counted.
    assert_problem(await reply(await visitor("198.51.100.21"), token), 409, "awaiting_team")


async def test_a_throttled_reply_takes_no_lock(
    visitor: Visitor, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Security review N4: the per-address throttle comes before the project, idea and
    submission locks, so a throttled client never waits for (or holds) a row lock: here the
    submission is locked elsewhere and the 31st attempt is still refused at once."""
    token, idea = await public_idea(db_session, settings, team)
    client = await visitor("198.51.100.30")
    for _ in range(30):
        assert_problem(await reply(client, token), 409, "awaiting_team")
    await db_session.execute(
        select(PublicSubmission.id).where(PublicSubmission.idea_id == idea.id).with_for_update()
    )
    try:
        refused = await asyncio.wait_for(reply(client, token), timeout=10)
    finally:
        await db_session.rollback()

    assert_problem(refused, 429, "too_many_attempts")


@pytest.mark.settings(trusted_proxies=["10.0.0.0/8"])
async def test_the_reply_throttle_uses_the_address_the_proxy_reports(
    visitor: Visitor, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, _ = await public_idea(db_session, settings, team)
    proxy = await visitor("10.0.0.5")
    for _ in range(30):
        response = await proxy.post(
            f"{PUBLIC}/track/messages",
            json={"token": token, "body": REPLY},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        assert_problem(response, 409, "awaiting_team")

    same = await proxy.post(
        f"{PUBLIC}/track/messages",
        json={"token": token, "body": REPLY},
        headers={"X-Forwarded-For": "198.51.100.1"},
    )
    other = await proxy.post(
        f"{PUBLIC}/track/messages",
        json={"token": token, "body": REPLY},
        headers={"X-Forwarded-For": "198.51.100.2"},
    )

    assert_problem(same, 429, "too_many_attempts")
    assert_problem(other, 409, "awaiting_team")


# --- "Remove my email address" (review M2) ------------------------------------------------------
async def test_removing_the_address_stops_every_email_and_keeps_the_conversation(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team, wants_updates=True)
    await team_writes(api, team, idea)  # queues a submission_message email
    assert await db_session.scalar(
        select(func.count()).select_from(OutboundEmail).where(OutboundEmail.idea_id == idea.id)
    )
    assert ok(await track(anon, token))["can_remove_email"] is True

    page = ok(await forget(anon, token))

    row, _ = await submitted(db_session, token)
    assert (row.email, row.email_verified_at, row.wants_updates) == (None, None, False)
    emails = await db_session.scalar(
        select(func.count()).select_from(OutboundEmail).where(OutboundEmail.idea_id == idea.id)
    )
    assert emails == 0
    assert page["email_hint"] is None
    assert page["can_remove_email"] is False
    assert page["team_messages_emailed"] is False
    assert len(page["messages"]) == 1
    summary = ok(await (await api(team.owner)).get(f"/ideas/{idea.id}/submission"))["messages"]
    assert summary["delivery"] == "tracking_page"
    # The link and the conversation stay: a reply still works, a message still lands.
    ok(await reply(anon, token), 201)
    sent = ok(await (await api(team.owner)).post(messages_url(idea), {"body": "Noted."}), 201)
    assert sent["emailed"] is False
    # Idempotent without an address.
    assert ok(await forget(anon, token))["email_hint"] is None


async def test_removing_the_address_deletes_sent_emails_too(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await public_idea(db_session, settings, team)
    for type_ in (EmailType.SUBMISSION_STATUS_CHANGED, EmailType.SUBMISSION_LINK):
        db_session.add(
            OutboundEmail(
                type=type_,
                to_address="sam@example.org",
                idea_id=idea.id,
                message_id=f"<{type_.value}@testserver>",
            )
        )
    await db_session.commit()
    await db_session.execute(
        update(OutboundEmail)
        .where(OutboundEmail.idea_id == idea.id)
        .values(status=EmailStatus.SENT, sent_at=utcnow(), next_attempt_at=None)
    )
    await db_session.commit()

    ok(await forget(anon, token))

    left = await db_session.scalar(
        select(func.count()).select_from(OutboundEmail).where(OutboundEmail.idea_id == idea.id)
    )
    assert left == 0


async def test_an_address_awaiting_confirmation_cannot_be_removed(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """It is what sends the idea to the team: delete the details to withdraw instead."""
    token, _ = await public_idea(
        db_session, settings, team, held_for=HoldReason.EMAIL_VERIFICATION, verified=False
    )
    assert ok(await track(anon, token))["can_remove_email"] is False

    assert_problem(await forget(anon, token), 409, "awaiting_confirmation")
    row, _ = await submitted(db_session, token)
    assert row.email == "sam@example.org"


async def test_without_an_address_nothing_changes(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, _ = await public_idea(db_session, settings, team, email=None, verified=False)

    page = ok(await forget(anon, token))

    assert (page["email_hint"], page["can_remove_email"]) == (None, False)


async def test_a_confirmation_link_for_a_removed_address_is_404(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    from app.auth.submission_tokens import make_confirmation_token

    token, _ = await public_idea(db_session, settings, team, verified=False)
    row, _ = await submitted(db_session, token)
    confirm = make_confirmation_token(settings, row.id, "sam@example.org", now=utcnow())

    ok(await forget(anon, token))

    assert_problem(
        await anon.post(f"{PUBLIC}/verify-email", json={"token": confirm}), 404, "not_found"
    )


async def test_replies_notify_nobody_while_unowned_and_unwritten(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Recipients may be nobody: an unowned idea whose only writer lost the rule."""
    token, idea = await public_idea(db_session, settings, team, owner=None)
    await add_message(db_session, idea, author=team.viewer)  # no longer holds the rule

    ok(await reply(anon, token), 201)

    notified = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.type == NotificationType.SUBMITTER_REPLIED)
    )
    assert notified == 0


async def test_the_submissions_row_is_untouched_by_a_reply(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """A reply moves neither the idea's activity time nor anything else others see."""
    token, idea = await public_idea(db_session, settings, team)
    await team_writes(api, team, idea)
    before = await db_session.scalar(
        select(Idea.last_activity_at)
        .where(Idea.id == idea.id)
        .execution_options(populate_existing=True)
    )
    updated = await db_session.scalar(
        select(PublicSubmission.updated_at).where(PublicSubmission.idea_id == idea.id)
    )

    ok(await reply(anon, token), 201)

    await db_session.commit()
    after = await db_session.scalar(
        select(Idea.last_activity_at)
        .where(Idea.id == idea.id)
        .execution_options(populate_existing=True)
    )
    assert after == before
    assert (
        await db_session.scalar(
            select(PublicSubmission.updated_at).where(PublicSubmission.idea_id == idea.id)
        )
        == updated
    )


async def test_keys_and_sessions_are_ignored_on_the_public_routes(
    app: Any, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Public routes (``public.track``): the token decides; a bearer key or a session
    neither helps nor hurts."""
    from tests.api_keys.helpers import key_client, make_key

    token, idea = await public_idea(db_session, settings, team)
    await team_writes(api, team, idea)
    key = await make_key(db_session, team.platform)

    async with key_client(app, key) as http:
        with_key = await http.post(
            f"{PUBLIC}/track/messages", json={"token": token, "body": "With a key header."}
        )
        bad_token = await http.post(
            f"{PUBLIC}/track/messages", json={"token": "B" * 43, "body": "Nope."}
        )
    signed_in = await (await api(team.admin)).http.post(
        f"{PUBLIC}/track/messages", json={"token": token, "body": "From a session."}
    )

    assert with_key.status_code == 201, with_key.text
    assert_problem(bad_token, 404, "not_found")
    assert signed_in.status_code == 201, signed_in.text
    listed = ok(await (await api(team.owner)).get(messages_url(idea)))
    assert all(m["author"] is None for m in listed["items"] if m["direction"] == "submitter")
