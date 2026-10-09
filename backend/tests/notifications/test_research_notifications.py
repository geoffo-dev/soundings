"""Phase 8b notifications (contract-phase8b section 6): "Asked to research"
(``researcher_assigned``) end to end, and what a researcher gets of the Phase 3 types.

* Who gets "Asked to research" (the new researcher, never the actor, not on removal), at
  most once per idea, person and local day (review S6); the inbox item; the email (subject,
  link to the Research panel, the guest line only for column R: review S2), never score
  data; preferences (digest, off), the digest line, unsubscribe scoping; cancelled at send
  time once the assignment ended.
* status changes reach the researcher always; mentions reach a guest researcher;
  "All N evaluations are in" never reaches an owner who is only the idea's guest (S3).
* ``soundings email-preview`` renders both new templates.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email.delivery import Runtime
from app.email.preview import sample_contents
from app.email.render import render
from app.models.enums import (
    EmailStatus,
    EvaluatorState,
    IdeaStatus,
    NotificationMode,
    NotificationType,
    ProjectVisibility,
    ResearchStep,
)
from app.models.idea import Idea
from app.models.notification import NotificationPreference
from app.models.project import Project, ProjectMember
from app.notifications.schedule import build_digests
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_idea
from tests.notifications.conftest import (
    API,
    AsUser,
    Outbox,
    RecordingTransport,
    Team,
    full_scores,
    ok,
    only,
)
from tests.research.conftest import assign, key_of, set_step

ASSIGNED = NotificationType.RESEARCHER_ASSIGNED
DUE = "2026-12-11T17:00:00+00:00"
GUEST_LINE = "not its scores, evaluations or proposal"
FORBIDDEN = re.compile(r"score|aggregate|disagree|recommend|\bno-go\b", re.IGNORECASE)


async def _idea(db: AsyncSession, team: Team, **kwargs: Any) -> tuple[Idea, str]:
    await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(
        db, team.project, owner=team.owner, title="Shared on-call calendar", **kwargs
    )
    return idea, key_of(team.project, idea)


async def _send_all(outbox: Outbox, runtime: Runtime) -> None:
    for email in await outbox.emails():
        if email.status is EmailStatus.QUEUED:
            await delivery.send_email(runtime, email.id)


def _bodies(message: Any) -> tuple[str, str, str]:
    html = message.get_body(("html",))
    text = message.get_body(("plain",))
    assert html is not None
    assert text is not None
    return str(message["Subject"]), html.get_content(), text.get_content()


# --- "Asked to research" ------------------------------------------------------------------
async def test_a_guest_researcher_is_asked_by_email(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    idea, key = await _idea(db_session, team)

    ok(await assign(await api(team.admin), key, team.outsider, DUE))

    note = only(await outbox.notifications(team.outsider.id, ASSIGNED))
    assert note.actor_id == team.admin.id
    assert note.idea_id == idea.id
    assert note.email_mode is NotificationMode.IMMEDIATE
    assert note.dedupe_key.startswith(f"researcher_assigned:{idea.id}:")
    await _send_all(outbox, runtime)
    subject, html, text = _bodies(only(transport.messages))
    assert subject == f'[{key}] Please research "Shared on-call calendar" by Fri 11 Dec'
    for body in (html, text):
        assert "Ada Admin asked you to do the research" in body
        assert GUEST_LINE in body
        assert f"/ideas/{key}?research=1" in body
        assert "You're researching" in body.replace("&#39;", "'")
        assert "Customer Innovation" in body
        assert not FORBIDDEN.search(body.replace(GUEST_LINE, ""))
    items = ok(await (await api(team.outsider)).get("/me/notifications"))["items"]
    (item,) = items
    assert item["type"] == "researcher_assigned"
    assert item["due_at"].startswith("2026-12-11T17:00:00")
    assert item["actor"]["id"] == str(team.admin.id)


@pytest.mark.parametrize("who", ["member", "internal_outsider"])
async def test_no_guest_line_for_someone_who_sees_more(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    who: str,
) -> None:
    if who == "internal_outsider":
        await db_session.execute(
            update(Project)
            .where(Project.id == team.project.id)
            .values(visibility=ProjectVisibility.INTERNAL)
        )
        await db_session.commit()
    _, key = await _idea(db_session, team)
    researcher = team.member if who == "member" else team.outsider

    ok(await assign(await api(team.owner), key, researcher))

    await _send_all(outbox, runtime)
    subject, html, text = _bodies(only(transport.messages))
    assert subject == f'[{key}] Please research "Shared on-call calendar"'  # no due date
    assert GUEST_LINE not in html
    assert GUEST_LINE not in text


async def test_once_per_idea_person_and_day_and_never_the_actor(
    api: AsUser, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    """Review S6: assigning and removing over and over sends one."""
    _, key = await _idea(db_session, team)
    owner = await api(team.owner)

    for _ in range(3):
        ok(await assign(owner, key, team.member, DUE))
        assert (await owner.delete(f"/ideas/{key}/research/assignment")).status_code == 204
    ok(await assign(owner, key, team.owner))  # yourself: nobody is told

    assert len(await outbox.notifications(team.member.id, ASSIGNED)) == 1
    assert await outbox.notifications(team.owner.id, ASSIGNED) == []
    assert len(await outbox.emails(team.member.id)) == 1


async def test_cancelled_at_send_time_once_the_assignment_ended(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    _, key = await _idea(db_session, team)
    admin = await api(team.admin)
    ok(await assign(admin, key, team.outsider, DUE))
    assert (await admin.delete(f"/ideas/{key}/research/assignment")).status_code == 204

    await _send_all(outbox, runtime)

    assert transport.messages == []
    email = only(await outbox.emails(team.outsider.id))
    assert email.status is EmailStatus.CANCELLED
    # And the inbox no longer shows it (the guest can't see the idea any more).
    assert ok(await (await api(team.outsider)).get("/me/notifications"))["items"] == []


async def test_preferences_digest_and_off(
    app: FastAPI,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    settings: Settings,
) -> None:
    member = await api(team.member)
    prefs = ok(await member.get("/me/notification-preferences"))
    types = [row["type"] for row in prefs["items"]]
    assert types[-2:] == ["researcher_assigned", "research_reminder"]
    assert {row["type"]: row["mode"] for row in prefs["items"]}["researcher_assigned"] == (
        "immediate"
    )
    db_session.add(
        NotificationPreference(user_id=team.member.id, type=ASSIGNED, mode=NotificationMode.DIGEST)
    )
    db_session.add(
        NotificationPreference(
            user_id=team.evaluators[0].id, type=ASSIGNED, mode=NotificationMode.OFF
        )
    )
    await db_session.commit()
    _, key = await _idea(db_session, team)
    other = await make_idea(db_session, team.project, owner=team.owner)
    owner = await api(team.owner)

    ok(await assign(owner, key, team.member, DUE))
    ok(await assign(owner, key_of(team.project, other), team.evaluators[0]))

    assert await outbox.emails() == []  # digest and off: nothing now
    assert only(await outbox.notifications(team.evaluators[0].id, ASSIGNED))  # still in-app
    from app.models.base import utcnow

    assert await build_digests(app.state.sessionmaker, settings, utcnow()) == 1
    await _send_all(outbox, runtime)
    subject, _, text = _bodies(only(transport.messages))
    assert subject.startswith("Soundings digest")
    assert "Olive Owner asked you to research it (due Fri 11 Dec)" in text


async def test_the_unsubscribe_link_turns_off_only_its_type(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    client: httpx.AsyncClient,
) -> None:
    _, key = await _idea(db_session, team)
    ok(await assign(await api(team.owner), key, team.member))
    await _send_all(outbox, runtime)
    message = only(transport.messages)
    url = str(message["List-Unsubscribe"]).strip("<>")
    token = parse_qs(urlparse(url).query)["token"][0]

    ok(await client.post(f"{API}/unsubscribe", params={"token": token}))

    prefs = ok(await (await api(team.member)).get("/me/notification-preferences"))
    modes = {row["type"]: row["mode"] for row in prefs["items"]}
    assert modes["researcher_assigned"] == "off"
    assert modes["research_reminder"] == "immediate"
    assert modes["comment"] != "off"


# --- What else a researcher gets -----------------------------------------------------------
async def test_status_changes_reach_the_researcher_even_unwatched(
    api: AsUser, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await make_idea(db_session, team.project, owner=team.owner, status=IdeaStatus.NEW)
    key = key_of(team.project, idea)
    ok(await assign(await api(team.admin), key, team.outsider))
    guest = await api(team.outsider)
    assert (await guest.delete(f"/ideas/{key}/watch")).status_code < 300

    ok(await (await api(team.owner)).post(f"/ideas/{key}/status", {"status": "evaluating"}))

    note = only(await outbox.notifications(team.outsider.id, NotificationType.STATUS_CHANGED))
    assert note.idea_id == idea.id
    items = ok(await guest.get("/me/notifications"))["items"]
    assert [item["type"] for item in items] == ["status_changed", "researcher_assigned"]


async def test_a_mention_reaches_the_guest_researcher(
    api: AsUser, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, key = await _idea(db_session, team)
    ok(await assign(await api(team.admin), key, team.outsider))
    body = {"body_md": f"Over to you, @[Otto](user:{team.outsider.id})."}

    ok(await (await api(team.member)).post(f"/ideas/{key}/comments", body), 201)

    assert only(await outbox.notifications(team.outsider.id, NotificationType.MENTION))
    # A comment by the guest reaches the owner as a watcher would (no score data).
    ok(await (await api(team.outsider)).post(f"/ideas/{key}/comments", {"body_md": "Done."}), 201)


async def test_an_owner_who_is_only_the_guest_gets_no_evaluations_complete(
    api: AsUser, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    """Review S3: the count of evaluations is the evaluation area."""
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await make_idea(db_session, team.project, owner=team.owner, status=IdeaStatus.EVALUATING)
    key = key_of(team.project, idea)
    await add_evaluator(db_session, idea, team.evaluators[0])
    await add_evaluator(db_session, idea, team.evaluators[1], state=EvaluatorState.SUBMITTED)
    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == team.project.id, ProjectMember.user_id == team.owner.id
        )
    )
    await db_session.commit()
    ok(await assign(await api(team.admin), key, team.owner))  # R now, still its owner

    ok(
        await (await api(team.evaluators[0])).put(
            f"/ideas/{key}/evaluations/me",
            {"scores": full_scores(team), "recommendation": "go", "submit": True},
        )
    )

    assert await outbox.notifications(team.owner.id, NotificationType.EVALUATIONS_COMPLETE) == []
    guest = ok(await (await api(team.owner)).get(f"/ideas/{key}"))
    assert guest["permissions"]["can_view_project"] is False
    assert guest["score"] is None


async def test_the_preview_renders_both_templates() -> None:
    contents = sample_contents()

    for name in ("researcher_assigned", "research_reminder"):
        rendered = render(contents[name])
        assert "TOOLS-12" in rendered.html
        assert "?research=1" in rendered.text
        assert not FORBIDDEN.search(rendered.html.replace(GUEST_LINE, ""))
    assert GUEST_LINE in render(contents["researcher_assigned"]).text
