"""Personal data of public submitters (contract-phase4 section 3.9): who sees the name
and the contact details, an admin erasing them, and the retention rules with a moved
clock."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import HoldReason, IdeaStatus, Resolution
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.public import AltchaUsedChallenge, PublicSubmission
from app.public import retention
from tests.public.conftest import (
    PUBLIC,
    AsUser,
    Team,
    assert_problem,
    make_public_idea,
    ok,
    send,
    submitted,
)

pytestmark = pytest.mark.usefixtures("form")


async def public_idea(anon: httpx.AsyncClient, team: Team, db: AsyncSession) -> tuple[str, Idea]:
    receipt = ok(
        await send(anon, team.slug, name="Jo", email="jo@example.org", wants_updates=True), 201
    )
    _, idea = await submitted(db)
    await db.execute(update(Idea).where(Idea.id == idea.id).values(held_for=None))
    await db.commit()
    return receipt["tracking_token"], idea


# --- Who sees what ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("who", "contact"),
    [("admin", True), ("platform", True), ("owner", False), ("member", False), ("viewer", False)],
)
async def test_the_name_is_shown_to_viewers_the_contact_only_to_admins(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    who: str,
    contact: bool,
) -> None:
    _, idea = await public_idea(anon, team, db_session)

    body = ok(await (await api(getattr(team, who))).get(f"/ideas/{idea.id}/submission"))

    assert body["name"] == "Jo"
    assert body["held_for"] is None
    assert body["erased_at"] is None
    if contact:
        assert body["contact"] == {
            "email": "jo@example.org",
            "email_verified": False,
            "wants_updates": True,
        }
        assert body["permissions"] == {"can_moderate": False, "can_erase": True}
    else:
        assert body["contact"] is None
        assert body["permissions"] == {"can_moderate": False, "can_erase": False}


async def test_an_internal_idea_has_no_submission(api: AsUser, team: Team) -> None:
    idea = await (await api(team.member)).create_idea(team.slug)

    response = await (await api(team.admin)).get(f"/ideas/{idea['id']}/submission")

    assert_problem(response, 404, "not_found")


async def test_admins_see_the_moderation_permission_while_held(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, held = await make_public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)

    body = ok(await (await api(team.admin)).get(f"/ideas/{held.id}/submission"))
    detail = ok(await (await api(team.admin)).get(f"/ideas/{held.id}"))

    assert body["held_for"] == "moderation"
    assert body["permissions"] == {"can_moderate": True, "can_erase": True}
    assert (detail["held_for"], detail["via_public_form"]) == ("moderation", True)


async def test_internal_ideas_are_not_via_the_public_form(api: AsUser, team: Team) -> None:
    idea = await (await api(team.member)).create_idea(team.slug)

    detail = ok(await (await api(team.member)).get(f"/ideas/{idea['id']}"))

    assert (detail["held_for"], detail["via_public_form"]) == (None, False)


# --- An admin erases ------------------------------------------------------------------------
async def test_an_admin_erases_the_submitters_details(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    token, idea = await public_idea(anon, team, db_session)
    admin = await api(team.admin)

    body = ok(await admin.post(f"/ideas/{idea.id}/submission/erase"))
    again = ok(await admin.post(f"/ideas/{idea.id}/submission/erase"))

    assert body["name"] is None
    assert body["contact"] == {"email": None, "email_verified": False, "wants_updates": False}
    assert body["erased_at"] is not None
    assert body["permissions"]["can_erase"] is False
    assert again["erased_at"] == body["erased_at"]  # idempotent
    row = await db_session.scalar(
        select(PublicSubmission).execution_options(populate_existing=True)
    )
    assert row is not None
    assert row.erased_by_id == team.admin.id
    assert (row.tracking_token_hash, row.submitted_title) == (None, None)
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 0
    entries = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "submission.erase"))
    )
    assert len(entries) == 1  # the second call changed nothing
    assert entries[0].actor_id == team.admin.id
    assert entries[0].details["rule"] == "public.erase_submitter"
    assert "jo@example.org" not in str(entries[0].details)
    assert "Jo" not in str(entries[0].details.get("rule"))
    # The link stops working; the idea stays.
    assert_problem(await anon.post(f"{PUBLIC}/track", json={"token": token}), 404, "not_found")
    assert ok(await admin.get(f"/ideas/{idea.id}"))["title"] == "Recycle packaging at the till"


@pytest.mark.parametrize("who", ["owner", "member"])
async def test_only_admins_may_erase(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession, who: str
) -> None:
    _, idea = await public_idea(anon, team, db_session)

    response = await (await api(getattr(team, who))).post(f"/ideas/{idea.id}/submission/erase")

    assert_problem(response, 403, "forbidden")


async def test_admins_may_erase_an_idea_held_for_moderation(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, held = await make_public_idea(
        db_session, settings, team, held_for=HoldReason.MODERATION, email="jo@example.org"
    )

    body = ok(await (await api(team.admin)).post(f"/ideas/{held.id}/submission/erase"))

    assert body["erased_at"] is not None


# --- Retention (hourly cleanup) --------------------------------------------------------------
async def run(db: AsyncSession, now: datetime) -> retention.RetentionResult:
    result = await retention.cleanup(db, now)
    await db.commit()
    return result


async def test_expired_challenges_are_forgotten(db_session: AsyncSession) -> None:
    now = utcnow()
    db_session.add_all(
        [
            AltchaUsedChallenge(signature="a" * 64, expires_at=now - timedelta(seconds=1)),
            AltchaUsedChallenge(signature="b" * 64, expires_at=now + timedelta(minutes=5)),
        ]
    )
    await db_session.commit()

    assert (await run(db_session, now)).challenges == 1

    left = list(await db_session.scalars(select(AltchaUsedChallenge.signature)))
    assert left == ["b" * 64]


async def test_ideas_never_confirmed_are_deleted_after_three_days(
    db_session: AsyncSession, settings: Settings, team: Team
) -> None:
    _, old = await make_public_idea(
        db_session, settings, team, held_for=HoldReason.EMAIL_VERIFICATION, email="a@example.org"
    )
    _, recent = await make_public_idea(
        db_session,
        settings,
        team,
        title="Recent",
        held_for=HoldReason.EMAIL_VERIFICATION,
        email="b@example.org",
    )
    _, moderated = await make_public_idea(
        db_session, settings, team, title="Moderated", held_for=HoldReason.MODERATION
    )
    now = utcnow() + timedelta(days=2)
    await db_session.execute(
        update(Idea)
        .where(Idea.id.in_([old.id, moderated.id]))
        .values(created_at=now - timedelta(days=3, minutes=1))
    )
    await db_session.commit()

    assert (await run(db_session, now)).unconfirmed_ideas == 1

    remaining = set(await db_session.scalars(select(Idea.id)))
    assert remaining == {recent.id, moderated.id}


async def test_unconfirmed_addresses_are_forgotten_after_three_days(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    token, _ = await public_idea(anon, team, db_session)
    later = utcnow() + timedelta(days=3, minutes=1)

    assert (await run(db_session, later)).addresses == 1

    row, _ = await submitted(db_session)
    assert (row.email, row.wants_updates, row.erased_at) == (None, False, None)
    assert row.name == "Jo"  # only the address goes
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 0
    tracked = ok(await anon.post(f"{PUBLIC}/track", json={"token": token}))
    assert tracked["email_hint"] is None


async def test_confirmed_addresses_are_kept(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    await public_idea(anon, team, db_session)
    await db_session.execute(update(PublicSubmission).values(email_verified_at=utcnow()))
    await db_session.commit()

    assert (await run(db_session, utcnow() + timedelta(days=30))).addresses == 0

    row, _ = await submitted(db_session)
    assert row.email == "jo@example.org"


async def test_details_are_erased_180_days_after_a_closed_ideas_last_activity(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    token, idea = await public_idea(anon, team, db_session)
    await db_session.execute(update(PublicSubmission).values(email_verified_at=utcnow()))
    await db_session.execute(
        update(Idea)
        .where(Idea.id == idea.id)
        .values(status=IdeaStatus.CLOSED, resolution=Resolution.REJECTED)
    )
    await db_session.commit()
    now = utcnow()

    assert (await run(db_session, now + timedelta(days=179))).erased == 0
    assert (await run(db_session, now + timedelta(days=181))).erased == 1
    assert (await run(db_session, now + timedelta(days=182))).erased == 0

    row, _ = await submitted(db_session)
    assert row.erased_at is not None
    assert row.erased_by_id is None
    [entry] = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "submission.erase"))
    )
    assert (entry.actor_id, entry.details) == (None, {"reason": "retention"})
    assert_problem(await anon.post(f"{PUBLIC}/track", json={"token": token}), 404, "not_found")


async def test_open_ideas_keep_their_submitters_details(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    await public_idea(anon, team, db_session)
    await db_session.execute(update(PublicSubmission).values(email_verified_at=utcnow()))
    await db_session.commit()

    assert (await run(db_session, utcnow() + timedelta(days=400))).erased == 0
