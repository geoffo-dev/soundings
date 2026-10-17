"""Phase 11 acceptance through the HTTP API and a real Mailpit (QA;
docs/test-plans/phase-11.md, AC11-API-*).

The product owner's change of 2026-10-16 (contract-phase11): **the team messages the person
who sent a public idea through Soundings**, and **the tracking link is emailed once the
address is confirmed**.

Everything goes through the HTTP API, as the SPA and a visitor's browser would (dev login
and CSRF for staff; no session at all for the visitor, who solves the real ALTCHA with the
Python ``altcha`` library), except the first platform admin, the AI agent's registration and
open run (as in the Phase 6 helpers), a few rows written straight to the database to bring a
conversation to a limit, and read-only database checks of what must be gone. The worker's
own code delivers the email (procrastinate runs the ``send_email`` jobs the requests
deferred, through the real SMTP transport, to the Phase 3 module's Mailpit), and every
email is read back from Mailpit: subjects, both parts, links and headers.

* AC11-API-1: the whole story: a submission with an address, held for moderation; the
  confirmation email carries no tracking link (and says the link follows); confirming
  emails the link once (a second confirmation sends nothing); an admin asks before
  approving and the submitter answers (no notification while held); approved, owned; the
  owner messages the submitter (the email escapes the text, keeps its line breaks, is
  signed by the team, names no person and has no ``Reply-To``; Reply opens the tracking
  page); the tracking page shows the conversation and the submitter replies; the owner and
  the admin who wrote get "The submitter replied" in the inbox and one email each an hour;
  a member, a viewer, a guest researcher, a person's API key (every scope, REST and MCP) and
  an AI agent's key see nothing of it anywhere (the panel, the routes, idea detail, the
  feed, search, notifications, MCP, ``last_activity_at``); the audit has one entry per team
  message and no text; no message text, token or address reached the logs.
* AC11-API-2: an unconfirmed address gets no message emails (delivery ``tracking_page``)
  and the limits: 10 replies since the team's latest message (409 ``awaiting_team``), 10
  replies a day (429 with ``Retry-After``), 30 team messages a person an hour, 20 team
  messages a submission a day (429 with ``Retry-After``), 100 messages a conversation (409
  ``conversation_full`` both ways).
* AC11-API-3: erasure and retention: "Delete my details" removes the conversation and every
  submitter email (queued and sent) and cancels the team's queued "The submitter replied"
  email; a tracking-link email queued and then erased is never sent; "Remove my email
  address" stops the emails and keeps the link and the conversation; retention rule 3 keeps
  the conversation of a forgotten address; rule 4 waits for a live conversation and then
  erases it with the details.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from datetime import timedelta
from typing import Any

import altcha
import httpx
import pytest
from fastapi import FastAPI
from procrastinate import App
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import (
    SUBMITTER_EMAIL_TYPES,
    AiRunKind,
    EmailStatus,
    EmailType,
    MessageDirection,
)
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.project import Project
from app.models.public import PublicSubmission, SubmissionMessage
from app.public import retention
from tests.acceptance.test_phase3_acceptance import (  # noqa: F401 - fixtures
    API,
    BASE,
    ZONE,
    Client,
    MailpitInbox,
    MailpitServer,
    Story,
    clock,
    inbox,
    jobs,
    mailpit,
    ok,
    run_worker_once,
    runtime,
    story,
    visible_text,
)
from tests.ai.helpers import make_agent, open_run
from tests.factories import make_user
from tests.mcp.conftest import call, connect  # noqa: F401 - the fixture

PUBLIC = f"{API}/public"
PROJECT_NAME = "Customer Innovation"
REPLY_TO = "ideas-team@example.com"
# Words that appear only in messages: a search, a feed or an MCP result that carries one
# has leaked the conversation.
MARK = "Quokkazeppelin"
SUBMITTER_TYPES = {str(t) for t in SUBMITTER_EMAIL_TYPES}


@pytest.fixture
def settings_overrides(mailpit: MailpitServer) -> dict[str, Any]:  # noqa: F811 - the fixture
    return {
        "smtp_host": mailpit.smtp_host,
        "smtp_port": mailpit.smtp_port,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        "smtp_from_name": "Soundings",
        # Phase 4's emails keep it; the two new submitter emails must leave it out (S1).
        "smtp_reply_to": REPLY_TO,
        "smtp_timeout": 3,
        "timezone": ZONE,
        "base_urls": [BASE],
        "altcha_cost": 1_000,
        "ai_enabled": True,
    }


# --- Helpers ----------------------------------------------------------------------------
def solve(challenge: dict[str, Any]) -> str:
    """The widget's payload for ``challenge``: solve it, base64 the JSON."""
    parsed = altcha.Challenge.from_dict(challenge)
    solution = altcha.solve_challenge(parsed)
    assert solution is not None
    return base64.b64encode(
        json.dumps(altcha.Payload(parsed, solution).to_dict()).encode()
    ).decode()


def links(message: dict[str, Any]) -> list[str]:
    return [href.replace("&amp;", "&") for href in re.findall(r'href="([^"]+)"', message["HTML"])]


def fragment(url: str, path: str) -> str:
    assert url.startswith(f"{BASE}{path}#"), url
    return url.split("#", 1)[1]


def problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, f"{response.request.url}: {response.text}"
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


def retry_after(response: httpx.Response) -> int:
    seconds = int(response.headers["Retry-After"])
    assert seconds >= 1
    return seconds


class Visitor:
    """A signed-out browser on the public pages: the form, the tracking page, the
    confirmation page."""

    def __init__(self, http: httpx.AsyncClient, slug: str) -> None:
        self.http = http
        self.slug = slug
        self.token = ""

    async def submit(
        self, title: str, email: str | None, *, name: str = "Sam Public"
    ) -> dict[str, Any]:
        challenge = ok(await self.http.get(f"{PUBLIC}/projects/{self.slug}/altcha"))
        receipt = ok(
            await self.http.post(
                f"{PUBLIC}/projects/{self.slug}/submissions",
                json={
                    "title": title,
                    "summary": f"{title}: the summary as sent.",
                    "name": name,
                    "email": email,
                    "wants_updates": False,
                    "altcha": solve(challenge),
                    "website": "",
                },
            ),
            201,
        )
        self.token = receipt["tracking_token"]
        return dict(receipt)

    async def page(self) -> httpx.Response:
        return await self.http.post(f"{PUBLIC}/track", json={"token": self.token})

    async def track(self) -> dict[str, Any]:
        return dict(ok(await self.page()))

    async def reply(self, body: str) -> httpx.Response:
        return await self.http.post(
            f"{PUBLIC}/track/messages", json={"token": self.token, "body": body}
        )

    async def confirm(self, verify_link: str) -> httpx.Response:
        return await self.http.post(
            f"{PUBLIC}/verify-email",
            json={"token": fragment(verify_link, f"/{self.slug}/verify")},
        )

    async def erase(self) -> httpx.Response:
        return await self.http.post(f"{PUBLIC}/track/erase", json={"token": self.token})

    async def forget_email(self) -> httpx.Response:
        return await self.http.post(f"{PUBLIC}/track/forget-email", json={"token": self.token})


async def verify_link_in(inbox: MailpitInbox, address: str) -> str:  # noqa: F811
    [summary] = [
        m for m in await inbox.wait_for(address) if m["Subject"].startswith("Confirm your idea")
    ]
    message = await inbox.message(summary["ID"])
    [link] = [href for href in links(message) if "/verify#" in href]
    return link


async def key_of(client: Client, slug: str, title: str) -> str:
    page = await client.get(f"/projects/{slug}/ideas", limit=100)
    [found] = [item["key"] for item in page["items"] if item["title"] == title]
    return str(found)


async def messages(client: Client, key: str) -> list[dict[str, Any]]:
    page = await client.get(f"/ideas/{key}/submission/messages", limit=200)
    return list(page["items"])


async def post_message(client: Client, key: str, body: str) -> httpx.Response:
    return await client.http.post(f"{API}/ideas/{key}/submission/messages", json={"body": body})


async def send_message(client: Client, key: str, body: str) -> dict[str, Any]:
    return dict(ok(await post_message(client, key, body), 201))


async def inbox_items(client: Client, kind: str | None = None) -> list[dict[str, Any]]:
    page = await client.get("/me/notifications", limit=100)
    return [item for item in page["items"] if kind is None or item["type"] == kind]


async def outbox(db: AsyncSession, idea_id: str, types: set[str] | None = None) -> list[Any]:
    rows = await db.scalars(
        select(OutboundEmail)
        .where(OutboundEmail.idea_id == uuid.UUID(idea_id))
        .order_by(OutboundEmail.created_at)
        .execution_options(populate_existing=True)
    )
    found = list(rows)
    await db.commit()
    return [row for row in found if types is None or str(row.type) in types]


async def staff_emails(db: AsyncSession, user_id: str, kind: EmailType) -> list[OutboundEmail]:
    rows = await db.scalars(
        select(OutboundEmail)
        .where(OutboundEmail.recipient_user_id == uuid.UUID(user_id), OutboundEmail.type == kind)
        .order_by(OutboundEmail.created_at)
        .execution_options(populate_existing=True)
    )
    found = list(rows)
    await db.commit()
    return found


async def stored_messages(db: AsyncSession, idea_id: str) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(SubmissionMessage)
        .join(PublicSubmission, PublicSubmission.id == SubmissionMessage.submission_id)
        .where(PublicSubmission.idea_id == uuid.UUID(idea_id))
    )
    await db.commit()
    return int(count or 0)


async def write_messages(
    db: AsyncSession,
    idea_id: str,
    count: int,
    *,
    author_id: str | None = None,
    direction: MessageDirection = MessageDirection.TEAM,
    age: timedelta = timedelta(0),
) -> None:
    """``count`` messages straight in the database (to bring a conversation to a limit)."""
    submission_id = await db.scalar(
        select(PublicSubmission.id).where(PublicSubmission.idea_id == uuid.UUID(idea_id))
    )
    assert submission_id is not None
    when = utcnow() - age
    db.add_all(
        SubmissionMessage(
            id=uuid.uuid4(),
            submission_id=submission_id,
            direction=direction,
            author_id=uuid.UUID(author_id) if author_id else None,
            body=f"Filler {n}.",
            emailed=False,
            created_at=when - timedelta(seconds=n),
        )
        for n in range(count)
    )
    await db.commit()


