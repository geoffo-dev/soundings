"""The outbox and one delivery attempt (contract-phase3 section 3.9): claim, re-check,
send, record; retries with backoff; permanent and internal failures; the 4-minute
deadline; the sweep; at-least-once with a fixed Message-ID; one recipient per email."""

from __future__ import annotations

import asyncio
import random
from datetime import timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import aiosmtplib
import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email import outbox as outbox_module
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import EmailStatus, NotificationMode, NotificationType, ProjectRole
from app.models.notification import NotificationPreference, OutboundEmail
from app.models.project import ProjectMember
from app.models.user import User
from tests.notifications.conftest import (
    AsUser,
    Clock,
    Outbox,
    RecordingTransport,
    Team,
    ok,
    only,
)

pytestmark = pytest.mark.usefixtures("team")


async def queue_owner_email(api: AsUser, team: Team, outbox: Outbox) -> OutboundEmail:
    """Alice makes Olive the owner of a new idea: one queued owner_assigned email."""
    idea = await (await api(team.member)).create_idea(team.slug, title="Self-service refunds")
    ok(
        await (await api(team.admin)).put(
            f"/ideas/{idea['key']}/owner", {"user_id": str(team.owner.id)}
        )
    )
    return only(await outbox.emails(team.owner.id))


async def invite_email(api: AsUser, team: Team, outbox: Outbox) -> tuple[OutboundEmail, str]:
    idea = await (await api(team.member)).create_idea(team.slug)
    body = {"user_ids": [str(team.evaluators[0].id)]}
    ok(await (await api(team.admin)).post(f"/ideas/{idea['key']}/evaluators", body))
    return only(await outbox.emails(team.evaluators[0].id)), idea["key"]


# --- Sending ----------------------------------------------------------------------------
async def test_an_email_is_sent_once_to_exactly_its_recipient(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)

    assert await delivery.send_email(runtime, email.id) == "sent"

    message, sender, recipient = only(transport.sent)
    assert (sender, recipient) == ("soundings@example.com", team.owner.email)
    assert message["To"] == team.owner.email
    assert message["From"] == "Soundings <soundings@example.com>"
    assert message["Message-ID"] == email.message_id
    assert message["Subject"] == '[CUST-1] You\'re now the owner of "Self-service refunds"'
    assert message["Auto-Submitted"] == "auto-generated"
    assert message["List-Unsubscribe"].startswith("<http://testserver/api/v1/unsubscribe?token=")
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message["References"].startswith("<idea-")
    assert message.get_content_type() == "multipart/alternative"
    parts = [part.get_content_type() for part in message.iter_parts()]
    assert parts == ["text/plain", "text/html"]
    row = await outbox.email(email.id)
    assert (row.status, row.attempts, row.last_error) == (EmailStatus.SENT, 1, None)
    assert row.sent_at is not None
    assert row.next_attempt_at is None
    # Sent mail is never sent again.
    assert await delivery.send_email(runtime, email.id) == "not_claimed"
    assert len(transport.sent) == 1


async def test_two_jobs_for_one_row_send_it_once(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)

    outcomes = await asyncio.gather(
        delivery.send_email(runtime, email.id), delivery.send_email(runtime, email.id)
    )

    assert sorted(outcomes) == ["not_claimed", "sent"]
    assert len(transport.sent) == 1


async def test_nothing_happens_while_smtp_is_not_configured(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, settings: Settings
) -> None:
    email = await queue_owner_email(api, team, outbox)
    runtime.settings = settings.model_copy(update={"smtp_host": None, "smtp_from": None})

    assert await delivery.send_email(runtime, email.id) == "skipped"
    assert await delivery.sweep_outbox(runtime) == delivery.SweepResult()

    row = await outbox.email(email.id)
    assert (row.status, row.attempts) == (EmailStatus.QUEUED, 0)


# --- Failures ------------------------------------------------------------------------------
async def test_a_transient_failure_queues_the_next_attempt_with_backoff(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)
    transport.errors.append(ConnectionRefusedError(111, "Connection refused: victim@x"))
    before = utcnow()

    assert await delivery.send_email(runtime, email.id) == "retry"

    row = await outbox.email(email.id)
    assert (row.status, row.attempts, row.last_error) == (
        EmailStatus.QUEUED,
        1,
        "connection refused",
    )
    assert row.next_attempt_at is not None
    wait = row.next_attempt_at - before
    assert timedelta(seconds=30) <= wait <= timedelta(seconds=34)
    jobs = await outbox.jobs()
    assert len(jobs) == 2  # the enqueue's and the retry's
    assert jobs[-1]["scheduled_at"] == row.next_attempt_at


