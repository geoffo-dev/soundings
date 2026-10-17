"""Phase 11: erasure and retention of the conversation with a public submitter
(contract-phase11 section 10): every erasure path deletes the conversation and every
submitter email of the idea (queued and sent); rule 3 keeps the conversation and stops the
emails; rule 4 counts the latest message as activity (in its candidate query, review S3,
and again under the lock); rule 5 sweeps what an older release's erasure left behind;
deleting or rejecting the idea deletes it with the submission."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.base import utcnow
from app.models.enums import (
    SUBMITTER_EMAIL_TYPES,
    EmailStatus,
    EmailType,
    HoldReason,
    IdeaStatus,
    Resolution,
)
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.public import PublicSubmission, SubmissionMessage
from app.public import retention
from tests.public.conftest import (
    PUBLIC,
    AsUser,
    Team,
    add_message,
    make_public_idea,
    messages_url,
    ok,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")


async def conversation(
    db: AsyncSession, settings: Settings, team: Team, api: AsUser, **values: Any
) -> tuple[str, Idea]:
    """A public idea with a confirmed address, a team message (queued email), a reply and
    one outbox row of every submitter type."""
    values.setdefault("email", "sam@example.org")
    values.setdefault("verified", True)
    token, idea = await make_public_idea(db, settings, team, **values)
    ok(await (await api(team.admin)).post(messages_url(idea), {"body": "Which stores?"}), 201)
    await add_message(db, idea, "submitter", body="The two in town.")
    for type_ in SUBMITTER_EMAIL_TYPES:
        if type_ is not EmailType.SUBMISSION_MESSAGE:
            db.add(
                OutboundEmail(
                    type=type_,
                    to_address=values["email"],
                    idea_id=idea.id,
                    message_id=f"<{type_.value}.{idea.id}@testserver>",
                )
            )
    await db.commit()
    await db.execute(
        update(OutboundEmail)
        .where(OutboundEmail.type == EmailType.SUBMISSION_STATUS_CHANGED)
        .values(status=EmailStatus.SENT, sent_at=utcnow(), next_attempt_at=None)
    )
    await db.commit()
    return token, idea


async def counts(db: AsyncSession, idea: Idea) -> tuple[int, int]:
    """(messages, submitter emails) of the idea."""
    await db.commit()
    messages = await db.scalar(
        select(func.count())
        .select_from(SubmissionMessage)
        .join(PublicSubmission, PublicSubmission.id == SubmissionMessage.submission_id)
        .where(PublicSubmission.idea_id == idea.id)
    )
    emails = await db.scalar(
        select(func.count())
        .select_from(OutboundEmail)
        .where(OutboundEmail.idea_id == idea.id, OutboundEmail.type.in_(SUBMITTER_EMAIL_TYPES))
    )
    return int(messages or 0), int(emails or 0)


async def run(db: AsyncSession, now: datetime) -> retention.RetentionResult:
    result = await retention.cleanup(db, now)
    await db.commit()
    return result


async def close(db: AsyncSession, idea: Idea, *, days_ago: float = 0) -> None:
    await db.execute(
        update(Idea)
        .where(Idea.id == idea.id)
        .values(
            status=IdeaStatus.CLOSED,
            resolution=Resolution.REJECTED,
            last_activity_at=utcnow() - timedelta(days=days_ago),
        )
    )
    await db.commit()


# --- Erasure, all three paths ----------------------------------------------------------------
async def test_an_admins_erasure_deletes_the_conversation_and_every_submitter_email(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await conversation(db_session, settings, team, api)
    assert await counts(db_session, idea) == (2, 4)

    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/erase"))

    assert await counts(db_session, idea) == (0, 0)


async def test_the_submitters_own_erasure_deletes_the_conversation(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    token, idea = await conversation(db_session, settings, team, api)

    response = await anon.post(f"{PUBLIC}/track/erase", json={"token": token})

    assert response.status_code == 204, response.text
    assert await counts(db_session, idea) == (0, 0)


async def test_retention_erasure_deletes_the_conversation(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await conversation(db_session, settings, team, api)
    await close(db_session, idea)
    later = utcnow() + timedelta(days=181)

    assert (await run(db_session, later)).erased == 1

    assert await counts(db_session, idea) == (0, 0)


async def test_deleting_or_rejecting_the_idea_deletes_the_conversation(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, held = await conversation(
        db_session, settings, team, api, held_for=HoldReason.MODERATION, title="Held"
    )
    _, other = await conversation(db_session, settings, team, api, title="Other")

    ok(await (await api(team.admin)).post(f"/ideas/{held.id}/submission/reject"), 204)
    ok(await (await api(team.admin)).delete(f"/ideas/{other.id}"), 204)

    assert await db_session.scalar(select(func.count()).select_from(SubmissionMessage)) == 0


# --- Retention ----------------------------------------------------------------------------------
async def test_forgetting_an_unconfirmed_address_keeps_the_conversation(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Rule 3: the tracking page still works, team messages reach it only."""
    token, idea = await conversation(db_session, settings, team, api, verified=False)
    later = utcnow() + timedelta(days=3, minutes=1)

    assert (await run(db_session, later)).addresses == 1

    assert await counts(db_session, idea) == (2, 0)
    page = ok(await anon.post(f"{PUBLIC}/track", json={"token": token}))
    assert len(page["messages"]) == 2
    assert page["team_messages_emailed"] is False
    summary = ok(await (await api(team.admin)).get(f"/ideas/{idea.id}/submission"))
    assert summary["messages"]["delivery"] == "tracking_page"


