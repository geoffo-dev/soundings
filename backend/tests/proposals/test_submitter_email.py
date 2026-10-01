"""Starting a proposal moves a Shortlisted public idea to Proposal like any status
change, so an opted-in, confirmed submitter gets their status email (contract-phase4
3.1 and 3.8)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import EmailType, IdeaStatus
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from tests.notifications.conftest import SMTP
from tests.proposals.conftest import AsUser, Team, idea_key, start
from tests.public.conftest import make_public_idea


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return dict(SMTP)


async def _public_idea(db: AsyncSession, settings: Settings, team: Team, **submission: Any) -> str:
    _, idea = await make_public_idea(db, settings, team, title="Recycle packaging", **submission)
    await db.execute(
        update(Idea)
        .where(Idea.id == idea.id)
        .values(status=IdeaStatus.SHORTLISTED, owner_id=team.owner.id)
    )
    await db.commit()
    return idea_key(team, idea)


async def _submitter_emails(db: AsyncSession) -> list[OutboundEmail]:
    rows = await db.scalars(
        select(OutboundEmail).where(OutboundEmail.type == EmailType.SUBMISSION_STATUS_CHANGED)
    )
    return list(rows)


async def test_the_confirmed_opted_in_submitter_hears_about_the_move(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    key = await _public_idea(
        db_session, settings, team, email="jo@example.org", verified=True, wants_updates=True
    )

    await start(await api(team.owner), key)

    [email] = await _submitter_emails(db_session)
    assert email.to_address == "jo@example.org"
    assert email.payload["to_status"] == "proposal"
    assert email.payload["from_status"] == "shortlisted"


@pytest.mark.parametrize(
    "submission",
    [
        {"email": "jo@example.org", "verified": False, "wants_updates": True},
        {"email": "jo@example.org", "verified": True, "wants_updates": False},
        {},
    ],
)
async def test_nobody_else_is_emailed(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    submission: dict[str, Any],
) -> None:
    key = await _public_idea(db_session, settings, team, **submission)

    await start(await api(team.owner), key)

    assert await _submitter_emails(db_session) == []
