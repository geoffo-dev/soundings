"""Admin settings -> Email (contract-phase3 section 3.10)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.email import delivery
from app.email.delivery import Runtime
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType
from app.models.notification import OutboundEmail
from app.models.user import User
from tests.factories import make_user
from tests.notifications.conftest import (
    SMTP,
    AsUser,
    Outbox,
    RecordingTransport,
    Team,
    assert_problem,
    ok,
    only,
)

pytestmark = pytest.mark.usefixtures("team")

ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/admin/email", None),
    ("POST", "/admin/email/test", {}),
    ("GET", "/admin/email/outbox", None),
    ("GET", "/admin/email/outbox/6d1f8a3b-2c4e-4b7a-9f0d-8e3c1b5a7d92", None),
    ("POST", "/admin/email/outbox/6d1f8a3b-2c4e-4b7a-9f0d-8e3c1b5a7d92/retry", None),
    ("POST", "/admin/email/outbox/retry-failed", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_only_platform_admins(
    api: AsUser, team: Team, client: httpx.AsyncClient, method: str, path: str, body: Any
) -> None:
    anonymous = await client.request(method, "/api/v1" + path, json=body)
    assert anonymous.status_code == 401
    for user in (team.admin, team.member):  # a project admin is not a platform admin
        response = await (await api(user)).http.request(method, "/api/v1" + path, json=body)
        assert_problem(response, 403, "forbidden")


@pytest.mark.settings(
    **SMTP,
    smtp_username=SecretStr("relay-user"),
    smtp_password=SecretStr("hunter2-hunter2"),
    smtp_reply_to="help@example.com",
    reminder_days="0,2",
)
async def test_config_shows_the_effective_settings_with_credentials_masked(
    api: AsUser, team: Team
) -> None:
    response = await (await api(team.platform)).get("/admin/email")

    body = ok(response)
    assert "relay-user" not in response.text
    assert "hunter2" not in response.text
    assert body["configured"] is True
    assert (body["host"], body["port"], body["security"]) == ("smtp.invalid", 2525, "none")
    assert (body["username_set"], body["password_set"]) == (True, True)
    assert (body["from_address"], body["from_name"], body["reply_to"]) == (
        "soundings@example.com",
        "Soundings",
        "help@example.com",
    )
    assert body["links_base_url"] == "http://testserver"
    assert body["reminder_days"] == [2, 0]
    assert body["outbox"] == {
        "queued": 0,
        "sending": 0,
        "failed": 0,
        "sent_last_24h": 0,
        "oldest_queued_at": None,
        "last_sent_at": None,
    }


@pytest.mark.settings(
    smtp_username=None, smtp_password=None, smtp_username_set=True, smtp_password_set=True
)
async def test_api_pods_without_the_credentials_still_show_them_as_set(
    api: AsUser, team: Team
) -> None:
    """Review L4: only the worker sends mail, so only the worker gets the SMTP Secret;
    the chart tells the API pods that credentials are set."""
    body = ok(await (await api(team.platform)).get("/admin/email"))

    assert (body["username_set"], body["password_set"]) == (True, True)


@pytest.mark.settings(smtp_username=None, smtp_password=None)
async def test_no_credentials_show_as_not_set(api: AsUser, team: Team) -> None:
    body = ok(await (await api(team.platform)).get("/admin/email"))

    assert (body["username_set"], body["password_set"]) == (False, False)


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_without_smtp_the_actions_are_409(api: AsUser, team: Team) -> None:
    pat = await api(team.platform)
    assert ok(await pat.get("/admin/email"))["configured"] is False

    assert_problem(await pat.post("/admin/email/test", {}), 409, "smtp_not_configured")
    assert_problem(await pat.post("/admin/email/outbox/retry-failed"), 409, "smtp_not_configured")


async def test_a_test_email_to_myself_goes_through_the_outbox(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    db_session: AsyncSession,
) -> None:
    pat = await api(team.platform)

    response = await pat.post("/admin/email/test", {})

    body = ok(response, 202)
    assert (body["type"], body["status"], body["max_attempts"]) == ("test", "queued", 1)
    assert body["recipient"]["id"] == str(team.platform.id)
    assert body["requested_by"]["id"] == str(team.platform.id)
    assert body["address_hint"] is None
    assert body["retryable"] is False
    assert len(await outbox.jobs()) == 1
    entry = only(
        list(await db_session.scalars(select(AuditLog).where(AuditLog.action.like("email.%"))))
    )
    assert entry.action == "email.test_send"
    assert entry.details["to_self"] is True
    assert entry.details["outbound_email_id"] == body["id"]
    assert "@" not in str(entry.details)

    assert await delivery.send_email(runtime, body["id"]) == "sent"
    message = only(transport.messages)
    assert message["Subject"] == "Soundings test email"
    assert message["List-Unsubscribe"] is None
    text_part = message.get_body(("plain",))
    assert text_part is not None
    text = text_part.get_content()
    assert "This is a test email from Soundings at http://testserver" in text
    assert "Pat Platform" in text
    assert "smtp.invalid" not in text  # no server details
    polled = ok(await pat.get(f"/admin/email/outbox/{body['id']}"))
    assert polled["status"] == "sent"


async def test_a_test_email_to_another_address(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    pat = await api(team.platform)

    body = ok(await pat.post("/admin/email/test", {"to": "ops@example.com"}), 202)

    assert body["recipient"] is None
    assert body["address_hint"] == "o•••@example.com"
    entry = only(
        list(await db_session.scalars(select(AuditLog).where(AuditLog.action.like("email.%"))))
    )
    assert entry.details["to_self"] is False
    assert "ops@" not in str(entry.details)


@pytest.mark.parametrize(
    "to", ["victim@corp.com,postmaster", "a@b.com b@c.com", "ops@soundings.invalid"]
)
async def test_one_plain_address_only(api: AsUser, team: Team, to: str) -> None:
    response = await (await api(team.platform)).post("/admin/email/test", {"to": to})

    assert_problem(response, 422, "validation_error")


async def test_my_own_address_must_be_usable(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    pat = await api(team.platform)
    await db_session.execute(
        update(User)
        .where(User.id == team.platform.id)
        .values(email="break-glass@soundings.invalid")
    )
    await db_session.commit()

    problem = assert_problem(await pat.post("/admin/email/test", {}), 422, "validation_error")
    assert problem["errors"][0]["loc"] == ["body", "to"]


async def test_at_most_five_test_emails_per_admin_in_ten_minutes(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    pat = await api(team.platform)
    for _ in range(5):
        ok(await pat.post("/admin/email/test", {}), 202)

    response = await pat.post("/admin/email/test", {"to": "ops@example.com"})

    assert_problem(response, 429, "too_many_attempts")
    assert 590 <= int(response.headers["Retry-After"]) <= 600
    first = (await outbox.emails())[0]
    await outbox.set(OutboundEmail, first.id, created_at=utcnow() - timedelta(minutes=11))
    ok(await pat.post("/admin/email/test", {}), 202)


# --- The outbox ------------------------------------------------------------------------------
async def failed_email(
    api: AsUser, team: Team, outbox: Outbox, *, age: timedelta = timedelta(hours=1)
) -> OutboundEmail:
    idea = await (await api(team.member)).create_idea(team.slug)
    body = {"user_id": str(team.owner.id)}
    ok(await (await api(team.admin)).put(f"/ideas/{idea['key']}/owner", body))
    email = only(await outbox.emails(team.owner.id))
    await outbox.set(
        OutboundEmail,
        email.id,
        status=EmailStatus.FAILED,
        attempts=12,
        next_attempt_at=None,
        last_error="SMTP 550: recipient refused",
        created_at=utcnow() - age,
    )
    return email


async def test_the_outbox_lists_newest_first_with_filters(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    failed = await failed_email(api, team, outbox)
    pat = await api(team.platform)
    test = ok(await pat.post("/admin/email/test", {"to": "ops@example.com"}), 202)

    everything = ok(await pat.get("/admin/email/outbox"))
    only_failed = ok(await pat.get("/admin/email/outbox", status="failed"))
    tests = ok(await pat.get("/admin/email/outbox", type=["test", "digest"]))
    first = ok(await pat.get("/admin/email/outbox", limit=1))
    rest = ok(await pat.get("/admin/email/outbox", limit=1, cursor=first["next_cursor"]))

    assert [item["id"] for item in everything["items"]] == [test["id"], str(failed.id)]
    item = only_failed["items"][0]
    assert (item["id"], item["retryable"], item["last_error"]) == (
        str(failed.id),
        True,
        "SMTP 550: recipient refused",
    )
    assert item["idea"]["key"] == "CUST-1"
    assert item["recipient"]["display_name"] == "Olive Owner"
    assert [item["type"] for item in tests["items"]] == ["test"]
    assert [i["id"] for i in first["items"] + rest["items"]] == [test["id"], str(failed.id)]
    assert team.owner.email not in str(everything)
    assert "ops@example.com" not in str(everything)


async def test_retry_requeues_a_recent_failed_email(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    email = await failed_email(api, team, outbox)
    pat = await api(team.platform)

    body = ok(await pat.post(f"/admin/email/outbox/{email.id}/retry"))

    assert (body["status"], body["attempts"], body["last_error"]) == ("queued", 0, None)
    assert len(await outbox.jobs()) == 2  # the original one and the retry's
    entry = only(
        list(await db_session.scalars(select(AuditLog).where(AuditLog.action.like("email.%"))))
    )
    assert (entry.action, entry.details["outbound_email_id"]) == ("email.retry", str(email.id))
    # Queued now: not retryable again.
    assert_problem(
        await pat.post(f"/admin/email/outbox/{email.id}/retry"), 409, "email_not_retryable"
    )


async def test_old_failures_cannot_be_retried_and_retry_all_skips_them(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    old = await failed_email(api, team, outbox, age=timedelta(days=3, minutes=1))
    pat = await api(team.platform)
    digest = OutboundEmail(
        type=EmailType.DIGEST,
        status=EmailStatus.QUEUED,
        recipient_user_id=team.member.id,
        message_id="<d@testserver>",
    )
    db_session.add(digest)
    await db_session.commit()
    await outbox.set(
        OutboundEmail,
        digest.id,
        status=EmailStatus.FAILED,
        next_attempt_at=None,
        created_at=utcnow() - timedelta(days=1),
    )
    old_digest_id = digest.id
    item = ok(await pat.get(f"/admin/email/outbox/{old.id}"))
    assert item["retryable"] is False

    assert_problem(
        await pat.post(f"/admin/email/outbox/{old.id}/retry"), 409, "email_not_retryable"
    )
    assert ok(await pat.post("/admin/email/outbox/retry-failed")) == {"retried": 1}
    assert (await outbox.email(old.id)).status is EmailStatus.FAILED
    assert (await outbox.email(old_digest_id)).status is EmailStatus.QUEUED
    entry = only(
        list(await db_session.scalars(select(AuditLog).where(AuditLog.action.like("email.%"))))
    )
    assert entry.details["count"] == 1


async def test_unknown_outbox_emails_are_404(api: AsUser, team: Team) -> None:
    pat = await api(team.platform)
    missing = "6d1f8a3b-2c4e-4b7a-9f0d-8e3c1b5a7d92"

    assert_problem(await pat.get(f"/admin/email/outbox/{missing}"), 404, "not_found")
    assert_problem(await pat.post(f"/admin/email/outbox/{missing}/retry"), 404, "not_found")


async def test_stats(api: AsUser, team: Team, outbox: Outbox) -> None:
    await failed_email(api, team, outbox)
    pat = await api(team.platform)
    ok(await pat.post("/admin/email/test", {}), 202)

    stats = ok(await pat.get("/admin/email"))["outbox"]

    assert (stats["queued"], stats["failed"], stats["sending"]) == (1, 1, 0)
    assert stats["oldest_queued_at"] is not None


async def fail(outbox: Outbox, email_id: str | UUID) -> None:
    await outbox.set(
        OutboundEmail,
        UUID(str(email_id)),
        status=EmailStatus.FAILED,
        attempts=1,
        next_attempt_at=None,
        last_error="connection refused",
    )


async def test_retrying_a_test_email_counts_towards_the_test_email_limit(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    """Review L9: a retry reset the attempts outside the five-per-ten-minutes limit, so a
    failing test email could be sent again and again."""
    pat = await api(team.platform)
    tests = [ok(await pat.post("/admin/email/test", {}), 202) for _ in range(4)]
    await fail(outbox, tests[0]["id"])

    body = ok(await pat.post(f"/admin/email/outbox/{tests[0]['id']}/retry"))  # 5th use
    assert (body["status"], body["attempts"]) == ("queued", 0)
    await fail(outbox, tests[0]["id"])

    response = await pat.post(f"/admin/email/outbox/{tests[0]['id']}/retry")
    assert_problem(response, 429, "too_many_attempts")
    assert 590 <= int(response.headers["Retry-After"]) <= 600
    assert_problem(await pat.post("/admin/email/test", {}), 429, "too_many_attempts")
    assert (await outbox.email(UUID(tests[0]["id"]))).status is EmailStatus.FAILED


async def test_another_admins_retry_uses_their_own_allowance(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    pat = await api(team.platform)
    tests = [ok(await pat.post("/admin/email/test", {}), 202) for _ in range(5)]
    await fail(outbox, tests[0]["id"])
    other = await make_user(db_session, "Polly Platform", platform_admin=True)

    ok(await (await api(other)).post(f"/admin/email/outbox/{tests[0]['id']}/retry"))


async def test_retry_all_includes_test_emails_only_within_the_limit(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    pat = await api(team.platform)
    tests = [ok(await pat.post("/admin/email/test", {}), 202) for _ in range(4)]
    for test in tests:
        await fail(outbox, test["id"])
    owner_email = await failed_email(api, team, outbox)

    assert ok(await pat.post("/admin/email/outbox/retry-failed")) == {"retried": 2}

    statuses = {UUID(t["id"]): (await outbox.email(UUID(t["id"]))).status for t in tests}
    assert sorted(status.value for status in statuses.values()) == ["failed"] * 3 + ["queued"]
    assert (await outbox.email(owner_email.id)).status is EmailStatus.QUEUED
    entry = only(
        list(await db_session.scalars(select(AuditLog).where(AuditLog.action == "email.retry")))
    )
    assert (entry.details["count"], entry.details["test_emails"]) == (2, 1)
    assert_problem(await pat.post("/admin/email/test", {}), 429, "too_many_attempts")
