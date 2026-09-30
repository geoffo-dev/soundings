#!/usr/bin/env bash
# Replace the e2e database's data with fresh demo data (soundings seed --reset) while
# the app keeps running. Used between runs when the stack is kept (E2E_KEEP_STACK=1).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=stack-env.sh
source "$here/stack-env.sh"

cd "$repo/backend"
log "reseeding $pg_container"
quietly uv run --quiet soundings seed --reset | grep -v '^{' >&2 || true
