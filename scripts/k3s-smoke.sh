#!/usr/bin/env bash
# Smoke-test the Soundings install through the k3s ingress: /healthz, /readyz, the SPA and
# the OpenAPI document; /metrics only on its own port; 413 for a 2 MiB body; with dev
# login on, sign in over the ingress (session + CSRF cookies) and read My work; with
# break-glass available, sign in with the credentials from its Secret; with
# SSO=1, the single sign-on acceptance through the ingress and the cluster's Keycloak
# (scripts/sso-smoke.sh: code flow, groups -> project access, removal at the next
# sign-in, sign-out at the IdP). Then `helm test`.
#
#   RELEASE / NAMESPACE as for k3s-install.sh
#   SSO=1             also the SSO checks (after `make k3s-keycloak k3s-install SSO=1`)
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

# Request bodies over 1 MiB: 413 from the app itself, anonymous, both with a
# Content-Length and streamed (chunked), so they never fill the API pod's memory.
# The app stops reading a streamed body just past the limit and closes the connection;
# Traefik, still sending it, then sometimes sees a reset and answers 502 instead of
# passing the 413 on (refused either way). So through the ingress a chunked body may
# be 413 or 502, and the app's own answer is checked inside the pod: always 413.
big="$workdir/big.json"
head -c $((2 * 1024 * 1024)) /dev/zero | tr '\0' 'x' >"$big"
for mode in content-length chunked; do
  extra=()
  if [ "$mode" = chunked ]; then extra=(-H 'Transfer-Encoding: chunked'); fi
  status="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code}' \
    -H 'Content-Type: application/json' ${extra[@]+"${extra[@]}"} --data-binary "@$big" \
    "$BASE_URL/api/v1/projects" 2>/dev/null || true)"
  if [ "$status" = "413" ]; then
    ok "2 MiB POST ($mode): 413"
  elif [ "$mode" = chunked ] && [ "$status" = "502" ]; then
    ok "2 MiB POST ($mode): 502 from the ingress (connection closed early by the app)"
  else
    fail "2 MiB POST ($mode): status $status (want 413)"
  fi
done
app_port="$(kubectl -n "$NAMESPACE" get "$deployment" \
  -o jsonpath='{.spec.template.spec.containers[0].ports[?(@.name=="http")].containerPort}')"
in_pod="$(kubectl -n "$NAMESPACE" exec "$deployment" -c api -- python -c "
import http.client
conn = http.client.HTTPConnection('127.0.0.1', $app_port, timeout=10)
chunks = (b'x' * 65536 for _ in range(32))
conn.request('POST', '/api/v1/projects', body=chunks, encode_chunked=True,
             headers={'Content-Type': 'application/json', 'Host': 'localhost:$K3S_HTTP_PORT'})
print(conn.getresponse().status)" 2>/dev/null || true)"
if [ "$in_pod" = "413" ]; then
  ok "2 MiB POST (chunked) inside the pod: 413"
else
  fail "2 MiB POST (chunked) inside the pod: status '${in_pod:-none}' (want 413)"
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

# Break-glass (when the release makes it available: enabled and no oidc.issuer): sign in
# with the credentials from the Secret the api pods read, as NOTES.txt tells operators.
config="$(curl -sS "${curl_args[@]}" "$BASE_URL/api/v1/auth/config" || true)"
if grep -q '"break_glass":true' <<<"$config"; then
  secret_of() { # env var -> "secret-name key" from the api Deployment
    kubectl -n "$NAMESPACE" get "$deployment" -o jsonpath="{.spec.template.spec.containers[0].env[?(@.name==\"$1\")].valueFrom.secretKeyRef['name','key']}"
  }
  read_secret() { # NAME KEY (never printed)
    kubectl -n "$NAMESPACE" get secret "$1" -o jsonpath="{.data.$2}" | base64 -d
  }
  # shellcheck disable=SC2046 # "name key" split on purpose
  bg_user="$(read_secret $(secret_of SOUNDINGS_BREAK_GLASS_USERNAME))"
  # shellcheck disable=SC2046
  bg_password="$(read_secret $(secret_of SOUNDINGS_BREAK_GLASS_PASSWORD))"
  bg_body="$workdir/break-glass.json"
  jq -n --arg u "$bg_user" --arg p "$bg_password" '{username: $u, password: $p}' >"$bg_body"
  wrong="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d '{"username": "nobody", "password": "not-the-password"}' "$BASE_URL/api/v1/auth/break-glass" || true)"
  bg_jar="$workdir/break-glass-cookies"
  me="$workdir/break-glass-me.json"
  status="$(curl -sS "${curl_args[@]}" -c "$bg_jar" -o "$me" -w '%{http_code}' \
    -H 'Content-Type: application/json' --data-binary "@$bg_body" "$BASE_URL/api/v1/auth/break-glass" || true)"
  rm -f "$bg_body"
  if [ "$wrong" = "401" ] && [ "$status" = "200" ] &&
    grep -q '"auth_method":"break_glass"' "$me" && grep -q '"is_platform_admin":true' "$me" &&
    [ ${#bg_password} -ge 16 ]; then
    ok "break-glass: wrong credentials 401; the Secret's ${#bg_password}-character password signs in as platform admin"
  else
    fail "break-glass: wrong credentials $wrong (want 401), Secret's credentials $status (want 200 break_glass admin)"
  fi
  csrf="$(awk '$6 ~ /soundings_csrf$/ { print $7 }' "$bg_jar" 2>/dev/null || true)"
  curl -sS "${curl_args[@]}" -b "$bg_jar" -o /dev/null -X POST -H "X-CSRF-Token: $csrf" \
    "$BASE_URL/api/v1/auth/logout" || true
else
  ok "break-glass is not available (/api/v1/auth/config: $config)"
fi

if [ "${SSO:-0}" = "1" ]; then
  CONNECT_HOST="${K3S_CONNECT_HOST:-}" "$(dirname "$0")/sso-smoke.sh" "$BASE_URL" || failed=1
fi

log "helm test $RELEASE"
helm test "$RELEASE" --namespace "$NAMESPACE" --logs --hide-notes || failed=1

[ $failed -eq 0 ] || die "smoke test failed"
log "smoke test passed"
