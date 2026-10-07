"""Performance review B4: large GET JSON responses are gzipped for clients that take
it; nothing an endpoint marks ``no-store`` (bodies with a secret: BREACH), no event
stream, file or small body is."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from app.middleware import JsonGzipMiddleware
from app.models.enums import ProjectRole
from tests.conftest import Login
from tests.factories import make_idea, make_project, make_user

BIG = {"items": [{"title": f"Idea {n}", "summary": "x" * 40} for n in range(60)]}


async def _app(request: object) -> Response:
    path = request.url.path  # type: ignore[attr-defined]
    if path == "/secret":
        return JSONResponse(BIG, headers={"Cache-Control": "no-store"})
    if path == "/small":
        return JSONResponse({"ok": True})
    if path == "/stream":

        async def events() -> object:
            yield b"data: " + json.dumps(BIG).encode() + b"\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")  # type: ignore[arg-type]
    if path == "/text":
        return Response("y" * 5000, media_type="text/markdown")
    return JSONResponse(BIG)


def _client() -> httpx.AsyncClient:
    paths = ["/big", "/secret", "/small", "/stream", "/text"]
    inner = Starlette(routes=[Route(p, _app, methods=["GET", "POST"]) for p in paths])
    transport = httpx.ASGITransport(app=JsonGzipMiddleware(inner))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _raw(path: str, method: str = "GET", encoding: str = "gzip") -> httpx.Response:
    async with _client() as http:
        request = http.build_request(method, path, headers={"Accept-Encoding": encoding})
        response = await http.send(request, stream=True)
        await response.aread()
        return response


async def test_large_get_json_is_gzipped() -> None:
    response = await _raw("/big")

    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert json.loads(response.content) == BIG  # httpx decoded it
    assert int(response.headers["content-length"]) < len(json.dumps(BIG)) / 4


@pytest.mark.parametrize(
    ("path", "method", "encoding"),
    [
        ("/secret", "GET", "gzip"),  # the endpoint said no-store: a body with a secret
        ("/small", "GET", "gzip"),  # under 1 KB
        ("/stream", "GET", "gzip"),  # an event stream
        ("/text", "GET", "gzip"),  # not JSON (Markdown and PDF exports, images)
        ("/big", "POST", "gzip"),  # only GET
        ("/big", "GET", "identity"),  # the client doesn't take it
        ("/big", "GET", "gzip;q=0"),
    ],
)
async def test_everything_else_goes_as_it_is(path: str, method: str, encoding: str) -> None:
    response = await _raw(path, method, encoding)

    assert "content-encoding" not in response.headers


async def test_the_board_comes_gzipped_through_the_app(
    login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session, members={ada: ProjectRole.MEMBER})
    for n in range(12):
        await make_idea(db_session, project, title=f"Idea number {n}", summary="s" * 80)
    http = await login(ada)
    request = http.build_request(
        "GET", f"/api/v1/projects/{project.slug}/board", headers={"Accept-Encoding": "gzip"}
    )

    response = await http.send(request, stream=True)
    raw = b"".join([chunk async for chunk in response.aiter_raw()])

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["cache-control"] == "no-store"  # the API's default stays
    assert json.loads(gzip.decompress(raw))["columns"]
