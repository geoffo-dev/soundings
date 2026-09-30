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

app_ready() {
  curl -fsS --noproxy '*' --max-time 2 -o /dev/null "$E2E_URL/readyz" 2>/dev/null
}