async def people(story: Story, db: AsyncSession, *names: str) -> tuple[Client, dict[str, Client]]:  # noqa: F811
    run = uuid.uuid4().hex[:6]
    root = await make_user(db, "Pat Platform", platform_admin=True)
    pat = await story.sign_in(str(root.id))
    found: dict[str, Client] = {}
    for name in names:
        first = name.split()[0].lower()
        created = await pat.send(
            "POST",
            "/admin/users",
            {"email": f"{first}.{run}@example.com", "display_name": name},
            201,
        )
        found[first] = await story.sign_in(created["id"])
    return pat, found


async def project_with_form(
    pat: Client,
    admin: Client,
    members: dict[str, str],
    *,
    moderated: bool,
) -> str:
    run = uuid.uuid4().hex[:6]
    project = await pat.send(
        "POST",
        "/projects",
        {
            "name": PROJECT_NAME,
            "slug": f"cust-{run}",
            "key": "CUST",
            "admin_user_id": admin.user["id"],
        },
        201,
    )
    slug = str(project["slug"])
    for user_id, role in members.items():
        await admin.send(
            "POST", f"/projects/{slug}/members", {"user_id": user_id, "role": role}, 201
        )
    await admin.send(
        "PATCH",
        f"/projects/{slug}/public-form",
        {"enabled": True, "moderation_required": moderated},
    )
    return slug


def assert_names_nobody(label: str, message: dict[str, Any], *people_: Client) -> None:
    """Public pages and submitter emails never show people (contract-phase11 section 8)."""
    parts = (message["Subject"], visible_text(message["HTML"]), message["HTML"], message["Text"])
    for person in people_:
        first = person.user["display_name"].split()[0]
        for value in (person.user["display_name"], first, person.user["email"]):
            for part in parts:
                assert value not in part, (label, value)


