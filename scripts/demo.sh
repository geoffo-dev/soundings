#!/usr/bin/env bash
# Run the Soundings image with demo data in Docker: Postgres plus the app (API + SPA)
# with the dev login on, migrated and seeded. `make demo` builds the image first.
#
#   scripts/demo.sh up      # start (or restart the app on a newer image; data is kept)
#   scripts/demo.sh down    # remove the containers, the data and the network
#
#   IMAGE           image to run (default soundings:dev)
#   DEMO_PORT       host port of the app (default 8000): http://localhost:$DEMO_PORT
#   DEMO_NAME       name prefix of the containers and network (default soundings-demo)
#   DEMO_RESET=1    replace the data with fresh demo data (soundings seed --reset)
#   DEMO_BIND_ADDRESS  address the port binds to (default 127.0.0.1)
#   POSTGRES_IMAGE  (default postgres:16-alpine)
# Development mode only: fixed database password, no TLS, anyone can sign in as anyone.
set -euo pipefail

IMAGE="${IMAGE:-soundings:dev}"
DEMO_PORT="${DEMO_PORT:-8000}"
DEMO_NAME="${DEMO_NAME:-soundings-demo}"
DEMO_BIND_ADDRESS="${DEMO_BIND_ADDRESS:-127.0.0.1}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"
network="$DEMO_NAME"
db="$DEMO_NAME-db"
app="$DEMO_NAME-app"
url="http://localhost:$DEMO_PORT"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# The app's settings (shared by every `soundings` command below).
app_env=(
  -e "SOUNDINGS_DATABASE_URL=postgresql+psycopg://soundings:soundings@$db:5432/soundings"
  -e SOUNDINGS_ENVIRONMENT=development
  -e SOUNDINGS_DEV_LOGIN_ENABLED=true
  -e "SOUNDINGS_BASE_URLS=$url,http://127.0.0.1:$DEMO_PORT"
)

soundings() {
  docker run --rm --network "$network" "${app_env[@]}" "$IMAGE" "$@"
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

  log "migrating and seeding the demo data ($IMAGE)"
  quietly soundings wait-for-db --timeout 60 >/dev/null
  quietly soundings migrate >/dev/null
  seed_args=(seed)
  if [ "${DEMO_RESET:-}" = "1" ]; then seed_args+=(--reset); fi
  seeded="$(quietly soundings "${seed_args[@]}")"
  grep -v '^{' <<<"$seeded" || true # the summary, without the JSON log lines

  docker rm -f "$app" >/dev/null 2>&1 || true
  log "starting the app '$app' on $url"
  docker run -d --name "$app" --network "$network" "${app_env[@]}" \
    -p "$DEMO_BIND_ADDRESS:$DEMO_PORT:8000" "$IMAGE" api >/dev/null

  for _ in $(seq 1 60); do
    if curl -fsS --noproxy '*' --max-time 2 -o /dev/null "$url/readyz" 2>/dev/null; then
      log "Soundings is ready: $url"
      printf '    Sign in as Alice Anders (platform admin) or any other demo user.\n'
      printf '    Logs: docker logs -f %s    Stop: make demo-down\n' "$app"
      return 0
    fi
    sleep 1
  done
  docker logs --tail 40 "$app" >&2 || true
  die "the app did not become ready on $url"
}

down() {
  log "removing $app, $db and network $network"
  docker rm -f -v "$app" "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}

case "${1:-up}" in
  up) up ;;
  down) down ;;
  *) die "usage: $0 up|down" ;;
esac
