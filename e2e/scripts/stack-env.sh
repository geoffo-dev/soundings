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
# Email (Phase 3): Mailpit ($E2E_PREFIX-mailpit) catches everything the worker sends:
# SMTP on 127.0.0.1:$E2E_MAILPIT_SMTP_PORT, inbox and API on $E2E_MAILPIT_URL. Its
# messages survive `docker stop`/`start` ("the SMTP server is down": stopMailpit() and
# startMailpit() in mailpit.ts, or `node e2e/scripts/mailpit.ts stop|start`).
# E2E_SMTP=0: no SMTP at all (in-app notifications only; admins see a banner).
E2E_SMTP="${E2E_SMTP:-1}"
E2E_MAILPIT_PORT="${E2E_MAILPIT_PORT:-8125}"
E2E_MAILPIT_SMTP_PORT="${E2E_MAILPIT_SMTP_PORT:-1125}"
E2E_MAILPIT_URL="http://localhost:${E2E_MAILPIT_PORT}"
mailpit_container="${E2E_PREFIX}mailpit"
MAILPIT_IMAGE="${MAILPIT_IMAGE:-axllent/mailpit:latest}"
# The instance time zone (digests, reminders, dates in emails): the browser's, as set
# in playwright.config.ts.
E2E_TIMEZONE="${E2E_TIMEZONE:-Europe/London}"
# What the running API and worker were started with (start-stack.sh restarts them when
# this changes).
stack_mode="sso=$E2E_SSO kc=$E2E_KC_PORT break_glass=$E2E_BREAK_GLASS smtp=$E2E_SMTP mailpit=$E2E_MAILPIT_SMTP_PORT tz=$E2E_TIMEZONE"

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

# Settings of the `soundings api` and `soundings worker` processes for the chosen mode.
app_env() {
  export SOUNDINGS_BASE_URLS="$E2E_URL,http://127.0.0.1:$E2E_PORT"
  export SOUNDINGS_TIMEZONE="$E2E_TIMEZONE"
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
  unset SOUNDINGS_SMTP_HOST SOUNDINGS_SMTP_PORT SOUNDINGS_SMTP_SECURITY SOUNDINGS_SMTP_FROM \
    SOUNDINGS_SMTP_FROM_NAME SOUNDINGS_SMTP_REPLY_TO SOUNDINGS_SMTP_USERNAME \
    SOUNDINGS_SMTP_PASSWORD SOUNDINGS_SMTP_CA_BUNDLE
  if [ "$E2E_SMTP" = "1" ]; then
    export SOUNDINGS_SMTP_HOST=127.0.0.1
    export SOUNDINGS_SMTP_PORT="$E2E_MAILPIT_SMTP_PORT"
    export SOUNDINGS_SMTP_SECURITY=none
    export SOUNDINGS_SMTP_FROM=soundings@example.com
    export SOUNDINGS_SMTP_FROM_NAME="Soundings (e2e)"
    # Fail fast when Mailpit is stopped (a refused connection is immediate anyway).
    export SOUNDINGS_SMTP_TIMEOUT=5
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

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

# Mailpit's HTTP API (curl args follow the path), e.g. mailpit_api /api/v1/messages -X DELETE.
mailpit_api() {
  local path="$1"
  shift
  curl -fsS --noproxy '*' --max-time 5 "$@" "$E2E_MAILPIT_URL$path"
}

mailpit_ready() {
  mailpit_api /readyz -o /dev/null 2>/dev/null
}

# Start (or create) the Mailpit container and wait until it answers.
start_mailpit() {
  if ! container_running "$mailpit_container"; then
    if docker inspect "$mailpit_container" >/dev/null 2>&1; then
      log "starting $mailpit_container"
      docker start "$mailpit_container" >/dev/null
    else
      log "starting $mailpit_container ($MAILPIT_IMAGE: SMTP 127.0.0.1:$E2E_MAILPIT_SMTP_PORT, $E2E_MAILPIT_URL)"
      # The database is a file in the container (not a temp file Mailpit deletes on
      # exit), so messages survive a stop and start.
      docker run -d --name "$mailpit_container" \
        -p "127.0.0.1:${E2E_MAILPIT_SMTP_PORT}:1025" -p "127.0.0.1:${E2E_MAILPIT_PORT}:8025" \
        -e MP_DATABASE=/tmp/mailpit.db -e MP_MAX_MESSAGES=5000 \
        -e MP_SMTP_AUTH_ACCEPT_ANY=true -e MP_SMTP_AUTH_ALLOW_INSECURE=true \
        -e MP_DISABLE_VERSION_CHECK=true \
        "$MAILPIT_IMAGE" >/dev/null
    fi
  fi
  for _ in $(seq 1 30); do
    if mailpit_ready; then return 0; fi
    sleep 0.5
  done
  die "Mailpit does not answer on $E2E_MAILPIT_URL"
}

# Delete every message in Mailpit (a fresh inbox with the fresh demo data).
clear_mailpit() {
  mailpit_api /api/v1/messages -X DELETE -o /dev/null || die "could not clear Mailpit"
}

# Start a background process of the stack: start_process NAME COMMAND... (from backend/,
# own process group; pid in $E2E_STATE_DIR/NAME.pid, output in NAME.log).
start_process() {
  local name="$1"
  shift
  (
    cd "$repo/backend" || exit 1
    app_env
    setsid nohup "$@" >"$E2E_STATE_DIR/$name.log" 2>&1 &
    echo $! >"$E2E_STATE_DIR/$name.pid"
  )
}

process_running() {
  local pid_file="$E2E_STATE_DIR/$1.pid"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# Stop a process start-stack.sh started (by its pid file only, never by pattern).
# setsid made it its own process group: stop uv, the app and any children.
stop_process() {
  local name="$1" pid_file="$E2E_STATE_DIR/$1.pid" pid
  [ -f "$pid_file" ] || return 0
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    log "stopping soundings $name (process group $pid)"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

# The API and the worker.
stop_app() {
  stop_process api
  stop_process worker
  rm -f "$E2E_STATE_DIR/mode"
}
