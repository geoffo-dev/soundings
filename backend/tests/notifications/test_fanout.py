"""The fan-out (contract-phase3 section 3.3): who is notified about which event, who
never is, one notification per person per event, idempotency, atomicity with the
request, and the email side (preferences, SMTP off)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import event, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import run_before_commit, session_scope
from app.domain.principal import Principal
from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.enums import (
    EmailStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
)
from app.models.idea import IdeaWatcher
from app.models.notification import Notification, NotificationPreference, OutboundEmail
from app.models.project import ProjectMember
from app.models.user import User
from app.notifications import fanout
from app.services import ideas as idea_service
from tests.factories import add_member, make_user
from tests.notifications.conftest import AsUser, Outbox, Team, full_scores, ok, only

pytestmark = pytest.mark.usefixtures("team")


def due(days: int = 3) -> datetime:
    return (utcnow() + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)


async def new_idea(api: AsUser, team: Team, author: User | None = None) -> dict[str, Any]:
    return await (await api(author or team.member)).create_idea(team.slug)


async def invite(
    api: AsUser, team: Team, idea: dict[str, Any], *users: User, due_at: datetime | None = None
) -> None:
    body: dict[str, Any] = {"user_ids": [str(user.id) for user in users]}
    if due_at is not None:
        body["due_at"] = due_at.isoformat()
    ok(await (await api(team.admin)).post(f"/ideas/{idea['key']}/evaluators", body))


async def set_owner(api: AsUser, team: Team, idea: dict[str, Any], owner: User) -> None:
    ok(await (await api(team.admin)).put(f"/ideas/{idea['key']}/owner", {"user_id": str(owner.id)}))


async def move(api: AsUser, actor: User, idea: dict[str, Any], status: str) -> None:
    body = {"status": status, "resolution": "accepted" if status == "closed" else None}
    ok(await (await api(actor)).post(f"/ideas/{idea['key']}/status", body))


# --- owner_assigned ---------------------------------------------------------------------
async def test_assigning_an_owner_notifies_them_and_queues_one_email(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)

    await set_owner(api, team, idea, team.owner)

    note = only(await outbox.notifications(team.owner.id))
    assert note.type is NotificationType.OWNER_ASSIGNED
    assert note.actor_id == team.admin.id
    assert note.email_mode is NotificationMode.IMMEDIATE
    email = only(await outbox.emails(team.owner.id))
    assert email.type.value == "owner_assigned"
    assert (email.status, email.attempts) == (EmailStatus.QUEUED, 0)
    assert note.email_id == email.id
    assert email.message_id.startswith("<")
    assert email.message_id.endswith("@testserver>")
    job = only(await outbox.jobs())
    assert job["args"] == {"email_id": str(email.id)}
    assert job["queueing_lock"] is None  # no lock on in-transaction defers


async def test_volunteering_notifies_nobody(api: AsUser, team: Team, outbox: Outbox) -> None:
    idea = await new_idea(api, team)

    ok(await (await api(team.owner)).post(f"/ideas/{idea['key']}/volunteer"))

    assert await outbox.notifications() == []
    assert await outbox.jobs() == []


# --- evaluator_invited --------------------------------------------------------------------
async def test_invitation_carries_the_due_date_set_by_the_same_request(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    """add_evaluators emits evaluator_added before it sets the default due date: the
    fan-out runs after the request's last write, so the invitation has the date."""
    idea = await new_idea(api, team)
    eve1, eve2 = team.evaluators[:2]

    await invite(api, team, idea, eve1, eve2)

    current = ok(await (await api(team.admin)).get(f"/ideas/{idea['key']}"))
    assert current["evaluation_due_at"] is not None
    for evaluator in (eve1, eve2):
        note = only(await outbox.notifications(evaluator.id))
        assert note.type is NotificationType.EVALUATOR_INVITED
        assert datetime.fromisoformat(note.payload["due_at"]) == datetime.fromisoformat(
            current["evaluation_due_at"]
        )
    assert len(await outbox.emails()) == 2


