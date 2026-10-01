"""Phase 3 acceptance with a real Mailpit (QA; docs/test-plans/phase-3.md, AC3-API-*).

SPEC section 13, Phase 3: *with Mailpit, assigning an evaluator sends a branded email
whose link opens the evaluate sheet; stopping Mailpit then restarting it delivers
queued mail.* (contract-phase3 section 3.14.)

Every arrangement and check goes through the HTTP API (dev login, session cookie, CSRF
header) except the first platform admin; the worker's own code delivers the mail:
procrastinate runs the ``send_email`` job the invitation deferred in its own
transaction, and the retries are the same job body (:func:`app.email.delivery.send_email`)
run with a clock moved past each backoff, so the test doesn't wait minutes of real time
(the e2e suite's ``email-acceptance.spec.ts`` does, against the running worker). The
real :class:`~app.email.smtp.SmtpTransport` talks to a real Mailpit, and the message is
read back through Mailpit's HTTP API.

* AC3-API-1: the invitation email (structure, headers, links, one-click unsubscribe);
* AC3-API-2: SMTP down, queued with backoff, back up, delivered exactly once;
* AC3-API-3: the hourly schedule's reminder and digests at the digest hour, through
  Mailpit, with no score data (the e2e suite can't move the clock).

The Mailpit, in this order of preference:

* ``SOUNDINGS_TEST_MAILPIT_SMTP`` (``host:port``) and ``SOUNDINGS_TEST_MAILPIT_URL`` (its
  web API), as CI provides: "SMTP down" is a relay in front of it that refuses
  connections while closed, as a stopped server does;
* otherwise an ``axllent/mailpit`` container (``SOUNDINGS_TEST_MAILPIT_IMAGE``) on fixed
  host ports, really stopped and started (its messages survive, as in the e2e stack);
* ``SOUNDINGS_TEST_MAILPIT=0`` or no Docker: skipped.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import os
import re
import socket
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from procrastinate import App, PsycopgConnector
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType
from app.models.notification import Notification, OutboundEmail
from app.notifications.schedule import run_schedule
from app.worker import procrastinate_app, worker_options
from tests.conftest import CONTAINER_PREFIX
from tests.factories import make_user

API = "/api/v1"
BASE = "http://testserver"
ZONE = "Europe/London"
MAILPIT_IMAGE = os.environ.get("SOUNDINGS_TEST_MAILPIT_IMAGE", "axllent/mailpit:latest")
# Score data must never appear in an email (role matrix section 3; contract 3.11).
SCORE_WORDS = re.compile(r"\b(score|scores|aggregate|recommend\w*|disagree\w*)\b", re.IGNORECASE)
SCORE_NUMBER = re.compile(r"\b[1-5]\.\d\b")


# --- Mailpit ----------------------------------------------------------------------------
@dataclass
class MailpitServer:
    """Where Mailpit listens; ``container`` is set when this module started it."""

    smtp_host: str
    smtp_port: int
    api_url: str
    container: Any = None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_up(api_url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(f"{api_url}/readyz", timeout=1, trust_env=False).status_code == 200:
                return
        time.sleep(0.25)
    raise RuntimeError(f"Mailpit at {api_url} did not come up")


@pytest.fixture(scope="module")
def mailpit() -> Iterator[MailpitServer]:
    if os.environ.get("SOUNDINGS_TEST_MAILPIT") == "0":
        pytest.skip("SOUNDINGS_TEST_MAILPIT=0")
    external_smtp = os.environ.get("SOUNDINGS_TEST_MAILPIT_SMTP")
    external_url = os.environ.get("SOUNDINGS_TEST_MAILPIT_URL")
    if external_smtp and external_url:
        host, _, port = external_smtp.rpartition(":")
        yield MailpitServer(host or "127.0.0.1", int(port), external_url.rstrip("/"))
        return

    os.environ.setdefault("RYUK_CONTAINER_IMAGE", "testcontainers/ryuk:0.11.0")
    try:
        from testcontainers.core.container import DockerContainer

        smtp_port, web_port = _free_port(), _free_port()
        # Fixed host ports, so a stopped and restarted Mailpit is at the same address;
        # its database is a file in the container, so messages survive the restart.
        container = (
            DockerContainer(MAILPIT_IMAGE)
            .with_name(f"{CONTAINER_PREFIX}mailpit-{uuid.uuid4().hex[:8]}")
            .with_bind_ports(1025, smtp_port)
            .with_bind_ports(8025, web_port)
            .with_env("MP_DATABASE", "/tmp/mailpit.db")  # noqa: S108 - inside the container
            .with_env("MP_SMTP_AUTH_ACCEPT_ANY", "true")
            .with_env("MP_SMTP_AUTH_ALLOW_INSECURE", "true")
            .with_env("MP_DISABLE_VERSION_CHECK", "true")
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - no Docker here: nothing to test against
        pytest.skip(f"no Mailpit: set SOUNDINGS_TEST_MAILPIT_SMTP/_URL or run Docker ({exc})")
    api_url = f"http://127.0.0.1:{web_port}"
    try:
        _wait_until_up(api_url)
        yield MailpitServer("127.0.0.1", smtp_port, api_url, container)
    finally:
        container.stop()


class SmtpRelay:
    """A TCP relay to an external Mailpit's SMTP port. Closed, it refuses connections
    exactly like a stopped server (the port stays the same when it reopens)."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self.target = (target_host, target_port)
        self.port = 0
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def open(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        self.port = int(self._server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_reader, up_writer = await asyncio.open_connection(*self.target)

        async def pipe(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
            with contextlib.suppress(ConnectionError):
                while data := await source.read(65536):
                    sink.write(data)
                    await sink.drain()
            sink.close()

        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


@dataclass
class Smtp:
    """The SMTP server the app is configured with, and a switch to take it down."""

    host: str
    port: int
    mailpit: MailpitServer
    relay: SmtpRelay | None = None

    async def down(self) -> None:
        if self.relay is not None:
            await self.relay.close()
        else:
            await asyncio.to_thread(self.mailpit.container.get_wrapped_container().stop, timeout=2)

    async def up(self) -> None:
        if self.relay is not None:
            await self.relay.open()
        else:
            await asyncio.to_thread(self.mailpit.container.get_wrapped_container().start)
            await asyncio.to_thread(_wait_until_up, self.mailpit.api_url)


@pytest.fixture
async def smtp(mailpit: MailpitServer) -> AsyncIterator[Smtp]:
    if mailpit.container is not None:
        yield Smtp(mailpit.smtp_host, mailpit.smtp_port, mailpit)
        # Always leave it running for the next test.
        await asyncio.to_thread(mailpit.container.get_wrapped_container().start)
        await asyncio.to_thread(_wait_until_up, mailpit.api_url)
        return
    relay = SmtpRelay(mailpit.smtp_host, mailpit.smtp_port)
    await relay.open()
    try:
        yield Smtp("127.0.0.1", relay.port, mailpit, relay)
    finally:
        await relay.close()


@pytest.fixture
def settings_overrides(smtp: Smtp) -> dict[str, Any]:
    return {
        "smtp_host": smtp.host,
        "smtp_port": smtp.port,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        "smtp_from_name": "Soundings",
        "smtp_timeout": 3,
        "timezone": ZONE,
        "base_urls": [BASE],
    }


class MailpitInbox:
    """Mailpit's HTTP API, filtered to one recipient (the inbox may be shared)."""

    def __init__(self, api_url: str) -> None:
        self.http = httpx.AsyncClient(base_url=api_url, timeout=5, trust_env=False)

    async def to(self, address: str) -> list[dict[str, Any]]:
        response = await self.http.get(
            "/api/v1/search", params={"query": f'to:"{address}"', "limit": 100}
        )
        response.raise_for_status()
        found = response.json().get("messages") or []
        return [
            message
            for message in found
            if any(to["Address"].lower() == address.lower() for to in message["To"])
        ]

    async def wait_for(self, address: str, count: int = 1, seconds: float = 15) -> list[Any]:
        for _ in range(int(seconds * 4)):
            messages = await self.to(address)
            if len(messages) >= count:
                return messages
            await asyncio.sleep(0.25)
        raise AssertionError(f"expected {count} email(s) in Mailpit, got {len(messages)}")

    async def message(self, message_id: str) -> dict[str, Any]:
        response = await self.http.get(f"/api/v1/message/{message_id}")
        response.raise_for_status()
        return dict(response.json())

    async def headers(self, message_id: str) -> dict[str, list[str]]:
        response = await self.http.get(f"/api/v1/message/{message_id}/headers")
        response.raise_for_status()
        return dict(response.json())

    async def raw(self, message_id: str) -> EmailMessage:
        response = await self.http.get(f"/api/v1/message/{message_id}/raw")
        response.raise_for_status()
        parsed = email.message_from_bytes(response.content, policy=policy.default)
        assert isinstance(parsed, EmailMessage)
        return parsed


@pytest.fixture
async def inbox(mailpit: MailpitServer) -> AsyncIterator[MailpitInbox]:
    box = MailpitInbox(mailpit.api_url)
    yield box
    await box.http.aclose()


# --- The worker -------------------------------------------------------------------------
class Clock:
    """The worker's clock: real time, or a moment the test moves forward."""

    def __init__(self) -> None:
        self.now: datetime | None = None

    def __call__(self) -> datetime:
        return self.now or utcnow()


@pytest.fixture
async def jobs(settings: Settings) -> AsyncIterator[App]:
    with procrastinate_app.replace_connector(
        PsycopgConnector(conninfo=settings.database_dsn, min_size=1, max_size=2)
    ) as job_app:
        async with job_app.open_async():
            yield job_app


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def runtime(app: FastAPI, settings: Settings, jobs: App, clock: Clock) -> Runtime:
    """The worker's runtime with the real SMTP transport (aiosmtplib -> Mailpit)."""
    return Runtime(settings=settings, sessionmaker=app.state.sessionmaker, jobs=jobs, clock=clock)


async def run_worker_once(jobs: App, runtime: Runtime) -> None:
    """``soundings worker`` for one pass: runs every due job on the email queue."""
    await jobs.run_worker_async(
        **worker_options(concurrency=1, runtime=runtime), queues=["email"], wait=False
    )


# --- HTTP -------------------------------------------------------------------------------
def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, f"{response.request.url}: {response.text}"
    return response.json() if response.content else None


class Client:
    """A signed-in browser: dev login, its own cookies, the CSRF header on writes."""

    def __init__(self, http: httpx.AsyncClient, user: dict[str, Any]) -> None:
        self.http = http
        self.user = user

    async def get(self, path: str, **params: Any) -> Any:
        return ok(await self.http.get(API + path, params=params))

    async def send(self, method: str, path: str, body: Any = None, status: int = 200) -> Any:
        return ok(await self.http.request(method, API + path, json=body), status)


@dataclass
class Story:
    app: FastAPI
    clients: list[httpx.AsyncClient] = field(default_factory=list)

    def browser(self) -> httpx.AsyncClient:
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url=BASE,
        )
        self.clients.append(http)
        return http

    async def sign_in(self, user_id: str) -> Client:
        http = self.browser()
        me = ok(await http.post(f"{API}/auth/dev/login", json={"user_id": user_id}))
        http.headers["X-CSRF-Token"] = http.cookies["soundings_csrf"]
        return Client(http, me)


@pytest.fixture
async def story(app: FastAPI) -> AsyncIterator[Story]:
    current = Story(app)
    yield current
    for http in current.clients:
        await http.aclose()


@dataclass
class Team:
    platform: Client
    alice: Client
    bob: Client
    carol: Client
    slug: str
    key: str
    title: str
    due_at: datetime


async def arrange(db_session: AsyncSession, story: Story) -> Team:
    """A platform admin (the one row made directly) creates Alice, Bob and Carol and a
    private project through the admin API; Alice adds an idea and owns it."""
    run = uuid.uuid4().hex[:6]
    root = await make_user(db_session, "Pat Platform", platform_admin=True)
    platform = await story.sign_in(str(root.id))
    people: dict[str, Client] = {}
    for name in ("Alice Anders", "Bob Brown", "Carol Chen"):
        first = name.split()[0].lower()
        created = await platform.send(
            "POST",
            "/admin/users",
            {"email": f"{first}.{run}@example.com", "display_name": name},
            201,
        )
        people[first] = await story.sign_in(created["id"])
    project = await platform.send(
        "POST",
        "/projects",
        {
            "name": "Customer Innovation",
            "slug": f"cust-{run}",
            "key": "CUST",
            "admin_user_id": people["alice"].user["id"],
        },
        201,
    )
    alice = people["alice"]
    for first in ("bob", "carol"):
        await alice.send(
            "POST",
            f"/projects/{project['slug']}/members",
            {"user_id": people[first].user["id"], "role": "member"},
            201,
        )
    title = "Self-service returns portal"
    idea = await alice.send(
        "POST",
        f"/projects/{project['slug']}/ideas",
        {"title": title, "summary": "Customers start a return without calling us."},
        201,
    )
    await alice.send("PUT", f"/ideas/{idea['key']}/owner", {"user_id": alice.user["id"]})
    # Due in a week at 17:00 London time (the email shows it in the instance zone).
    local_due = (datetime.now(ZoneInfo(ZONE)) + timedelta(days=7)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    return Team(
        platform=platform,
        alice=alice,
        bob=people["bob"],
        carol=people["carol"],
        slug=project["slug"],
        key=idea["key"],
        title=title,
        due_at=local_due.astimezone(UTC),
    )


async def invite(team: Team, evaluator: Client) -> None:
    await team.alice.send(
        "POST",
        f"/ideas/{team.key}/evaluators",
        {"user_ids": [evaluator.user["id"]], "due_at": team.due_at.isoformat()},
    )


async def rows_for(db: AsyncSession, user_id: str) -> list[OutboundEmail]:
    return list(
        await db.scalars(
            select(OutboundEmail)
            .where(OutboundEmail.recipient_user_id == uuid.UUID(user_id))
            .order_by(OutboundEmail.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def send_jobs(db: AsyncSession, email_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT id, status, scheduled_at FROM procrastinate_jobs"
            " WHERE task_name = 'send_email' AND args->>'email_id' = :id ORDER BY id"
        ),
        {"id": str(email_id)},
    )
    await db.commit()
    return [dict(row._mapping) for row in rows]


def day(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo(ZONE))
    return f"{local:%a} {local.day} {local:%b}"


def visible_text(html: str) -> str:
    """What a reader sees in the HTML part: no head, styles, tags or attributes."""
    body = re.sub(r"(?is)<(head|style)\b.*?</\1>", " ", html)
    return unescape(re.sub(r"(?s)<[^>]+>", " ", body))


def assert_no_score_data(*parts: str) -> None:
    for part in parts:
        assert not SCORE_WORDS.search(part), SCORE_WORDS.search(part)
        assert not SCORE_NUMBER.search(part), SCORE_NUMBER.search(part)


# --- AC3-API-1: the invitation email ----------------------------------------------------
async def test_an_invited_evaluator_gets_one_branded_email_with_the_evaluate_link(
    story: Story,
    db_session: AsyncSession,
    jobs: App,
    runtime: Runtime,
    inbox: MailpitInbox,
) -> None:
    team = await arrange(db_session, story)
    bob = team.bob.user["email"]

    await invite(team, team.bob)

    # The invitation wrote the outbox row and deferred its job in the same transaction.
    row = (await rows_for(db_session, team.bob.user["id"]))[0]
    assert (row.type, row.status, row.attempts) == (EmailType.EVALUATOR_INVITED, "queued", 0)
    assert [job["status"] for job in await send_jobs(db_session, row.id)] == ["todo"]
    notification = await db_session.scalar(
        select(Notification).where(Notification.email_id == row.id)
    )
    assert notification is not None
    assert notification.user_id == uuid.UUID(team.bob.user["id"])

    await run_worker_once(jobs, runtime)

    [summary] = await inbox.wait_for(bob)
    message = await inbox.message(summary["ID"])
    headers = await inbox.headers(summary["ID"])
    raw = await inbox.raw(summary["ID"])
    evaluate_link = f"{BASE}/ideas/{team.key}?evaluate=1"

    # One branded email: subject with the due date, both parts, the evaluate button.
    assert (
        message["Subject"] == f'[{team.key}] Please evaluate "{team.title}" by {day(team.due_at)}'
    )
    assert message["From"] == {"Name": "Soundings", "Address": "soundings@example.com"}
    assert [to["Address"] for to in message["To"]] == [bob]
    assert raw.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in raw.iter_parts()] == ["text/plain", "text/html"]
    html, plain = message["HTML"], message["Text"]
    assert f'href="{evaluate_link}"' in html.replace("&amp;", "&")
    assert evaluate_link in plain
    assert "Soundings" in html  # the wordmark
    assert "Soundings" in plain
    assert "Customer Innovation" in html
    assert team.title in html
    assert f"{BASE}/settings/notifications" in plain  # footer: preferences
    assert "<table" in html  # table layout
    assert 'name="color-scheme"' in html  # dark-mode safe
    assert_no_score_data(message["Subject"], visible_text(html), plain)

    # Headers: Message-ID fixed at insert, auto-generated, one-click unsubscribe.
    assert headers["Message-Id"] == [row.message_id]
    assert headers["Auto-Submitted"] == ["auto-generated"]
    assert headers["List-Unsubscribe-Post"] == ["List-Unsubscribe=One-Click"]
    [unsubscribe] = re.findall(r"<([^>]+)>", headers["List-Unsubscribe"][0])
    assert unsubscribe.startswith(f"{BASE}/api/v1/unsubscribe?token=")
    assert unsubscribe.split("token=")[1] in plain  # the footer's link: the same token

    # Delivered once; the row records it and the finished job is gone.
    await db_session.refresh(row)
    assert (row.status, row.attempts, row.last_error) == (EmailStatus.SENT, 1, None)
    assert await send_jobs(db_session, row.id) == []
    assert await delivery.send_email(runtime, row.id) == "not_claimed"
    assert len(await inbox.to(bob)) == 1

    # The link's idea is Bob's to evaluate: the sheet the SPA opens can be submitted.
    mine = await team.bob.get(f"/ideas/{team.key}/evaluations/me")
    assert (mine["state"], mine["editable"]) == ("invited", True), mine
    assert datetime.fromisoformat(mine["due_at"]) == team.due_at

    # The header's URL: a browser is sent to the SPA page; a mail client's one-click
    # POST (no cookies, form body) turns invitations off for Bob.
    anonymous = story.browser()
    redirect = await anonymous.get(unsubscribe, headers={"Accept": "text/html"})
    assert redirect.status_code == 303
    assert (
        redirect.headers["location"] == f"{BASE}/unsubscribe?token={unsubscribe.split('token=')[1]}"
    )
    one_click = await anonymous.post(
        unsubscribe,
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert ok(one_click)["unsubscribed"] is True
    preferences = await team.bob.get("/me/notification-preferences")
    modes = {item["type"]: item["mode"] for item in preferences["items"]}
    assert modes["evaluator_invited"] == "off"


# --- AC3-API-2: SMTP down, then back ----------------------------------------------------
async def test_mail_queued_while_smtp_is_down_is_delivered_once_when_it_is_back(
    story: Story,
    db_session: AsyncSession,
    jobs: App,
    runtime: Runtime,
    clock: Clock,
    smtp: Smtp,
    inbox: MailpitInbox,
) -> None:
    team = await arrange(db_session, story)
    await invite(team, team.bob)
    await run_worker_once(jobs, runtime)
    await inbox.wait_for(team.bob.user["email"])

    await smtp.down()
    await invite(team, team.carol)
    [row] = await rows_for(db_session, team.carol.user["id"])

    # Attempt 1 (the job the invitation deferred): refused, queued again with backoff.
    started = utcnow()
    await run_worker_once(jobs, runtime)
    await db_session.refresh(row)
    assert (row.status, row.attempts, row.last_error) == ("queued", 1, "connection refused")
    assert row.next_attempt_at is not None
    first_wait = row.next_attempt_at - started
    assert timedelta(seconds=29) <= first_wait <= timedelta(seconds=35), first_wait
    # ... with its next job scheduled for then, in the same transaction.
    [retry_job] = await send_jobs(db_session, row.id)
    assert retry_job["status"] == "todo"
    assert abs(retry_job["scheduled_at"] - row.next_attempt_at) < timedelta(seconds=1)

    # What a platform admin sees on Admin -> Email meanwhile.
    config = await team.platform.get("/admin/email")
    assert config["outbox"]["queued"] == 1
    assert config["outbox"]["oldest_queued_at"]
    listed = await team.platform.get("/admin/email/outbox", status="queued")
    [queued] = [item for item in listed["items"] if item["id"] == str(row.id)]
    assert queued["recipient"]["display_name"] == "Carol Chen"
    assert queued["idea"]["key"] == team.key
    assert (queued["attempts"], queued["last_error"], queued["retryable"]) == (
        1,
        "connection refused",
        False,
    )
    assert queued["address_hint"] is None  # a user: shown by name, no address
    assert team.carol.user["email"] not in str(listed)

    # Attempt 2, when it is due (still down): the wait doubles.
    clock.now = row.next_attempt_at + timedelta(seconds=1)
    assert await delivery.send_email(runtime, row.id) == "retry"
    await db_session.refresh(row)
    assert (row.status, row.attempts) == ("queued", 2)
    assert timedelta(seconds=59) <= row.next_attempt_at - clock.now <= timedelta(seconds=67)
    # Not due yet: a duplicate job (or the sweep's) claims nothing.
    assert await delivery.send_email(runtime, row.id) == "not_claimed"

    # Mailpit is back: the next attempt delivers it, once, with its Message-ID.
    await smtp.up()
    assert await inbox.to(team.carol.user["email"]) == []
    clock.now = row.next_attempt_at + timedelta(seconds=1)
    assert await delivery.send_email(runtime, row.id) == "sent"
    [summary] = await inbox.wait_for(team.carol.user["email"])
    headers = await inbox.headers(summary["ID"])
    assert headers["Message-Id"] == [row.message_id]
    await db_session.refresh(row)
    assert (row.status, row.attempts, row.last_error) == (EmailStatus.SENT, 3, None)

    # The retry jobs still waiting, and the sweep, send nothing more.
    for _ in await send_jobs(db_session, row.id):
        assert await delivery.send_email(runtime, row.id) == "not_claimed"
    clock.now = clock.now + timedelta(minutes=10)
    await delivery.sweep_outbox(runtime)
    assert await delivery.send_email(runtime, row.id) == "not_claimed"
    await asyncio.sleep(1)
    assert len(await inbox.to(team.carol.user["email"])) == 1
    # Bob's email from before the outage is still there, once.
    assert len(await inbox.to(team.bob.user["email"])) == 1

    config = await team.platform.get("/admin/email")
    assert config["outbox"]["queued"] == 0
    assert config["outbox"]["failed"] == 0
    assert config["outbox"]["sent_last_24h"] == 2


# --- AC3-API-3: the hourly schedule's reminder and digests, through Mailpit -------------
async def test_the_digest_hour_sends_reminders_and_digests_without_score_data(
    story: Story,
    app: FastAPI,
    settings: Settings,
    db_session: AsyncSession,
    jobs: App,
    runtime: Runtime,
    clock: Clock,
    inbox: MailpitInbox,
) -> None:
    """Carol gets mentions in the daily digest; Alice (submitter, watcher) gets comments
    there by default. At the digest hour of the day two days before the due date, the
    schedule queues Carol's reminder (Bob, who submitted, gets none) and one digest each;
    the worker sends them through Mailpit; a second run in the hour does nothing."""
    team = await arrange(db_session, story)
    zone = ZoneInfo(ZONE)
    local_due = (datetime.now(zone) + timedelta(days=3)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    team.due_at = local_due.astimezone(UTC)
    await team.carol.send("PATCH", "/me/notification-preferences", {"mention": "digest"})
    await team.alice.send(
        "POST",
        f"/ideas/{team.key}/evaluators",
        {
            "user_ids": [team.bob.user["id"], team.carol.user["id"]],
            "due_at": team.due_at.isoformat(),
        },
    )
    await run_worker_once(jobs, runtime)  # the two invitations
    await inbox.wait_for(team.carol.user["email"])

    # Bob submits (the idea now has score data) and mentions Carol in a comment.
    project = await team.alice.get(f"/projects/{team.slug}")
    scores = [{"criterion_id": c["id"], "score": 4} for c in project["rubric"]]
    await team.bob.send(
        "PUT",
        f"/ideas/{team.key}/evaluations/me",
        {"scores": scores, "recommendation": "go", "comment": "Private rationale", "submit": True},
    )
    carol_token = f"@[Carol Chen](user:{team.carol.user['id']})"
    await team.bob.send(
        "POST", f"/ideas/{team.key}/comments", {"body_md": f"{carol_token} over to you"}, 201
    )
    assert len(await rows_for(db_session, team.carol.user["id"])) == 1  # mention: no email yet

    # The digest hour (08:00 local), two days before the due date.
    fire = datetime.combine(
        (local_due - timedelta(days=2)).date(), datetime.min.time(), tzinfo=zone
    ).replace(hour=settings.digest_hour, minute=30)
    clock.now = fire.astimezone(UTC)
    result = await run_schedule(app.state.sessionmaker, settings, clock.now)
    assert (result.reminders, result.digests) == (1, 2)
    queued = [
        row
        for user in (team.alice, team.bob, team.carol)
        for row in await rows_for(db_session, user.user["id"])
        if row.status == EmailStatus.QUEUED
    ]
    assert sorted(row.type.value for row in queued) == ["digest", "digest", "evaluation_reminder"]
    for row in queued:
        assert await delivery.send_email(runtime, row.id) == "sent"

    carol_mail = await inbox.wait_for(team.carol.user["email"], count=3)
    subjects = sorted(message["Subject"] for message in carol_mail)
    reminder_subject = (
        f'[{team.key}] Reminder: your evaluation of "{team.title}" is due {day(team.due_at)}'
    )
    assert subjects == sorted(
        [
            f'[{team.key}] Please evaluate "{team.title}" by {day(team.due_at)}',
            reminder_subject,
            "Soundings digest: 1 update on 1 idea",
        ]
    )
    for summary in carol_mail:
        message = await inbox.message(summary["ID"])
        html, plain = visible_text(message["HTML"]), message["Text"]
        assert "Private rationale" not in html + plain
        assert_no_score_data(message["Subject"], html, plain)
        if message["Subject"] == reminder_subject:
            assert f"{BASE}/ideas/{team.key}?evaluate=1" in plain
        if message["Subject"].startswith("Soundings digest"):
            assert "Bob Brown" in plain
            assert "@Carol Chen over to you" in plain
            headers = await inbox.headers(summary["ID"])
            [url] = re.findall(r"<([^>]+)>", headers["List-Unsubscribe"][0])
            info = ok(await story.browser().get(url, headers={"Accept": "application/json"}))
            assert info["scope"] == "digest"
            assert "mention" in info["types"]

    alice_mail = await inbox.wait_for(team.alice.user["email"])
    [alice_digest] = [m for m in alice_mail if m["Subject"].startswith("Soundings digest")]
    alice_text = (await inbox.message(alice_digest["ID"]))["Text"]
    assert "Bob Brown commented" in alice_text
    assert_no_score_data(alice_text)
    # Bob submitted: no reminder for him.
    assert [m["Subject"] for m in await inbox.to(team.bob.user["email"])] == [
        f'[{team.key}] Please evaluate "{team.title}" by {day(team.due_at)}'
    ]

    # Another run in the same hour: nothing new.
    clock.now = clock.now + timedelta(minutes=20)
    again = await run_schedule(app.state.sessionmaker, settings, clock.now)
    assert (again.reminders, again.digests) == (0, 0)
