"""Phase 11: the team's side of the conversation with a public submitter
(contract-phase11 sections 2-5 and 11, role matrix table G notes "who reaches the
conversation"): who reads and writes it, the summary in the submission panel, the order
of checks, the states (held, closed, archived, erased, instance switch off), the limits,
the body rules, the audit entry, and that nobody else learns a conversation exists."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.activity import ActivityEvent, AuditLog
from app.models.base import utcnow
from app.models.enums import HoldReason, IdeaStatus, NotificationType, ProjectRole
from app.models.idea import Idea, IdeaWatcher
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project, ProjectMember
from app.models.public import SubmissionMessage
from app.models.user import User
from tests.ai.helpers import make_agent
from tests.api_keys.helpers import ALL_SCOPES, key_client, make_key
from tests.factories import make_idea, make_project, make_user, set_researcher
from tests.public.conftest import (
    API,
    AsUser,
    Team,
    add_message,
    assert_problem,
    make_public_idea,
    messages_url,
    ok,
)

pytestmark = pytest.mark.usefixtures("form")

BODY = "Thanks, Sam! Which stores did you have in mind?\nWe'd like to try it in two."


async def public_idea(
    db: AsyncSession, settings: Settings, team: Team, **values: Any
) -> tuple[str, Idea]:
    """CUST's public idea, owned by ``team.owner``, with a confirmed address."""
    values.setdefault("email", "sam@example.org")
    values.setdefault("verified", True)
    values.setdefault("owner", team.owner)
    return await make_public_idea(db, settings, team, **values)


async def send(api: AsUser, user: User, idea: Idea, body: str = BODY) -> httpx.Response:
    return await (await api(user)).post(messages_url(idea), {"body": body})


async def listed(api: AsUser, user: User, idea: Idea, **params: Any) -> httpx.Response:
    return await (await api(user)).get(messages_url(idea), **params)


async def panel(api: AsUser, user: User, idea: Idea) -> httpx.Response:
    return await (await api(user)).get(f"/ideas/{idea.id}/submission")


async def stored(db: AsyncSession) -> list[SubmissionMessage]:
    return list(
        await db.scalars(
            select(SubmissionMessage)
            .order_by(SubmissionMessage.created_at, SubmissionMessage.id)
            .execution_options(populate_existing=True)
        )
    )


