"""Fixtures for the proposal tests (docs/api/contract-phase4.md 3.1-3.4).

``team`` (tests/ideas/conftest.py) is "Customer Innovation" (key ``CUST``) with an
admin, an owner-to-be, a member, three evaluators, a viewer, an outsider and a platform
admin. ``idea`` is a Shortlisted idea there, owned by ``team.owner``; ``key`` its key.

* ``api(user)``: a signed-in client (``Api``) for that user.
* ``start(api, key)``: start the proposal (201) and return the ``ProposalView``.
* ``proposal_url(key)``: ``/ideas/<key>/proposal``.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IdeaStatus
from app.models.idea import Idea
from tests.factories import make_idea
from tests.ideas.conftest import (  # noqa: F401 - fixtures
    API,
    Api,
    AsUser,
    Team,
    api,
    assert_problem,
    ok,
    team,
)

__all__ = [
    "API",
    "SECTION_KEYS",
    "Api",
    "AsUser",
    "Team",
    "assert_problem",
    "idea_key",
    "ok",
    "proposal_url",
    "start",
]

SECTION_KEYS = [
    "summary",
    "problem",
    "solution",
    "market",
    "cost",
    "benefits",
    "risks",
    "next_steps",
]


def idea_key(team: Team, idea: Idea) -> str:  # noqa: F811 - not the fixture
    return f"{team.project.key}-{idea.number}"


def proposal_url(key: str) -> str:
    return f"/ideas/{key}/proposal"


async def start(client: Api, key: str) -> dict[str, Any]:
    view: dict[str, Any] = ok(await client.post(proposal_url(key)), 201)
    return view


@pytest.fixture
async def idea(db_session: AsyncSession, team: Team) -> Idea:  # noqa: F811 - the fixture
    return await make_idea(
        db_session,
        team.project,
        title="Self-service refunds",
        summary="Let customers refund without calling us.",
        status=IdeaStatus.SHORTLISTED,
        owner=team.owner,
        submitted_by=team.member,
    )


@pytest.fixture
def key(team: Team, idea: Idea) -> str:  # noqa: F811 - the fixtures
    return idea_key(team, idea)
