"""Unused images expire (contract-phase4 sections 3.11 and 3.13): images no profile
references are deleted by the hourly cleanup 24 hours after upload; referenced ones
never; an image a save is checking right now is skipped; and an image that vanishes
under a save is a 422 ``invalid_asset``, never a 500."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.principal import Principal
from app.models.base import utcnow
from app.models.branding import BrandAsset
from app.notifications.schedule import run_schedule
from app.schemas.branding import BrandingUpdate
from app.services import brand_assets, branding
from tests.branding.conftest import AsUser, Team, assert_problem, ok, upload
from tests.branding.images import png


async def _age(db: AsyncSession, asset_id: str, hours: float) -> None:
    await db.execute(
        update(BrandAsset)
        .where(BrandAsset.id == asset_id)
        .values(created_at=utcnow() - timedelta(hours=hours))
    )
    await db.commit()


async def _ids(db: AsyncSession) -> set[str]:
    return {str(asset_id) for asset_id in await db.scalars(select(BrandAsset.id))}


async def test_only_old_unreferenced_images_are_deleted(
    api: AsUser, team: Team, app: FastAPI, db_session: AsyncSession
) -> None:
    platform = await api(team.platform)
    used = ok(await upload(platform, png((1, 1))), 201)
    old = ok(await upload(platform, png((2, 1))), 201)
    young = ok(await upload(platform, png((3, 1))), 201)
    project_used = ok(await upload(platform, png((4, 1)), kind="favicon", slug=team.slug), 201)
    ok(await platform.put("/admin/branding", {"logo_asset_id": used["id"]}))
    ok(
        await platform.put(
            f"/projects/{team.slug}/branding", {"favicon_asset_id": project_used["id"]}
        )
    )
    for asset in (used, old, project_used):
        await _age(db_session, asset["id"], 25)
    await _age(db_session, young["id"], 23)

    async with app.state.sessionmaker() as db:
        assert await brand_assets.delete_unreferenced(db, utcnow()) == 1
        await db.commit()

    assert await _ids(db_session) == {used["id"], young["id"], project_used["id"]}
    # Releasing an image (saving without it) lets it expire on a later run.
    ok(await platform.put("/admin/branding", {}))
    async with app.state.sessionmaker() as db:
        assert await brand_assets.delete_unreferenced(db, utcnow()) == 1
        await db.commit()
    assert await _ids(db_session) == {young["id"], project_used["id"]}


async def test_the_hourly_schedule_runs_it(
    api: AsUser, team: Team, app: FastAPI, settings: Settings, db_session: AsyncSession
) -> None:
    old = ok(await upload(await api(team.platform), png()), 201)
    await _age(db_session, old["id"], 30)

    await run_schedule(app.state.sessionmaker, settings, utcnow())

    assert await _ids(db_session) == set()


async def test_an_image_being_saved_is_skipped_and_kept(
    api: AsUser, team: Team, app: FastAPI, db_session: AsyncSession
) -> None:
    platform = await api(team.platform)
    asset = ok(await upload(platform, png()), 201)
    await _age(db_session, asset["id"], 30)
    async with app.state.sessionmaker() as saving, app.state.sessionmaker() as cleaning:
        # The save checks the image (and keeps it locked) ...
        await branding._check_assets(
            saving, BrandingUpdate(logo_asset_id=asset["id"]), project_id=None
        )
        # ... so the cleanup, meanwhile, skips it instead of waiting or deleting it.
        assert await brand_assets.delete_unreferenced(cleaning, utcnow()) == 0
        await cleaning.commit()
        await branding._save(
            saving, Principal(user=team.platform), None, BrandingUpdate(logo_asset_id=asset["id"])
        )
        await saving.commit()

    async with app.state.sessionmaker() as db:
        assert await brand_assets.delete_unreferenced(db, utcnow()) == 0
        await db.commit()
    assert await _ids(db_session) == {asset["id"]}


async def test_an_image_gone_under_a_save_is_invalid_asset(
    api: AsUser, team: Team, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = await api(team.platform)
    asset = ok(await upload(platform, png()), 201)
    await db_session.execute(delete(BrandAsset))
    await db_session.commit()

    async def checked_before_it_went(*_args: Any) -> None:
        return None

    monkeypatch.setattr(branding, "_check_assets", checked_before_it_went)
    response = await platform.put("/admin/branding", {"logo_asset_id": asset["id"]})

    assert_problem(response, 422, "invalid_asset")
    assert await db_session.scalar(select(func.count()).select_from(BrandAsset)) == 0
