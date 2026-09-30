from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException

from app.spa import inline_script_hashes, is_backend_path

THEME_SCRIPT = "document.documentElement.dataset.theme = localStorage.theme || 'system';"
INDEX_HTML = f"""<!doctype html>
<html>
<head>
  <script>{THEME_SCRIPT}</script>
  <script type="module" crossorigin src="/assets/index-abc123.js"></script>
</head>
<body><div id="root"></div></body>
</html>
"""


def sha256_source(script: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML)
    (root / "assets" / "index-abc123.js").write_text("console.log('app')")
    (root / "favicon.svg").write_text("<svg/>")
    (root / ".env").write_text("SECRET=dotfile")
    (tmp_path / "outside.txt").write_text("outside the build")
    return root


@pytest.fixture
def settings_overrides(dist: Path) -> dict[str, Any]:
    return {"static_dir": dist}


async def test_root_serves_index_with_no_cache(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert '<div id="root">' in response.text


async def test_client_side_routes_fall_back_to_index(client: httpx.AsyncClient) -> None:
    for path in ("/ideas/5f0c", "/projects/acme/board", "/acme.io/submit"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert '<div id="root">' in response.text


async def test_csp_allows_exactly_the_inline_theme_script(client: httpx.AsyncClient) -> None:
    csp = (await client.get("/")).headers["content-security-policy"]

    script_src = next(d for d in csp.split("; ") if d.startswith("script-src "))
    assert script_src == f"script-src 'self' '{sha256_source(THEME_SCRIPT)}'"
    assert "frame-ancestors 'none'" in csp


async def test_assets_are_immutable(client: httpx.AsyncClient) -> None:
    response = await client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_missing_asset_is_a_404_problem_not_index(client: httpx.AsyncClient) -> None:
    response = await client.get("/assets/index-old.js")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_root_files_are_served_with_revalidation(client: httpx.AsyncClient) -> None:
    response = await client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.text == "<svg/>"
    assert response.headers["cache-control"] == "no-cache"


async def test_path_traversal_and_dotfiles_are_not_served(client: httpx.AsyncClient) -> None:
    for path in ("/assets/%2e%2e/%2e%2e/outside.txt", "/%2e%2e/outside.txt", "/.env"):
        response = await client.get(path)
        assert "outside the build" not in response.text, path
        assert "dotfile" not in response.text, path


@pytest.mark.parametrize(
    "path", ["/api", "/api/v1/nope", "/api/unknown", "/mcp/x", "/healthz/extra"]
)
async def test_backend_paths_keep_problem_json_404s(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_non_get_requests_do_not_fall_back(client: httpx.AsyncClient) -> None:
    response = await client.post("/ideas/5f0c")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_endpoint_404s_are_never_replaced_by_the_spa(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    router = APIRouter()

    @router.get("/auth/callback")
    async def callback() -> None:
        raise HTTPException(404)

    app.include_router(router)

    response = await client.get("/auth/callback")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.settings(static_dir=Path("/nonexistent/dist"))
async def test_without_a_build_unknown_paths_are_404_problems(client: httpx.AsyncClient) -> None:
    response = await client.get("/ideas/5f0c")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    csp = response.headers["content-security-policy"]
    assert "script-src 'self';" in csp


def test_inline_script_hashes_skip_external_and_empty_scripts() -> None:
    html = "<script src='/a.js'></script><script>\n</script><SCRIPT type='x'>a()</SCRIPT>"

    assert inline_script_hashes(html) == (sha256_source("a()"),)


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/api", True), ("/api/v1", True), ("/apiary", False), ("/metrics", True), ("/", False)],
)
def test_is_backend_path(path: str, expected: bool) -> None:
    assert is_backend_path(path) is expected
