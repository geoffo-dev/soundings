"""Kubernetes probes and the Prometheus scrape endpoint (not part of the public API).

``/metrics`` has its own router: normally it is served on a separate port
(``SOUNDINGS_METRICS_PORT``, see ``app.cli``), and on the app port only outside
production when that port is 0.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.errors import problem_response
from app.observability import render_metrics

logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 2.0

router = APIRouter(include_in_schema=False)
metrics_router = APIRouter(include_in_schema=False)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is serving requests. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness: the database answers ``SELECT 1`` within the timeout."""
    engine: AsyncEngine = request.app.state.engine
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        logger.warning("readiness check failed", extra={"error_type": type(exc).__name__})
        return problem_response(
            request, status=503, code="not_ready", detail="The database is not reachable."
        )
    return JSONResponse({"status": "ok"})


@metrics_router.get("/metrics")
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(payload, media_type=content_type)
