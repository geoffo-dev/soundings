#!/usr/bin/env bash
# Replace the e2e database's data with fresh demo data (soundings seed --reset --force)
# while the app keeps running, and with E2E_SSO=1 the Keycloak realm with a fresh dev
# realm.
# Used between runs when the stack is kept (E2E_KEEP_STACK=1).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=stack-env.sh
source "$here/stack-env.sh"

cd "$repo/backend"
log "reseeding $pg_container"
seed_demo_data

if [ "$E2E_SSO" = "1" ]; then
  log "reloading the dev realm into $kc_container"
  quietly kc reset-realm "$E2E_URL" "http://127.0.0.1:$E2E_PORT" >/dev/null
fi
