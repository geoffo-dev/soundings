"""Review M1: an unreachable SMTP server must not hold up the worker's other jobs.

* The periodic jobs (the outbox sweep, the notification schedule, the job cleanup) run
  before any waiting ``send_email`` job (procrastinate priority).
* After repeated connection failures the worker stops trying for a while (a circuit
  breaker): due emails are postponed without using an attempt, then probed again.
"""

from __future__ import annotations

from datetime import timedelta

import aiosmtplib
import pytest
from procrastinate import App
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.email import delivery, tasks
from app.email.delivery import Breaker, Runtime
from app.email.smtp import classify
from app.models.base import utcnow
from app.models.enums import EmailStatus
from app.models.notification import OutboundEmail
from tests.notifications.conftest import AsUser, Clock, Outbox, RecordingTransport, Team, ok

pytestmark = pytest.mark.usefixtures("team")


# --- Priorities ------------------------------------------------------------------------
def test_periodic_jobs_outrank_sends() -> None:
    send = tasks.send_email.priority
    for task in (tasks.sweep_outbox, tasks.notification_schedule, tasks.remove_old_jobs):
        assert task.priority > send, task.name


async def test_the_sweep_runs_before_a_backlog_of_sends(
    jobs: App, db_session: AsyncSession
) -> None:
    for n in range(20):
        await jobs.configure_task("send_email").defer_async(email_id=f"{n:032x}")
    await jobs.configure_task("sweep_outbox").defer_async(timestamp=0)
    worker_id = await jobs.job_manager.register_worker()
    try:
        job = await jobs.job_manager.fetch_job(queues=None, worker_id=worker_id)
    finally:
        await db_session.execute(text("UPDATE procrastinate_jobs SET worker_id = NULL"))
        await db_session.commit()
        await jobs.job_manager.unregister_worker(worker_id)

    assert job is not None
    assert job.task_name == "sweep_outbox"


# --- The breaker ------------------------------------------------------------------------
def unreachable() -> OSError:
    return ConnectionRefusedError(111, "Connection refused")


def test_connection_failures_are_unreachable_and_replies_are_not() -> None:
    for error in (
        ConnectionRefusedError(),
        TimeoutError(),
        OSError("no route"),
        aiosmtplib.SMTPConnectError("refused"),
        aiosmtplib.SMTPConnectTimeoutError("slow"),
        aiosmtplib.SMTPTimeoutError("slow"),
        aiosmtplib.SMTPServerDisconnected("gone"),
    ):
        assert classify(error).unreachable, error
    replies: tuple[Exception, ...] = (
        aiosmtplib.SMTPResponseException(451, "busy"),
        aiosmtplib.SMTPRecipientRefused(550, "no", "x@example.com"),
        aiosmtplib.SMTPConnectResponseError(421, "busy"),
        aiosmtplib.SMTPAuthenticationError(535, "no"),
    )
    for reply in replies:
        assert not classify(reply).unreachable, reply


def test_the_breaker_opens_after_five_failures_and_backs_off() -> None:
    breaker = Breaker()
    now = utcnow()
    for _ in range(4):
        breaker.failed(now)
    assert not breaker.is_open(now)

    breaker.failed(now)

    assert breaker.is_open(now)
    assert breaker.open_until == now + timedelta(seconds=30)
    assert not breaker.is_open(now + timedelta(seconds=30))
    # Half-open: the next failure reopens it at once, for twice as long.
    later = now + timedelta(seconds=31)
    breaker.failed(later)
    assert breaker.open_until == later + timedelta(seconds=60)
    for _ in range(10):
        later = breaker.open_until or later
        breaker.failed(later)
    assert breaker.open_until == later + timedelta(minutes=5)  # capped

    breaker.succeeded()

    assert not breaker.is_open(later)
    for _ in range(4):
        breaker.failed(later)
    assert not breaker.is_open(later)


async def queue_emails(api: AsUser, team: Team, outbox: Outbox, count: int) -> list[OutboundEmail]:
    admin = await api(team.admin)
    for _ in range(count):
        idea = await (await api(team.member)).create_idea(team.slug)
        ok(await admin.put(f"/ideas/{idea['key']}/owner", {"user_id": str(team.owner.id)}))
    emails = await outbox.emails(team.owner.id)
    assert len(emails) == count
    return emails


async def test_an_unreachable_server_postpones_mail_without_using_attempts(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    clock: Clock,
) -> None:
    emails = await queue_emails(api, team, outbox, 8)
    transport.errors += [unreachable() for _ in range(6)]

    outcomes = [await delivery.send_email(runtime, email.id) for email in emails]

    assert outcomes == ["retry"] * 5 + ["postponed"] * 3
    assert len(transport.errors) == 1  # only five connection attempts were made
    open_until = runtime.breaker.open_until
    assert open_until is not None
    for email in emails[5:]:
        row = await outbox.email(email.id)
        assert (row.status, row.attempts, row.last_error) == (EmailStatus.QUEUED, 0, None)
        assert row.next_attempt_at is not None
        assert open_until <= row.next_attempt_at <= open_until + timedelta(seconds=8)
    scheduled = {job["args"]["email_id"]: job["scheduled_at"] for job in await outbox.jobs()}
    assert all(scheduled[str(email.id)] is not None for email in emails[5:])

    # Still down when the breaker lets one through: postponed again, for longer.
    waits = [row.next_attempt_at for row in await outbox.emails() if row.next_attempt_at]
    now = max(waits) + timedelta(seconds=1)
    clock.now = now
    first = await delivery.send_email(runtime, emails[5].id)
    assert first == "retry"
    assert runtime.breaker.is_open(now)
    assert await delivery.send_email(runtime, emails[6].id) == "postponed"

    # Back up: the next probe goes through and closes the breaker.
    now += timedelta(minutes=10)
    clock.now = now
    assert await delivery.send_email(runtime, emails[7].id) == "sent"
    assert not runtime.breaker.is_open(now)
    assert await delivery.send_email(runtime, emails[6].id) == "sent"


async def test_test_emails_are_tried_while_the_breaker_is_open(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    """An admin's test email is the probe: it is sent, and closes the breaker."""
    for _ in range(5):
        runtime.breaker.failed(utcnow())
    assert runtime.breaker.is_open(utcnow())
    test = ok(await (await api(team.platform)).post("/admin/email/test", {}), 202)

    assert await delivery.send_email(runtime, test["id"]) == "sent"
    assert not runtime.breaker.is_open(utcnow())


async def test_replies_from_the_server_do_not_open_the_breaker(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, transport: RecordingTransport
) -> None:
    emails = await queue_emails(api, team, outbox, 6)
    transport.errors += [aiosmtplib.SMTPResponseException(451, "busy") for _ in range(6)]

    outcomes = [await delivery.send_email(runtime, email.id) for email in emails]

    assert outcomes == ["retry"] * 6
    assert not runtime.breaker.is_open(utcnow())
