"""FastAPI application factory.

``create_app()`` wires settings, database, middleware, error handlers, routers and
the SPA. ``app`` is the module-level instance uvicorn serves (``app.main:app``).
"""

from __future__ import annotations

import functools
import gc
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.ai.sse import get_hub
from app.api import docs, health
from app.api.v1 import api_router
from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.errors import install_exception_handlers
from app.mcp import MCP_PATH, McpTransport, install_mcp
from app.middleware import (
    PROBE_PATHS,
    BodySizeLimitMiddleware,
    ProxyHeadersMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TrustedHostMiddleware,
    content_security_policy,
)
from app.observability import configure_logging
from app.openapi import build_openapi, operation_id
from app.spa import SpaBundle, install_spa
from app.tracing import telemetry_config
from app.worker import open_job_queue

logger = logging.getLogger(__name__)


@functools.cache
def freeze_startup_heap() -> None:
    """Move what is alive once the app has started (~160k objects: modules, routes,
    schemas) out of the cyclic collector's reach, once per process.

    Otherwise the first full collection walks all of it (~80 ms) and lands on
    whichever request happens to trigger it (board p95 151 ms → 75 ms with 10k ideas;
    tests/ideas/test_performance.py).
    """
    gc.collect()
    gc.freeze()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, redact_exception_messages=settings.is_production)

    engine = create_engine(settings, application_name="soundings-api")
    telemetry, tracer_provider = telemetry_config(settings)
    spa = SpaBundle.load(settings.static_dir)
    mcp = McpTransport()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "api starting",
            extra={
                "environment": settings.environment,
                "version": __version__,
                "spa": spa is not None,
            },
        )
        try:
            # The MCP session manager runs here: a route's own lifespan never runs.
            async with open_job_queue(settings) as job_queue, mcp.run():
                app.state.job_queue = job_queue
                freeze_startup_heap()
                try:
                    yield
                finally:
                    # AI run event pollers (one per run with open streams; app.ai.sse).
                    await get_hub(app).close()
        finally:
            await engine.dispose()
            if tracer_provider is not None:
                tracer_provider.shutdown()

    app = FastAPI(
        title="Soundings API",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
        telemetry=telemetry,
    )
    app.state.settings = settings
    app.state.tracer_provider = tracer_provider
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    install_exception_handlers(app, not_found_fallback=spa.fallback if spa else None)

    # add_middleware prepends: the last one added is the outermost, so security
    # headers also land on the 500s that RequestContextMiddleware produces, and
    # refused hosts and oversized bodies still get a request id, an access-log line
    # and metrics. No middleware reads the body, so the size limit needs no more.
    app.add_middleware(BodySizeLimitMiddleware)
    # /mcp is exempt like the probes: agents call the cluster Service by name; the bearer
    # key and the Origin check cover what the Host check guards (contract-phase5 3.5).
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
        exempt_paths=PROBE_PATHS | {MCP_PATH},
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        content_security_policy=content_security_policy(spa.script_hashes if spa else ()),
    )
    # Outermost: everything inside sees the client and scheme behind trusted proxies.
    app.add_middleware(
        ProxyHeadersMiddleware,
        trusted_proxies=settings.trusted_proxies,
        hops=settings.trusted_proxy_hops,
    )

    app.include_router(health.router)
    if settings.metrics_on_app_port:
        app.include_router(health.metrics_router)
    app.include_router(docs.router)
    app.include_router(api_router)
    install_mcp(app, settings, mcp)
    if spa is not None:
        install_spa(app, spa)

    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
