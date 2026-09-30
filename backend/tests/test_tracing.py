from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import tracing
from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings


def test_tracing_is_off_without_endpoint() -> None:
    config, provider = tracing.telemetry_config(make_settings())

    assert provider is None
    assert config["tracing"] is False


def test_tracer_provider_targets_the_traces_path() -> None:
    provider = tracing.create_tracer_provider("http://collector:4318")

    assert provider is not None
    provider.shutdown()


async def test_requests_are_traced_with_route_templates(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "create_tracer_provider", lambda _endpoint: provider)
    app: FastAPI = create_app(
        settings.model_copy(update={"otel_endpoint": "http://collector:4318"})
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await client.get("/healthz")).status_code == 200

    server_spans = [s for s in exporter.get_finished_spans() if s.name == "GET /healthz"]
    assert server_spans, [s.name for s in exporter.get_finished_spans()]
    assert server_spans[0].attributes is not None
    assert server_spans[0].attributes["http.route"] == "/healthz"
