#!/usr/bin/env bash
# Stop what start-stack.sh started: the `soundings api` process (by its pid file only,
# never by pattern) and the Postgres container. Safe to run twice.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=stack-env.sh
source "$here/stack-env.sh"

pid_file="$E2E_STATE_DIR/api.pid"
if [ -f "$pid_file" ]; then
  pid="$(cat "$pid_file")"
  # setsid made the api its own process group: stop uv, uvicorn and any children.
  if kill -0 "$pid" 2>/dev/null; then
    log "stopping soundings api (process group $pid)"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 25); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
fi

if docker inspect "$pg_container" >/dev/null 2>&1; then
  log "removing $pg_container"
  docker rm -f -v "$pg_container" >/dev/null
fi
