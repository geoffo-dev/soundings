"""Swagger UI at ``/api/docs``, served entirely from vendored files (no CDN).

The assets in ``app/static/swagger`` come from the ``swagger-ui-dist`` npm package;
refresh them with ``make -C backend vendor-swagger``.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.errors import NotFoundProblem

SWAGGER_DIR = Path(__file__).resolve().parent.parent / "static" / "swagger"
OPENAPI_PATH = "/api/v1/openapi.json"
DOCS_PATH = "/api/docs"

_ASSETS: dict[str, str] = {
    "swagger-ui-bundle.js": "text/javascript",
    "swagger-init.js": "text/javascript",
    "swagger-ui.css": "text/css",
    "favicon-32x32.png": "image/png",
}

router = APIRouter(include_in_schema=False)


@router.get(DOCS_PATH, response_class=HTMLResponse)
async def swagger_ui(request: Request) -> HTMLResponse:
    prefix = escape(request.scope.get("root_path", "").rstrip("/"))
    assets = f"{prefix}{DOCS_PATH}"
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Soundings API</title>
  <link rel="icon" type="image/png" href="{assets}/favicon-32x32.png">
  <link rel="stylesheet" href="{assets}/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui" data-openapi-url="{prefix}{OPENAPI_PATH}"></div>
  <script src="{assets}/swagger-ui-bundle.js"></script>
  <script src="{assets}/swagger-init.js"></script>
</body>
</html>
"""
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@router.get(DOCS_PATH + "/{filename}")
async def swagger_asset(filename: str) -> FileResponse:
    media_type = _ASSETS.get(filename)
    if media_type is None:
        raise NotFoundProblem
    return FileResponse(
        SWAGGER_DIR / filename,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
