#!/usr/bin/env bash
# Start the real Soundings stack for the end-to-end tests, from the working tree:
#
#   1. Postgres 16 in Docker ($E2E_PREFIX-pg, data on tmpfs) on 127.0.0.1:$E2E_PG_PORT
#   2. `soundings migrate` and `soundings seed --reset --force` (the demo data, uv from
#      backend/)
#   3. the SPA built with Vite into $E2E_STATE_DIR/dist (frontend/dist is left alone)
#   4. `soundings api` on http://localhost:$E2E_PORT serving the API and that build,
#      with the dev login and the break-glass admin on, in the background (pid and log
#      in $E2E_STATE_DIR)
#
# E2E_SSO=1 adds Keycloak 26 ($E2E_PREFIX-kc on http://localhost:$E2E_KC_PORT) with a
# fresh copy of the dev realm on every start (users and groups as committed, this
# stack's origin allowed as redirect URI), and points the API at it: issuer
# http://localhost:$E2E_KC_PORT/realms/soundings, client secret, groups and
# employee_no claims. The dev login stays on (tests arrange data as Alice); the
# break-glass admin is then configured but unavailable, as SSO switches it off.
#
# Why not the container image? The image is what CI tests (`make demo` / the GitLab
# e2e job set E2E_BASE_URL and this script is skipped). Locally the working tree is
# what changes between runs, and building it here takes ~20 s instead of an image
# rebuild; the code paths are the same (one process serves API + SPA).
#
# Idempotent: if the app already answers on $E2E_PORT in the same mode it only reseeds
# (fresh data per run); in another mode (E2E_SSO, E2E_KC_PORT, E2E_BREAK_GLASS) it
# restarts the API. E2E_SKIP_BUILD=1 reuses the last SPA build. Stop everything:
# stop-stack.sh.
#
#   E2E_PORT      app port (default 8100)         E2E_PG_PORT   Postgres port (55433)
#   E2E_PREFIX    Docker name prefix (p1-qa-)     E2E_STATE_DIR (e2e/.stack)
#   E2E_SSO       1: Keycloak + SSO               E2E_KC_PORT   Keycloak port (8180)
#   E2E_BREAK_GLASS  0: no break-glass admin      E2E_BREAK_GLASS_USERNAME / _PASSWORD
#                 (default 1: admin / e2e-break-glass-password)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=stack-env.sh
source "$here/stack-env.sh"

log "stack: $E2E_URL (Postgres ${pg_container} on 127.0.0.1:${E2E_PG_PORT})"
[ "$E2E_SSO" != "1" ] || log "single sign-on: Keycloak ${kc_container} on $E2E_KC_URL"
mkdir -p "$E2E_STATE_DIR"

# --- 1. Postgres ---------------------------------------------------------------------
if [ "$(docker inspect -f '{{.State.Running}}' "$pg_container" 2>/dev/null)" != "true" ]; then
  docker rm -f "$pg_container" >/dev/null 2>&1 || true
  log "starting $pg_container (postgres:16-alpine)"
  docker run -d --name "$pg_container" \
    -e POSTGRES_DB=soundings -e POSTGRES_USER=soundings -e POSTGRES_PASSWORD=soundings \
    -p "127.0.0.1:${E2E_PG_PORT}:5432" --tmpfs /var/lib/postgresql/data \
    postgres:16-alpine -c fsync=off -c synchronous_commit=off -c full_page_writes=off \
    >/dev/null
fi

# --- 1b. Keycloak (E2E_SSO=1), booting while the database is prepared ---------------
if [ "$E2E_SSO" = "1" ] &&
  [ "$(docker inspect -f '{{.State.Running}}' "$kc_container" 2>/dev/null)" != "true" ]; then
  docker rm -f "$kc_container" >/dev/null 2>&1 || true
  log "starting $kc_container ($KEYCLOAK_IMAGE)"
  # No realm import at startup: the realm is (re)loaded through the admin API below,
  # the same way on a fresh or a reused container. The issuer follows the URL used
  # (KC_HOSTNAME_STRICT=false): http://localhost:$E2E_KC_PORT for browser and API.
  docker run -d --name "$kc_container" -p "127.0.0.1:${E2E_KC_PORT}:8080" \
    -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
    -e KC_HOSTNAME_STRICT=false -e KC_HEALTH_ENABLED=true -e KC_LOG_LEVEL=warn \
    "$KEYCLOAK_IMAGE" start-dev >/dev/null
fi

# --- 2. Schema and demo data -----------------------------------------------------------
(
  cd "$repo/backend"
  quietly uv run --quiet soundings wait-for-db --timeout 60 >/dev/null
  quietly uv run --quiet soundings migrate >/dev/null
  log "seeding the demo data (soundings seed --reset --force)"
  seed_demo_data
)

# --- 2b. A fresh realm (E2E_SSO=1) ------------------------------------------------------
if [ "$E2E_SSO" = "1" ]; then
  log "loading the dev realm into $kc_container (allowing $E2E_URL)"
  quietly kc wait 180 master >/dev/null
  quietly kc reset-realm "$E2E_URL" "http://127.0.0.1:$E2E_PORT" >/dev/null
fi

if app_ready; then
  if [ "$(cat "$E2E_STATE_DIR/mode" 2>/dev/null)" = "$stack_mode" ]; then
    log "the app already answers on $E2E_URL: reseeded, not restarted"
    exit 0
  fi
  [ -f "$E2E_STATE_DIR/api.pid" ] ||
    die "the app on $E2E_URL was not started by this script; stop it or use another E2E_PORT"
  log "restarting the app for: $stack_mode"
  stop_api
fi

# --- 3. The SPA ------------------------------------------------------------------------
if [ "${E2E_SKIP_BUILD:-}" = "1" ] && [ -f "$E2E_STATE_DIR/dist/index.html" ]; then
  log "reusing the SPA build in $E2E_STATE_DIR/dist (E2E_SKIP_BUILD=1)"
else
  log "building the SPA into $E2E_STATE_DIR/dist"
  [ -d "$repo/frontend/node_modules" ] || quietly npm --prefix "$repo/frontend" ci --no-audit --no-fund
  # vite only (no tsc -b): type errors are `make check-frontend`'s job, runtime is ours.
  (cd "$repo/frontend" && quietly node_modules/.bin/vite build \
    --outDir "$E2E_STATE_DIR/dist" --emptyOutDir --logLevel warn >/dev/null)
fi

# --- 4. The app ------------------------------------------------------------------------
log "starting soundings api on $E2E_URL (log: $E2E_STATE_DIR/api.log)"
(
  cd "$repo/backend"
  api_env
  SOUNDINGS_STATIC_DIR="$E2E_STATE_DIR/dist" \
    SOUNDINGS_BASE_URLS="$E2E_URL,http://127.0.0.1:$E2E_PORT" \
    SOUNDINGS_METRICS_PORT=0 \
    SOUNDINGS_LOG_LEVEL=WARNING \
    setsid nohup uv run --quiet soundings api --host 127.0.0.1 --port "$E2E_PORT" \
    >"$E2E_STATE_DIR/api.log" 2>&1 &
  echo $! >"$E2E_STATE_DIR/api.pid"
)
printf '%s\n' "$stack_mode" >"$E2E_STATE_DIR/mode"

for _ in $(seq 1 60); do
  if app_ready; then
    log "ready: $E2E_URL"
    exit 0
  fi
  sleep 1
done
tail -n 40 "$E2E_STATE_DIR/api.log" >&2 || true
die "the app did not become ready on $E2E_URL"
