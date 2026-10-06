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
# Public form (Phase 4): every spec submits from 127.0.0.1, and the API keeps its
# per-address count (per hour, in memory) across runs that reuse it, so the stack
# allows E2E_PUBLIC_PER_IP submissions per hour (the app's default is 10; a spec that
# tests the limit can restart the stack with a low value). E2E_ALTCHA_COST, when set,
# overrides the proof-of-work cost (the app's default, 5000, when unset).
E2E_PUBLIC_PER_IP="${E2E_PUBLIC_PER_IP:-1000}"
E2E_ALTCHA_COST="${E2E_ALTCHA_COST:-}"
# AI assistance (Phase 6): E2E_AI=1 runs Soundings' fake kagent agent (dev/fake-agent,
# `uv run`, no container) on 127.0.0.1:$E2E_FAKE_AGENT_PORT in kagent's A2A layout, turns
# AI on in the API and worker (SOUNDINGS_KAGENT_URL pointing at it, runs limited to
# E2E_AI_RUN_TIMEOUT), and after every seed registers E2E_AI_AGENT (<namespace>/<name>,
# all three purposes, Customer Innovation) through the API as alice, writing its key to
# $E2E_FAKE_AGENT_KEYS_DIR/<namespace>.<name>, where the fake reads it (E2E_AI_PROVISION=0:
# no agent; specs register their own and hand over keys with scripts/fake-agent.ts).
E2E_AI="${E2E_AI:-0}"
E2E_FAKE_AGENT_PORT="${E2E_FAKE_AGENT_PORT:-8183}"
E2E_FAKE_AGENT_URL="http://127.0.0.1:${E2E_FAKE_AGENT_PORT}"
E2E_FAKE_AGENT_KEYS_DIR="${E2E_FAKE_AGENT_KEYS_DIR:-$E2E_STATE_DIR/fake-agent-keys}"
E2E_AI_RUN_TIMEOUT="${E2E_AI_RUN_TIMEOUT:-PT1M}"
E2E_AI_AGENT="${E2E_AI_AGENT:-soundings/idea-evaluator}"
E2E_AI_PROVISION="${E2E_AI_PROVISION:-1}"
# What the running API and worker were started with (start-stack.sh restarts them when
# this changes).
stack_mode="sso=$E2E_SSO kc=$E2E_KC_PORT break_glass=$E2E_BREAK_GLASS smtp=$E2E_SMTP mailpit=$E2E_MAILPIT_SMTP_PORT tz=$E2E_TIMEZONE public_per_ip=$E2E_PUBLIC_PER_IP altcha_cost=$E2E_ALTCHA_COST ai=$E2E_AI fake_agent=$E2E_FAKE_AGENT_PORT ai_timeout=$E2E_AI_RUN_TIMEOUT"

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
  export SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP="$E2E_PUBLIC_PER_IP"
  # The specs' requests come from 127.0.0.1, trusted as the proxy (one hop; the app's
  # defaults, spelled out): a spec can be a client of its own with X-Forwarded-For
  # (public-abuse.spec.ts PA-05/06 exhaust per-address throttles without blocking the run).
  export SOUNDINGS_TRUSTED_PROXIES=127.0.0.1
  export SOUNDINGS_TRUSTED_PROXY_HOPS=1
  unset SOUNDINGS_ALTCHA_COST
  if [ -n "$E2E_ALTCHA_COST" ]; then export SOUNDINGS_ALTCHA_COST="$E2E_ALTCHA_COST"; fi
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
  unset SOUNDINGS_AI_ENABLED SOUNDINGS_KAGENT_URL SOUNDINGS_KAGENT_TOKEN SOUNDINGS_AI_RUN_TIMEOUT \
    SOUNDINGS_AI_MCP_URL SOUNDINGS_AI_AGENT_NAMESPACES SOUNDINGS_AI_DEFAULT_PROTOCOL
  if [ "$E2E_AI" = "1" ]; then
    export SOUNDINGS_AI_ENABLED=true
    export SOUNDINGS_KAGENT_URL="$E2E_FAKE_AGENT_URL"
    export SOUNDINGS_AI_RUN_TIMEOUT="$E2E_AI_RUN_TIMEOUT"
    export SOUNDINGS_AI_MCP_URL="$E2E_URL/mcp"
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

