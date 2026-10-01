"""Uploading and serving logos and favicons (contract-phase4 section 3.11): raw bodies,
the bytes decide, size and daily limits, sha256 dedupe, and serving with a fixed type,
``nosniff``, a sandboxing CSP, immutable caching and ETags."""

from __future__ import annotations

import hashlib
import io
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branding import BrandAsset
from app.services.brand_assets import ASSET_CSP, UPLOADS_PER_DAY
from tests.branding.conftest import API, AsUser, Team, assert_problem, ok, upload
from tests.branding.images import FIGMA_LOGO, png, png_with_metadata

IMMUTABLE = "public, max-age=31536000, immutable"


async def test_a_png_is_stored_re_encoded_and_served_with_safe_headers(
    client: httpx.AsyncClient, api: AsUser, team: Team
) -> None:
    platform = await api(team.platform)

    asset = ok(await upload(platform, png_with_metadata()), 201)

    assert asset["kind"] == "logo"
    assert asset["content_type"] == "image/png"
    assert (asset["width"], asset["height"]) == (64, 32)
    assert asset["url"] == f"{API}/branding/assets/{asset['id']}"
    served = await client.get(asset["url"])  # public: no session
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-security-policy"] == ASSET_CSP
    assert served.headers["cache-control"] == IMMUTABLE
    assert served.headers["content-disposition"] == 'inline; filename="logo.png"'
    assert served.headers["etag"] == f'"{hashlib.sha256(served.content).hexdigest()}"'
    assert asset["byte_size"] == len(served.content)
    assert b"eXIf" not in served.content
    assert b"tEXt" not in served.content
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.size == (64, 32)


async def test_an_svg_is_stored_re_serialised_and_sandboxed(
    client: httpx.AsyncClient, api: AsUser, team: Team
) -> None:
    project_admin = await api(team.admin)

    # The header is only a hint: the bytes decide.
    asset = ok(
        await upload(
            project_admin, FIGMA_LOGO, kind="favicon", slug=team.slug, content_type="image/png"
        ),
        201,
    )

    assert asset["content_type"] == "image/svg+xml"
    assert (asset["width"], asset["height"]) == (120, 32)
    served = await client.get(asset["url"])
    assert served.headers["content-type"] == "image/svg+xml"
    assert served.headers["content-security-policy"] == ASSET_CSP
    assert served.headers["content-disposition"] == 'inline; filename="favicon.svg"'
    assert served.content.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns=')
    assert b"<!--" not in served.content


async def test_etags_answer_304(client: httpx.AsyncClient, api: AsUser, team: Team) -> None:
    asset = ok(await upload(await api(team.platform), png()), 201)
    etag = (await client.get(asset["url"])).headers["etag"]

    for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        cached = await client.get(asset["url"], headers={"If-None-Match": header})
        assert cached.status_code == 304, header
        assert cached.content == b""
        assert cached.headers["etag"] == etag
        assert cached.headers["cache-control"] == IMMUTABLE
    fresh = await client.get(asset["url"], headers={"If-None-Match": '"stale"'})
    assert fresh.status_code == 200


async def test_unknown_images_are_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/branding/assets/4d3c2b1a-0f9e-4d8c-b7a6-5f4e3d2c1b0a")
    assert_problem(response, 404, "not_found")


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"<!DOCTYPE html><script>alert(1)</script>", id="html"),
        pytest.param(b"GIF89a\x01\x00\x01\x00", id="gif"),
        pytest.param(b"", id="empty"),
        pytest.param(
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', id="svg-onload"
        ),
    ],
)
async def test_anything_else_is_refused_and_nothing_stored(
    api: AsUser, team: Team, db_session: AsyncSession, data: bytes
) -> None:
    response = await upload(await api(team.platform), data)

    assert_problem(response, 422, "invalid_image")
    assert await db_session.scalar(select(func.count()).select_from(BrandAsset)) == 0


