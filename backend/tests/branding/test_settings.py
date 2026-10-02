"""Branding profiles (contract-phase4 section 3.10): the global profile (Admin settings
-> Branding, ``platform.edit_branding``), project overrides (``project.edit_settings``),
resolution field by field (override -> global -> default), strict validation, audit,
and the per-process cache with invalidation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.branding import BrandingProfile
from app.models.enums import BrandFont, ProjectRole
from app.models.project import Project
from app.services import branding
from tests.branding.conftest import API, AsUser, Team, assert_problem, ok, upload
from tests.branding.images import png, svg
from tests.conftest import Login
from tests.factories import make_project, make_user

DEFAULTS = {
    "app_name": "Soundings",
    "primary_color": "#1d5fa8",
    "accent_color": "#1d5fa8",
    "font": "inter",
    "logo_url": None,
    "favicon_url": None,
}

ACME = {
    "app_name": "Acme Ideas",
    "primary_color": "#0B6E4F",
    "font": "ibm_plex_sans",
    "email_footer": "Acme Ltd\n1 High Street, London",
}


async def audit_entries(db: AsyncSession, action: str) -> list[AuditLog]:
    return list(
        await db.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
    )


# --- Global ------------------------------------------------------------------------------
async def test_without_any_profile_everything_is_the_default(
    client: Any, api: AsUser, team: Team
) -> None:
    assert ok(await client.get(f"{API}/branding")) == DEFAULTS

    settings = ok(await (await api(team.platform)).get("/admin/branding"))

    assert settings["scope"] == "global"
    for field in ("app_name", "primary_color", "accent_color", "font", "email_footer"):
        assert settings[field] is None
    assert settings["logo"] is None
    assert settings["favicon"] is None
    assert settings["inherited"] == {
        **{key: DEFAULTS[key] for key in ("app_name", "primary_color", "accent_color", "font")},
        "email_footer": None,
        "logo": None,
        "favicon": None,
    }
    assert settings["effective"] == DEFAULTS
    assert settings["updated_at"] is None
    assert settings["updated_by"] is None


async def test_a_global_save_applies_at_once_and_is_audited_by_field_name(
    client: Any, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    admin = await api(team.platform)
    assert ok(await client.get(f"{API}/branding")) == DEFAULTS  # cached now

    saved = ok(await admin.put("/admin/branding", ACME))

    assert saved["app_name"] == "Acme Ideas"
    assert saved["primary_color"] == "#0b6e4f"  # normalised
    assert saved["accent_color"] is None
    assert saved["email_footer"] == "Acme Ltd\n1 High Street, London"
    assert saved["effective"] == {
        **DEFAULTS,
        "app_name": "Acme Ideas",
        "primary_color": "#0b6e4f",
        "font": "ibm_plex_sans",
    }
    assert saved["updated_by"]["id"] == str(team.platform.id)
    assert saved["updated_at"] is not None
    # Everyone sees it straight away (the save invalidated this process's cache).
    assert ok(await client.get(f"{API}/branding")) == saved["effective"]

    [entry] = await audit_entries(db_session, "branding.update")
    assert entry.actor_id == team.platform.id
    assert entry.target_type is None
    assert entry.details["rule"] == "platform.edit_branding"
    assert entry.details["fields"] == ["app_name", "primary_color", "font", "email_footer"]
    assert "Acme" not in str(entry.details)

    # Saving the same values again changes nothing and audits nothing.
    ok(await admin.put("/admin/branding", ACME))
    assert len(await audit_entries(db_session, "branding.update")) == 1


async def test_the_put_is_the_complete_profile_and_empty_resets_it(
    client: Any, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    admin = await api(team.platform)
    ok(await admin.put("/admin/branding", ACME))

    partial = ok(await admin.put("/admin/branding", {"accent_color": "#F59E0B"}))
    assert partial["app_name"] is None  # omitted = inherit (the default)
    assert partial["effective"] == {**DEFAULTS, "accent_color": "#f59e0b"}

    reset = ok(await admin.put("/admin/branding", {}))
    assert reset["updated_at"] is None
    assert reset["effective"] == DEFAULTS
    assert await db_session.scalar(select(BrandingProfile)) is None
    assert ok(await client.get(f"{API}/branding")) == DEFAULTS
    fields = [
        entry.details["fields"] for entry in await audit_entries(db_session, "branding.update")
    ]
    assert fields[-1] == ["accent_color"]


@pytest.mark.parametrize(
    "body",
    [
        {"primary_color": "red"},
        {"primary_color": "#abc"},
        {"primary_color": "#1d5fa8;}body{background:url(//x)"},
        {"accent_color": "rgb(0,0,0)"},
        {"font": "Comic Sans MS"},
        {"font": "inter;color:red"},
        {"app_name": "Acme\nIdeas"},
        {"app_name": "A" * 41},
        {"app_name": "   "},
        {"email_footer": "a\nb\nc\nd\ne\nf"},
        {"email_footer": "x" * 501},
        {"email_footer": "Acme\u202eLtd"},
        {"css": "body{}"},
    ],
)
async def test_values_that_could_reach_css_are_validated(
    api: AsUser, team: Team, body: dict[str, Any]
) -> None:
    admin = await api(team.platform)

    assert_problem(await admin.put("/admin/branding", body), 422, "validation_error")
    assert_problem(
        await admin.put(f"/projects/{team.slug}/branding", body), 422, "validation_error"
    )


async def test_only_platform_admins_edit_the_global_branding(
    client: Any, api: AsUser, team: Team
) -> None:
    for user in (team.admin, team.member, team.viewer, team.outsider):
        member = await api(user)
        assert_problem(await member.get("/admin/branding"), 403, "forbidden")
        assert_problem(await member.put("/admin/branding", ACME), 403, "forbidden")
        assert_problem(await upload(member, png()), 403, "forbidden")
    assert_problem(await client.get(f"{API}/admin/branding"), 401, "unauthorized")
    # The effective branding is public (the sign-in page needs it).
    assert (await client.get(f"{API}/branding")).status_code == 200


# --- Projects ----------------------------------------------------------------------------
async def test_a_project_override_inherits_field_by_field(
    client: Any, api: AsUser, team: Team, app: FastAPI
) -> None:
    ok(await (await api(team.platform)).put("/admin/branding", ACME))
    project_admin = await api(team.admin)

    saved = ok(
        await project_admin.put(
            f"/projects/{team.slug}/branding",
            {"primary_color": "#7A1F5C", "font": "source_serif_4"},
        )
    )

    assert saved["scope"] == "project"
    assert saved["app_name"] is None
    assert saved["inherited"]["app_name"] == "Acme Ideas"
    assert saved["inherited"]["primary_color"] == "#0b6e4f"
    assert saved["inherited"]["email_footer"] == "Acme Ltd\n1 High Street, London"
    assert saved["effective"] == {
        **DEFAULTS,
        "app_name": "Acme Ideas",
        "primary_color": "#7a1f5c",
        "font": "source_serif_4",
    }
    # The signed-in app keeps the global branding.
    assert ok(await client.get(f"{API}/branding"))["primary_color"] == "#0b6e4f"
    # The project's outward-facing surfaces resolve the override (one function for all).
    async with app.state.sessionmaker() as db:
        resolved = await branding.resolve(db, team.project.id)
        assert resolved.primary_color == "#7a1f5c"
        assert resolved.app_name == "Acme Ideas"
        assert resolved.email_footer == "Acme Ltd\n1 High Street, London"
        assert resolved.font is BrandFont.SOURCE_SERIF_4
        assert (await branding.effective_branding(db, team.project.id)) == resolved.effective()
    assert ok(await project_admin.get(f"/projects/{team.slug}/branding")) == saved

    # A later global change shows through every field the project leaves empty.
    ok(await (await api(team.platform)).put("/admin/branding", {**ACME, "app_name": "Acme 2"}))
    async with app.state.sessionmaker() as db:
        assert (await branding.resolve(db, team.project.id)).app_name == "Acme 2"


async def test_an_empty_override_removes_it_and_saves_are_audited_as_project_updates(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    project_admin = await api(team.admin)
    ok(await project_admin.put(f"/projects/{team.slug}/branding", {"accent_color": "#f59e0b"}))

    removed = ok(await project_admin.put(f"/projects/{team.slug}/branding", {}))

    assert removed["updated_at"] is None
    assert removed["effective"] == DEFAULTS
    entries = await audit_entries(db_session, "project.update")
    assert [entry.details["fields"] for entry in entries] == [["branding"], ["branding"]]
    assert all(entry.project_id == team.project.id for entry in entries)
    assert all(entry.details["rule"] == "project.edit_settings" for entry in entries)
    assert await audit_entries(db_session, "branding.update") == []


async def test_project_branding_needs_project_edit_settings(api: AsUser, team: Team) -> None:
    path = f"/projects/{team.slug}/branding"
    for user in (team.member, team.viewer):
        client = await api(user)
        assert_problem(await client.get(path), 403, "forbidden")
        assert_problem(await client.put(path, {"accent_color": "#f59e0b"}), 403, "forbidden")
        assert_problem(await upload(client, png(), slug=team.slug), 403, "forbidden")
    outsider = await api(team.outsider)  # a private project: it doesn't exist for them
    assert_problem(await outsider.get(path), 404, "not_found")
    assert_problem(await upload(outsider, png(), slug=team.slug), 404, "not_found")
    for user in (team.admin, team.platform):
        assert (await (await api(user)).get(path)).status_code == 200


async def test_an_archived_project_keeps_its_branding_read_only(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=Project.created_at)
    )
    await db_session.commit()
    client = await api(team.admin)

    assert (await client.get(f"/projects/{team.slug}/branding")).status_code == 200
    assert_problem(
        await client.put(f"/projects/{team.slug}/branding", {"accent_color": "#f59e0b"}),
        409,
        "project_archived",
    )
    assert_problem(await upload(client, png(), slug=team.slug), 409, "project_archived")


# --- Images in profiles -------------------------------------------------------------------
async def test_images_must_belong_to_the_profile_and_kind(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    platform = await api(team.platform)
    project_admin = await api(team.admin)
    global_logo = ok(await upload(platform, png()), 201)
    global_favicon = ok(await upload(platform, png((32, 32)), kind="favicon"), 201)
    project_logo = ok(await upload(project_admin, svg("<rect/>"), slug=team.slug), 201)
    other = await make_project(db_session, members={team.admin: ProjectRole.ADMIN})
    other_logo = ok(await upload(project_admin, png((10, 10)), slug=other.slug), 201)

    saved = ok(
        await platform.put(
            "/admin/branding",
            {"logo_asset_id": global_logo["id"], "favicon_asset_id": global_favicon["id"]},
        )
    )
    assert saved["logo"] == global_logo
    assert saved["effective"]["logo_url"] == global_logo["url"]
    assert saved["effective"]["favicon_url"] == global_favicon["url"]

    refused = [
        (platform, "/admin/branding", {"logo_asset_id": project_logo["id"]}),
        (platform, "/admin/branding", {"logo_asset_id": global_favicon["id"]}),
        (platform, "/admin/branding", {"favicon_asset_id": global_logo["id"]}),
        (platform, "/admin/branding", {"logo_asset_id": "4d3c2b1a-0f9e-4d8c-b7a6-5f4e3d2c1b0a"}),
        (project_admin, f"/projects/{team.slug}/branding", {"logo_asset_id": global_logo["id"]}),
        (project_admin, f"/projects/{team.slug}/branding", {"logo_asset_id": other_logo["id"]}),
    ]
    for client, path, body in refused:
        assert_problem(await client.put(path, body), 422, "invalid_asset")

    own = ok(
        await project_admin.put(
            f"/projects/{team.slug}/branding", {"logo_asset_id": project_logo["id"]}
        )
    )
    assert own["logo"]["content_type"] == "image/svg+xml"
    assert own["inherited"]["logo"] == global_logo
    assert own["inherited"]["favicon"] == global_favicon
    assert own["effective"]["logo_url"] == project_logo["url"]
    assert own["effective"]["favicon_url"] == global_favicon["url"]  # inherited


async def test_a_project_logo_without_an_app_name_makes_the_project_name_the_wordmark(
    api: AsUser, team: Team, app: FastAPI
) -> None:
    """One identity per audience (UX review M3): a project that brings its own logo but
    no app name is its own brand, so its emails, PDF header and public pages' name say
    "Customer Innovation", not the instance's app name."""
    platform = await api(team.platform)
    ok(await platform.put("/admin/branding", ACME))
    project_admin = await api(team.admin)
    logo = ok(await upload(project_admin, png(), slug=team.slug), 201)

    # A colour of its own only: still the instance's app name.
    ok(await project_admin.put(f"/projects/{team.slug}/branding", {"primary_color": "#7a1f5c"}))
    async with app.state.sessionmaker() as db:
        assert (await branding.resolve(db, team.project.id)).app_name == "Acme Ideas"

    saved = ok(
        await project_admin.put(f"/projects/{team.slug}/branding", {"logo_asset_id": logo["id"]})
    )
    assert saved["app_name"] is None  # the override itself is unchanged
    assert saved["inherited"]["app_name"] == "Acme Ideas"
    assert saved["effective"]["app_name"] == "Customer Innovation"
    async with app.state.sessionmaker() as db:
        resolved = await branding.resolve(db, team.project.id)
        assert resolved.app_name == "Customer Innovation"
        assert resolved.email().product_name == "Customer Innovation"
        assert (await branding.effective_branding(db, team.project.id)).app_name == (
            "Customer Innovation"
        )
        # The signed-in app and other projects keep the instance's name.
        assert (await branding.resolve(db, None)).app_name == "Acme Ideas"

    # An app name of the project's own wins.
    ok(
        await project_admin.put(
            f"/projects/{team.slug}/branding",
            {"logo_asset_id": logo["id"], "app_name": "Customer Lab"},
        )
    )
    async with app.state.sessionmaker() as db:
        assert (await branding.resolve(db, team.project.id)).app_name == "Customer Lab"