async def test_a_live_conversation_keeps_a_closed_idea_from_being_erased(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """Rule 4: the idea's activity *and* its newest message must be 180 days old."""
    _, idea = await conversation(db_session, settings, team, api)
    await close(db_session, idea, days_ago=200)
    await db_session.execute(
        update(SubmissionMessage).values(created_at=utcnow() - timedelta(days=100))
    )
    await db_session.commit()

    assert (await run(db_session, utcnow())).erased == 0
    assert (await run(db_session, utcnow() + timedelta(days=79))).erased == 0
    assert (await run(db_session, utcnow() + timedelta(days=81))).erased == 1


async def test_a_live_conversation_does_not_starve_the_next_idea(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review S3: with one idea a batch, a skipped idea (the oldest) doesn't stop the next
    one from being erased: the check is in the candidate query."""
    monkeypatch.setattr(retention, "BATCH", 1)
    _, live = await conversation(db_session, settings, team, api, title="Live")
    _, quiet = await make_public_idea(
        db_session, settings, team, title="Quiet", email="kim@example.org", verified=True
    )
    await close(db_session, live, days_ago=300)
    await close(db_session, quiet, days_ago=200)

    assert (await run(db_session, utcnow())).erased == 1

    rows = {
        row.idea_id: row.erased_at
        for row in await db_session.scalars(
            select(PublicSubmission).execution_options(populate_existing=True)
        )
    }
    assert rows[live.id] is None
    assert rows[quiet.id] is not None


async def test_a_reply_after_the_candidates_were_chosen_is_seen_under_the_lock(
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check again under the idea's and submission's locks (a reply takes the same):
    here the candidate query is made to miss the reply."""
    _, idea = await make_public_idea(
        db_session, settings, team, email="sam@example.org", verified=True
    )
    await add_message(db_session, idea, author=team.admin, at=utcnow() - timedelta(days=1))
    await close(db_session, idea, days_ago=200)
    real: Callable[..., Any] = retention._quiet_conversation
    calls: list[int] = []

    def blind_first(submission_id: Any, now: datetime) -> Any:
        calls.append(1)
        return true() if len(calls) == 1 else real(submission_id, now)

    monkeypatch.setattr(retention, "_quiet_conversation", blind_first)

    assert (await run(db_session, utcnow())).erased == 0
    assert len(calls) == 2
    row, _ = await submitted(db_session)
    assert row.erased_at is None


async def test_rule_5_sweeps_what_an_older_erasure_left_behind(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    """0.3.0's erasure (during a rollback) knew neither the conversation nor the two new
    email types: the hourly cleanup deletes both."""
    _, idea = await conversation(db_session, settings, team, api)
    await db_session.execute(
        update(PublicSubmission)
        .where(PublicSubmission.idea_id == idea.id)
        .values(
            name=None,
            email=None,
            email_verified_at=None,
            wants_updates=False,
            tracking_token_hash=None,
            tracking_token_sealed=None,
            submitted_title=None,
            submitted_summary=None,
            erased_at=utcnow(),
        )
    )
    await db_session.commit()
    assert await counts(db_session, idea) == (2, 4)

    result = await run(db_session, utcnow())

    assert result.swept == 1
    assert await counts(db_session, idea) == (0, 0)
    assert (await run(db_session, utcnow())).swept == 0
