#!/usr/bin/env bash
# Shared settings for start-stack.sh, stop-stack.sh and reseed.sh (sourced, not run).
# shellcheck disable=SC2034  # variables are used by the scripts that source this file

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

E2E_PORT="${E2E_PORT:-8100}"
E2E_PG_PORT="${E2E_PG_PORT:-55433}"
E2E_PREFIX="${E2E_PREFIX:-p1-qa-}"
E2E_STATE_DIR="${E2E_STATE_DIR:-$repo/e2e/.stack}"
E2E_URL="http://localhost:${E2E_PORT}"
pg_container="${E2E_PREFIX}pg"

# E2E_SSO=1: also Keycloak 26 with the dev realm ($E2E_PREFIX-kc on $E2E_KC_PORT), and
# the API configured for single sign-on against it (dev login stays on). The issuer is
# http://localhost:$E2E_KC_PORT/realms/soundings for the browser and the API alike.
E2E_SSO="${E2E_SSO:-0}"
E2E_KC_PORT="${E2E_KC_PORT:-8180}"
E2E_KC_URL="http://localhost:${E2E_KC_PORT}"
kc_container="${E2E_PREFIX}kc"
KEYCLOAK_IMAGE="${KEYCLOAK_IMAGE:-keycloak/keycloak:26.0}"
# The break-glass admin (E2E_BREAK_GLASS=0 turns it off). Available only without SSO.
E2E_BREAK_GLASS="${E2E_BREAK_GLASS:-1}"
E2E_BREAK_GLASS_USERNAME="${E2E_BREAK_GLASS_USERNAME:-admin}"
E2E_BREAK_GLASS_PASSWORD="${E2E_BREAK_GLASS_PASSWORD:-e2e-break-glass-password}"
# What the running API was started with (start-stack.sh restarts it when this changes).
stack_mode="sso=$E2E_SSO kc=$E2E_KC_PORT break_glass=$E2E_BREAK_GLASS"

# Every `soundings` command below talks to this database. Development mode: the dev
# login works and `seed` is allowed.
export SOUNDINGS_DATABASE_URL="postgresql+psycopg://soundings:soundings@127.0.0.1:${E2E_PG_PORT}/soundings"
export SOUNDINGS_ENVIRONMENT=development
export SOUNDINGS_DEV_LOGIN_ENABLED=true

log() { printf '\033[1;34m[e2e]\033[0m %s\n' "$*" >&2; }
die() {
  printf '\033[1;31m[e2e] error:\033[0m %s\n' "$*" >&2
  exit 1
}

# Run a command; print its output only if it fails (then stop).
quietly() {
  local out
  if ! out="$("$@" 2>&1)"; then
    printf '%s\n' "$out" | tail -n 60 >&2
    die "failed: $*"
  fi
  printf '%s\n' "$out"
}

# Replace the database's data with fresh demo data (run from backend/). --force: this
# throwaway database (tmpfs) may hold people a previous run created, and a plain
# --reset refuses then. A failure stops the caller (no `|| true` around it).
seed_demo_data() {
  local out
  out="$(quietly uv run --quiet soundings seed --reset --force)"
  printf '%s\n' "$out" | grep -v '^{' >&2 || true
}

# Settings of the `soundings api` process for the chosen mode.
api_env() {
  export SOUNDINGS_BREAK_GLASS_ENABLED=false
  if [ "$E2E_BREAK_GLASS" = "1" ]; then
    export SOUNDINGS_BREAK_GLASS_ENABLED=true
    export SOUNDINGS_BREAK_GLASS_USERNAME="$E2E_BREAK_GLASS_USERNAME"
    export SOUNDINGS_BREAK_GLASS_PASSWORD="$E2E_BREAK_GLASS_PASSWORD"
  fi
  unset SOUNDINGS_OIDC_ISSUER SOUNDINGS_OIDC_CLIENT_ID SOUNDINGS_OIDC_CLIENT_SECRET \
    SOUNDINGS_OIDC_GROUPS_CLAIM SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM SOUNDINGS_OIDC_EXTERNAL_ID_KIND
  if [ "$E2E_SSO" = "1" ]; then
    export SOUNDINGS_OIDC_ISSUER="$E2E_KC_URL/realms/soundings"
    export SOUNDINGS_OIDC_CLIENT_ID=soundings
    export SOUNDINGS_OIDC_CLIENT_SECRET=soundings-dev-secret
    export SOUNDINGS_OIDC_GROUPS_CLAIM=groups
    export SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM=employee_no
  fi
}

# The Keycloak helper (e2e/scripts/keycloak.ts) from the shell. The flag lets Node
# 22.12-22.17 run TypeScript too (later versions do by default).
kc() {
  E2E_KC_URL="$E2E_KC_URL" node --experimental-strip-types --disable-warning=ExperimentalWarning \
    "$repo/e2e/scripts/keycloak.ts" "$@"
}

app_ready() {
  curl -fsS --noproxy '*' --max-time 2 -o /dev/null "$E2E_URL/readyz" 2>/dev/null
}

# Stop the `soundings api` process start-stack.sh started (by its pid file only, never
# by pattern). setsid made it its own process group: stop uv, uvicorn and any children.
stop_api() {
  local pid_file="$E2E_STATE_DIR/api.pid" pid
  [ -f "$pid_file" ] || return 0
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    log "stopping soundings api (process group $pid)"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 25); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file" "$E2E_STATE_DIR/mode"
}
