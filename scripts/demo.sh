#!/usr/bin/env bash
# Run the Soundings image with demo data in Docker: Postgres, the app (API + SPA) with
# the dev login on, migrated and seeded, the worker (email, reminders, digests) and
# Mailpit, which catches every email. `make demo` builds the image first.
#
#   scripts/demo.sh up      # start (or restart app and worker on a newer image; data kept)
#   scripts/demo.sh down    # remove the containers, the data and the network
#
#   IMAGE           image to run (default soundings:dev)
#   DEMO_PORT       host port of the app (default 8000): http://localhost:$DEMO_PORT
#   DEMO_MAILPIT_PORT  host port of Mailpit's inbox and API (default 8026); its SMTP
#                   port stays inside the demo network ($DEMO_NAME-mailpit:1025)
#   DEMO_NAME       name prefix of the containers and network (default soundings-demo)
#   DEMO_RESET=1    replace the data with fresh demo data (soundings seed --reset)
#   DEMO_BIND_ADDRESS  address the ports bind to (default 127.0.0.1)
#   DEMO_BREAK_GLASS_PASSWORD  set: the break-glass admin "admin" with this password
#   DEMO_SMTP=0     no Mailpit and no SMTP: in-app notifications only (admins see a banner)
#   DEMO_TIMEZONE   instance time zone of digests, reminders and dates in emails (UTC)
#   DEMO_PUBLIC_PER_IP  public-form submissions per client address and hour (the app's
#                   default, 10, when unset; CI's e2e sends more from one address)
#   POSTGRES_IMAGE  (default postgres:16-alpine)   MAILPIT_IMAGE  (axllent/mailpit:latest)
# Development mode only: fixed database password, no TLS, anyone can sign in as anyone.
set -euo pipefail

IMAGE="${IMAGE:-soundings:dev}"
DEMO_PORT="${DEMO_PORT:-8000}"
DEMO_NAME="${DEMO_NAME:-soundings-demo}"
DEMO_BIND_ADDRESS="${DEMO_BIND_ADDRESS:-127.0.0.1}"
DEMO_MAILPIT_PORT="${DEMO_MAILPIT_PORT:-8026}"
DEMO_SMTP="${DEMO_SMTP:-1}"
DEMO_TIMEZONE="${DEMO_TIMEZONE:-UTC}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"
MAILPIT_IMAGE="${MAILPIT_IMAGE:-axllent/mailpit:latest}"
network="$DEMO_NAME"
db="$DEMO_NAME-db"
app="$DEMO_NAME-app"
worker="$DEMO_NAME-worker"
mailpit="$DEMO_NAME-mailpit"
url="http://localhost:$DEMO_PORT"
mailpit_url="http://localhost:$DEMO_MAILPIT_PORT"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# The app's settings (shared by every `soundings` command below).
app_env=(
  -e "SOUNDINGS_DATABASE_URL=postgresql+psycopg://soundings:soundings@$db:5432/soundings"
  -e SOUNDINGS_ENVIRONMENT=development
  -e SOUNDINGS_DEV_LOGIN_ENABLED=true
  -e "SOUNDINGS_BASE_URLS=$url,http://127.0.0.1:$DEMO_PORT"
  -e "SOUNDINGS_TIMEZONE=$DEMO_TIMEZONE"
)
if [ "$DEMO_SMTP" = "1" ]; then
  app_env+=(-e "SOUNDINGS_SMTP_HOST=$mailpit" -e SOUNDINGS_SMTP_PORT=1025
    -e SOUNDINGS_SMTP_SECURITY=none -e SOUNDINGS_SMTP_FROM=soundings@example.com
    -e "SOUNDINGS_SMTP_FROM_NAME=Soundings (demo)")
fi
if [ -n "${DEMO_BREAK_GLASS_PASSWORD:-}" ]; then
  app_env+=(-e SOUNDINGS_BREAK_GLASS_ENABLED=true -e SOUNDINGS_BREAK_GLASS_USERNAME=admin
    -e "SOUNDINGS_BREAK_GLASS_PASSWORD=$DEMO_BREAK_GLASS_PASSWORD")
fi
if [ -n "${DEMO_PUBLIC_PER_IP:-}" ]; then
  app_env+=(-e "SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP=$DEMO_PUBLIC_PER_IP")
fi
# The app and the worker run as in Kubernetes: read-only root filesystem with a
# writable /tmp (fontconfig's cache, PDF export), no capabilities.
hardening=(--read-only --tmpfs "/tmp:rw,nosuid,nodev,size=256m" --cap-drop ALL
  --security-opt no-new-privileges)

