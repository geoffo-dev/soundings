from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from app.pagination import (
    MAX_LIMIT,
    InvalidCursorProblem,
    Page,
    PageParamsDep,
    decode_cursor,
    encode_cursor,
    slice_page,
)


def test_cursor_round_trip() -> None:
    when = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    ident = uuid.uuid4()

    cursor = encode_cursor({"created_at": when, "id": ident, "n": 3})

    assert "=" not in cursor
    assert set(cursor) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    decoded = decode_cursor(cursor)
    assert decoded == {"created_at": when.isoformat(), "id": str(ident), "n": 3}
    assert datetime.fromisoformat(decoded["created_at"]) == when


def test_cursor_encoding_is_deterministic() -> None:
    assert encode_cursor({"b": 1, "a": 2}) == encode_cursor({"a": 2, "b": 1})


def test_unsupported_cursor_values_are_rejected() -> None:
    with pytest.raises(TypeError):
        encode_cursor({"x": object()})


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not base64!",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(b"[1, 2]").decode(),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
        "a" * 2000,
    ],
)
def test_invalid_cursors_raise_a_400_problem(cursor: str) -> None:
    with pytest.raises(InvalidCursorProblem) as caught:
        decode_cursor(cursor)

    assert caught.value.status == 400
    assert caught.value.code == "invalid_cursor"


def test_slice_page_returns_next_cursor_only_when_more_rows_exist() -> None:
    rows = [1, 2, 3]

    items, next_cursor = slice_page(rows, 2, lambda n: {"n": n})
    assert items == [1, 2]
    assert next_cursor is not None
    assert decode_cursor(next_cursor) == {"n": 2}

    items, next_cursor = slice_page(rows, 3, lambda n: {"n": n})
    assert items == [1, 2, 3]
    assert next_cursor is None

    assert slice_page([], 3, lambda n: {"n": n}) == ([], None)


@pytest.fixture
def paged_client(app: FastAPI, client: httpx.AsyncClient) -> httpx.AsyncClient:
    router = APIRouter()
    numbers = list(range(1, 8))

    @router.get("/api/v1/test-numbers")
    async def list_test_numbers(page: PageParamsDep) -> Page[int]:
        after = decode_cursor(page.cursor)["n"] if page.cursor else 0
        rows = [n for n in numbers if n > after][: page.limit + 1]
        items, next_cursor = slice_page(rows, page.limit, lambda n: {"n": n})
        return Page(items=items, next_cursor=next_cursor)

    app.include_router(router)
    return client


async def test_endpoint_pages_through_results(paged_client: httpx.AsyncClient) -> None:
    seen: list[int] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = (await paged_client.get("/api/v1/test-numbers", params=params)).json()
        seen.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == [1, 2, 3, 4, 5, 6, 7]


async def test_endpoint_rejects_bad_cursor_and_limits(paged_client: httpx.AsyncClient) -> None:
    bad_cursor = await paged_client.get("/api/v1/test-numbers", params={"cursor": "%%%"})
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["code"] == "invalid_cursor"

    for limit in (0, MAX_LIMIT + 1):
        response = await paged_client.get("/api/v1/test-numbers", params={"limit": limit})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
