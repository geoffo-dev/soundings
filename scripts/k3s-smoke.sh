#!/usr/bin/env bash
# Smoke-test the Soundings install through the k3s ingress: /healthz, /readyz and the SPA,
# then run `helm test`.
#
#   RELEASE / NAMESPACE as for k3s-install.sh
#   K3S_CONNECT_HOST  where the ingress port is reachable when not on localhost (CI with
#                     docker:dind: "docker"); requests still carry Host: localhost:<port>.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

RELEASE="${RELEASE:-soundings}"
NAMESPACE="${NAMESPACE:-soundings}"
BASE_URL="http://localhost:$K3S_HTTP_PORT"
curl_args=(--noproxy '*')
if [ -n "${K3S_CONNECT_HOST:-}" ]; then
  curl_args+=(--connect-to "localhost:$K3S_HTTP_PORT:$K3S_CONNECT_HOST:$K3S_HTTP_PORT")
fi
require_k3s

# check PATH EXPECTED_STATUS CONTENT_TYPE_PREFIX: retried for up to 60 s (ingress warm-up).
check() {
  local path="$1" want_status="$2" want_type="$3" out status type
  for _ in $(seq 1 30); do
    out="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL$path" 2>/dev/null || true)"
    status="${out%% *}"; type="${out#* }"
    if [ "$status" = "$want_status" ] && [[ "$type" == "$want_type"* ]]; then
      printf '  ok  %-10s %s %s\n' "$path" "$status" "$type"
      return 0
    fi
    sleep 2
  done
  printf '  FAIL %-10s got "%s", want %s %s\n' "$path" "$out" "$want_status" "$want_type" >&2
  return 1
}

log "smoke test against $BASE_URL"
failed=0
check /healthz 200 application/json || failed=1
check /readyz 200 application/json || failed=1
check / 200 text/html || failed=1
check /api/v1/openapi.json 200 application/json || failed=1

log "helm test $RELEASE"
helm test "$RELEASE" --namespace "$NAMESPACE" --logs --hide-notes || failed=1

[ $failed -eq 0 ] || die "smoke test failed"
log "smoke test passed"
