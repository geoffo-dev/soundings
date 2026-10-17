"""Phase 11's "The submitter replied" (``submitter_replied``; contract-phase11 section 6):
the recipients (the idea's owner and everyone who wrote, each holding
``public.message_submitter`` when it is written and again when it is shown or sent), the
hourly coalescing of immediate emails, the digest, unsubscribe scoping, the inbox's SQL form,
and that the reply's text never reaches a notification, its email or the digest."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import (
    EmailStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
)
from app.models.idea import Idea
from app.models.notification import Notification, NotificationPreference, OutboundEmail
from app.models.project import Project, ProjectMember
from app.models.public import SubmissionMessage
from app.models.user import User
from app.notifications.schedule import build_digests
from tests.notifications.conftest import (
    API,
    AsUser,
    Outbox,
    RecordingTransport,
    Team,
    ok,
    only,
)
from tests.public.conftest import make_public_idea, messages_url

REPLIED = NotificationType.SUBMITTER_REPLIED
SECRET_REPLY = "Call me on 07700 900123 or visit evil.example/login"


@pytest.fixture
async def public(db_session: AsyncSession, settings: Settings, team: Team) -> tuple[str, Idea]:
    """A public idea owned by ``team.owner`` with a confirmed address (the form is on)."""
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(public_submission_enabled=True)
    )
    await db_session.commit()
    return await make_public_idea(
        db_session,
        settings,
        team,
        email="sam@example.org",
        verified=True,
        owner=team.owner,
        title="Reusable delivery boxes",
    )


async def write(api: AsUser, user: User, idea: Idea, body: str = "Which stores?") -> None:
    ok(await (await api(user)).post(messages_url(idea), {"body": body}), 201)


async def reply(client: httpx.AsyncClient, token: str, body: str = SECRET_REPLY) -> None:
    response = await client.post(
        f"{API}/public/track/messages", json={"token": token, "body": body}
    )
    assert response.status_code == 201, response.text


async def replied(outbox: Outbox, user: User | None = None) -> list[Notification]:
    return await outbox.notifications(user.id if user else None, REPLIED)


async def send_all(outbox: Outbox, runtime: Runtime) -> None:
    for email in await outbox.emails():
        if email.status is EmailStatus.QUEUED:
            await delivery.send_email(runtime, email.id)


def bodies(message: Any) -> tuple[str, str, str]:
    html = message.get_body(("html",))
    text = message.get_body(("plain",))
    assert html is not None
    assert text is not None
    return str(message["Subject"]), str(html.get_content()), str(text.get_content())


# --- Recipients -------------------------------------------------------------------------------
async def test_the_owner_and_everyone_who_wrote_are_told(
    api: AsUser,
    client: httpx.AsyncClient,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    token, idea = public
    await write(api, team.admin, idea)
    await write(api, team.platform, idea)
    await write(api, team.owner, idea)  # the owner wrote too: told once
    await write(api, team.admin, idea)

    await reply(client, token)

    notes = await replied(outbox)
    assert {note.user_id for note in notes} == {team.owner.id, team.admin.id, team.platform.id}
    message_id = str(
        (
            await outbox.db.scalars(
                select(SubmissionMessage.id).where(SubmissionMessage.direction == "submitter")
            )
        ).one()
    )
    for note in notes:
        assert note.payload == {"message_id": message_id}  # never the text
        assert note.actor_id is None
        assert note.dedupe_key == f"submitter_replied:{message_id}"
        assert note.email_mode is NotificationMode.IMMEDIATE
    transport.sent.clear()
    await send_all(outbox, runtime)
    assert {str(m["To"]) for m in transport.messages} >= {team.owner.email, team.admin.email}
    key = f"CUST-{idea.number}"
    for message in transport.messages:
        if str(message["To"]) == "sam@example.org":
            continue  # the team's own messages to the submitter
        subject, html, text = bodies(message)
        # Security review L1: no title (a public idea's title is the submitter's words).
        assert subject == f"[{key}] The submitter replied"
        assert f"The person who sent {key} through the public form replied to the team." in text
        assert f"Read the reply: http://testserver/ideas/{key}?submission=1" in text
        # UX review p3: the reason that applies.
        if str(message["To"]) == team.owner.email:
            assert f"You're the owner of {key}." in text
        else:
            assert f"You wrote to the person who sent {key}." in text
        assert "Unsubscribe from replies from public submitters" in text
        for secret in ("07700", "evil.example", "sam@example.org", "Reusable delivery boxes"):
            assert secret not in subject + html + text


async def test_people_who_cannot_hold_the_rule_are_not_told(
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    """A writer who left the project, a demoted owner and a deactivated writer get nothing;
    members never wrote (and aren't told)."""
    token, idea = public
    await write(api, team.admin, idea)
    await write(api, team.platform, idea)
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.user_id == team.admin.id, ProjectMember.project_id == team.project.id
        )
    )
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id, ProjectMember.project_id == team.project.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.execute(
        update(User).where(User.id == team.platform.id).values(is_active=False)
    )
    await db_session.commit()

    await reply(client, token)

    assert await replied(outbox) == []


