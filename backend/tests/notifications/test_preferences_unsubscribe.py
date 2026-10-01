"""Email preferences (contract-phase3 section 3.4) and unsubscribe links (3.5)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import NotificationMode, NotificationType
from app.models.notification import NotificationPreference
from app.models.user import User
from app.notifications.unsubscribe import make_token, read_token
from app.schemas.notifications import UnsubscribeScope
from tests.notifications.conftest import AsUser, Team, assert_problem, ok

pytestmark = pytest.mark.usefixtures("team")

API = "/api/v1"


def modes(body: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {item["type"]: (item["mode"], item["default_mode"]) for item in body["items"]}


async def test_defaults_then_an_override_then_back_to_the_default(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    olive = await api(team.owner)

    body = ok(await olive.get("/me/notification-preferences"))
    assert body["email_available"] is True
    assert (body["digest_hour"], body["timezone"]) == (8, "UTC")
    assert [item["type"] for item in body["items"]] == [t.value for t in NotificationType]
    assert modes(body)["comment"] == ("digest", "digest")
    assert modes(body)["mention"] == ("immediate", "immediate")

    body = ok(
        await olive.patch("/me/notification-preferences", {"comment": "off", "mention": None})
    )
    assert modes(body)["comment"] == ("off", "digest")
    assert modes(body)["mention"] == ("immediate", "immediate")
    stored = await db_session.scalar(select(func.count()).select_from(NotificationPreference))
    assert stored == 1

    body = ok(await olive.patch("/me/notification-preferences", {"comment": "digest"}))
    assert modes(body)["comment"] == ("digest", "digest")
    stored = await db_session.scalar(select(func.count()).select_from(NotificationPreference))
    assert stored == 0


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_preferences_say_when_email_is_off(api: AsUser, team: Team) -> None:
    body = ok(await (await api(team.owner)).get("/me/notification-preferences"))

    assert body["email_available"] is False


async def test_preferences_need_a_session(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/me/notification-preferences")

    assert response.status_code == 401


# --- Tokens ----------------------------------------------------------------------------------
def test_tokens_round_trip_and_refuse_tampering(settings: Settings) -> None:
    user_id = uuid4()
    token = make_token(settings, user_id, UnsubscribeScope.COMMENT)
    found = read_token(settings, token)

    assert found is not None
    assert (found.user_id, found.scope) == (user_id, UnsubscribeScope.COMMENT)
    assert all(c.isalnum() or c in "_.-" for c in token)
    body, _, signature = token.partition(".")
    other = settings.model_copy(update={"secret_key": SecretStr("another-secret-key-0123456789")})
    for forged in (
        token[:-2],
        body + "." + signature[::-1],
        body,
        make_token(other, user_id, UnsubscribeScope.COMMENT),
        "e30." + signature,  # {} with a stolen signature
    ):
        assert read_token(settings, forged) is None


# --- The routes ----------------------------------------------------------------------------
async def info(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.get(
        f"{API}/unsubscribe", params={"token": token}, headers={"Accept": "application/json"}
    )


async def test_get_describes_the_link_and_changes_nothing(
    client: httpx.AsyncClient, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    token = make_token(settings, team.owner.id, UnsubscribeScope.COMMENT)

    body = ok(await info(client, token))

    assert body["scope"] == "comment"
    assert body["types"] == ["comment"]
    assert body["unsubscribed"] is False
    assert body["email_hint"] == "o•••@example.com"
    assert await db_session.scalar(select(func.count()).select_from(NotificationPreference)) == 0


async def test_a_browser_opening_the_header_url_is_sent_to_the_page(
    client: httpx.AsyncClient,
) -> None:
    token = "anything-at-all-0123456789"

    response = await client.get(
        f"{API}/unsubscribe",
        params={"token": token},
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"http://testserver/unsubscribe?token={token}"


async def test_one_click_post_without_cookies_turns_the_type_off(
    client: httpx.AsyncClient, settings: Settings, team: Team, api: AsUser
) -> None:
    token = make_token(settings, team.owner.id, UnsubscribeScope.MENTION)

    response = await client.post(
        f"{API}/unsubscribe",
        params={"token": token},
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    body = ok(response)
    assert (body["scope"], body["types"], body["unsubscribed"]) == ("mention", ["mention"], True)
    prefs = ok(await (await api(team.owner)).get("/me/notification-preferences"))
    assert modes(prefs)["mention"] == ("off", "immediate")
    # Idempotent; GET now says it is done.
    ok(await client.post(f"{API}/unsubscribe", params={"token": token}))
    assert ok(await info(client, token))["unsubscribed"] is True


async def test_the_digest_link_turns_off_every_digest_type(
    client: httpx.AsyncClient, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    db_session.add(
        NotificationPreference(
            user_id=team.owner.id,
            type=NotificationType.MENTION,
            mode=NotificationMode.DIGEST,
        )
    )
    await db_session.commit()
    token = make_token(settings, team.owner.id, UnsubscribeScope.DIGEST)

    before = ok(await info(client, token))
    after = ok(await client.post(f"{API}/unsubscribe", params={"token": token}))

    assert before["types"] == ["status_changed", "comment", "mention"]
    assert after["types"] == ["status_changed", "comment", "mention"]
    rows = await db_session.execute(
        select(NotificationPreference.type, NotificationPreference.mode).where(
            NotificationPreference.user_id == team.owner.id
        )
    )
    assert dict(rows.all()) == {
        NotificationType.STATUS_CHANGED: NotificationMode.OFF,
        NotificationType.COMMENT: NotificationMode.OFF,
        NotificationType.MENTION: NotificationMode.OFF,
    }


async def test_the_all_link_turns_off_everything(
    client: httpx.AsyncClient, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    """The footer's "Unsubscribe from all email" link carries the only token scoped to
    all; all=true with it changes nothing more."""
    token = make_token(settings, team.owner.id, UnsubscribeScope.ALL)
    every = [t.value for t in NotificationType]

    before = ok(await info(client, token))
    body = ok(await client.post(f"{API}/unsubscribe", params={"token": token}))
    again = ok(await client.post(f"{API}/unsubscribe", params={"token": token, "all": "true"}))

    assert (before["scope"], before["types"], before["unsubscribed"]) == ("all", every, False)
    assert (body["scope"], body["types"], body["unsubscribed"]) == ("all", every, True)
    assert (again["scope"], again["types"]) == ("all", every)
    rows = await db_session.scalars(
        select(NotificationPreference.mode).where(NotificationPreference.user_id == team.owner.id)
    )
    assert list(rows) == [NotificationMode.OFF] * len(NotificationType)


@pytest.mark.parametrize("scope", [UnsubscribeScope.COMMENT, UnsubscribeScope.DIGEST])
async def test_a_type_or_digest_link_cannot_turn_off_every_email(
    client: httpx.AsyncClient,
    settings: Settings,
    team: Team,
    db_session: AsyncSession,
    scope: UnsubscribeScope,
) -> None:
    """Lead decision L8: a link that turns off one type (or the digest) can't be
    widened with all=true, so a forwarded email can't silence its recipient entirely.
    The token is still checked first (404 before 403)."""
    token = make_token(settings, team.owner.id, scope)

    response = await client.post(f"{API}/unsubscribe", params={"token": token, "all": "true"})

    assert_problem(response, 403, "insufficient_scope")
    stored = await db_session.scalar(
        select(func.count())
        .select_from(NotificationPreference)
        .where(NotificationPreference.user_id == team.owner.id)
    )
    assert stored == 0
    assert ok(await info(client, token))["unsubscribed"] is False
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    assert_problem(
        await client.post(f"{API}/unsubscribe", params={"token": forged, "all": "true"}),
        404,
        "not_found",
    )


async def test_invalid_tokens_and_inactive_users_get_404(
    client: httpx.AsyncClient, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    valid = make_token(settings, team.owner.id, UnsubscribeScope.COMMENT)
    unknown = make_token(settings, uuid4(), UnsubscribeScope.COMMENT)
    for token in (valid[:-3], unknown, valid.replace(".", ".x", 1)):
        assert_problem(await info(client, token), 404, "not_found")
        assert_problem(
            await client.post(f"{API}/unsubscribe", params={"token": token}), 404, "not_found"
        )
    await db_session.execute(update(User).where(User.id == team.owner.id).values(is_active=False))
    await db_session.commit()
    assert_problem(await info(client, valid), 404, "not_found")
