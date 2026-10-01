#!/usr/bin/env bash
# Stop what start-stack.sh started: the `soundings api` process (by its pid file only,
# never by pattern), the Postgres container and, from an E2E_SSO=1 run, the Keycloak
# container (whatever E2E_SSO is now). Safe to run twice.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=stack-env.sh
source "$here/stack-env.sh"

stop_api

if docker inspect "$pg_container" >/dev/null 2>&1; then
  log "removing $pg_container"
  docker rm -f -v "$pg_container" >/dev/null
fi

if docker inspect "$kc_container" >/dev/null 2>&1; then
  log "removing $kc_container"
  docker rm -f -v "$kc_container" >/dev/null
fi