# --- AC11-API-1 -------------------------------------------------------------------------
async def test_ac11_api_1_the_team_talks_to_a_public_submitter(
    story: Story,  # noqa: F811 - the fixture
    app: FastAPI,
    db_session: AsyncSession,
    jobs: App,  # noqa: F811 - the fixture
    runtime: Runtime,  # noqa: F811 - the fixture
    inbox: MailpitInbox,  # noqa: F811 - the fixture
    connect: Any,  # noqa: F811 - the fixture
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="soundings")
    caplog.set_level(logging.INFO)
    pat, crew = await people(
        story, db_session, "Alice Anders", "Olive Owner", "Mia Member", "Vic Viewer", "Gus Guest"
    )
    alice, olive, mia, vic, gus = (crew[n] for n in ("alice", "olive", "mia", "vic", "gus"))
    slug = await project_with_form(
        pat,
        alice,
        {olive.user["id"]: "member", mia.user["id"]: "member", vic.user["id"]: "viewer"},
        moderated=True,
    )
    # The research step, so that Gus (no role in this private project) can be its guest.
    research = await alice.get(f"/projects/{slug}/research")
    await alice.send(
        "PUT",
        f"/projects/{slug}/research",
        {"step": "before_evaluation", "items": research["default_items"]},
    )

    # --- 1. A submission with an address, held for moderation ----------------------------
    sam = f"sam.{uuid.uuid4().hex[:6]}@example.org"
    title = "Reusable delivery boxes with a deposit"
    visitor = Visitor(story.browser(), slug)
    receipt = await visitor.submit(title, sam)
    token = visitor.token
    assert (receipt["held_for"], receipt["email_sent"]) == ("moderation", True)
    tracking_url = f"{BASE}/track#{token}"

    # The confirmation email: still no tracking link (anyone can type any address), and
    # one new sentence saying the link follows the confirmation.
    await run_worker_once(jobs, runtime)
    verify_link = await verify_link_in(inbox, sam)
    [summary] = await inbox.to(sam)
    confirmation = await inbox.message(summary["ID"])
    for part in (visible_text(confirmation["HTML"]), confirmation["Text"]):
        assert "Once you confirm, we'll email you a private link to follow your idea." in " ".join(
            part.split()
        )
        assert token not in part
    assert not [href for href in links(confirmation) if "/track" in href]
    assert token not in confirmation["HTML"]
    # Phase 4's emails keep the instance's Reply-To.
    assert (await inbox.headers(summary["ID"])).get("Reply-To") == [REPLY_TO]

    # --- 2. Confirming emails the link, once ---------------------------------------------
    first = ok(await visitor.confirm(verify_link))
    assert first["tracking_link_emailed"] is True
    again = ok(await visitor.confirm(verify_link))
    assert again["tracking_link_emailed"] is False  # a repeat sends nothing
    resend = await visitor.http.post(f"{PUBLIC}/track/verification-email", json={"token": token})
    assert resend.status_code in (200, 409), resend.text  # nothing to resend once confirmed
    await run_worker_once(jobs, runtime)
    mails = await inbox.wait_for(sam, count=2)
    await run_worker_once(jobs, runtime)
    assert sorted(m["Subject"] for m in await inbox.to(sam)) == sorted(
        [
            f"Confirm your idea for {PROJECT_NAME}",
            f"Your link to follow your idea for {PROJECT_NAME}",
        ]
    )
    [link_summary] = [m for m in mails if m["Subject"].startswith("Your link")]
    link_email = await inbox.message(link_summary["ID"])
    link_text = " ".join(visible_text(link_email["HTML"]).split())
    assert "Your link to follow your idea" in link_text
    assert f"the idea you sent to {PROJECT_NAME}, “{title}”" in link_text or (
        f'the idea you sent to {PROJECT_NAME}, "{title}"' in link_text
    )
    assert "See where your idea stands" in link_text
    assert (
        "Keep this link private: anyone who has it can see where your idea stands, reply to "
        "the team and delete your details." in link_text
    )
    assert "Stop emails about this idea" in link_text
    hrefs = links(link_email)
    assert hrefs.count(tracking_url) >= 2  # the button and the footer's stop link
    assert tracking_url in link_email["Text"]
    link_headers = await inbox.headers(link_summary["ID"])
    assert "Reply-To" not in link_headers  # review S1
    assert "List-Unsubscribe" not in link_headers
    assert link_headers["To"] == [sam]
    assert_names_nobody("link email", link_email, alice, olive, pat)

    # --- 3. Held: an admin asks before approving; the submitter answers ------------------
    [queued] = (await alice.get(f"/projects/{slug}/moderation"))["items"]
    key = queued["key"]
    assert queued["submission"]["permissions"]["can_message"] is True
    assert queued["submission"]["messages"]["count"] == 0
    asked = await send_message(alice, key, f"Before we approve it: which stores? {MARK} one.")
    assert (asked["direction"], asked["emailed"]) == ("team", True)
    assert asked["author"]["id"] == alice.user["id"]
    tracked = await visitor.track()
    assert [m["direction"] for m in tracked["messages"]] == ["team"]
    assert (tracked["can_reply"], tracked["reply_blocked"]) == (True, None)
    assert tracked["team_messages_emailed"] is True
    ok(await visitor.reply(f"The two in the city centre. {MARK} two."), 201)
    # Held ideas are in nobody's inbox: no notification while held (contract section 6).
    assert await inbox_items(alice, "submitter_replied") == []
    [queued] = (await alice.get(f"/projects/{slug}/moderation"))["items"]
    assert queued["submission"]["messages"]["last_direction"] == "submitter"
    ok(await alice.http.post(f"{API}/ideas/{key}/submission/approve"))

    # --- 4. Owned; a guest researcher; the owner writes ----------------------------------
    await alice.send("PUT", f"/ideas/{key}/owner", {"user_id": olive.user["id"]})
    await alice.send(
        "PUT",
        f"/ideas/{key}/research/assignment",
        {"researcher_id": gus.user["id"], "due_at": None},
    )
    detail = await olive.get(f"/ideas/{key}")
    idea_id = detail["id"]
    last_activity = detail["last_activity_at"]
    feed_before = [item["type"] for item in (await olive.get(f"/ideas/{key}/activity"))["items"]]
    panel = await olive.get(f"/ideas/{key}/submission")
    assert panel["permissions"]["can_message"] is True
    assert panel["messages"]["delivery"] == "email"
    assert panel["messages"]["blocked"] is None
    body = (
        f'<script>alert("x")</script> **Thanks**, see [our site](https://evil.example/x).\n'
        f"Could you send a photo of the boxes? {MARK} three."
    )
    sent = await send_message(olive, key, body)
    assert (sent["body"], sent["emailed"]) == (body, True)
    newest, *_ = await messages(olive, key)
    assert newest["id"] == sent["id"]  # newest first

    await run_worker_once(jobs, runtime)
    mails = await inbox.wait_for(sam, count=4)
    to_sam = [m for m in mails if m["Subject"] == f"A message about your idea for {PROJECT_NAME}"]
    assert len(to_sam) == 2  # Alice's question and Olive's message
    for summary in to_sam:
        email_ = await inbox.message(summary["ID"])
        assert_names_nobody("message email", email_, olive, alice, pat)
        headers = await inbox.headers(summary["ID"])
        assert "Reply-To" not in headers  # review S1
        assert "List-Unsubscribe" not in headers
    [olive_mail] = [
        m
        for m in [await inbox.message(s["ID"]) for s in to_sam]
        if "photo of the boxes" in m["Text"]
    ]
    html, plain = olive_mail["HTML"], olive_mail["Text"]
    shown = " ".join(visible_text(html).split())
    assert "<script" not in html.lower()
    assert "&lt;script&gt;" in html
    assert "https://evil.example/x" not in links(olive_mail)
    assert "<strong>Thanks</strong>" not in html  # never Markdown
    assert "**Thanks**" in shown
    assert re.search(r"evil\.example/x\)\.<br>\s*Could you send", html), "line break kept"
    for line in body.split("\n"):
        assert line in plain  # the text part as typed
    assert f"A message from the {PROJECT_NAME} team" in shown
    assert f"About your idea “{title}”" in shown or f'About your idea "{title}"' in shown
    assert f"The {PROJECT_NAME} team" in shown.split("Could you send", 1)[1]
    assert "Replies to this email aren't read: reply on your tracking page." in shown
    assert "Stop emails about this idea" in shown
    assert (
        "To stop all email about this idea, remove your email address on your tracking page."
        in " ".join(plain.split())
    )
    assert links(olive_mail).count(tracking_url) >= 2  # Reply and the stop link
    assert tracking_url in plain

    # --- 5. The tracking page; the submitter replies -------------------------------------
    tracked = await visitor.track()
    assert [m["direction"] for m in tracked["messages"]] == ["team", "submitter", "team"]
    assert tracked["messages"][2]["body"] == body
    assert all(set(m) == {"id", "direction", "body", "created_at"} for m in tracked["messages"])
    exposed = json.dumps(tracked)
    for person in (olive, alice):
        assert person.user["display_name"] not in exposed
        assert person.user["id"] not in exposed
    assert (tracked["can_reply"], tracked["can_remove_email"]) == (True, True)
    reply = f"Here is a photo link: https://example.org/boxes {MARK} four."
    page = ok(await visitor.reply(reply), 201)
    assert page["messages"][-1] == {**page["messages"][-1], "direction": "submitter", "body": reply}

    # The owner and the admin who wrote are told, without the reply's text.
    for person in (olive, alice):
        [item] = await inbox_items(person, "submitter_replied")
        assert (item["idea"]["key"], item["actor"]) == (key, None)
        assert MARK not in json.dumps(item)
    await run_worker_once(jobs, runtime)
    for person in (olive, alice):
        [summary] = [
            m
            for m in await inbox.wait_for(person.user["email"])
            if "The submitter replied" in m["Subject"]
        ]
        assert summary["Subject"] == f'[{key}] The submitter replied about "{title}"'
        email_ = await inbox.message(summary["ID"])
        shown = " ".join(visible_text(email_["HTML"]).split())
        assert f"The person who sent {key} through the public form replied to the team." in shown
        assert "Read the reply" in shown
        assert f"{BASE}/ideas/{key}?submission=1" in links(email_)
        for part in (shown, email_["Text"], email_["Subject"]):
            assert MARK not in part
            assert "photo" not in part
            assert sam not in part
            assert "Sam Public" not in part

    # A second reply within the hour: the inbox only (one email per recipient and idea an
    # hour).
    ok(await visitor.reply(f"And the deposit could be two pounds. {MARK} five."), 201)
    await run_worker_once(jobs, runtime)
    for person in (olive, alice):
        assert len(await inbox_items(person, "submitter_replied")) == 2
        assert (
            len(await staff_emails(db_session, person.user["id"], EmailType.SUBMITTER_REPLIED)) == 1
        )
        mailed = [
            m
            for m in await inbox.to(person.user["email"])
            if "The submitter replied" in m["Subject"]
        ]
        assert len(mailed) == 1

    # --- 6. Nobody else sees any of it ----------------------------------------------------
    for label, person in (("member", mia), ("viewer", vic)):
        seen = await person.get(f"/ideas/{key}/submission")
        assert (seen["messages"], seen["permissions"]["can_message"]) == (None, False), label
        problem(await person.http.get(f"{API}/ideas/{key}/submission/messages"), 403, "forbidden")
        problem(await post_message(person, key, "Hello?"), 403, "forbidden")
        assert await inbox_items(person, "submitter_replied") == [], label
    # The guest researcher reaches the idea, never its submission or the conversation.
    assert (await gus.get(f"/ideas/{key}"))["key"] == key
    problem(await gus.http.get(f"{API}/ideas/{key}/submission"), 404, "not_found")
    problem(await gus.http.get(f"{API}/ideas/{key}/submission/messages"), 404, "not_found")
    problem(await post_message(gus, key, "Hello?"), 404, "not_found")
    assert await inbox_items(gus, "submitter_replied") == []
    for person in (olive, alice, pat, mia, vic, gus):
        assert MARK not in json.dumps(await person.get(f"/ideas/{key}"))
        assert (await person.get("/search", q=MARK))["ideas"] == []
        assert MARK not in json.dumps(await person.get("/me/work"))
        assert MARK not in json.dumps(await person.get("/me/notifications", limit=100))
    feed = await olive.get(f"/ideas/{key}/activity")
    assert [item["type"] for item in feed["items"]] == feed_before  # no event for messages
    assert MARK not in json.dumps(feed)
    assert (await olive.get(f"/ideas/{key}"))["last_activity_at"] == last_activity
    # A person's API key, of every scope: the routes are session only, the panel says
    # nothing, MCP carries nothing.
    for scopes in (
        ["read"],
        ["write"],
        ["evaluate"],
        ["mcp"],
        ["read", "write", "evaluate", "mcp"],
    ):
        created = await alice.send(
            "POST", "/me/api-keys", {"name": f"Key {'+'.join(scopes)}", "scopes": scopes}, 201
        )
        secret = created["secret"]
        auth = {"Authorization": f"Bearer {secret}"}
        rest = story.browser()
        listed = await rest.get(f"{API}/ideas/{key}/submission/messages", headers=auth)
        problem(listed, 403, "insufficient_scope")
        written = await rest.post(
            f"{API}/ideas/{key}/submission/messages", json={"body": "Hi"}, headers=auth
        )
        problem(written, 403, "insufficient_scope")
        seen = await rest.get(f"{API}/ideas/{key}/submission", headers=auth)
        if seen.status_code == 200:
            assert (seen.json()["messages"], seen.json()["permissions"]["can_message"]) == (
                None,
                False,
            ), scopes
        if "mcp" in scopes:
            async with connect(secret) as session:
                for tool, arguments in (
                    ("get_idea", {"idea": key}),
                    ("search_ideas", {"query": MARK}),
                    ("search_ideas", {"query": key}),
                ):
                    result = await call(session, tool, **arguments)
                    if scopes == ["mcp"]:  # mcp alone doesn't include read
                        assert result.is_error, result.content
                        assert result.structured_content["code"] == "insufficient_scope"
                    else:
                        assert not result.is_error, result.content
                    assert MARK not in json.dumps(result.structured_content), (tool, scopes)
                tools = [tool.name for tool in (await session.list_tools()).tools]
                assert not [name for name in tools if "message" in name or "submitter" in name]
        await alice.send("DELETE", f"/me/api-keys/{created['key']['id']}", status=204)
    # An AI agent's key, in its own open run on the idea: REST refused, MCP says nothing.
    project = await db_session.scalar(select(Project).where(Project.slug == slug))
    idea_row = await db_session.get(Idea, uuid.UUID(idea_id))
    assert project is not None
    assert idea_row is not None
    agent = await make_agent(
        db_session, [project], purposes=[AiRunKind.RESEARCH], key=True, display_name="Scout"
    )
    run = await open_run(db_session, agent, idea_row, AiRunKind.RESEARCH)
    assert agent.key is not None
    agent_rest = await story.browser().get(
        f"{API}/ideas/{key}/submission/messages",
        headers={"Authorization": f"Bearer {agent.key}"},
    )
    assert agent_rest.status_code == 403, agent_rest.text
    async with connect(agent.key) as session:
        for tool, arguments in (("get_idea", {"idea": key}), ("search_ideas", {"query": MARK})):
            result = await call(session, tool, run_id=str(run.id), **arguments)
            assert not result.is_error, result.content
            assert MARK not in json.dumps(result.structured_content), tool

    # --- 7. The audit: one entry per team message, never the text -------------------------
    audit = await pat.get("/admin/audit", action="submission.message")
    entries = [item for item in audit["items"] if item["target_id"] == idea_id]
    assert sorted(item["actor_id"] for item in entries) == sorted(
        [alice.user["id"], olive.user["id"]]
    )
    serialised = json.dumps(entries)
    for secret_ in (MARK, "photo", "stores", sam, "Sam Public", token):
        assert secret_ not in serialised, secret_

    # Nothing personal or secret reached the logs: no token, address, name or message.
    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "request" in logged  # the capture worked
    for secret_ in (token, fragment(verify_link, f"/{slug}/verify"), sam, "Sam Public", MARK):
        assert secret_ not in logged, secret_