# --- Who reaches the conversation (role matrix table G notes) ---------------------------------
@pytest.mark.parametrize(
    ("who", "reads", "writes"),
    [
        ("owner", 200, 201),
        ("admin", 200, 201),
        ("platform", 200, 201),
        ("member", 403, 403),
        ("viewer", 403, 403),
        ("evaluator", 403, 403),
        ("outsider", 404, 404),  # a private non-member
        ("guest", 404, 404),  # the idea's guest researcher (column R)
    ],
)
async def test_who_reads_and_writes_the_conversation(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    who: str,
    reads: int,
    writes: int,
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    guest = await make_user(db_session, "Gus Guest")
    await set_researcher(db_session, idea, guest)
    user = {"guest": guest, "evaluator": team.evaluators[0]}.get(who) or getattr(team, who)

    sent = await send(api, user, idea)
    read = await listed(api, user, idea)
    seen = await panel(api, user, idea)

    assert sent.status_code == writes, sent.text
    assert read.status_code == reads, read.text
    if writes == 403:
        assert_problem(sent, 403, "forbidden")
        assert_problem(read, 403, "forbidden")
    if reads == 404:
        assert_problem(read, 404, "not_found")
        assert_problem(seen, 404, "not_found")
        return
    body = ok(seen)
    if reads == 200:
        assert body["permissions"]["can_message"] is True
        assert body["messages"] == {
            "count": 1,
            "last_message_at": body["messages"]["last_message_at"],
            "last_direction": "team",
            "delivery": "email",
            "blocked": None,
        }
        message = ok(read)["items"][0]
        assert message["body"] == BODY
        assert message["author"]["id"] == str(user.id)
        assert message["emailed"] is True
    else:
        # Nothing of the conversation, not even that it exists.
        assert body["messages"] is None
        assert body["permissions"]["can_message"] is False
        assert await stored(db_session) == []


async def test_anonymous_callers_get_401(
    client: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)

    read = await client.get(API + messages_url(idea))
    sent = await client.post(API + messages_url(idea), json={"body": BODY})

    assert_problem(read, 401, "unauthorized")
    assert_problem(sent, 401, "unauthorized")


@pytest.mark.parametrize("scopes", [*((scope,) for scope in ALL_SCOPES), ALL_SCOPES])
async def test_api_keys_never_reach_the_conversation(
    app: FastAPI,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    scopes: tuple[str, ...],
) -> None:
    """Session only (``ROUTE_KEY_ACCESS``): a platform admin's key, whatever its scopes."""
    _, idea = await public_idea(db_session, settings, team)
    key = await make_key(db_session, team.platform, scopes=scopes)

    async with key_client(app, key) as http:
        read = await http.get(API + messages_url(idea))
        sent = await http.post(API + messages_url(idea), json={"body": BODY})
        seen = await http.get(f"{API}/ideas/{idea.id}/submission")

    for response in (read, sent, seen):
        assert_problem(response, 403, "insufficient_scope")
    assert await stored(db_session) == []


async def test_an_agents_key_is_refused(
    app: FastAPI, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    agent = await make_agent(db_session, [team.project], key=True, role=ProjectRole.ADMIN)
    assert agent.key is not None

    async with key_client(app, agent.key) as http:
        read = await http.get(API + messages_url(idea))
        sent = await http.post(API + messages_url(idea), json={"body": BODY})

    assert_problem(read, 403, "insufficient_scope")
    assert_problem(sent, 403, "insufficient_scope")


BREAK_GLASS = {
    "break_glass_enabled": True,
    "break_glass_username": "emergency-admin",
    "break_glass_password": "correct horse battery staple",
}


@pytest.mark.settings(**BREAK_GLASS)
async def test_the_break_glass_account_is_no_one_to_write_from(
    client: httpx.AsyncClient, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """c31: a platform admin, but an emergency login: 403, and it reads nothing of the
    conversation (``messages`` null)."""
    _, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.admin, body="Seen only by named people.")
    signed_in = await client.post(
        f"{API}/auth/break-glass",
        json={"username": "emergency-admin", "password": "correct horse battery staple"},
    )
    assert signed_in.status_code == 200, signed_in.text
    client.headers["X-CSRF-Token"] = client.cookies["soundings_csrf"]

    read = await client.get(API + messages_url(idea))
    sent = await client.post(API + messages_url(idea), json={"body": BODY})
    seen = ok(await client.get(f"{API}/ideas/{idea.id}/submission"))

    assert_problem(read, 403, "forbidden")
    assert_problem(sent, 403, "forbidden")
    assert "Seen only by named people" not in read.text
    assert seen["messages"] is None
    assert seen["permissions"]["can_message"] is False
    assert seen["permissions"]["can_erase"] is True  # still a platform admin otherwise


async def test_an_internal_non_member_sees_nothing(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    from app.models.enums import ProjectVisibility

    internal = await make_project(
        db_session,
        slug="internal-ideas",
        key="INT",
        visibility=ProjectVisibility.INTERNAL,
        members={team.admin: ProjectRole.ADMIN},
    )
    await db_session.execute(
        update(Project).where(Project.id == internal.id).values(public_submission_enabled=True)
    )
    await db_session.commit()
    _, idea = await public_idea(db_session, settings, team, project=internal, owner=None)
    await add_message(db_session, idea, author=team.admin)

    assert_problem(await listed(api, team.outsider, idea), 403, "forbidden")
    assert_problem(await send(api, team.outsider, idea), 403, "forbidden")
    seen = ok(await panel(api, team.outsider, idea))
    assert seen["messages"] is None
    assert seen["permissions"]["can_message"] is False


async def test_an_owner_demoted_to_viewer_loses_the_conversation(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id, ProjectMember.project_id == team.project.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    assert_problem(await listed(api, team.owner, idea), 403, "forbidden")
    assert_problem(await send(api, team.owner, idea), 403, "forbidden")
    assert ok(await panel(api, team.owner, idea))["messages"] is None


async def test_an_idea_that_did_not_come_through_the_form_is_404(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)

    assert_problem(await listed(api, team.admin, idea), 404, "not_found")
    assert_problem(await send(api, team.admin, idea), 404, "not_found")


# --- Security review M1: volunteering never opens the conversation (c32) ------------------------
@pytest.mark.parametrize("conversation", [True, False])
async def test_a_member_cannot_volunteer_to_own_a_public_idea(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, conversation: bool
) -> None:
    """The owner overlay opens the conversation, so a member can't make themselves the owner
    of an idea sent through the public form (an admin names its owner): the same answer
    whether a conversation exists or not, so the refusal tells nothing."""
    _, idea = await public_idea(db_session, settings, team, owner=None)
    if conversation:
        await add_message(db_session, idea, author=team.admin)
        await add_message(db_session, idea, "submitter")
    await db_session.commit()
    member = await api(team.member)

    detail = ok(await member.get(f"/ideas/{idea.id}"))
    volunteered = await member.post(f"/ideas/{idea.id}/volunteer")

    assert detail["permissions"]["can_volunteer"] is False
    assert_problem(volunteered, 403, "public_idea_owner_needs_admin")
    assert_problem(await listed(api, team.member, idea), 403, "forbidden")
    assert ok(await panel(api, team.member, idea))["messages"] is None
    owner = await db_session.scalar(
        select(Idea.owner_id).where(Idea.id == idea.id).execution_options(populate_existing=True)
    )
    assert owner is None


async def test_a_member_still_volunteers_for_an_idea_the_team_wrote(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    await db_session.commit()
    member = await api(team.member)

    assert ok(await member.get(f"/ideas/{idea.id}"))["permissions"]["can_volunteer"] is True
    assert ok(await member.post(f"/ideas/{idea.id}/volunteer"))


async def test_admins_volunteer_or_name_the_owner_of_a_public_idea(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """A project admin may own it themselves; the member an admin names owns the
    conversation too (the admin's choice, not the member's)."""
    _, idea = await public_idea(db_session, settings, team, owner=None)
    _, other = await public_idea(db_session, settings, team, owner=None, title="Refill station")
    await db_session.commit()
    admin = await api(team.admin)

    assert ok(await admin.get(f"/ideas/{idea.id}"))["permissions"]["can_volunteer"] is True
    assert ok(await admin.post(f"/ideas/{idea.id}/volunteer"))
    assert ok(await admin.put(f"/ideas/{other.id}/owner", {"user_id": str(team.member.id)}))

    assert (await listed(api, team.admin, idea)).status_code == 200
    assert (await send(api, team.member, other)).status_code == 201


# --- States -------------------------------------------------------------------------------------
async def test_held_for_email_confirmation_is_404_for_everyone(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(
        db_session, settings, team, held_for=HoldReason.EMAIL_VERIFICATION, verified=False
    )

    for user in (team.admin, team.platform):
        assert_problem(await listed(api, user, idea), 404, "not_found")
        assert_problem(await send(api, user, idea), 404, "not_found")


async def test_moderators_may_ask_before_approving(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """c19 doesn't apply to messages: the admins who see a held idea may write; the owner
    (a member) doesn't see it at all (c12)."""
    _, idea = await public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)

    ok(await send(api, team.admin, idea), 201)
    ok(await send(api, team.platform, idea), 201)
    assert_problem(await send(api, team.owner, idea), 404, "not_found")
    queue = ok(await (await api(team.admin)).get(f"/projects/{team.slug}/moderation"))
    [item] = queue["items"]
    assert item["submission"]["messages"]["count"] == 2
    assert item["submission"]["messages"]["last_direction"] == "team"
    assert item["submission"]["permissions"]["can_message"] is True


async def test_closed_ideas_still_take_messages(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(status=IdeaStatus.CLOSED, resolution="parked")
    )
    await db_session.commit()

    ok(await send(api, team.owner, idea), 201)


async def test_an_archived_project_reads_but_does_not_send(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.admin)
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()

    assert len(ok(await listed(api, team.owner, idea))["items"]) == 1
    assert_problem(await send(api, team.owner, idea), 409, "project_archived")
    seen = ok(await panel(api, team.admin, idea))
    assert seen["messages"]["blocked"] == "project_archived"
    assert seen["permissions"]["can_message"] is False


@pytest.mark.settings(public_submission_enabled=False)
async def test_with_public_submission_off_the_team_reads_but_does_not_send(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Review C4: no tracking link opens, so nobody could read or answer a message."""
    _, idea = await public_idea(db_session, settings, team)

    assert ok(await listed(api, team.owner, idea))["items"] == []
    assert_problem(await send(api, team.owner, idea), 409, "public_submission_off")
    assert ok(await panel(api, team.owner, idea))["messages"]["blocked"] == (
        "public_submission_off"
    )


async def test_erased_details_leave_no_one_to_write_to(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    ok(await send(api, team.owner, idea), 201)
    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/erase"))

    assert ok(await listed(api, team.owner, idea))["items"] == []
    assert_problem(await send(api, team.owner, idea), 409, "submitter_erased")
    seen = ok(await panel(api, team.admin, idea))
    assert seen["messages"] == {
        "count": 0,
        "last_message_at": None,
        "last_direction": None,
        "delivery": "tracking_page",
        "blocked": "submitter_erased",
    }


async def test_the_archived_project_leads_the_409s(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Review C6: archived first, then erased, then full."""
    _, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.admin, count=100)
    assert_problem(await send(api, team.owner, idea), 409, "conversation_full")
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    assert_problem(await send(api, team.owner, idea), 409, "project_archived")
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=None)
    )
    await db_session.commit()
    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/erase"))
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    assert_problem(await send(api, team.owner, idea), 409, "project_archived")
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=None)
    )
    await db_session.commit()
    assert_problem(await send(api, team.owner, idea), 409, "submitter_erased")


# --- Limits ---------------------------------------------------------------------------------
async def test_a_conversation_holds_100_messages(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    old = utcnow() - timedelta(days=3)
    await add_message(db_session, idea, author=team.admin, count=50, at=old)
    await add_message(db_session, idea, "submitter", count=49, at=old)
    ok(await send(api, team.owner, idea), 201)

    assert_problem(await send(api, team.owner, idea), 409, "conversation_full")
    seen = ok(await panel(api, team.owner, idea))
    assert seen["messages"]["count"] == 100
    assert seen["messages"]["blocked"] == "conversation_full"
    assert len(ok(await listed(api, team.owner, idea, limit=100))["items"]) == 100


async def test_20_team_messages_to_one_submitter_a_day(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    oldest = utcnow() - timedelta(hours=23)
    await add_message(db_session, idea, author=team.admin, count=1, at=oldest)
    await add_message(db_session, idea, author=team.platform, count=18)
    await add_message(db_session, idea, author=team.admin, count=5, at=utcnow() - timedelta(days=2))
    ok(await send(api, team.owner, idea), 201)  # the 20th in 24 hours

    refused = await send(api, team.owner, idea)

    assert_problem(refused, 429, "too_many_attempts")
    assert 3400 <= int(refused.headers["Retry-After"]) <= 3600
    assert "20 messages to this person today" in refused.json()["detail"]
    assert ok(await panel(api, team.owner, idea))["messages"]["blocked"] == "daily_limit"


async def test_30_messages_of_one_person_an_hour_across_ideas(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, first = await public_idea(db_session, settings, team)
    _, second = await public_idea(db_session, settings, team, title="Second public idea")
    await add_message(
        db_session, first, author=team.admin, count=15, at=utcnow() - timedelta(minutes=50)
    )
    await add_message(db_session, second, author=team.admin, count=15)

    refused = await send(api, team.admin, second)

    assert_problem(refused, 429, "too_many_attempts")
    assert 500 <= int(refused.headers["Retry-After"]) <= 600
    ok(await send(api, team.owner, second), 201)  # someone else still may
    # Not a daily limit of the submission: the panel doesn't say so.
    assert ok(await panel(api, team.admin, second))["messages"]["blocked"] is None


async def test_concurrent_sends_never_pass_the_hourly_limit_of_one_person(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Security review N3: one person's sends to different submitters are serialised (an
    advisory lock on the sender), so of six racing for the 30th place, one wins."""
    ideas = [
        (await public_idea(db_session, settings, team, title=f"Public idea {n}"))[1]
        for n in range(6)
    ]
    await add_message(db_session, ideas[0], author=team.admin, count=29)
    clients = [await api(team.admin) for _ in ideas]

    responses = await asyncio.gather(
        *(
            http.post(messages_url(idea), {"body": f"Race {n}"})
            for n, (http, idea) in enumerate(zip(clients, ideas, strict=True))
        )
    )

    assert sorted(response.status_code for response in responses) == [201] + [429] * 5
    count = await db_session.scalar(select(func.count()).select_from(SubmissionMessage))
    assert count == 30


async def test_concurrent_sends_never_pass_the_daily_limit(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """The submission's lock serialises sends: of five racing for the 20th place, one wins."""
    _, idea = await public_idea(db_session, settings, team)
    await add_message(db_session, idea, author=team.platform, count=19)
    clients = [await api(user) for user in (team.owner, team.admin, team.platform)] * 2

    responses = await asyncio.gather(
        *(http.post(messages_url(idea), {"body": f"Race {n}"}) for n, http in enumerate(clients))
    )

    assert sorted(response.status_code for response in responses) == [201] + [429] * 5
    count = await db_session.scalar(select(func.count()).select_from(SubmissionMessage))
    assert count == 20


# --- The body ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    ["", "   \n\t ", "\u200b\u200b", "Hi\x00there", "Hi \U000e0041", "x" * 4_001],
)
async def test_bodies_that_show_nothing_or_hide_something_are_422(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings, body: str
) -> None:
    _, idea = await public_idea(db_session, settings, team)

    assert_problem(await send(api, team.owner, idea, body), 422, "validation_error")
    assert await stored(db_session) == []


async def test_the_body_is_plain_text_kept_as_typed(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Line breaks become ``\\n``; Markdown, HTML and a mention-shaped token stay as typed
    (review S5): the mention notifies nobody and adds no watcher."""
    _, idea = await public_idea(db_session, settings, team)
    typed = (
        f"Hi @[Max Member](user:{team.member.id})\r\n**bold** <script>x</script>\u2028"
        "[a link](https://example.org)\rend"
    )

    sent = ok(await send(api, team.owner, idea, typed), 201)

    expected = (
        f"Hi @[Max Member](user:{team.member.id})\n**bold** <script>x</script>\n"
        "[a link](https://example.org)\nend"
    )
    assert sent["body"] == expected
    [row] = await stored(db_session)
    assert row.body == expected
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.type == NotificationType.MENTION)
        )
        == 0
    )
    watchers = await db_session.scalars(
        select(IdeaWatcher.user_id).where(IdeaWatcher.idea_id == idea.id)
    )
    assert team.member.id not in set(watchers)


# --- The conversation's page ------------------------------------------------------------------
async def test_the_conversation_is_listed_newest_first_with_a_cursor(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)
    start = utcnow() - timedelta(hours=5)
    for n in range(5):
        await add_message(
            db_session,
            idea,
            "team" if n % 2 == 0 else "submitter",
            author=team.admin,
            body=f"Message {n}",
            at=start + timedelta(minutes=n),
        )

    first = ok(await listed(api, team.owner, idea, limit=3))
    second = ok(await listed(api, team.owner, idea, limit=3, cursor=first["next_cursor"]))

    assert [m["body"] for m in first["items"]] == ["Message 4", "Message 3", "Message 2"]
    assert [m["body"] for m in second["items"]] == ["Message 1", "Message 0"]
    assert second["next_cursor"] is None
    reply = first["items"][1]
    assert reply["direction"] == "submitter"
    assert reply["author"] is None
    assert reply["emailed"] is False
    assert first["items"][0]["author"]["display_name"] == "Ada Admin"
    assert_problem(
        await listed(api, team.owner, idea, cursor="not-a-cursor"), 400, "invalid_cursor"
    )


async def test_the_summary_says_where_a_message_goes(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Email only to a confirmed address; the reason isn't given."""
    _, confirmed = await public_idea(db_session, settings, team)
    _, unconfirmed = await public_idea(db_session, settings, team, title="Two", verified=False)
    _, anonymous = await public_idea(
        db_session, settings, team, title="Three", email=None, verified=False
    )

    assert ok(await panel(api, team.owner, confirmed))["messages"]["delivery"] == "email"
    for idea in (unconfirmed, anonymous):
        assert ok(await panel(api, team.owner, idea))["messages"]["delivery"] == "tracking_page"
        sent = ok(await send(api, team.owner, idea), 201)
        assert sent["emailed"] is False
    emails = await db_session.scalar(select(func.count()).select_from(OutboundEmail))
    assert emails == 0


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_without_email_set_up_messages_reach_the_tracking_page_only(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)

    assert ok(await panel(api, team.owner, idea))["messages"]["delivery"] == "tracking_page"
    assert ok(await send(api, team.owner, idea), 201)["emailed"] is False


# --- Audit, activity and what else must not change ---------------------------------------------
async def test_each_team_message_is_audited_without_its_text(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await public_idea(db_session, settings, team)

    sent = ok(await send(api, team.owner, idea, "A secret plan for Sam"), 201)

    [entry] = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "submission.message"))
    )
    assert entry.actor_id == team.owner.id
    assert entry.target_type == "idea"
    assert entry.target_id == idea.id
    assert entry.project_id == team.project.id
    assert {key: entry.details[key] for key in ("rule", "message_id", "emailed")} == {
        "rule": "public.message_submitter",
        "message_id": sent["id"],
        "emailed": True,
    }
    assert set(entry.details) - {"rule", "message_id", "emailed"} <= {"auth", "auth_method"}
    assert "secret" not in str(entry.details).lower()


async def test_a_message_moves_nothing_others_can_see(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Not in the feed; the idea's activity time, ``updated_at`` and detail don't change."""
    _, idea = await public_idea(db_session, settings, team)
    before = ok(await (await api(team.member)).get(f"/ideas/{idea.id}"))
    activity_before = before["last_activity_at"]
    events = await db_session.scalar(select(func.count()).select_from(ActivityEvent))

    ok(await send(api, team.owner, idea, "Zanzibar-quokka wording"), 201)

    after = ok(await (await api(team.member)).get(f"/ideas/{idea.id}"))
    assert after["last_activity_at"] == activity_before
    assert after == before
    assert await db_session.scalar(select(func.count()).select_from(ActivityEvent)) == events
    feed = await (await api(team.admin)).get(f"/ideas/{idea.id}/activity")
    assert "Zanzibar" not in feed.text
    found = await (await api(team.admin)).get("/search", q="Zanzibar-quokka")
    assert found.status_code == 200
    assert "Zanzibar" not in found.text


async def test_the_moderation_queue_reads_every_conversation_in_one_statement(
    app: FastAPI, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    from sqlalchemy import event

    for n in range(3):
        _, idea = await public_idea(
            db_session, settings, team, held_for=HoldReason.MODERATION, title=f"Held {n}"
        )
        await add_message(db_session, idea, author=team.admin, count=n)
    admin = await api(team.admin)
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(str(args[2]))

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        page = ok(await admin.get(f"/projects/{team.slug}/moderation"))
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert [item["submission"]["messages"]["count"] for item in page["items"]] == [0, 1, 2]
    assert sum("submission_messages" in statement for statement in seen) == 1
