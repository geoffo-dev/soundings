"""Security review P7 L4: a signed-in person may make at most
``SOUNDINGS_SESSION_WRITES_PER_MINUTE`` changes a minute (default 120), then 429
``rate_limited`` with ``Retry-After``. Reads, other people and sign-out are unaffected."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import ProjectRole
from tests.conftest import Login
from tests.factories import make_idea, make_project, make_user

API = "/api/v1"
LIMIT = 10


def test_the_default_is_120_writes_a_minute(settings: Settings) -> None:
    assert Settings.model_fields["session_writes_per_minute"].default == 120


@pytest.mark.settings(session_writes_per_minute=LIMIT)
async def test_writes_past_the_limit_get_429_rate_limited(
    login: Login, db_session: AsyncSession
) -> None:
    max_ = await make_user(db_session, "Max Member")
    nia = await make_user(db_session, "Nia Neighbour")
    project = await make_project(
        db_session, members={max_: ProjectRole.MEMBER, nia: ProjectRole.MEMBER}
    )
    idea = await make_idea(db_session, project, title="Watch me")
    first = await login(max_)
    second = await login(max_)  # another session of the same person shares the budget
    other = await login(nia)
    watch = f"{API}/ideas/{idea.id}/watch"

    statuses = [(await (first if n % 2 else second).put(watch)).status_code for n in range(LIMIT)]
    refused = await first.put(watch)
    read = await first.get(f"{API}/ideas/{idea.id}")
    elsewhere = await other.put(watch)
    signed_out = await first.post(f"{API}/auth/logout")

    assert statuses == [200] * LIMIT
    assert refused.status_code == 429
    assert refused.headers["content-type"] == "application/problem+json"
    assert refused.json()["code"] == "rate_limited"
    assert 1 <= int(refused.headers["retry-after"]) <= 60
    assert read.status_code == 200
    assert elsewhere.status_code == 200
    assert signed_out.status_code == 204


@pytest.mark.settings(session_writes_per_minute=LIMIT)
async def test_a_refused_write_is_not_counted_and_needs_csrf_first(
    login: Login, db_session: AsyncSession, client: httpx.AsyncClient
) -> None:
    max_ = await make_user(db_session, "Max Member")
    project = await make_project(db_session, members={max_: ProjectRole.MEMBER})
    idea = await make_idea(db_session, project)
    http = await login(max_)
    watch = f"{API}/ideas/{idea.id}/watch"
    token = http.headers.pop("X-CSRF-Token")

    forged = [(await http.put(watch)).status_code for _ in range(LIMIT + 2)]
    http.headers["X-CSRF-Token"] = token
    allowed = [(await http.put(watch)).status_code for _ in range(LIMIT)]

    assert set(forged) == {403}  # csrf_failed: not counted against the person
    assert allowed == [200] * LIMIT
    assert (await http.put(watch)).status_code == 429
