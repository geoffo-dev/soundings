#!/usr/bin/env bash
# Smoke-test the Soundings install through the k3s ingress: /healthz, /readyz, the SPA and
# the OpenAPI document; /metrics only on its own port; with dev login on, sign in over
# the ingress (session + CSRF cookies) and read My work. Then `helm test`.
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
curl_args=(--noproxy '*' --max-time 10)
if [ -n "${K3S_CONNECT_HOST:-}" ]; then
  curl_args+=(--connect-to "localhost:$K3S_HTTP_PORT:$K3S_CONNECT_HOST:$K3S_HTTP_PORT")
fi
require_k3s
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# check PATH EXPECTED_STATUS CONTENT_TYPE_PREFIX: retried for up to 60 s (ingress warm-up).
check() {
  local path="$1" want_status="$2" want_type="$3" out status type
  for _ in $(seq 1 30); do
    out="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL$path" 2>/dev/null || true)"
    status="${out%% *}"; type="${out#* }"
    if [ "$status" = "$want_status" ] && [[ "$type" == "$want_type"* ]]; then
      printf '  ok  %-24s %s %s\n' "$path" "$status" "$type"
      return 0
    fi
    sleep 2
  done
  printf '  FAIL %-24s got "%s", want %s %s\n' "$path" "$out" "$want_status" "$want_type" >&2
  return 1
}

ok() { printf '  ok  %s\n' "$*"; }
fail() { printf '  FAIL %s\n' "$*" >&2; failed=1; }

log "smoke test against $BASE_URL"
failed=0
check /healthz 200 application/json || failed=1
check /readyz 200 application/json || failed=1
check / 200 text/html || failed=1
check /api/v1/openapi.json 200 application/json || failed=1

# /metrics lives on its own port (Service port "metrics"), never behind the ingress.
# (Outputs are captured first: `grep -q` on a pipe can make the pipeline fail.)
public_metrics="$(curl -sS "${curl_args[@]}" "$BASE_URL/metrics" 2>/dev/null || true)"
if grep -q '^# TYPE' <<<"$public_metrics"; then
  fail "/metrics is exposed through the ingress"
else
  ok "/metrics not exposed through the ingress"
fi
deployment="$(kubectl -n "$NAMESPACE" get deploy -o name \
  -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=api" | head -n 1)"
metrics_port="$(kubectl -n "$NAMESPACE" get "$deployment" \
  -o jsonpath='{.spec.template.spec.containers[0].ports[?(@.name=="metrics")].containerPort}')"
pod_metrics="$(kubectl -n "$NAMESPACE" exec "$deployment" -c api -- python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:$metrics_port/metrics', timeout=5).read().decode())" \
  2>/dev/null || true)"
if grep -q '^# TYPE' <<<"$pod_metrics"; then
  ok "/metrics on the metrics port ($metrics_port) inside the pod"
else
  fail "no Prometheus metrics on port $metrics_port"
fi

# Dev login (only when the release enables it): sign in as the first listed user (a
# platform admin), check CSRF on a write, and read My work.
dev_users="$workdir/users.json"
status="$(curl -sS "${curl_args[@]}" -o "$dev_users" -w '%{http_code}' "$BASE_URL/api/v1/auth/dev/users" || true)"
if [ "$status" = "200" ]; then
  ok "/api/v1/auth/dev/users 200 ($(grep -o '"id":' "$dev_users" | wc -l | tr -d ' ') users)"
  user_id="$(grep -o '"id":"[0-9a-f-]*"' "$dev_users" | head -n 1 | cut -d'"' -f4)"
  jar="$workdir/cookies"
  login="$(curl -sS "${curl_args[@]}" -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "{\"user_id\":\"$user_id\"}" \
    "$BASE_URL/api/v1/auth/dev/login" || true)"
  csrf="$(awk '$6 == "soundings_csrf" { print $7 }' "$jar" 2>/dev/null || true)"
  if [ "$login" = "200" ] && [ -n "$csrf" ] && grep -q soundings_session "$jar"; then
    ok "dev login 200 (session and CSRF cookies set)"
  else
    fail "dev login: status $login, csrf cookie '${csrf:-missing}'"
  fi
  # A write without the CSRF header is refused before anything else; with it, the
  # request gets as far as the (missing) idea.
  without="$(curl -sS "${curl_args[@]}" -b "$jar" -o /dev/null -w '%{http_code}' -X PUT \
    "$BASE_URL/api/v1/ideas/NOPE-1/watch" || true)"
  with="$(curl -sS "${curl_args[@]}" -b "$jar" -o /dev/null -w '%{http_code}' -X PUT \
    -H "X-CSRF-Token: $csrf" "$BASE_URL/api/v1/ideas/NOPE-1/watch" || true)"
  if [ "$without" = "403" ] && [ "$with" = "404" ]; then
    ok "CSRF: write without token 403, with token 404 (no such idea)"
  else
    fail "CSRF: without token $without (want 403), with token $with (want 404)"
  fi
  work="$workdir/work.json"
  status="$(curl -sS "${curl_args[@]}" -b "$jar" -o "$work" -w '%{http_code}' "$BASE_URL/api/v1/me/work" || true)"
  if [ "$status" = "200" ] && grep -q '"evaluations_due"' "$work"; then
    ok "/api/v1/me/work 200: $(grep -o '"counts":{[^}]*}' "$work")"
  else
    fail "/api/v1/me/work: status $status"
  fi
else
  ok "dev login is off (/api/v1/auth/dev/users $status)"
fi

log "helm test $RELEASE"
helm test "$RELEASE" --namespace "$NAMESPACE" --logs --hide-notes || failed=1

[ $failed -eq 0 ] || die "smoke test failed"
log "smoke test passed"