def test_backoff_doubles_from_30_seconds_to_an_hour_with_at_most_10_percent_jitter() -> None:
    rng = random.Random(7)  # noqa: S311 - jitter, not security
    expected = [30, 60, 120, 240, 480, 960, 1920, 3600, 3600, 3600, 3600]
    for attempt, base in enumerate(expected, start=1):
        wait = outbox_module.backoff(attempt, rng=rng).total_seconds()
        assert base <= wait <= base * 1.1
    total = sum(expected)
    assert 4.5 * 3600 < total < 5.5 * 3600  # 12 attempts span about five hours


async def test_a_permanent_failure_fails_at_once(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)
    refused = aiosmtplib.SMTPRecipientRefused(550, "5.1.1 <olive@x> unknown", "olive@x")
    transport.errors.append(aiosmtplib.SMTPRecipientsRefused([refused]))

    assert await delivery.send_email(runtime, email.id) == "failed"

    row = await outbox.email(email.id)
    assert (row.status, row.last_error, row.next_attempt_at) == (
        EmailStatus.FAILED,
        "SMTP 550: recipient refused",
        None,
    )
    assert "olive" not in (row.last_error or "")


async def test_authentication_failures_are_retried(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)
    transport.errors.append(aiosmtplib.SMTPAuthenticationError(535, "5.7.8 bad credentials"))

    assert await delivery.send_email(runtime, email.id) == "retry"

    assert (await outbox.email(email.id)).last_error == "SMTP 535: authentication failed"


async def test_the_last_attempt_fails_for_good(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)
    await outbox.set(OutboundEmail, email.id, attempts=11)
    transport.errors.append(aiosmtplib.SMTPResponseException(451, "4.3.0 try later"))

    assert await delivery.send_email(runtime, email.id) == "failed"

    row = await outbox.email(email.id)
    assert (row.status, row.attempts, row.last_error) == (
        EmailStatus.FAILED,
        12,
        "SMTP 451: server busy",
    )


