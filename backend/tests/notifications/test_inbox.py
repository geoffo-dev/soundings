"""The in-app inbox API (contract-phase3 section 3.2) and the bell's poll, which must
not keep a session alive."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.enums import EmailStatus
from app.models.notification import Notification, OutboundEmail
from app.models.user import User, UserSession
from tests.conftest import Login
from tests.notifications.conftest import AsUser, Outbox, Team, assert_problem, ok, only

pytestmark = pytest.mark.usefixtures("team")


async def scenario(api: AsUser, team: Team) -> dict[str, Any]:
    """Olive gets: owner_assigned, status_changed and a comment (as a watcher)."""
    member = await api(team.member)
    idea = await member.create_idea(team.slug, title="Self-service refunds")
    admin = await api(team.admin)
    ok(await admin.put(f"/ideas/{idea['key']}/owner", {"user_id": str(team.owner.id)}))
    ok(await admin.post(f"/ideas/{idea['key']}/status", {"status": "evaluating"}))
    body = "**Great** idea, see [the doc](https://x.test) @[Ada](user:" + str(team.owner.id) + ")"
    ok(await member.post(f"/ideas/{idea['key']}/comments", {"body_md": body}), 201)
    return idea


async def test_the_inbox_lists_my_notifications_newest_first(api: AsUser, team: Team) -> None:
    idea = await scenario(api, team)
    olive = await api(team.owner)

    page = ok(await olive.get("/me/notifications"))

    types = [item["type"] for item in page["items"]]
    assert types == ["mention", "status_changed", "owner_assigned"]
    mention, moved, owner = page["items"]
    assert mention["comment"]["excerpt"] == "Great idea, see the doc @Olive Owner"
    assert mention["comment"]["deleted"] is False
    assert mention["actor"]["display_name"] == "Max Member"
    assert (moved["from_label"], moved["to_label"]) == ("New", "Evaluating")
    assert owner["idea"]["key"] == idea["key"]
    assert owner["idea"]["title"] == "Self-service refunds"
    assert owner["read_at"] is None
    assert page["next_cursor"] is None
    for item in page["items"]:
        assert "score" not in str(item).lower()
        assert "aggregate" not in str(item).lower()


async def test_pages_with_a_cursor_and_the_unread_filter(api: AsUser, team: Team) -> None:
    await scenario(api, team)
    olive = await api(team.owner)

    first = ok(await olive.get("/me/notifications", limit=2))
    second = ok(await olive.get("/me/notifications", limit=2, cursor=first["next_cursor"]))
    assert [i["type"] for i in first["items"] + second["items"]] == [
        "mention",
        "status_changed",
        "owner_assigned",
    ]
    assert second["next_cursor"] is None

    ok(await olive.post(f"/me/notifications/{first['items'][0]['id']}/read"), 204)
    unread = ok(await olive.get("/me/notifications", unread="true"))
    assert [i["type"] for i in unread["items"]] == ["status_changed", "owner_assigned"]
    assert_problem(await olive.get("/me/notifications", cursor="bm9wZQ"), 400, "invalid_cursor")


async def test_mark_read_is_idempotent_and_only_for_my_own(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    await scenario(api, team)
    olive = await api(team.owner)
    note = (await outbox.notifications(team.owner.id))[0]

    ok(await olive.post(f"/me/notifications/{note.id}/read"), 204)
    first_read = (await outbox.notifications(team.owner.id))[0].read_at
    ok(await olive.post(f"/me/notifications/{note.id}/read"), 204)
    assert (await outbox.notifications(team.owner.id))[0].read_at == first_read

    other = await api(team.member)
    assert_problem(await other.post(f"/me/notifications/{note.id}/read"), 404, "not_found")


async def test_notifications_about_ideas_i_can_no_longer_view_disappear(
    api: AsUser, team: Team
) -> None:
    await scenario(api, team)
    olive = await api(team.owner)
    ok(await (await api(team.admin)).delete(f"/projects/{team.slug}/members/{team.owner.id}"), 204)

    assert ok(await olive.get("/me/notifications"))["items"] == []
    summary = ok(await olive.get("/me/notifications/summary"))
    assert summary["unread_count"] == 0


async def test_summary_counts_unread_and_read_all_clears_them(api: AsUser, team: Team) -> None:
    idea = await scenario(api, team)
    olive = await api(team.owner)

    summary = ok(await olive.get("/me/notifications/summary"))
    assert summary == {"unread_count": 3, "email_available": True, "email_trouble": False}

    after = ok(await olive.post(f"/me/notifications/read-all?idea={idea['key'].lower()}"))
    assert after["unread_count"] == 0
    assert_problem(await olive.post("/me/notifications/read-all?idea=CUST-999"), 404, "not_found")


async def test_read_all_without_an_idea(api: AsUser, team: Team) -> None:
    await scenario(api, team)
    olive = await api(team.owner)

    assert ok(await olive.post("/me/notifications/read-all"))["unread_count"] == 0


async def test_unread_count_stops_at_100(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await scenario(api, team)
    rows = [
        Notification(
            user_id=team.owner.id,
            type="owner_assigned",
            idea_id=idea["id"],
            dedupe_key=f"bulk:{n}",
            email_mode="off",
        )
        for n in range(120)
    ]
    db_session.add_all(rows)
    await db_session.commit()

    olive = await api(team.owner)
    assert ok(await olive.get("/me/notifications/summary"))["unread_count"] == 100


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_without_smtp_email_is_unavailable(api: AsUser, team: Team) -> None:
    summary = ok(await (await api(team.platform)).get("/me/notifications/summary"))

    assert summary == {"unread_count": 0, "email_available": False, "email_trouble": False}


async def test_email_trouble_is_for_platform_admins_only(
    api: AsUser, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    await scenario(api, team)
    platform, member = await api(team.platform), await api(team.member)
    assert ok(await platform.get("/me/notifications/summary"))["email_trouble"] is False

    stuck = (await outbox.emails())[0]
    await outbox.set(OutboundEmail, stuck.id, created_at=utcnow() - timedelta(minutes=16))
    assert ok(await platform.get("/me/notifications/summary"))["email_trouble"] is True
    assert ok(await member.get("/me/notifications/summary"))["email_trouble"] is False

    await outbox.set(
        OutboundEmail,
        stuck.id,
        status=EmailStatus.FAILED,
        next_attempt_at=None,
        created_at=utcnow() - timedelta(days=2),
    )
    assert ok(await platform.get("/me/notifications/summary"))["email_trouble"] is True
    await db_session.execute(
        update(OutboundEmail)
        .where(OutboundEmail.id == stuck.id)
        .values(updated_at=utcnow() - timedelta(hours=25))
    )
    await db_session.commit()
    assert ok(await platform.get("/me/notifications/summary"))["email_trouble"] is False


# --- The poll isn't activity ---------------------------------------------------------------
async def test_polling_the_summary_does_not_keep_the_session_alive(
    app: FastAPI, login: Login, team: Team, db_session: AsyncSession
) -> None:
    owner_id = team.owner.id
    http = await login(team.owner)
    old = utcnow() - timedelta(hours=2)
    await db_session.execute(update(UserSession).values(last_seen_at=old))
    await db_session.execute(update(User).where(User.id == owner_id).values(last_seen_at=old))
    await db_session.commit()

    assert (await http.get("/api/v1/me/notifications/summary")).status_code == 200

    session_seen = await db_session.scalar(select(UserSession.last_seen_at))
    user_seen = await db_session.scalar(select(User.last_seen_at).where(User.id == owner_id))
    assert session_seen == old
    assert user_seen == old
    # Any other request is activity.
    assert (await http.get("/api/v1/me/notifications")).status_code == 200
    touched = await db_session.scalar(select(UserSession.last_seen_at))
    assert touched is not None
    assert touched > old


async def test_an_idle_session_gets_401_from_the_poll(
    login: Login, team: Team, db_session: AsyncSession
) -> None:
    http = await login(team.owner)
    await db_session.execute(
        update(UserSession).values(last_seen_at=utcnow() - timedelta(hours=13))
    )
    await db_session.commit()

    response = await http.get("/api/v1/me/notifications/summary")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_signed_out_requests_get_401(client: Any) -> None:
    for path in ("/api/v1/me/notifications", "/api/v1/me/notifications/summary"):
        assert (await client.get(path)).status_code == 401


def test_only_is_strict() -> None:
    with pytest.raises(AssertionError):
        only([1, 2])