# --- AC11-API-2 -------------------------------------------------------------------------
async def test_ac11_api_2_an_unconfirmed_address_and_the_limits(
    story: Story,  # noqa: F811 - the fixture
    db_session: AsyncSession,
    jobs: App,  # noqa: F811 - the fixture
    runtime: Runtime,  # noqa: F811 - the fixture
    inbox: MailpitInbox,  # noqa: F811 - the fixture
) -> None:
    pat, crew = await people(story, db_session, "Alice Anders", "Olive Owner")
    alice, olive = crew["alice"], crew["olive"]
    slug = await project_with_form(pat, alice, {olive.user["id"]: "member"}, moderated=False)
    run = uuid.uuid4().hex[:6]

    # --- An unconfirmed address: the tracking page only ----------------------------------
    sam = f"sam.{run}@example.org"
    visitor = Visitor(story.browser(), slug)
    await visitor.submit("Deposit boxes", sam)
    key = await key_of(alice, slug, "Deposit boxes")
    await alice.send("PUT", f"/ideas/{key}/owner", {"user_id": olive.user["id"]})
    panel = await olive.get(f"/ideas/{key}/submission")
    assert panel["messages"]["delivery"] == "tracking_page"
    first = await send_message(olive, key, "Thanks! Which stores?")
    assert first["emailed"] is False
    tracked = await visitor.track()
    assert (tracked["team_messages_emailed"], tracked["can_reply"]) == (False, True)
    await run_worker_once(jobs, runtime)
    await inbox.wait_for(sam)
    await run_worker_once(jobs, runtime)
    assert [m["Subject"] for m in await inbox.to(sam)] == [f"Confirm your idea for {PROJECT_NAME}"]
    idea_id = (await olive.get(f"/ideas/{key}"))["id"]
    assert await outbox(db_session, idea_id, {"submission_message"}) == []

    # --- 10 replies since the team's latest message, then awaiting_team -------------------
    for n in range(10):
        ok(await visitor.reply(f"Reply {n + 1}."), 201)
    problem(await visitor.reply("Reply 11."), 409, "awaiting_team")
    tracked = await visitor.track()
    assert (tracked["can_reply"], tracked["reply_blocked"]) == (False, "awaiting_team")
    # The team writes back: the submitter may answer again, but not past 10 a day.
    await send_message(olive, key, "Thanks for all of that.")
    refused = await visitor.reply("Reply 11, again.")
    problem(refused, 429, "too_many_attempts")
    assert retry_after(refused) <= 24 * 3600
    tracked = await visitor.track()
    assert (tracked["can_reply"], tracked["reply_blocked"]) == (False, "daily_limit")

    # --- 30 team messages a person an hour (across ideas) ---------------------------------
    other = Visitor(story.browser(), slug)
    await other.submit("Refill station", None)
    other_key = await key_of(alice, slug, "Refill station")
    other_id = (await alice.get(f"/ideas/{other_key}"))["id"]
    await write_messages(db_session, other_id, 15, author_id=alice.user["id"])
    third = Visitor(story.browser(), slug)
    await third.submit("Cargo bikes", None)
    third_key = await key_of(alice, slug, "Cargo bikes")
    third_id = (await alice.get(f"/ideas/{third_key}"))["id"]
    await write_messages(db_session, third_id, 15, author_id=alice.user["id"])
    busy = await post_message(alice, key, "One more from me.")
    problem(busy, 429, "too_many_attempts")
    assert retry_after(busy) <= 3600
    # Olive isn't limited by Alice's messages.
    await send_message(olive, key, "Message 3.")

    # --- 20 team messages a submission a day ----------------------------------------------
    for n in range(4, 21):
        await send_message(olive, key, f"Message {n}.")
    full_day = await post_message(olive, key, "Message 21.")
    problem(full_day, 429, "too_many_attempts")
    assert retry_after(full_day) <= 24 * 3600
    panel = await olive.get(f"/ideas/{key}/submission")
    assert panel["messages"]["count"] == 30  # 20 team messages and 10 replies
    assert panel["messages"]["blocked"] == "daily_limit"
    assert panel["permissions"]["can_message"] is False
    assert await outbox(db_session, idea_id, {"submission_message"}) == []

    # Another submission's tracking page carries only its own conversation.
    for page in ((await other.track())["messages"], (await third.track())["messages"]):
        assert len(page) == 15
        assert not [m for m in page if "Which stores" in m["body"] or "Reply" in m["body"]]

    # --- 100 messages a conversation, both ways --------------------------------------------
    fourth = Visitor(story.browser(), slug)
    await fourth.submit("Shared lockers", None)
    fourth_key = await key_of(alice, slug, "Shared lockers")
    fourth_id = (await alice.get(f"/ideas/{fourth_key}"))["id"]
    await alice.send("PUT", f"/ideas/{fourth_key}/owner", {"user_id": olive.user["id"]})
    # Two days old, so only the cap applies.
    await write_messages(
        db_session, fourth_id, 99, author_id=olive.user["id"], age=timedelta(days=2)
    )
    await send_message(olive, fourth_key, "The hundredth.")
    problem(await post_message(olive, fourth_key, "The 101st."), 409, "conversation_full")
    problem(await fourth.reply("Can I still answer?"), 409, "conversation_full")
    tracked = await fourth.track()
    assert len(tracked["messages"]) == 100  # the tracking page shows them all
    assert (tracked["can_reply"], tracked["reply_blocked"]) == (False, "conversation_full")
    assert (await alice.get(f"/ideas/{fourth_key}/submission"))["messages"]["blocked"] == (
        "conversation_full"
    )


