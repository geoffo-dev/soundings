"""Optional OpenTelemetry tracing via FastAPI's native telemetry.

Off unless ``SOUNDINGS_OTEL_ENDPOINT`` is set (an OTLP/HTTP base URL such as
``http://otel-collector:4318``) and the ``otel`` extra is installed
(``uv sync --extra otel``). Only traces are exported: metrics go to Prometheus and
logs to stdout. Spans carry route templates and URL paths, never bodies or headers
- another reason never to put secrets or PII in URLs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.telemetry import TelemetryConfig

from app import __version__
from app.config import Settings

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

_DISABLED: TelemetryConfig = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}


def create_tracer_provider(endpoint: str) -> TracerProvider | None:
    """An SDK tracer provider exporting to ``{endpoint}/v1/traces``, if the SDK is installed."""
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("SOUNDINGS_OTEL_ENDPOINT is set but the 'otel' extra is not installed")
        return None
    resource = Resource.create({"service.name": "soundings", "service.version": __version__})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    return provider


def telemetry_config(settings: Settings) -> tuple[TelemetryConfig, TracerProvider | None]:
    """FastAPI ``telemetry=`` config and the provider to shut down on exit (if any)."""
    if not settings.otel_endpoint:
        return _DISABLED, None
    provider = create_tracer_provider(settings.otel_endpoint)
    if provider is None:
        return _DISABLED, None
    config: TelemetryConfig = {
        **_DISABLED,
        "tracing": True,
        "operation_spans": True,
        "tracer_provider": provider,
    }
    return config, provider
