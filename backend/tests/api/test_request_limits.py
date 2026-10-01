"""Request body size limit (code review F1): a body over 1 MiB is refused with 413
``content_too_large`` before it is read into memory, even before authentication."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from app.middleware import MAX_REQUEST_BODY_BYTES, BodySizeLimitMiddleware

API = "/api/v1"
MIB = 1024 * 1024


def _post(*headers: tuple[bytes, bytes]) -> Scope:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/projects",
        "raw_path": b"/api/v1/projects",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), *headers],
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
    }


def assert_too_large(response: httpx.Response) -> None:
    assert response.status_code == 413, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "content_too_large"
    # Inside the request context and security headers: traceable and hardened.
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["connection"] == "close"  # the unread rest is never drained


def test_the_limit_is_one_mebibyte() -> None:
    assert MAX_REQUEST_BODY_BYTES == MIB


async def test_an_anonymous_2_mib_post_is_refused_by_content_length(
    client: httpx.AsyncClient,
) -> None:
    body = b'{"name": "' + b"x" * (2 * MIB) + b'"}'

    response = await client.post(
        f"{API}/projects", content=body, headers={"Content-Type": "application/json"}
    )

    assert_too_large(response)


async def test_a_streamed_body_is_counted_and_cut_off(client: httpx.AsyncClient) -> None:
    """No Content-Length (chunked): the bytes are counted as they arrive and the app
    stops reading soon after the limit (the rest is never pulled)."""
    chunk = b"x" * (64 * 1024)
    sent = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(64):  # 4 MiB if it were all read
            sent += 1
            yield chunk

    response = await client.post(
        f"{API}/projects", content=endless(), headers={"Content-Type": "application/json"}
    )

    assert_too_large(response)
    assert sent <= MIB // len(chunk) + 2


async def test_a_body_just_under_the_limit_is_not_refused(client: httpx.AsyncClient) -> None:
    body = b'{"name": "' + b"x" * (MIB - 100) + b'"}'

    response = await client.post(
        f"{API}/projects", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 401, response.text  # read in full, then not signed in


async def test_get_requests_without_a_body_are_untouched(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200


@pytest.mark.parametrize("declared", [str(2 * MIB), str(MIB + 1)])
async def test_the_middleware_never_reads_a_body_declared_too_large(declared: str) -> None:
    """Pure-ASGI check: the 413 goes out without a single receive()."""
    called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:  # pragma: no cover
        nonlocal called
        called = True

    async def receive() -> Message:  # pragma: no cover - must not be called
        raise AssertionError("the body was read")

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await BodySizeLimitMiddleware(app)(_post((b"content-length", declared.encode())), receive, send)

    assert not called
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


async def test_a_body_read_outside_fastapi_is_cut_off_too() -> None:
    """An ASGI app that reads the body itself (no FastAPI handler to turn the error
    into a response) still gets a 413, not a 500."""
    chunks = [b"x" * (512 * 1024)] * 4

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive()).get("more_body"):
            pass
        raise AssertionError("the whole body was read")  # pragma: no cover

    async def receive() -> Message:
        return {"type": "http.request", "body": chunks.pop(), "more_body": bool(chunks)}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await BodySizeLimitMiddleware(app)(_post(), receive, send)

    assert sent[0]["status"] == 413
    assert len(chunks) == 1  # stopped at the third half-MiB chunk


async def test_every_route_is_covered(client: httpx.AsyncClient) -> None:
    """Not only project creation: any write, e.g. saving an evaluation."""
    response = await client.put(
        f"{API}/ideas/CUST-1/evaluations/me",
        content=b"x" * (MIB + 1),
        headers={"Content-Type": "application/json"},
    )
    assert_too_large(response)
