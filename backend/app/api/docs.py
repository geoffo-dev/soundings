"""Swagger UI at ``/api/docs`` and the OpenAPI document at ``/api/v1/openapi.json``,
served entirely from vendored files (no CDN).

In production both need a signed-in session or a person's API key with ``read``
(security review P7 N1: anonymously they mapped the whole admin surface); 401
``unauthorized`` otherwise, 403 ``insufficient_scope`` for a key without ``read`` or
an AI agent's key (c22). Outside production they stay open (the SPA's codegen, tests).
The vendored assets (Swagger UI's own files) are public.

The assets in ``app/static/swagger`` come from the ``swagger-ui-dist`` npm package;
refresh them with ``make -C backend vendor-swagger``.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.auth.sources import UnauthorizedProblem, authenticate
from app.authz import InsufficientScopeProblem, is_agent, require_key_scope
from app.db import SessionDep
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


async def readers_in_production(request: Request, session: SessionDep) -> None:
    """Production: a session, or a person's key with ``read``; else 401/403."""
    if not request.app.state.settings.is_production:
        return
    principal = await authenticate(request, session, touch=False)
    if principal is None:
        raise UnauthorizedProblem
    if principal.auth != "session":
        if is_agent(principal):  # c22: an agent's key is MCP only
            raise InsufficientScopeProblem
        require_key_scope(principal, "read")


@router.get(OPENAPI_PATH, dependencies=[Depends(readers_in_production)])
async def openapi_document(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi(), headers={"Cache-Control": "no-cache"})


@router.get(DOCS_PATH, response_class=HTMLResponse, dependencies=[Depends(readers_in_production)])
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