@pytest.mark.settings(branding_max_upload_bytes=16 * 1024)
async def test_uploads_over_the_limit_are_413(api: AsUser, team: Team) -> None:
    platform = await api(team.platform)
    big = png((512, 512), "RGB", colour=(1, 2, 3)) + b"\0" * (17 * 1024)

    assert_problem(await upload(platform, big), 413, "content_too_large")
    assert_problem(await upload(platform, b"\0" * (1024 * 1024 + 1)), 413, "content_too_large")


async def test_the_same_bytes_again_are_the_same_image(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    platform = await api(team.platform)

    first = ok(await upload(platform, png()), 201)
    again = ok(await upload(platform, png()), 201)
    as_favicon = ok(await upload(platform, png(), kind="favicon"), 201)
    for_project = ok(await upload(platform, png(), slug=team.slug), 201)

    assert again == first
    assert as_favicon["id"] != first["id"]  # another kind
    assert for_project["id"] != first["id"]  # another profile
    assert await db_session.scalar(select(func.count()).select_from(BrandAsset)) == 3


async def test_an_unused_image_near_its_expiry_is_stored_again(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    platform = await api(team.platform)
    first = ok(await upload(platform, png()), 201)
    used = ok(await upload(platform, png((8, 8)), kind="favicon"), 201)
    ok(await platform.put("/admin/branding", {"favicon_asset_id": used["id"]}))
    await db_session.execute(
        update(BrandAsset).values(
            created_at=BrandAsset.created_at - func.make_interval(0, 0, 0, 0, 20)
        )
    )
    await db_session.commit()

    again = ok(await upload(platform, png()), 201)
    used_again = ok(await upload(platform, png((8, 8)), kind="favicon"), 201)

    assert again["id"] != first["id"]  # the old one may expire any minute
    assert used_again["id"] == used["id"]  # in use: never expires


async def test_each_profile_may_add_twenty_images_a_day(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    project_admin = await api(team.admin)
    platform = await api(team.platform)
    for n in range(UPLOADS_PER_DAY):
        ok(await upload(project_admin, png((n + 1, 1)), slug=team.slug), 201)

    refused = await upload(project_admin, png((99, 1)), slug=team.slug)

    assert_problem(refused, 429, "too_many_attempts")
    assert 0 < int(refused.headers["Retry-After"]) <= 24 * 3600
    # An image already uploaded is still answered (no new row), and other profiles
    # have their own quota.
    assert (await upload(project_admin, png((1, 1)), slug=team.slug)).status_code == 201
    assert (await upload(platform, png((99, 1)))).status_code == 201
    # A day later there is room again.
    await db_session.execute(
        update(BrandAsset).values(created_at=BrandAsset.created_at - func.make_interval(0, 0, 0, 1))
    )
    await db_session.commit()
    assert (await upload(project_admin, png((99, 1)), slug=team.slug)).status_code == 201


async def test_uploads_need_a_session_and_the_rule(
    client: httpx.AsyncClient, api: AsUser, team: Team
) -> None:
    anonymous = await client.post(
        f"{API}/admin/branding/assets?kind=logo",
        content=png(),
        headers={"Content-Type": "image/png"},
    )
    assert_problem(anonymous, 401, "unauthorized")
    member = await api(team.member)
    assert_problem(await upload(member, png(), slug=team.slug), 403, "forbidden")
    project_admin = await api(team.admin)
    assert_problem(await upload(project_admin, png()), 403, "forbidden")  # not global


async def test_uploads_need_the_csrf_header(api: AsUser, team: Team) -> None:
    platform = await api(team.platform)
    headers: dict[str, Any] = {"Content-Type": "image/png"}
    platform.http.headers.pop("X-CSRF-Token")

    response = await platform.http.post(
        f"{API}/admin/branding/assets?kind=logo", content=png(), headers=headers
    )

    assert_problem(response, 403, "csrf_failed")
