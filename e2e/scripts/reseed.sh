#!/usr/bin/env bash
# Replace the e2e database's data with fresh demo data (soundings seed --reset --force)
# while the app keeps running, empty Mailpit, with E2E_SSO=1 the Keycloak realm with a
# fresh dev realm, and with E2E_AI=1 register the AI agent again (its key to the fake).
# Used between runs when the stack is kept (E2E_KEEP_STACK=1).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=stack-env.sh
source "$here/stack-env.sh"

cd "$repo/backend"
log "reseeding $pg_container"
[ "$E2E_AI" != "1" ] || reset_fake_agent
seed_demo_data

if [ "$E2E_SMTP" = "1" ] && mailpit_ready; then
  log "emptying $mailpit_container"
  clear_mailpit
fi

if [ "$E2E_SSO" = "1" ]; then
  log "reloading the dev realm into $kc_container"
  quietly kc reset-realm "$E2E_URL" "http://127.0.0.1:$E2E_PORT" >/dev/null
fi

if [ "$E2E_AI" = "1" ]; then
  provision_ai_agent
fi