# --- Cache -------------------------------------------------------------------------------
async def test_resolution_is_cached_briefly_and_invalidated_by_saves(
    api: AsUser, team: Team, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_000.0]
    monkeypatch.setattr("app.services.branding.time.monotonic", lambda: clock[0])
    sessionmaker = app.state.sessionmaker

    async with sessionmaker() as db:
        first = await branding.resolve(db, team.project.id)
        # Another replica's save (written straight to the database here) ...
        db.add(BrandingProfile(project_id=None, app_name="Elsewhere"))
        await db.commit()
        # ... shows up once the entry expires, not before.
        assert await branding.resolve(db, team.project.id) is first
        clock[0] += branding.CACHE_TTL + 0.1
        assert (await branding.resolve(db, team.project.id)).app_name == "Elsewhere"

    # A save in this process is visible at once, for the global and every project.
    ok(await (await api(team.platform)).put("/admin/branding", {"app_name": "Here"}))
    async with sessionmaker() as db:
        assert (await branding.resolve(db, None)).app_name == "Here"
        assert (await branding.resolve(db, team.project.id)).app_name == "Here"


async def test_an_uncommitted_save_is_never_cached(app: FastAPI, team: Team) -> None:
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as writer:
        writer.add(BrandingProfile(project_id=None, app_name="Not yet"))
        await writer.flush()
        await branding.resolve(writer, None, cached=False)
        branding.invalidate(writer, "all")
        await writer.rollback()
    async with sessionmaker() as reader:
        assert (await branding.resolve(reader, None)).app_name == "Soundings"


async def test_concurrent_first_saves_do_not_fail(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session, "Pat", platform_admin=True)
    clients = [await login(admin) for _ in range(4)]

    responses = await asyncio.gather(
        *(
            client.put(f"{API}/admin/branding", json={"app_name": f"Name {n}"})
            for n, client in enumerate(clients)
        )
    )

    assert [response.status_code for response in responses] == [200] * 4
    assert len(list(await db_session.scalars(select(BrandingProfile)))) == 1