soundings() {
  docker run --rm --network "$network" "${hardening[@]}" "${app_env[@]}" "$IMAGE" "$@"
}

# Run a command quietly; show its output only if it fails.
quietly() {
  local out
  if ! out="$("$@" 2>&1)"; then
    printf '%s\n' "$out" >&2
    die "failed: $*"
  fi
  printf '%s\n' "$out"
}

running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

up() {
  docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image '$IMAGE' not found (run: make image)"
  docker network inspect "$network" >/dev/null 2>&1 || docker network create "$network" >/dev/null

  if running "$db"; then
    log "Postgres '$db' is already running (data kept)"
  else
    docker rm -f "$db" >/dev/null 2>&1 || true
    log "starting Postgres '$db' ($POSTGRES_IMAGE)"
    # Throwaway data on tmpfs: fast, and gone with `demo.sh down`.
    docker run -d --name "$db" --network "$network" \
      -e POSTGRES_DB=soundings -e POSTGRES_USER=soundings -e POSTGRES_PASSWORD=soundings \
      --tmpfs /var/lib/postgresql/data \
      "$POSTGRES_IMAGE" -c fsync=off -c synchronous_commit=off >/dev/null
  fi

  if [ "$DEMO_SMTP" = "1" ]; then
    if running "$mailpit"; then
      log "Mailpit '$mailpit' is already running (messages kept)"
    else
      docker rm -f "$mailpit" >/dev/null 2>&1 || true
      log "starting Mailpit '$mailpit' ($MAILPIT_IMAGE) on $mailpit_url"
      # Messages in a file inside the container: they survive `docker stop`/`start`
      # (an SMTP outage drill), not `demo.sh down`.
      docker run -d --name "$mailpit" --network "$network" \
        -p "$DEMO_BIND_ADDRESS:$DEMO_MAILPIT_PORT:8025" \
        -e MP_DATABASE=/tmp/mailpit.db -e MP_MAX_MESSAGES=5000 \
        -e MP_SMTP_AUTH_ACCEPT_ANY=true -e MP_SMTP_AUTH_ALLOW_INSECURE=true \
        -e MP_DISABLE_VERSION_CHECK=true \
        "$MAILPIT_IMAGE" >/dev/null
    fi
  fi

  log "migrating and seeding the demo data ($IMAGE)"
  quietly soundings wait-for-db --timeout 60 >/dev/null
  quietly soundings migrate >/dev/null
  seed_args=(seed)
  if [ "${DEMO_RESET:-}" = "1" ]; then seed_args+=(--reset); fi
  seeded="$(quietly soundings "${seed_args[@]}")"
  grep -v '^{' <<<"$seeded" || true # the summary, without the JSON log lines

  docker rm -f "$app" "$worker" >/dev/null 2>&1 || true
  log "starting the app '$app' on $url and the worker '$worker'"
  docker run -d --name "$app" --network "$network" "${hardening[@]}" "${app_env[@]}" \
    -p "$DEMO_BIND_ADDRESS:$DEMO_PORT:8000" "$IMAGE" api >/dev/null
  # The worker sends the email the app queues, and runs reminders and digests.
  docker run -d --name "$worker" --network "$network" "${hardening[@]}" "${app_env[@]}" \
    "$IMAGE" worker >/dev/null

  for _ in $(seq 1 60); do
    if curl -fsS --noproxy '*' --max-time 2 -o /dev/null "$url/readyz" 2>/dev/null; then
      running "$worker" || {
        docker logs --tail 40 "$worker" >&2 || true
        die "the worker '$worker' stopped"
      }
      log "Soundings is ready: $url"
      printf '    Sign in as Alice Anders (platform admin) or any other demo user.\n'
      if [ "$DEMO_SMTP" = "1" ]; then
        printf '    Email: %s (Mailpit; e.g. add an evaluator to an idea)\n' "$mailpit_url"
      else
        printf '    Email: off (DEMO_SMTP=0): in-app notifications only\n'
      fi
      printf '    MCP: %s/mcp with a key from Settings > API keys (dev/README.md, "MCP clients")\n' "$url"
      printf '    Logs: docker logs -f %s (or %s)    Stop: make demo-down\n' "$app" "$worker"
      return 0
    fi
    sleep 1
  done
  docker logs --tail 40 "$app" >&2 || true
  die "the app did not become ready on $url"
}

down() {
  log "removing $app, $worker, $mailpit, $db and network $network"
  docker rm -f -v "$app" "$worker" "$mailpit" "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}

case "${1:-up}" in
  up) up ;;
  down) down ;;
  *) die "usage: $0 up|down" ;;
esac
