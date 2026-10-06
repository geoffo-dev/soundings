#!/usr/bin/env bash
# The performance stack: the e2e stack (scripts/start-stack.sh) on its own ports, with
# Postgres started first with pg_stat_statements, then the large data set on top of the
# demo story (backend/tests/perf/seed_large.py: 10k ideas in Big Ideas + 2k elsewhere,
# 50 people, ~30k evaluations, ~31k comments, ~120k feed events, ~20k notifications).
#
#   e2e/perf/stack.sh up      start (or reseed) everything; ~2 minutes from cold
#   e2e/perf/stack.sh seed    reseed the demo story + the large data set only
#   e2e/perf/stack.sh down    stop the API and worker, remove the containers
#   e2e/perf/stack.sh stats   pg_stat_statements: the 25 statements with the most time
#   e2e/perf/stack.sh restart-api   restart only the API with PERF_API_ENV, e.g.
#                             PERF_API_ENV="SOUNDINGS_WORKERS=2 SOUNDINGS_DATABASE_POOL_SIZE=10"
#
# Defaults (PERF_* override): app http://localhost:8320, Postgres 127.0.0.1:55436,
# containers p7-perf-*, state (SPA build, logs, pids) in e2e/perf/.stack. No SMTP (the
# worker still runs: memory, schedules). PERF_SCALE=0.1 seeds a tenth of the ideas.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
export E2E_PORT="${PERF_PORT:-8320}"
export E2E_PG_PORT="${PERF_PG_PORT:-55436}"
export E2E_PREFIX="${PERF_PREFIX:-p7-perf-}"
export E2E_STATE_DIR="${PERF_STATE_DIR:-$here/.stack}"
export E2E_SMTP=0 E2E_SSO=0 E2E_AI=0
pg="${E2E_PREFIX}pg"
export SOUNDINGS_DATABASE_URL="postgresql+psycopg://soundings:soundings@127.0.0.1:${E2E_PG_PORT}/soundings"
export SOUNDINGS_ENVIRONMENT=development SOUNDINGS_DEV_LOGIN_ENABLED=true

log() { printf '\033[1;35m[perf]\033[0m %s\n' "$*" >&2; }

start_pg() {
  [ "$(docker inspect -f '{{.State.Running}}' "$pg" 2>/dev/null)" = "true" ] && return
  docker rm -f "$pg" >/dev/null 2>&1 || true
  log "starting $pg (postgres:16-alpine, pg_stat_statements, tmpfs)"
  # The e2e stack's settings (no durability on tmpfs) plus pg_stat_statements; memory
  # settings stay at the image's defaults (shared_buffers 128 MB), as an untuned server.
  docker run -d --name "$pg" \
    -e POSTGRES_DB=soundings -e POSTGRES_USER=soundings -e POSTGRES_PASSWORD=soundings \
    -p "127.0.0.1:${E2E_PG_PORT}:5432" --tmpfs /var/lib/postgresql/data \
    postgres:16-alpine -c fsync=off -c synchronous_commit=off -c full_page_writes=off \
    -c shared_preload_libraries=pg_stat_statements -c pg_stat_statements.track=top >/dev/null
  for _ in $(seq 1 30); do
    docker exec "$pg" pg_isready -U soundings -q 2>/dev/null && break
    sleep 1
  done
  sleep 1
}

seed_large() {
  log "seeding the large data set (tests/perf/seed_large.py, scale ${PERF_SCALE:-1})"
  (cd "$repo/backend" && SOUNDINGS_LOG_LEVEL=WARNING uv run --quiet python -m tests.perf.seed_large \
    --scale "${PERF_SCALE:-1}")
  docker exec "$pg" psql -U soundings -qc "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" \
    -c "SELECT pg_stat_statements_reset()" >/dev/null
}

case "${1:-up}" in
  up)
    start_pg
    "$repo/e2e/scripts/start-stack.sh"
    seed_large
    log "ready: http://localhost:${E2E_PORT} (Big Ideas: /p/big-ideas)"
    ;;
  seed)
    (cd "$repo/backend" && uv run --quiet soundings seed --reset --force >/dev/null)
    seed_large
    ;;
  down)
    "$repo/e2e/scripts/stop-stack.sh"
    ;;
  restart-api)
    # shellcheck source-path=SCRIPTDIR source=../scripts/stack-env.sh
    source "$repo/e2e/scripts/stack-env.sh"
    stop_process api
    log "starting soundings api with: ${PERF_API_ENV:-(defaults)}"
    # shellcheck disable=SC2086  # PERF_API_ENV is a list of NAME=value words
    SOUNDINGS_STATIC_DIR="$E2E_STATE_DIR/dist" SOUNDINGS_METRICS_PORT=0 SOUNDINGS_LOG_LEVEL=WARNING \
      start_process api env ${PERF_API_ENV:-} uv run --quiet soundings api --host 127.0.0.1 --port "$E2E_PORT"
    for _ in $(seq 1 60); do
      curl -fsS -o /dev/null "http://127.0.0.1:${E2E_PORT}/readyz" 2>/dev/null && { log "ready"; exit 0; }
      sleep 1
    done
    tail -n 30 "$E2E_STATE_DIR/api.log" >&2
    exit 1
    ;;
  stats)
    docker exec "$pg" psql -U soundings -P pager=off -c "
      SELECT calls, round(total_exec_time::numeric, 0) AS total_ms,
             round(mean_exec_time::numeric, 2) AS mean_ms,
             round(max_exec_time::numeric, 1) AS max_ms, rows,
             left(regexp_replace(query, '\s+', ' ', 'g'), 160) AS query
      FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'soundings')
      ORDER BY total_exec_time DESC LIMIT ${PERF_STATS_LIMIT:-25}"
    ;;
  *)
    echo "usage: $0 up|seed|down|stats|restart-api" >&2
    exit 2
    ;;
esac
