"""The ``soundings`` command: ``api``, ``worker``, ``migrate``, ``wait-for-db``, ``seed``,
``openapi``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from app.config import BACKEND_DIR, DatabaseSettings, Settings, get_database_settings, get_settings
from app.observability import configure_logging

logger = logging.getLogger("soundings.cli")

# Commands that only talk to the database: they read DatabaseSettings, so they run
# without the API's secrets (e.g. a Helm pre-upgrade migration Job).
_DATABASE_COMMANDS = frozenset({"migrate", "wait-for-db", "seed"})


def start_metrics_server(settings: Settings) -> None:
    """Serve Prometheus ``/metrics`` on ``settings.metrics_port`` in a daemon thread.

    Started in the ``soundings api`` process before uvicorn, so it survives worker
    restarts. With several uvicorn workers set ``PROMETHEUS_MULTIPROC_DIR`` and every
    worker's samples are aggregated here.
    """
    from prometheus_client import REGISTRY, CollectorRegistry, start_http_server
    from prometheus_client.multiprocess import MultiProcessCollector

    registry: CollectorRegistry = REGISTRY
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    start_http_server(settings.metrics_port, addr=settings.host, registry=registry)
    logger.info("metrics listening", extra={"port": settings.metrics_port})


def _api(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    if args.reload:
        # The reloader serves from a child process that re-reads the environment:
        # serve /metrics on the app port there (development only) rather than an
        # empty registry from this process.
        os.environ["SOUNDINGS_METRICS_PORT"] = "0"
    elif settings.metrics_port:
        start_metrics_server(settings)
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        workers=args.workers or settings.workers,
        reload=args.reload,
        reload_dirs=[str(BACKEND_DIR / "app")] if args.reload else None,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        log_config=None,  # app.observability configures JSON logging
        access_log=False,  # replaced by RequestContextMiddleware's PII-free access log
        server_header=False,
        timeout_graceful_shutdown=20,
    )
    return 0


def _worker(args: argparse.Namespace) -> int:
    from app.worker import run_worker

    asyncio.run(run_worker(get_settings(), concurrency=args.concurrency))
    return 0


def _migrate(_: argparse.Namespace) -> int:
    from app.migrate import upgrade_database

    upgrade_database(get_database_settings().sqlalchemy_url)
    return 0


def _wait_for_db(args: argparse.Namespace) -> int:
    from app.migrate import wait_for_database

    ready = wait_for_database(get_database_settings().database_dsn, timeout=args.timeout)
    return 0 if ready else 1


def _seed(args: argparse.Namespace) -> int:
    from app.seed import SeedRefused, check_allowed, run_seed

    settings = get_database_settings()
    try:
        check_allowed(settings, force=args.force)
    except SeedRefused as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    report = asyncio.run(run_seed(settings, reset=args.reset))
    sys.stdout.write(f"{report.summary()}\n")
    return 0


def _openapi(args: argparse.Namespace) -> int:
    from app.main import app
    from app.openapi import export_openapi

    document = export_openapi(app)
    if args.output in (None, "-"):
        sys.stdout.write(document)
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(document, encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="soundings", description="Soundings backend.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    api = commands.add_parser("api", help="serve the REST API and the built SPA (uvicorn)")
    api.add_argument("--host", help="bind address (default: SOUNDINGS_HOST or 127.0.0.1)")
    api.add_argument("--port", type=int, help="port (default: SOUNDINGS_PORT or 8000)")
    api.add_argument(
        "--workers", type=int, help="uvicorn workers (default: SOUNDINGS_WORKERS or 1)"
    )
    api.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev only)")
    api.set_defaults(func=_api)

    worker = commands.add_parser("worker", help="run the background job worker (procrastinate)")
    worker.add_argument(
        "--concurrency", type=int, help="parallel jobs (default: SOUNDINGS_WORKER_CONCURRENCY or 4)"
    )
    worker.set_defaults(func=_worker)

    migrate = commands.add_parser(
        "migrate", help="apply database migrations (app schema + procrastinate schema)"
    )
    migrate.set_defaults(func=_migrate)

    wait = commands.add_parser(
        "wait-for-db", help="wait until the database accepts connections (exit 1 on timeout)"
    )
    wait.add_argument(
        "--timeout", type=float, default=60.0, help="seconds to wait before giving up (default 60)"
    )
    wait.set_defaults(func=_wait_for_db)

    seed = commands.add_parser(
        "seed",
        help="load demo data: people, projects and ideas (development and demos only)",
        description=(
            "Load the demo data (sign in as alice, the platform admin, with the dev login). "
            "Does nothing when the database already has projects, unless --reset."
        ),
    )
    seed.add_argument(
        "--reset", action="store_true", help="delete all application data first, then seed"
    )
    seed.add_argument(
        "--force", action="store_true", help="allow seeding when SOUNDINGS_ENVIRONMENT=production"
    )
    seed.set_defaults(func=_seed)

    openapi = commands.add_parser("openapi", help="export the OpenAPI document as sorted JSON")
    openapi.add_argument("--output", "-o", help="file to write (default: stdout)")
    openapi.set_defaults(func=_openapi)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings: DatabaseSettings = (
        get_database_settings() if args.command in _DATABASE_COMMANDS else get_settings()
    )
    configure_logging(
        settings.log_level,
        redact_exception_messages=settings.is_production,
        # `openapi` may write the document to stdout: keep logs off it.
        stream="stderr" if args.command == "openapi" else "stdout",
    )
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