# --- AC11-API-3 -------------------------------------------------------------------------
async def test_ac11_api_3_erasure_and_retention(
    story: Story,  # noqa: F811 - the fixture
    db_session: AsyncSession,
    jobs: App,  # noqa: F811 - the fixture
    runtime: Runtime,  # noqa: F811 - the fixture
    inbox: MailpitInbox,  # noqa: F811 - the fixture
) -> None:
    pat, crew = await people(story, db_session, "Alice Anders", "Olive Owner")
    alice, olive = crew["alice"], crew["olive"]
    slug = await project_with_form(pat, alice, {olive.user["id"]: "member"}, moderated=False)
    run = uuid.uuid4().hex[:6]

    async def submitted(title: str, email: str | None) -> tuple[Visitor, str, str]:
        visitor = Visitor(story.browser(), slug)
        await visitor.submit(title, email)
        key = await key_of(alice, slug, title)
        await alice.send("PUT", f"/ideas/{key}/owner", {"user_id": olive.user["id"]})
        return visitor, key, (await alice.get(f"/ideas/{key}"))["id"]

    # --- "Delete my details": the conversation and every submitter email go ---------------
    erin = f"erin.{run}@example.org"
    visitor, key, idea_id = await submitted("Bottle returns", erin)
    await run_worker_once(jobs, runtime)
    ok(await visitor.confirm(await verify_link_in(inbox, erin)))
    await send_message(olive, key, "Thanks! A question for you.")
    await run_worker_once(jobs, runtime)
    await inbox.wait_for(erin, count=3)  # confirmation, link, message: sent
    ok(await visitor.reply("Happy to help."), 201)  # queues Olive's "The submitter replied"
    await send_message(olive, key, "And one more question.")  # queued, not sent yet
    kinds = {str(row.type) for row in await outbox(db_session, idea_id, SUBMITTER_TYPES)}
    assert kinds == {"submission_received", "submission_link", "submission_message"}
    [replied] = await staff_emails(db_session, olive.user["id"], EmailType.SUBMITTER_REPLIED)
    assert replied.status is EmailStatus.QUEUED

    ok(await visitor.erase(), 204)
    assert await stored_messages(db_session, idea_id) == 0
    assert await outbox(db_session, idea_id, SUBMITTER_TYPES) == []
    leftovers = await db_session.scalar(
        text("SELECT count(*) FROM outbound_email WHERE lower(to_address) = :a"), {"a": erin}
    )
    assert leftovers == 0
    problem(await visitor.page(), 404, "not_found")
    panel = await olive.get(f"/ideas/{key}/submission")
    assert panel["messages"]["blocked"] == "submitter_erased"
    assert panel["messages"]["count"] == 0
    assert panel["permissions"]["can_message"] is False
    problem(await post_message(olive, key, "Hello?"), 409, "submitter_erased")
    assert await messages(olive, key) == []
    # The team's notification stays (it holds no text); its email no longer applies.
    assert len(await inbox_items(olive, "submitter_replied")) == 1
    await run_worker_once(jobs, runtime)
    [replied] = await staff_emails(db_session, olive.user["id"], EmailType.SUBMITTER_REPLIED)
    assert replied.status is EmailStatus.CANCELLED
    assert not [
        m for m in await inbox.to(olive.user["email"]) if "The submitter replied" in m["Subject"]
    ]
    assert len(await inbox.to(erin)) == 3  # nothing more reached the erased address

    # --- A link email queued, then erased: never sent --------------------------------------
    finn = f"finn.{run}@example.org"
    visitor, key, idea_id = await submitted("Tote bag library", finn)
    await run_worker_once(jobs, runtime)
    assert ok(await visitor.confirm(await verify_link_in(inbox, finn)))["tracking_link_emailed"]
    assert [str(r.type) for r in await outbox(db_session, idea_id, {"submission_link"})] == [
        "submission_link"
    ]
    ok(await visitor.erase(), 204)
    assert await outbox(db_session, idea_id, SUBMITTER_TYPES) == []
    await run_worker_once(jobs, runtime)
    assert [m["Subject"] for m in await inbox.to(finn)] == [f"Confirm your idea for {PROJECT_NAME}"]

    # --- "Remove my email address": no more email; the link and the conversation stay -----
    gina = f"gina.{run}@example.org"
    visitor, key, idea_id = await submitted("Repair cafe", gina)
    await run_worker_once(jobs, runtime)
    ok(await visitor.confirm(await verify_link_in(inbox, gina)))
    assert (await send_message(olive, key, "When does it open?"))["emailed"] is True
    page = ok(await visitor.forget_email())
    assert (page["email_hint"], page["can_remove_email"], page["team_messages_emailed"]) == (
        None,
        False,
        False,
    )
    assert len(page["messages"]) == 1
    assert await outbox(db_session, idea_id, SUBMITTER_TYPES) == []
    assert (await olive.get(f"/ideas/{key}/submission"))["messages"]["delivery"] == "tracking_page"
    assert (await send_message(olive, key, "Still there?"))["emailed"] is False
    ok(await visitor.reply("Yes, I'm here."), 201)
    await run_worker_once(jobs, runtime)
    received = [m["Subject"] for m in await inbox.to(gina)]
    assert f"A message about your idea for {PROJECT_NAME}" not in received  # never sent

    # --- Retention rule 3: an unconfirmed address forgotten, the conversation kept --------
    hal = f"hal.{run}@example.org"
    visitor, key, idea_id = await submitted("Water fountains", hal)
    await send_message(olive, key, "Thanks, Hal!")
    await retention.cleanup(db_session, utcnow() + timedelta(days=4))
    await db_session.commit()
    row = await db_session.scalar(
        select(PublicSubmission)
        .where(PublicSubmission.idea_id == uuid.UUID(idea_id))
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert (row.email, row.erased_at) == (None, None)
    assert await stored_messages(db_session, idea_id) == 1
    assert len((await visitor.track())["messages"]) == 1
    assert (await olive.get(f"/ideas/{key}/submission"))["messages"]["delivery"] == "tracking_page"

    # --- Retention rule 4: a live conversation waits; a quiet one is erased ---------------
    visitor, key, idea_id = await submitted("Old idea", None)
    await olive.send("POST", f"/ideas/{key}/status", {"status": "closed", "resolution": "parked"})
    await send_message(olive, key, "Any news?")
    ok(await visitor.reply("Not yet."), 201)
    await db_session.execute(
        update(Idea)
        .where(Idea.id == uuid.UUID(idea_id))
        .values(last_activity_at=utcnow() - timedelta(days=200))
    )
    await db_session.commit()
    await retention.cleanup(db_session, utcnow())
    await db_session.commit()
    assert await stored_messages(db_session, idea_id) == 2
    assert len((await visitor.track())["messages"]) == 2  # still there, link works
    await retention.cleanup(db_session, utcnow() + timedelta(days=181))
    await db_session.commit()
    assert await stored_messages(db_session, idea_id) == 0
    problem(await visitor.page(), 404, "not_found")
    assert (await olive.get(f"/ideas/{key}/submission"))["messages"]["blocked"] == (
        "submitter_erased"
    )
    erased = await pat.get("/admin/audit", action="submission.erase")
    assert any(item["target_id"] == idea_id for item in erased["items"])
    # The team's notification holds no text and stays.
    assert [item["idea"]["key"] for item in await inbox_items(olive, "submitter_replied")].count(
        key
    ) == 1
