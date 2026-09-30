"""RFC 9457 problem details for every error the API returns.

Raise :class:`ProblemError` (or a subclass) from application code::

    raise NotFoundProblem("Idea not found.")
    raise ProblemError(409, "idea_already_owned", detail="This idea already has an owner.")

``HTTPException``, request-validation errors and unhandled exceptions are converted
too. Responses never contain stack traces, exception messages or request input.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability import request_id_var
from app.schemas.common import FieldError, Problem, ValidationProblem

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_TYPE_PREFIX = "urn:soundings:problem:"

NotFoundFallback = Callable[[Request], Awaitable[Response | None]]


def _status_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    410: "gone",
    412: "precondition_failed",
    413: "content_too_large",
    415: "unsupported_media_type",
    422: "unprocessable_content",
    429: "too_many_requests",
    500: "internal_error",
    501: "not_implemented",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}


def code_for_status(status: int) -> str:
    """Default machine code for a bare HTTP status, e.g. 404 -> ``not_found``.

    An explicit table (not the status phrase) keeps codes stable across Python versions.
    """
    return _STATUS_CODES.get(status, f"http_{status}")


class ProblemError(Exception):
    """An error that renders as a problem+json response.

    ``code`` is the stable identifier clients branch on; ``detail`` is shown to
    users, so keep it free of internal information.
    """

    def __init__(
        self,
        status: int,
        code: str,
        title: str | None = None,
        detail: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.title = title or _status_phrase(status)
        self.detail = detail
        self.headers = dict(headers or {})
        super().__init__(detail or self.title)


class NotFoundProblem(ProblemError):
    def __init__(self, detail: str | None = None, *, code: str = "not_found") -> None:
        super().__init__(404, code, detail=detail)


class ConflictProblem(ProblemError):
    def __init__(self, detail: str | None = None, *, code: str = "conflict") -> None:
        super().__init__(409, code, detail=detail)


class NotImplementedProblem(ProblemError):
    """Raised by contract stubs that have no implementation yet (501)."""

    def __init__(self, detail: str = "This endpoint is not implemented yet.") -> None:
        super().__init__(501, "not_implemented", detail=detail)


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str | None = None,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    model: type[Problem] = Problem,
    **extra: Any,
) -> JSONResponse:
    problem = model(
        type=PROBLEM_TYPE_PREFIX + code,
        title=title or _status_phrase(status),
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id_var.get(),
        **extra,
    )
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=status,
        headers=dict(headers or {}),
        media_type=PROBLEM_CONTENT_TYPE,
    )


def internal_error_response(request: Request) -> JSONResponse:
    return problem_response(
        request,
        status=500,
        code="internal_error",
        detail="An unexpected error occurred. Quote the request id when reporting it.",
    )


def problem_from_problem_error(request: Request, exc: ProblemError) -> JSONResponse:
    return problem_response(
        request,
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        headers=exc.headers,
    )


def problem_from_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    title = _status_phrase(exc.status_code)
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != title else None
    return problem_response(
        request,
        status=exc.status_code,
        code=code_for_status(exc.status_code),
        title=title,
        detail=detail,
        headers=exc.headers,
    )


def problem_from_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Only location, message and type: never echo the submitted input back.
    errors = [
        FieldError(
            loc=list(err.get("loc", ())), msg=str(err.get("msg", "")), type=str(err.get("type", ""))
        )
        for err in exc.errors()
    ]
    return problem_response(
        request,
        status=422,
        code="validation_error",
        title="Validation Failed",
        detail="The request is invalid; see errors for details.",
        model=ValidationProblem,
        errors=errors,
    )


def install_exception_handlers(
    app: FastAPI, *, not_found_fallback: NotFoundFallback | None = None
) -> None:
    """Register problem+json handlers.

    ``not_found_fallback`` gets a chance to answer requests that matched no route
    (used to serve the SPA's index.html); a 404 raised by an endpoint is never
    handed to it. Unhandled exceptions become 500 problems in
    ``app.middleware.RequestContextMiddleware``.
    """

    async def handle(request: Request, exc: Exception) -> Response:
        if isinstance(exc, ProblemError):
            return problem_from_problem_error(request, exc)
        if isinstance(exc, RequestValidationError):
            return problem_from_validation_error(request, exc)
        if isinstance(exc, StarletteHTTPException):
            if (
                not_found_fallback is not None
                and exc.status_code == 404
                and "route" not in request.scope
            ):
                response = await not_found_fallback(request)
                if response is not None:
                    return response
            return problem_from_http_exception(request, exc)
        raise exc  # pragma: no cover - only registered for the classes above

    for exc_class in (ProblemError, RequestValidationError, StarletteHTTPException):
        app.add_exception_handler(exc_class, handle)