async def test_no_notification_while_held_for_moderation(
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    team: Team,
    outbox: Outbox,
) -> None:
    from app.models.enums import HoldReason

    token, idea = await make_public_idea(
        db_session, settings, team, email="sam@example.org", held_for=HoldReason.MODERATION
    )
    await write(api, team.admin, idea)

    await reply(client, token)

    assert await replied(outbox) == []


# --- One unread item per recipient and idea (UX review M2), one email an hour ------------------
async def test_replies_bring_the_unread_item_up_to_date(
    api: AsUser,
    client: httpx.AsyncClient,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    """A burst of replies is one unread inbox item (the latest reply's time and id), not one
    each, and one email: public input can't fill the team's inboxes."""
    token, idea = public
    await write(api, team.admin, idea)

    await reply(client, token, "First")
    first = only(await replied(outbox, team.owner))
    first_id, first_at, first_email = first.id, first.created_at, first.email_id
    for body in ("Second", "Third"):
        await reply(client, token, body)

    note = only(await replied(outbox, team.owner))
    latest = (
        await outbox.db.scalars(
            select(SubmissionMessage)
            .where(SubmissionMessage.direction == "submitter")
            .order_by(SubmissionMessage.created_at.desc())
        )
    ).first()
    assert latest is not None
    assert note.id == first_id
    assert note.created_at > first_at
    assert note.payload == {"message_id": str(latest.id)}
    assert note.dedupe_key == f"submitter_replied:{latest.id}"
    assert note.email_mode is NotificationMode.IMMEDIATE
    assert note.email_id == first_email  # still the one email
    assert len(await outbox.emails(team.owner.id)) == 1
    owner = await api(team.owner)
    assert [i["type"] for i in ok(await owner.get("/me/notifications"))["items"]] == [
        "submitter_replied"
    ]
    assert ok(await owner.get("/me/notifications/summary"))["unread_count"] == 1


async def test_once_read_a_reply_within_the_hour_reaches_the_inbox_only(
    api: AsUser,
    client: httpx.AsyncClient,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    token, idea = public
    await write(api, team.admin, idea)
    await reply(client, token, "First")
    first = only(await replied(outbox, team.owner))
    owner = await api(team.owner)
    assert (await owner.post(f"/me/notifications/{first.id}/read")).status_code == 204

    await reply(client, token, "Second")

    read, unread = await replied(outbox, team.owner)
    assert read.id == first.id
    assert unread.read_at is None
    assert unread.email_mode is NotificationMode.OFF  # emailed less than an hour ago
    assert unread.email_id is None


async def test_an_hour_after_the_last_email_the_next_reply_is_emailed_again(
    api: AsUser,
    client: httpx.AsyncClient,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    """Counted from the email (its outbox row), not from the item, which every reply
    brings up to date."""
    token, idea = public
    await write(api, team.admin, idea)
    await reply(client, token, "First")
    first_email = only(await replied(outbox, team.owner)).email_id
    await reply(client, token, "Second")  # brings it up to date, no second email
    assert first_email is not None
    assert only(await replied(outbox, team.owner)).email_id == first_email
    await outbox.set(OutboundEmail, first_email, created_at=utcnow() - timedelta(minutes=61))

    await reply(client, token, "Third")

    note = only(await replied(outbox, team.owner))
    assert note.email_mode is NotificationMode.IMMEDIATE
    assert note.email_id is not None
    assert note.email_id != first_email
    assert len(await outbox.emails(team.owner.id)) == 2


async def test_coalescing_is_per_idea(
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    token, idea = public
    other_token, other = await make_public_idea(
        db_session, settings, team, email="kim@example.org", verified=True, owner=team.owner
    )
    await write(api, team.admin, idea)
    await write(api, team.admin, other)

    await reply(client, token)
    await reply(client, other_token)

    modes = [note.email_mode for note in await replied(outbox, team.owner)]
    assert modes == [NotificationMode.IMMEDIATE, NotificationMode.IMMEDIATE]


async def test_digest_recipients_get_one_line_per_unread_item(
    app: FastAPI,
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    """Two replies before the digest: one line. A reply after the digest went out puts the
    (still unread) item in the next one."""
    token, idea = public
    db_session.add(
        NotificationPreference(user_id=team.owner.id, type=REPLIED, mode=NotificationMode.DIGEST)
    )
    await db_session.commit()
    await write(api, team.admin, idea)
    await reply(client, token, "First")
    await reply(client, token, "Second")
    note = only(await replied(outbox, team.owner))
    assert (note.email_mode, note.email_id) == (NotificationMode.DIGEST, None)

    any_hour = settings.model_copy(update={"digest_hour": 0})
    assert await build_digests(app.state.sessionmaker, any_hour, utcnow()) >= 1
    transport.sent.clear()
    await send_all(outbox, runtime)

    digest = only([m for m in transport.messages if str(m["To"]) == team.owner.email])
    subject, html, text = bodies(digest)
    assert subject.startswith("Soundings digest: 1 update")
    assert text.count("The submitter replied") == 1
    for secret in ("First", "Second", "07700"):
        assert secret not in html + text

    await reply(client, token, "Third")
    again = only(await replied(outbox, team.owner))
    assert (again.email_mode, again.email_id) == (NotificationMode.DIGEST, None)


async def test_the_unsubscribe_link_turns_off_this_type_only(
    api: AsUser,
    client: httpx.AsyncClient,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    token, idea = public
    owner = await api(team.owner)
    before = {
        row["type"]: row["mode"]
        for row in ok(await owner.get("/me/notification-preferences"))["items"]
    }
    await write(api, team.admin, idea)
    await reply(client, token)
    transport.sent.clear()
    await send_all(outbox, runtime)
    message = only([m for m in transport.messages if str(m["To"]) == team.owner.email])

    url = str(message["List-Unsubscribe"]).strip("<>")
    unsubscribe = parse_qs(urlparse(url).query)["token"][0]
    ok(await client.post(f"{API}/unsubscribe", params={"token": unsubscribe}))

    modes = {
        row["type"]: row["mode"]
        for row in ok(await owner.get("/me/notification-preferences"))["items"]
    }
    assert modes == {**before, "submitter_replied": "off"}


# --- Send time, the inbox ----------------------------------------------------------------------
async def test_a_queued_email_is_cancelled_once_the_reply_is_gone(
    api: AsUser,
    client: httpx.AsyncClient,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
    runtime: Runtime,
) -> None:
    """An erasure deletes the conversation: the notification stays (no text), its email
    no longer applies."""
    token, idea = public
    await write(api, team.admin, idea)
    await reply(client, token)
    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/erase"))

    note = only(await replied(outbox, team.owner))
    assert note.email_id is not None
    assert await delivery.send_email(runtime, note.email_id) == "cancelled"
    inbox = ok(await (await api(team.owner)).get("/me/notifications"))
    assert [item["type"] for item in inbox["items"]] == ["submitter_replied"]


async def test_the_inbox_shows_the_item_only_while_the_rule_is_held(
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    """The SQL form (review S4): a writer who left the private project, or an owner demoted
    to viewer, sees no item and an unread count of 0."""
    token, idea = public
    await write(api, team.admin, idea)
    await reply(client, token)
    for user in (team.owner, team.admin):
        page = ok(await (await api(user)).get("/me/notifications"))
        item = only(page["items"])
        assert item["type"] == "submitter_replied"
        assert item["actor"] is None
        assert set(item) == {"id", "type", "created_at", "read_at", "idea", "actor"}
        assert SECRET_REPLY not in str(page)
        summary = ok(await (await api(user)).get("/me/notifications/summary"))
        assert summary["unread_count"] == 1

    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.user_id == team.admin.id, ProjectMember.project_id == team.project.id
        )
    )
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id, ProjectMember.project_id == team.project.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    for user in (team.owner, team.admin):
        assert ok(await (await api(user)).get("/me/notifications"))["items"] == []
        assert ok(await (await api(user)).get("/me/notifications/summary"))["unread_count"] == 0


async def test_a_member_never_sees_one(
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
) -> None:
    """Even a notification row written for a member (as if by an older release) is hidden."""
    token, idea = public
    await write(api, team.admin, idea)
    await reply(client, token)
    note = only(await replied(outbox, team.admin))
    db_session.add(
        Notification(
            user_id=team.member.id,
            type=REPLIED,
            idea_id=idea.id,
            payload=note.payload,
            dedupe_key=note.dedupe_key,
            email_mode=NotificationMode.OFF,
        )
    )
    await db_session.commit()

    member = await api(team.member)
    assert ok(await member.get("/me/notifications"))["items"] == []
    assert ok(await member.get("/me/notifications/summary"))["unread_count"] == 0


async def test_losing_the_rule_before_the_send_cancels_the_email(
    api: AsUser,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    team: Team,
    public: tuple[str, Idea],
    outbox: Outbox,
    runtime: Runtime,
) -> None:
    """Checked again at send time: an owner demoted to viewer after the reply came in gets
    no email."""
    token, idea = public
    await write(api, team.admin, idea)
    await reply(client, token)
    note = only(await replied(outbox, team.owner))
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id, ProjectMember.project_id == team.project.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    assert note.email_id is not None
    assert await delivery.send_email(runtime, note.email_id) == "cancelled"
