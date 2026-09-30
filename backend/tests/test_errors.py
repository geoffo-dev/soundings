from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.errors import NotImplementedProblem, ProblemError, code_for_status

PROBLEM_KEYS = {"type", "title", "status", "instance", "code", "request_id"}


class Payload(BaseModel):
    title: str = Field(min_length=3)
    secret: str


@pytest.fixture
def app_with_error_routes(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/api/v1/test-errors")

    @router.post("/validate")
    async def validate(payload: Payload) -> dict[str, str]:
        return {"title": payload.title}

    @router.get("/crash")
    async def crash() -> None:
        raise RuntimeError("database password is hunter2")

    @router.get("/problem")
    async def problem() -> None:
        raise ProblemError(409, "idea_already_owned", detail="This idea already has an owner.")

    @router.get("/http-exception")
    async def http_exception() -> None:
        raise HTTPException(403, detail="Only the owner can do that.", headers={"X-Extra": "1"})

    @router.get("/not-implemented")
    async def not_implemented() -> None:
        raise NotImplementedProblem

    app.include_router(router)
    return app


@pytest.fixture
def error_client(app_with_error_routes: FastAPI, client: httpx.AsyncClient) -> httpx.AsyncClient:
    return client


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, object]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, object] = response.json()
    assert body.keys() >= PROBLEM_KEYS
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:soundings:problem:{code}"
    assert body["request_id"] == response.headers["x-request-id"]
    return body


async def test_unknown_api_path_is_a_404_problem(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    body = assert_problem(response, 404, "not_found")
    assert body["title"] == "Not Found"
    assert body["instance"] == "/api/v1/does-not-exist"


async def test_wrong_method_is_a_405_problem_with_allow_header(
    error_client: httpx.AsyncClient,
) -> None:
    response = await error_client.delete("/api/v1/test-errors/crash")

    assert_problem(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"


async def test_validation_errors_are_422_problems_without_input_echo(
    error_client: httpx.AsyncClient,
) -> None:
    response = await error_client.post(
        "/api/v1/test-errors/validate", json={"title": "x", "secret": 123456789}
    )

    body = assert_problem(response, 422, "validation_error")
    errors = body["errors"]
    assert isinstance(errors, list)
    assert {tuple(error["loc"]) for error in errors} == {("body", "title"), ("body", "secret")}
    assert all(set(error) == {"loc", "msg", "type"} for error in errors)
    assert "123456789" not in response.text


async def test_malformed_json_is_a_422_problem(error_client: httpx.AsyncClient) -> None:
    response = await error_client.post(
        "/api/v1/test-errors/validate",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert_problem(response, 422, "validation_error")


async def test_unhandled_errors_are_generic_500_problems(
    error_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="soundings.request"):
        response = await error_client.get("/api/v1/test-errors/crash")

    body = assert_problem(response, 500, "internal_error")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    assert body["title"] == "Internal Server Error"
    # The details go to the log, correlated by request id.
    [record] = [r for r in caplog.records if r.message == "unhandled error"]
    assert record.exc_info is not None
    assert record.request_id == response.headers["x-request-id"]  # type: ignore[attr-defined]


async def test_problem_error_renders_its_code_and_detail(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/api/v1/test-errors/problem")

    body = assert_problem(response, 409, "idea_already_owned")
    assert body["title"] == "Conflict"
    assert body["detail"] == "This idea already has an owner."


async def test_http_exception_keeps_detail_and_headers(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/api/v1/test-errors/http-exception")

    body = assert_problem(response, 403, "forbidden")
    assert body["detail"] == "Only the owner can do that."
    assert response.headers["x-extra"] == "1"


async def test_not_implemented_problem(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/api/v1/test-errors/not-implemented")

    assert_problem(response, 501, "not_implemented")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (404, "not_found"),
        (413, "content_too_large"),
        (429, "too_many_requests"),
        (422, "unprocessable_content"),
        (599, "http_599"),
    ],
)
def test_code_for_status(status: int, code: str) -> None:
    assert code_for_status(status) == code
