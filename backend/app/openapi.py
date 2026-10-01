"""OpenAPI document tweaks: problem+json error responses and stable operation ids."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic.json_schema import models_json_schema

from app.errors import PROBLEM_CONTENT_TYPE
from app.schemas.common import Problem, ValidationProblem
from app.schemas.proposals import ProposalConflictProblem

API_DESCRIPTION = """\
Soundings REST API.

* Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details
  (`application/problem+json`); branch on the `code` field.
* Lists use cursor pagination: pass `next_cursor` back as `?cursor=`.
* JSON fields are snake_case; timestamps are ISO 8601 with a UTC offset.
"""

_SCHEMA_REF = "#/components/schemas/{model}"
_UNUSED_DEFAULT_SCHEMAS = ("HTTPValidationError", "ValidationError")
_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def operation_id(route: APIRoute) -> str:
    """Use the endpoint function name as the operationId (must be unique)."""
    return route.name


def _problem_content(model: str) -> dict[str, Any]:
    return {PROBLEM_CONTENT_TYPE: {"schema": {"$ref": _SCHEMA_REF.format(model=model)}}}


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate (and cache) the OpenAPI document for ``app``."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=API_DESCRIPTION,
        routes=app.routes,
    )
    components: dict[str, Any] = schema.setdefault("components", {}).setdefault("schemas", {})
    _, definitions = models_json_schema(
        [(Problem, "serialization"), (ValidationProblem, "serialization")],
        ref_template=_SCHEMA_REF,
    )
    components.update(definitions.get("$defs", {}))
    # 409 proposal_conflict carries the section as it is now (contract-phase4 section
    # 3.2); the route references it by name. Models routes already use (ProposalSection,
    # UserRef) keep FastAPI's schema.
    _, definitions = models_json_schema(
        [(ProposalConflictProblem, "serialization")], ref_template=_SCHEMA_REF
    )
    for name, definition in definitions.get("$defs", {}).items():
        components.setdefault(name, definition)

    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            responses: dict[str, Any] = operation.setdefault("responses", {})
            if "422" in responses:
                responses["422"] = {
                    "description": "Validation Failed",
                    "content": _problem_content("ValidationProblem"),
                }
            responses.setdefault(
                "default", {"description": "Problem", "content": _problem_content("Problem")}
            )

    # HTTPValidationError first: it is what references ValidationError.
    for name in _UNUSED_DEFAULT_SCHEMAS:
        if f'"{_SCHEMA_REF.format(model=name)}"' not in json.dumps(schema):
            components.pop(name, None)

    app.openapi_schema = schema
    return schema


def export_openapi(app: FastAPI) -> str:
    """Deterministic JSON (sorted keys, trailing newline) for committing/codegen."""
    return json.dumps(build_openapi(app), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