# --- The fake kagent agent (E2E_AI=1) ------------------------------------------------
fake_agent_ready() {
  curl -fsS --noproxy '*' --max-time 2 -o /dev/null "$E2E_FAKE_AGENT_URL/healthz" 2>/dev/null
}

# Start it (from dev/fake-agent with uv; pid and log in $E2E_STATE_DIR) unless it runs.
start_fake_agent() {
  mkdir -p "$E2E_FAKE_AGENT_KEYS_DIR"
  chmod 700 "$E2E_FAKE_AGENT_KEYS_DIR"
  if process_running fake-agent && fake_agent_ready; then return 0; fi
  stop_process fake-agent
  log "starting the fake kagent agent on $E2E_FAKE_AGENT_URL (log: $E2E_STATE_DIR/fake-agent.log)"
  (
    cd "$repo/dev/fake-agent" || exit 1
    FAKE_AGENT_HOST=127.0.0.1 FAKE_AGENT_PORT="$E2E_FAKE_AGENT_PORT" \
      FAKE_AGENT_MCP_URL="$E2E_URL/mcp" FAKE_AGENT_KEYS_DIR="$E2E_FAKE_AGENT_KEYS_DIR" \
      setsid nohup uv run --quiet fake-agent >"$E2E_STATE_DIR/fake-agent.log" 2>&1 &
    echo $! >"$E2E_STATE_DIR/fake-agent.pid"
  )
  for _ in $(seq 1 60); do
    if fake_agent_ready; then return 0; fi
    sleep 0.5
  done
  tail -n 40 "$E2E_STATE_DIR/fake-agent.log" >&2 || true
  die "the fake kagent agent does not answer on $E2E_FAKE_AGENT_URL"
}

# Forget every key (a fresh seed has no agents) and what the fake saw.
reset_fake_agent() {
  rm -f "$E2E_FAKE_AGENT_KEYS_DIR"/* 2>/dev/null || true
  curl -fsS --noproxy '*' --max-time 5 -X DELETE -o /dev/null "$E2E_FAKE_AGENT_URL/_fake/observations" || true
}

# Register E2E_AI_AGENT through the API as alice (dev login) and give its key to the fake.
provision_ai_agent() {
  [ "$E2E_AI_PROVISION" = "1" ] || return 0
  command -v jq >/dev/null || die "E2E_AI=1 needs jq to register the agent"
  local namespace="${E2E_AI_AGENT%%/*}" name="${E2E_AI_AGENT#*/}" jar body alice project status
  jar="$(mktemp)" body="$(mktemp)"
  local c=(curl -sS --noproxy '*' --max-time 15 -b "$jar" -c "$jar")
  alice="$("${c[@]}" "$E2E_URL/api/v1/auth/dev/users" | jq -r '.[] | select(.email == "alice@example.com") | .id')"
  "${c[@]}" -o /dev/null -H 'Content-Type: application/json' -d "{\"user_id\":\"$alice\"}" \
    "$E2E_URL/api/v1/auth/dev/login"
  project="$("${c[@]}" "$E2E_URL/api/v1/projects/customer-innovation" | jq -r .id)"
  status="$("${c[@]}" -o "$body" -w '%{http_code}' -H 'Content-Type: application/json' \
    -H "X-CSRF-Token: $(awk '$6 ~ /soundings_csrf$/ { print $7 }' "$jar")" \
    --data-binary "$(jq -nc --arg ns "$namespace" --arg n "$name" --arg p "$project" \
      '{display_name: "Idea evaluator", description: "The e2e stack'"'"'s fake kagent agent (E2E_AI=1).",
        namespace: $ns, name: $n, purposes: ["evaluate", "research", "draft_section"], project_ids: [$p]}')" \
    "$E2E_URL/api/v1/admin/ai-agents" || true)"
  if [ "$status" != "201" ]; then
    rm -f "$jar" "$body"
    die "registering the AI agent $E2E_AI_AGENT answered $status (E2E_AI_PROVISION=0 skips it)"
  fi
  (umask 077 && jq -r '"Bearer " + .key.secret' "$body" >"$E2E_FAKE_AGENT_KEYS_DIR/$namespace.$name")
  log "AI agent $E2E_AI_AGENT registered ($(jq -r .agent.id "$body")); its key is with the fake agent"
  rm -f "$jar" "$body"
}

# The API and the worker.
stop_app() {
  stop_process api
  stop_process worker
  rm -f "$E2E_STATE_DIR/mode"
}