async def test_invitation_with_an_explicit_due_date(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)
    when = due(5)

    await invite(api, team, idea, team.evaluators[0], due_at=when)

    note = only(await outbox.notifications(team.evaluators[0].id))
    assert datetime.fromisoformat(note.payload["due_at"]) == when.astimezone(UTC)


async def test_service_accounts_inactive_and_break_glass_users_are_never_notified(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    robot = await make_user(db_session, "Robo Evaluator", service_account=True)
    ghost = await make_user(db_session, "Gone Person")
    glass = await make_user(db_session, "Break Glass")
    for user in (robot, ghost, glass):
        await add_member(db_session, team.project, user, ProjectRole.MEMBER)
    idea = await new_idea(api, team)
    await invite(api, team, idea, robot, ghost, glass)
    assert {note.user_id for note in await outbox.notifications()} == {ghost.id, glass.id}
    await db_session.execute(update(User).where(User.id == ghost.id).values(is_active=False))
    await db_session.execute(update(User).where(User.id == glass.id).values(is_break_glass=True))
    await db_session.commit()

    # A status change reaches every evaluator, but none of these three.
    await move(api, team.admin, idea, "evaluating")

    assert await outbox.notifications(type_=NotificationType.STATUS_CHANGED) == [
        note
        for note in await outbox.notifications(type_=NotificationType.STATUS_CHANGED)
        if note.user_id == team.member.id
    ]


# --- evaluations_complete ------------------------------------------------------------------
async def submit(api: AsUser, team: Team, user: User, idea: dict[str, Any]) -> None:
    body = {"scores": full_scores(team), "recommendation": "go", "comment": "", "submit": True}
    ok(await (await api(user)).put(f"/ideas/{idea['key']}/evaluations/me", body))


async def test_the_last_submission_tells_the_owner_once(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)
    await set_owner(api, team, idea, team.owner)
    eve1, eve2 = team.evaluators[:2]
    await invite(api, team, idea, eve1, eve2)

    await submit(api, team, eve1, idea)
    assert await outbox.notifications(team.owner.id, NotificationType.EVALUATIONS_COMPLETE) == []
    await submit(api, team, eve2, idea)

    note = only(await outbox.notifications(team.owner.id, NotificationType.EVALUATIONS_COMPLETE))
    assert note.payload == {"evaluator_count": 2}
    assert note.actor_id == eve2.id


async def test_removing_the_last_pending_evaluator_completes_the_set(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)
    await set_owner(api, team, idea, team.owner)
    eve1, eve2 = team.evaluators[:2]
    await invite(api, team, idea, eve1, eve2)
    await submit(api, team, eve1, idea)

    ok(await (await api(team.admin)).delete(f"/ideas/{idea['key']}/evaluators/{eve2.id}"))

    note = only(await outbox.notifications(team.owner.id, NotificationType.EVALUATIONS_COMPLETE))
    assert note.payload == {"evaluator_count": 1}


# --- status_changed ----------------------------------------------------------------------
async def test_status_change_reaches_owner_evaluators_and_watchers_but_not_the_actor(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team, team.member)  # member submits: watches
    await set_owner(api, team, idea, team.owner)  # the owner watches too
    await invite(api, team, idea, team.evaluators[0])
    ok(await (await api(team.viewer)).put(f"/ideas/{idea['key']}/watch"))

    await move(api, team.owner, idea, "evaluating")

    notes = await outbox.notifications(type_=NotificationType.STATUS_CHANGED)
    assert {note.user_id for note in notes} == {
        team.member.id,
        team.evaluators[0].id,
        team.viewer.id,
    }
    assert len(notes) == 3  # one per person, though the evaluator also watches
    assert notes[0].payload == {
        "from_status": "new",
        "from_resolution": None,
        "to_status": "evaluating",
        "to_resolution": None,
    }
    # Status changes default to the daily digest: no immediate emails.
    assert {note.email_mode for note in notes} == {NotificationMode.DIGEST}
    assert [email.type.value for email in await outbox.emails()] == [
        "owner_assigned",
        "evaluator_invited",
    ]


async def test_unwatching_stops_watcher_status_changes_but_not_the_owners(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team, team.member)
    await set_owner(api, team, idea, team.owner)
    await invite(api, team, idea, team.evaluators[0])
    for user in (team.member, team.owner, team.evaluators[0]):
        ok(await (await api(user)).delete(f"/ideas/{idea['key']}/watch"))

    await move(api, team.admin, idea, "evaluating")

    notes = await outbox.notifications(type_=NotificationType.STATUS_CHANGED)
    assert {note.user_id for note in notes} == {team.owner.id, team.evaluators[0].id}


async def test_people_who_lost_access_are_not_notified(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team, team.member)
    ok(await (await api(team.admin)).delete(f"/projects/{team.slug}/members/{team.member.id}"), 204)

    await move(api, team.admin, idea, "evaluating")

    assert await outbox.notifications(team.member.id) == []


# --- comments ----------------------------------------------------------------------------
async def test_a_comment_notifies_watchers_except_its_author(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team, team.member)
    ok(await (await api(team.viewer)).put(f"/ideas/{idea['key']}/watch"))

    item = ok(
        await (await api(team.admin)).post(f"/ideas/{idea['key']}/comments", {"body_md": "Nice"}),
        201,
    )

    notes = await outbox.notifications(type_=NotificationType.COMMENT)
    assert {note.user_id for note in notes} == {team.member.id, team.viewer.id}
    assert {str(note.comment_id) for note in notes} == {item["comment"]["id"]}
    assert {note.email_mode for note in notes} == {NotificationMode.DIGEST}


# --- Idempotency and atomicity -----------------------------------------------------------
async def test_a_repeated_fan_out_inserts_nothing(
    app: FastAPI, api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)
    await set_owner(api, team, idea, team.owner)
    before = len(await outbox.notifications())

    async with session_scope(app.state.sessionmaker, settings=app.state.settings) as db:
        event = await db.scalar(select(ActivityEvent).where(ActivityEvent.type == "owner_changed"))
        assert event is not None
        fanout.queue_event(db, event)
        fanout.queue_event(db, event)

    assert len(await outbox.notifications()) == before
    assert len(await outbox.emails()) == 1
    assert len(await outbox.jobs()) == 1


async def test_a_rolled_back_request_leaves_no_notification_email_or_job(
    app: FastAPI, api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)

    class Boom(Exception):
        pass

    written: list[object] = []

    async def failing_request() -> None:
        async with session_scope(app.state.sessionmaker, settings=app.state.settings) as db:
            admin = await db.get(User, team.admin.id)
            assert admin is not None
            principal = Principal(user=admin)
            loaded = await idea_service.load_idea(db, principal, idea["key"], for_update=True)
            await idea_service.set_owner(db, principal, loaded, team.owner.id)
            await run_before_commit(db)  # the fan-out wrote its rows in this transaction
            written.append(await db.scalar(select(Notification.id)))
            written.append(await db.scalar(select(OutboundEmail.id)))
            raise Boom

    with pytest.raises(Boom):
        await failing_request()

    assert None not in written

    assert await outbox.notifications() == []
    assert await outbox.emails() == []
    assert await outbox.jobs() == []


# --- Preferences and SMTP ----------------------------------------------------------------
async def test_preference_digest_and_off_queue_no_email(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    eve1, eve2 = team.evaluators[:2]
    db_session.add_all(
        [
            NotificationPreference(
                user_id=eve1.id,
                type=NotificationType.EVALUATOR_INVITED,
                mode=NotificationMode.DIGEST,
            ),
            NotificationPreference(
                user_id=eve2.id, type=NotificationType.EVALUATOR_INVITED, mode=NotificationMode.OFF
            ),
        ]
    )
    await db_session.commit()
    idea = await new_idea(api, team)

    await invite(api, team, idea, eve1, eve2, team.evaluators[2])

    modes = {note.user_id: note.email_mode for note in await outbox.notifications()}
    assert modes == {
        eve1.id: NotificationMode.DIGEST,
        eve2.id: NotificationMode.OFF,
        team.evaluators[2].id: NotificationMode.IMMEDIATE,
    }
    assert [email.recipient_user_id for email in await outbox.emails()] == [team.evaluators[2].id]


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_without_smtp_notifications_are_in_app_only(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team)

    await set_owner(api, team, idea, team.owner)
    await invite(api, team, idea, team.evaluators[0])

    notes = await outbox.notifications()
    assert {note.type for note in notes} == {
        NotificationType.OWNER_ASSIGNED,
        NotificationType.EVALUATOR_INVITED,
    }
    assert {note.email_mode for note in notes} == {NotificationMode.OFF}
    assert await outbox.emails() == []
    assert await outbox.jobs() == []


async def test_an_address_that_cannot_receive_mail_gets_in_app_only(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(User).where(User.id == team.owner.id).values(email="victim@corp.com,postmaster")
    )
    await db_session.commit()
    idea = await new_idea(api, team)

    await set_owner(api, team, idea, team.owner)

    assert only(await outbox.notifications(team.owner.id)).email_mode is NotificationMode.OFF
    assert await outbox.emails() == []


async def test_watchers_table_is_untouched_by_mentions(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Mentioned users don't start watching (section 3.8)."""
    idea = await new_idea(api, team, team.member)
    body = f"Ping @[x](user:{team.owner.id})"
    member = await api(team.member)
    ok(await member.post(f"/ideas/{idea['key']}/comments", {"body_md": body}), 201)

    watchers = set(await db_session.scalars(select(IdeaWatcher.user_id)))
    assert team.owner.id not in watchers


async def test_outbox_row_is_never_written_for_the_actor(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    idea = await new_idea(api, team, team.owner)
    ok(await (await api(team.owner)).post(f"/ideas/{idea['key']}/volunteer"))
    await move(api, team.owner, idea, "evaluating")

    assert await outbox.notifications(team.owner.id) == []
    assert (await outbox.db.scalar(select(OutboundEmail.id))) is None


async def _watchers(db: AsyncSession, team: Team, idea_id: Any, count: int) -> None:
    users = [
        {
            "id": uuid4(),
            "email": f"watcher{n}-{uuid4().hex[:6]}@example.com",
            "display_name": f"W{n}",
        }
        for n in range(count)
    ]
    await db.execute(insert(User).values(users))
    await db.execute(
        insert(ProjectMember).values(
            [
                {"project_id": team.project.id, "user_id": u["id"], "role": ProjectRole.VIEWER}
                for u in users
            ]
        )
    )
    await db.execute(
        insert(IdeaWatcher).values([{"idea_id": idea_id, "user_id": u["id"]} for u in users])
    )
    # Status changes by email at once (the default is the digest).
    await db.execute(
        insert(NotificationPreference).values(
            [
                {
                    "user_id": u["id"],
                    "type": NotificationType.STATUS_CHANGED,
                    "mode": NotificationMode.IMMEDIATE,
                }
                for u in users
            ]
        )
    )
    await db.commit()


async def test_the_fan_out_costs_the_same_statements_for_many_watchers(
    app: FastAPI, api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    """Review L6: the fan-out ran in the request with one UPDATE per email (3,000
    watchers: 4 s while the idea was locked). Its statements must not grow per person."""
    admin = await api(team.admin)
    executed: list[int] = []

    def count(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        # A DBAPI executemany runs one statement per parameter set; a batched
        # multi-row INSERT (one parameter dict) is one statement.
        executed.append(len(params) if many and isinstance(params, list) else 1)

    async def statements_for(watchers: int) -> int:
        idea = await new_idea(api, team)
        await _watchers(db_session, team, idea["id"], watchers)
        engine = app.state.engine.sync_engine
        executed.clear()
        event.listen(engine, "before_cursor_execute", count)
        try:
            await move(api, team.admin, idea, "evaluating")
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return sum(executed)

    few = await statements_for(20)
    many = await statements_for(400)

    assert many <= few + 2, (few, many)
    notes = await outbox.notifications(type_=NotificationType.STATUS_CHANGED)
    assert len(notes) >= 420
    emails = {e.id: e for e in await outbox.emails()}
    by_note = {note.user_id: note.email_id for note in notes if note.email_id is not None}
    assert len(by_note) >= 420  # every watcher's notification is linked to its own email
    assert all(emails[email_id].recipient_user_id == user for user, email_id in by_note.items())
    assert admin is not None


async def test_a_large_audience_is_notified_by_the_worker(
    app: FastAPI,
    settings: Any,
    api: AsUser,
    team: Team,
    outbox: Outbox,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review L6: above the inline limit the request only defers a job (atomically);
    the worker notifies everyone, once however often it runs."""
    monkeypatch.setattr(fanout, "FAN_OUT_INLINE_LIMIT", 3)
    idea = await new_idea(api, team)
    await _watchers(db_session, team, idea["id"], 5)

    await move(api, team.admin, idea, "evaluating")

    assert await outbox.notifications(type_=NotificationType.STATUS_CHANGED) == []
    [job] = await outbox.jobs("notify_event")
    assert job["status"] == "todo"
    event_id = job["args"]["event_id"]

    await fanout.notify_deferred_event(app.state.sessionmaker, settings, UUID(event_id))
    await fanout.notify_deferred_event(app.state.sessionmaker, settings, UUID(event_id))

    notes = await outbox.notifications(type_=NotificationType.STATUS_CHANGED)
    people = [note.user_id for note in notes]
    assert len(people) == len(set(people)) >= 6  # 5 watchers and the submitter
    assert team.admin.id not in people  # the actor
    emails = await outbox.emails()
    assert {note.email_id for note in notes if note.email_id} == {e.id for e in emails}
    assert len(emails) >= 5  # the watchers chose immediate


async def test_a_deferred_comment_fan_out_keeps_mentions_separate(
    app: FastAPI,
    settings: Any,
    api: AsUser,
    team: Team,
    outbox: Outbox,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fanout, "FAN_OUT_INLINE_LIMIT", 3)
    idea = await new_idea(api, team)
    await _watchers(db_session, team, idea["id"], 4)
    ok(await (await api(team.owner)).put(f"/ideas/{idea['key']}/watch"))
    body = {"body_md": f"@[Olive](user:{team.owner.id}) have a look"}

    ok(await (await api(team.admin)).post(f"/ideas/{idea['key']}/comments", body), 201)

    [mention] = await outbox.notifications(type_=NotificationType.MENTION)  # inline
    assert mention.user_id == team.owner.id
    assert await outbox.notifications(type_=NotificationType.COMMENT) == []
    [job] = await outbox.jobs("notify_event")
    await fanout.notify_deferred_event(
        app.state.sessionmaker, settings, UUID(job["args"]["event_id"])
    )

    comments = await outbox.notifications(type_=NotificationType.COMMENT)
    users = {note.user_id for note in comments}
    assert len(users) >= 5  # 4 watchers and the submitter
    assert team.owner.id not in users  # mentioned instead
    assert team.admin.id not in users  # the author


async def test_a_rolled_back_request_defers_no_fan_out_job(
    app: FastAPI, api: AsUser, team: Team, outbox: Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fanout, "FAN_OUT_INLINE_LIMIT", 0)
    idea = await new_idea(api, team)

    class Boom(Exception):
        pass

    deferred: list[object] = []

    async def failing_request() -> None:
        async with session_scope(app.state.sessionmaker, settings=app.state.settings) as db:
            admin = await db.get(User, team.admin.id)
            assert admin is not None
            principal = Principal(user=admin)
            loaded = await idea_service.load_idea(db, principal, idea["key"], for_update=True)
            await idea_service.set_owner(db, principal, loaded, team.owner.id)
            await run_before_commit(db)
            deferred.append(
                await db.scalar(
                    text("SELECT id FROM procrastinate_jobs WHERE task_name = 'notify_event'")
                )
            )
            raise Boom

    with pytest.raises(Boom):
        await failing_request()

    assert deferred[0] is not None  # deferred in the transaction ...
    assert await outbox.jobs("notify_event") == []  # ... and rolled back with it
    assert await outbox.notifications() == []
