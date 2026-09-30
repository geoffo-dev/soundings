"""JSON logging, request-id context and Prometheus metrics.

Logging rules (enforced by review, not by code): never log emails, names, tokens,
cookies, headers, query strings, raw paths or request/response bodies. Log ids
(request id, entity UUIDs) and route templates instead.

Exception *messages* can carry data (e.g. a unique-violation's key values), so in
production tracebacks are logged with frames and exception types only.
"""

from __future__ import annotations

import logging
import logging.config
import os
import sys
import traceback
from contextvars import ContextVar
from typing import Any, Literal, TextIO

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.multiprocess import MultiProcessCollector
from pythonjsonlogger.core import RESERVED_ATTRS
from pythonjsonlogger.json import JsonFormatter as BaseJsonFormatter

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
"""The current request's id (``X-Request-ID``); ``None`` outside requests."""


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


LogStream = Literal["stdout", "stderr"]


class ConsoleHandler(logging.StreamHandler[TextIO]):
    """StreamHandler that always writes to the *current* ``sys.stdout``/``sys.stderr``.

    Resolving the stream lazily keeps logging working when it is swapped (pytest
    capture, uvicorn reloader).
    """

    def __init__(self, target: LogStream = "stdout") -> None:
        self.target = target
        super().__init__()

    @property
    def stream(self) -> TextIO:
        return sys.stderr if self.target == "stderr" else sys.stdout

    @stream.setter
    def stream(self, value: TextIO) -> None:
        """Ignore assignments; the stream is chosen by ``target``."""


def format_exception_without_messages(exc: BaseException) -> str:
    """A traceback with frames and exception types but no exception messages."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    chain: list[BaseException] = []
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    for index, error in enumerate(reversed(chain)):
        if index:
            parts.append("\nThe above exception led to the following exception:\n\n")
        parts.append("Traceback (most recent call last):\n")
        parts.extend(traceback.format_tb(error.__traceback__))
        error_type = type(error)
        parts.append(f"{error_type.__module__}.{error_type.__qualname__}: <message redacted>\n")
    return "".join(parts).rstrip("\n")


class JsonFormatter(BaseJsonFormatter):
    """python-json-logger formatter that can drop exception messages from tracebacks."""

    def __init__(self, *args: Any, redact_exception_messages: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.redact_exception_messages = redact_exception_messages

    def formatException(self, ei: Any) -> str | list[str]:  # type: ignore[override]  # noqa: N802
        if self.redact_exception_messages and isinstance(ei, tuple) and ei[1] is not None:
            return format_exception_without_messages(ei[1])
        return super().formatException(ei)


_configured = False


def logging_config(
    level: str, *, redact_exception_messages: bool = False, stream: LogStream = "stdout"
) -> dict[str, Any]:
    """``logging.config.dictConfig`` payload: one JSON handler on the root logger."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {
            "json": {
                "()": JsonFormatter,
                "fmt": "%(levelname)s %(name)s %(message)s",
                "redact_exception_messages": redact_exception_messages,
                "rename_fields": {"levelname": "level", "name": "logger"},
                "reserved_attrs": [*RESERVED_ATTRS, "color_message"],  # uvicorn's ANSI copy
                "timestamp": True,
            }
        },
        "handlers": {
            "console": {
                "()": ConsoleHandler,
                "target": stream,
                "formatter": "json",
                "filters": ["request_id"],
            }
        },
        "root": {"level": level, "handlers": ["console"]},
        "loggers": {
            # Uvicorn logs flow through our JSON handler.
            "uvicorn": {"handlers": [], "propagate": True},
            "uvicorn.error": {"handlers": [], "propagate": True},
            # Uvicorn's access log contains client IPs and raw paths (PII, tokens);
            # RequestContextMiddleware writes a PII-free access log instead.
            "uvicorn.access": {"handlers": [], "propagate": False, "level": "CRITICAL"},
            # httpx logs full URLs at INFO.
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
            "alembic.runtime.plugins": {"level": "WARNING"},
            "procrastinate.blueprints": {"level": "WARNING"},
        },
    }


def configure_logging(
    level: str, *, redact_exception_messages: bool = False, stream: LogStream = "stdout"
) -> None:
    """Configure JSON logging once per process; later calls are no-ops.

    The CLI configures logging before importing the app, so its choices (e.g.
    ``stream="stderr"`` for ``soundings openapi``) win over ``create_app()``'s call.
    """
    global _configured  # noqa: PLW0603 - process-wide logging state
    if _configured:
        return
    logging.config.dictConfig(
        logging_config(level, redact_exception_messages=redact_exception_messages, stream=stream)
    )
    _configured = True


# --- Prometheus ---------------------------------------------------------------------

HTTP_REQUESTS = Counter(
    "soundings_http_requests_total",
    "HTTP requests handled, by route template.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "soundings_http_request_duration_seconds",
    "HTTP request latency in seconds, by route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

_KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


def observe_request(method: str, route: str, status: int, duration: float) -> None:
    """Record one finished HTTP request. ``route`` must be a template, never a raw path."""
    method = method if method in _KNOWN_METHODS else "OTHER"
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration)


def render_metrics() -> tuple[bytes, str]:
    """Exposition payload and content type.

    With several uvicorn workers set ``PROMETHEUS_MULTIPROC_DIR`` so every worker's
    samples are aggregated; with one worker per pod (the default) it is not needed.
    """
    registry: CollectorRegistry = REGISTRY
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    return generate_latest(registry), CONTENT_TYPE_LATEST
