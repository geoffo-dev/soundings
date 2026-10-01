"""Project settings -> Public form (contract-phase4 sections 3.5 and 3.12): project
admins turn the form on, require a confirmed address, moderate and write the intro;
the instance switch, reserved slugs, missing email and archived projects say no; every
change is audited as ``project.update`` with column names."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import HoldReason, ProjectRole
from app.models.project import Project
from tests.factories import make_project
from tests.moderation.conftest import (
    PUBLIC,
    AsUser,
    Team,
    assert_problem,
    make_public_idea,
    ok,
)


async def _form_off(db: AsyncSession, team: Team) -> None:
    await db.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(public_submission_enabled=False, public_intro_md="")
    )
    await db.commit()


async def test_admins_turn_the_form_on_and_it_is_audited(
    api: AsUser, team: Team, db_session: AsyncSession, anon: httpx.AsyncClient
) -> None:
    await _form_off(db_session, team)
    admin = await api(team.admin)
    path = f"/projects/{team.slug}/public-form"

    before = ok(await admin.get(path))
    assert before == {
        "available": True,
        "email_available": True,
        "enabled": False,
        "require_email_verification": False,
        "moderation_required": True,
        "intro_md": "",
        "form_url": f"http://testserver/{team.slug}/submit",
        "awaiting_moderation": 0,
    }
    assert_problem(await anon.get(f"{PUBLIC}/projects/{team.slug}"), 404, "not_found")

    after = ok(
        await admin.patch(
            path,
            {"enabled": True, "require_email_verification": True, "intro_md": "  We read all.  "},
        )
    )

    assert after["enabled"] is True
    assert after["require_email_verification"] is True
    assert after["intro_md"] == "We read all."
    assert after["moderation_required"] is True  # omitted: unchanged
    public = ok(await anon.get(f"{PUBLIC}/projects/{team.slug}"))
    assert public["intro_md"] == "We read all."
    assert public["email_required"] is True
    [entry] = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "project.update"))
    )
    assert entry.details["fields"] == [
        "public_submission_enabled",
        "public_require_email_verification",
        "public_intro_md",
    ]
    assert entry.details["rule"] == "project.edit_settings"
    assert "We read" not in str(entry.details)
    # The same values again: nothing changes, nothing is audited.
    ok(await admin.patch(path, {"enabled": True, "intro_md": "We read all."}))
    assert (
        len(
            list(
                await db_session.scalars(
                    select(AuditLog).where(AuditLog.action == "project.update")
                )
            )
        )
        == 1
    )


async def test_awaiting_moderation_counts_the_queue(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    for _ in range(2):
        await make_public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)
    await make_public_idea(db_session, settings, team, held_for=HoldReason.EMAIL_VERIFICATION)
    await make_public_idea(db_session, settings, team)

    settings_page = ok(await (await api(team.platform)).get(f"/projects/{team.slug}/public-form"))

    assert settings_page["awaiting_moderation"] == 2


@pytest.mark.settings(public_submission_enabled=False)
async def test_the_instance_switch_keeps_forms_off(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await _form_off(db_session, team)
    admin = await api(team.admin)
    path = f"/projects/{team.slug}/public-form"

    assert ok(await admin.get(path))["available"] is False
    assert_problem(await admin.patch(path, {"enabled": True}), 409, "public_submission_unavailable")
    # Other settings can still be prepared.
    assert ok(await admin.patch(path, {"intro_md": "Soon."}))["intro_md"] == "Soon."


async def test_a_reserved_slug_can_not_have_a_form(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    older = await make_project(db_session, slug="track", members={team.admin: ProjectRole.ADMIN})
    admin = await api(team.admin)

    assert ok(await admin.get(f"/projects/{older.slug}/public-form"))["available"] is False
    assert_problem(
        await admin.patch(f"/projects/{older.slug}/public-form", {"enabled": True}),
        409,
        "public_submission_unavailable",
    )


@pytest.mark.settings(smtp_host=None, smtp_from=None)
async def test_requiring_a_confirmed_address_needs_email(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    admin = await api(team.admin)
    path = f"/projects/{team.slug}/public-form"

    assert ok(await admin.get(path))["email_available"] is False
    assert_problem(
        await admin.patch(path, {"require_email_verification": True}), 409, "smtp_not_configured"
    )
    assert (
        ok(await admin.patch(path, {"require_email_verification": False}))[
            "require_email_verification"
        ]
        is False
    )


async def test_an_archived_project_can_not_change_its_form(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    admin = await api(team.admin)
    path = f"/projects/{team.slug}/public-form"

    assert ok(await admin.get(path))["available"] is False
    assert_problem(await admin.patch(path, {"moderation_required": False}), 409, "project_archived")


@pytest.mark.parametrize("body", [{"intro_md": "x" * 2_001}, {"enabled": "maybe"}, {"slug": "x"}])
async def test_invalid_settings_are_422(api: AsUser, team: Team, body: dict[str, Any]) -> None:
    response = await (await api(team.admin)).patch(f"/projects/{team.slug}/public-form", body)
    assert_problem(response, 422, "validation_error")


async def test_only_project_admins_change_the_form(api: AsUser, team: Team) -> None:
    path = f"/projects/{team.slug}/public-form"
    for user in (team.member, team.viewer):
        client = await api(user)
        assert_problem(await client.get(path), 403, "forbidden")
        assert_problem(await client.patch(path, {"enabled": False}), 403, "forbidden")
    assert_problem(await (await api(team.outsider)).get(path), 404, "not_found")
    assert (await (await api(team.platform)).patch(path, {"enabled": False})).status_code == 200


async def test_changes_apply_to_new_submissions_only(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, waiting = await make_public_idea(db_session, settings, team, held_for=HoldReason.MODERATION)
    admin = await api(team.admin)

    ok(
        await admin.patch(
            f"/projects/{team.slug}/public-form", {"moderation_required": False, "enabled": False}
        )
    )

    queue = ok(await admin.get(f"/projects/{team.slug}/moderation"))
    assert [item["id"] for item in queue["items"]] == [str(waiting.id)]
    assert (await admin.post(f"/ideas/{waiting.id}/submission/approve")).status_code == 200
