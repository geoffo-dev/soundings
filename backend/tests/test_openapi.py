from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from app.cli import main
from app.openapi import export_openapi


class EchoIn(BaseModel):
    text: str


@pytest.fixture
def app_with_route(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/api/v1/test-echo", tags=["test"])

    @router.post("")
    async def echo_text(body: EchoIn) -> EchoIn:
        return body

    app.include_router(router)
    app.openapi_schema = None
    return app


async def test_openapi_is_served_under_api_v1(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "Soundings API"
    assert {"Problem", "ValidationProblem", "FieldError"} <= document["components"][
        "schemas"
    ].keys()


async def test_operations_document_problem_responses(
    app_with_route: FastAPI, client: httpx.AsyncClient
) -> None:
    document = (await client.get("/api/v1/openapi.json")).json()

    operation = document["paths"]["/api/v1/test-echo"]["post"]
    assert operation["operationId"] == "echo_text"
    assert operation["responses"]["422"]["content"] == {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/ValidationProblem"}}
    }
    assert operation["responses"]["default"]["content"] == {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
    }
    schemas = document["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_export_is_sorted_and_deterministic(app: FastAPI) -> None:
    first = export_openapi(app)
    app.openapi_schema = None
    second = export_openapi(app)

    assert first == second
    assert first.endswith("}\n")
    assert (
        first == json.dumps(json.loads(first), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def test_cli_writes_openapi_file(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "openapi.json"

    assert main(["openapi", "--output", str(output)]) == 0

    assert json.loads(output.read_text())["openapi"].startswith("3.")


def test_cli_writes_pure_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["openapi"]) == 0

    assert json.loads(capsys.readouterr().out)["info"]["title"] == "Soundings API"


async def test_swagger_ui_uses_only_local_assets(client: httpx.AsyncClient) -> None:
    page = await client.get("/api/docs")

    assert page.status_code == 200
    references = re.findall(r'(?:src|href)="([^"]+)"', page.text)
    assert references, "expected script and stylesheet references"
    for reference in references:
        assert reference.startswith("/api/docs/"), reference
        asset = await client.get(reference)
        assert asset.status_code == 200, reference
    assert 'data-openapi-url="/api/v1/openapi.json"' in page.text
    assert "<script>" not in page.text  # no inline scripts, CSP stays strict


async def test_swagger_init_disables_the_remote_validator(client: httpx.AsyncClient) -> None:
    script = (await client.get("/api/docs/swagger-init.js")).text

    assert "validatorUrl: null" in script


async def test_unknown_docs_asset_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/docs/..%2f..%2fconfig.py")

    assert response.status_code == 404