async def test_an_error_while_rendering_fails_the_email_as_internal(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = await queue_owner_email(api, team, outbox)

    def broken(*_: Any, **__: Any) -> None:
        raise KeyError("olive@example.com")

    monkeypatch.setattr(delivery, "render", broken)

    assert await delivery.send_email(runtime, email.id) == "failed"

    row = await outbox.email(email.id)
    assert (row.status, row.last_error) == (EmailStatus.FAILED, "Internal error")
    assert transport.sent == []


async def test_an_attempt_over_the_deadline_is_transient_and_recorded_before_the_lease_ends(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime
) -> None:
    email = await queue_owner_email(api, team, outbox)

    class Slow(RecordingTransport):
        async def send(self, message: EmailMessage, *, sender: str, recipient: str) -> None:
            await asyncio.sleep(5)

    runtime.transport = Slow()
    runtime.deadline = timedelta(milliseconds=200)

    assert await delivery.send_email(runtime, email.id) == "retry"

    row = await outbox.email(email.id)
    assert (row.status, row.last_error) == (EmailStatus.QUEUED, "timed out")


async def test_a_row_that_changed_meanwhile_is_not_overwritten(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime
) -> None:
    """The record step only writes a row still ``sending`` with this attempt."""
    email = await queue_owner_email(api, team, outbox)
    sessionmaker = runtime.sessionmaker

    class Reclaimed(RecordingTransport):
        async def send(self, message: EmailMessage, *, sender: str, recipient: str) -> None:
            async with sessionmaker() as db:  # the sweep and another worker took it over
                await db.execute(
                    update(OutboundEmail)
                    .where(OutboundEmail.id == email.id)
                    .values(attempts=OutboundEmail.attempts + 1)
                )
                await db.commit()
            await super().send(message, sender=sender, recipient=recipient)

    runtime.transport = Reclaimed()

    assert await delivery.send_email(runtime, email.id) == "lost"

    row = await outbox.email(email.id)
    assert (row.status, row.attempts, row.sent_at) == (EmailStatus.SENDING, 2, None)


# --- SMTP down, then up -------------------------------------------------------------------
async def test_mail_queued_while_smtp_is_down_goes_out_when_it_is_back(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    clock: Clock,
) -> None:
    email = await queue_owner_email(api, team, outbox)
    transport.errors += [aiosmtplib.SMTPConnectError("refused"), ConnectionRefusedError()]

    assert await delivery.send_email(runtime, email.id) == "retry"
    assert await delivery.send_email(runtime, email.id) == "not_claimed"  # not due yet
    clock.now = utcnow() + timedelta(minutes=1)
    assert await delivery.send_email(runtime, email.id) == "retry"
    clock.now = utcnow() + timedelta(minutes=5)
    assert await delivery.send_email(runtime, email.id) == "sent"

    message = only(transport.messages)
    assert message["Message-ID"] == email.message_id
    row = await outbox.email(email.id)
    assert (row.status, row.attempts) == (EmailStatus.SENT, 3)


async def test_a_crash_after_sending_resends_with_the_same_message_id(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    clock: Clock,
) -> None:
    """At-least-once: the worker died between the server's 250 and the record step."""
    email = await queue_owner_email(api, team, outbox)
    assert await delivery.send_email(runtime, email.id) == "sent"
    await outbox.set(
        OutboundEmail,
        email.id,
        status=EmailStatus.SENDING,
        sent_at=None,
        next_attempt_at=utcnow() + outbox_module.LEASE,
    )

    clock.now = utcnow() + outbox_module.LEASE + timedelta(seconds=1)
    swept = await delivery.sweep_outbox(runtime)
    assert (swept.requeued, swept.deferred) == (1, 1)
    assert await delivery.send_email(runtime, email.id) == "sent"

    first, second = transport.messages
    assert first["Message-ID"] == second["Message-ID"] == email.message_id


# --- The sweep ----------------------------------------------------------------------------
async def test_the_sweep_fails_an_expired_lease_on_its_last_attempt(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime
) -> None:
    email = await queue_owner_email(api, team, outbox)
    await outbox.set(
        OutboundEmail,
        email.id,
        status=EmailStatus.SENDING,
        attempts=12,
        next_attempt_at=utcnow() - timedelta(seconds=1),
    )

    swept = await delivery.sweep_outbox(runtime)

    assert swept.failed == 1
    row = await outbox.email(email.id)
    assert (row.status, row.last_error) == (EmailStatus.FAILED, "Worker stopped while sending")


async def test_the_sweep_redefers_a_lost_job_once(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, db_session: AsyncSession
) -> None:
    email = await queue_owner_email(api, team, outbox)
    await db_session.execute(text("DELETE FROM procrastinate_jobs"))
    await outbox.set(OutboundEmail, email.id, next_attempt_at=utcnow() - timedelta(minutes=5))

    first = await delivery.sweep_outbox(runtime)
    second = await delivery.sweep_outbox(runtime)

    assert (first.deferred, second.deferred, second.already_waiting) == (1, 0, 1)
    job = only(await outbox.jobs())
    assert job["queueing_lock"] == f"send_email:{email.id}"
    assert job["args"] == {"email_id": str(email.id)}


async def test_the_sweep_leaves_rows_that_are_not_due_alone(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime
) -> None:
    await queue_owner_email(api, team, outbox)  # due now: its own job is waiting

    assert await delivery.sweep_outbox(runtime) == delivery.SweepResult()
    assert len(await outbox.jobs()) == 1


# --- Send-time checks (cancelled without SMTP) ---------------------------------------------
async def test_mail_about_an_idea_the_recipient_can_no_longer_view_is_cancelled(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    email = await queue_owner_email(api, team, outbox)
    ok(await (await api(team.admin)).delete(f"/projects/{team.slug}/members/{team.owner.id}"), 204)

    assert await delivery.send_email(runtime, email.id) == "cancelled"

    row = await outbox.email(email.id)
    assert (row.status, row.last_error) == (EmailStatus.CANCELLED, "Not sent: no longer applies")
    assert transport.sent == []


async def test_an_invitation_to_a_removed_or_demoted_evaluator_is_cancelled(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    db_session: AsyncSession,
) -> None:
    email, key = await invite_email(api, team, outbox)
    await db_session.execute(
        update(ProjectMember)
        .where(
            ProjectMember.project_id == team.project.id,
            ProjectMember.user_id == team.evaluators[0].id,
        )
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"
    assert (await outbox.email(email.id)).last_error == "Not sent: no longer applies"

    other = team.evaluators[1]
    ok(
        await (await api(team.admin)).post(
            f"/ideas/{key}/evaluators", {"user_ids": [str(other.id)]}
        )
    )
    second = only(await outbox.emails(other.id))
    ok(await (await api(team.admin)).delete(f"/ideas/{key}/evaluators/{other.id}"))
    assert await delivery.send_email(runtime, second.id) == "cancelled"


async def test_a_type_turned_off_after_queueing_is_cancelled(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, db_session: AsyncSession
) -> None:
    email = await queue_owner_email(api, team, outbox)
    db_session.add(
        NotificationPreference(
            user_id=team.owner.id, type=NotificationType.OWNER_ASSIGNED, mode=NotificationMode.OFF
        )
    )
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"
    assert (await outbox.email(email.id)).last_error == "Not sent: turned off by the recipient"


@pytest.mark.parametrize(
    ("type_", "age", "cancelled"),
    [
        ("owner_assigned", timedelta(days=3, minutes=1), True),
        ("owner_assigned", timedelta(days=2, hours=23), False),
    ],
)
async def test_mail_older_than_three_days_is_cancelled(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    type_: str,
    age: timedelta,
    cancelled: bool,
) -> None:
    email = await queue_owner_email(api, team, outbox)
    await outbox.set(OutboundEmail, email.id, created_at=utcnow() - age)

    outcome = await delivery.send_email(runtime, email.id)

    assert outcome == ("cancelled" if cancelled else "sent")
    if cancelled:
        assert (await outbox.email(email.id)).last_error == "Not sent: out of date"


@pytest.mark.parametrize(
    "address",
    [
        "victim@corp.com,postmaster",
        "victim@corp.com postmaster@corp.com",
        "Victim <victim@corp.com>",
        "olive@soundings.invalid",
        "ölive@example.com",
    ],
)
async def test_an_unusable_address_is_cancelled_without_smtp(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    db_session: AsyncSession,
    address: str,
) -> None:
    email = await queue_owner_email(api, team, outbox)
    await db_session.execute(update(User).where(User.id == team.owner.id).values(email=address))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"

    assert (await outbox.email(email.id)).last_error == "Not sent: unusable address"
    assert transport.sent == []


async def test_mail_to_a_deactivated_user_is_cancelled(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, db_session: AsyncSession
) -> None:
    email = await queue_owner_email(api, team, outbox)
    await db_session.execute(update(User).where(User.id == team.owner.id).values(is_active=False))
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"


async def test_mail_about_a_deleted_idea_is_cancelled(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime
) -> None:
    email = await queue_owner_email(api, team, outbox)
    ok(await (await api(team.admin)).delete("/ideas/CUST-1"), 204)

    assert await delivery.send_email(runtime, email.id) == "cancelled"


def email_ids(rows: list[OutboundEmail]) -> list[UUID]:
    return [row.id for row in rows]


async def test_phase_4_submitter_emails_go_to_an_address_with_their_payload(
    app: Any, settings: Settings, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    """The plumbing Phase 4 uses: an address recipient, content from the payload, no
    notification row and no unsubscribe header (Phase 4 adds its own opt-out link)."""
    from app.db import session_scope
    from app.models.enums import EmailType

    async with session_scope(app.state.sessionmaker) as db:
        [email_id] = await outbox_module.enqueue(
            db,
            settings,
            [
                outbox_module.NewEmail(
                    type=EmailType.SUBMISSION_RECEIVED,
                    to_address="jo@example.org",
                    payload={"title": "Recycle at the till", "project": "Customer Innovation"},
                    idempotency_key="submission:1",
                )
            ],
        )

    assert await delivery.send_email(runtime, email_id) == "sent"

    message, _, recipient = only(transport.sent)
    assert recipient == "jo@example.org"
    assert message["Subject"] == 'We received your idea: "Recycle at the till"'
    assert message["List-Unsubscribe"] is None
    assert await outbox.notifications() == []


async def test_the_sweep_handles_a_bounded_batch_oldest_first(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(outbox_module, "SWEEP_BATCH", 2)
    idea = await (await api(team.member)).create_idea(team.slug)
    body = {"user_ids": [str(user.id) for user in team.evaluators]}
    ok(await (await api(team.admin)).post(f"/ideas/{idea['key']}/evaluators", body))
    emails = await outbox.emails()
    assert len(emails) == 3
    await db_session.execute(text("DELETE FROM procrastinate_jobs"))
    for minutes, email in zip((7, 9, 5), emails, strict=True):
        await outbox.set(
            OutboundEmail, email.id, next_attempt_at=utcnow() - timedelta(minutes=minutes)
        )

    swept = await delivery.sweep_outbox(runtime)

    assert swept.deferred == 2
    locks = {job["queueing_lock"] for job in await outbox.jobs()}
    assert locks == {f"send_email:{emails[1].id}", f"send_email:{emails[0].id}"}
