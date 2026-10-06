#!/usr/bin/env bash
# Smoke-test the Soundings install through the k3s ingress: /healthz, /readyz, the SPA and
# the OpenAPI document; /metrics only on its own port; 413 for a 2 MiB body; with dev
# login on, sign in over the ingress (session + CSRF cookies) and read My work; with
# break-glass available, sign in with the credentials from its Secret; the public form,
# branding and proposal export (scripts/public-smoke.sh: the public project and its logo,
# and with the dev login an anonymous idea with a solved ALTCHA, approved, shortlisted,
# its proposal exported as PDF in the API pod and as Markdown, then deleted); with
# SSO=1, the single sign-on acceptance through the ingress and the cluster's Keycloak
# (scripts/sso-smoke.sh: code flow, groups -> project access, removal at the next
# sign-in, sign-out at the IdP); with SMTP=1, email through the cluster's Mailpit
# (scripts/email-smoke.sh: an invited evaluator gets the branded email with the evaluate
# link; with Mailpit scaled to 0 the next one waits in the outbox and arrives, once, when
# it is back); with MCP=1, the MCP server (scripts/mcp-smoke.sh through the ingress:
# a key, initialize, the nine tools, blind search and get_idea, submit_evaluation, the
# key's project restriction and scopes, the audit trail, revoke -> 401; and an MCP SDK
# client in a pod of the "kagent" namespace calling the Service URL, before and after
# the revoke: scripts/k3s-mcp-client.sh), plus, when the API's NetworkPolicy restricts
# ingressFrom, a pod in another namespace that can't connect; with AI=1, AI assistance
# against the fake kagent in the cluster (scripts/ai-smoke.sh through the ingress: an
# agent registered, its Secret manifest applied and its key given to the fake, test
# connection, "Ask AI to evaluate" watched over SSE by a pending evaluator, the AI
# evaluation left out of the aggregate and included on request, research, a section
# draft, a cancelled slow run, the key refused outside its runs), the example kagent
# resources against kagent's CRDs when installed, and a pod in an agent namespace
# without kagent's label that can't reach /mcp. Then `helm test` (which also calls /mcp
# through the Service: 401 without a key).
#
#   RELEASE / NAMESPACE as for k3s-install.sh
#   SSO=1             also the SSO checks (after `make k3s-keycloak k3s-install SSO=1`)
#   SMTP=1            also the email checks (after `make k3s-mailpit k3s-install SMTP=1`)
#   MCP=1             also the MCP checks (after `make k3s-install MCP=1`)
#   AI=1              also the AI checks (after `make k3s-fake-agent k3s-install AI=1`)
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

# Public form, branding and proposal export through the ingress. The ALTCHA is solved
# with the api pod's Python (it has the altcha package; CI's runner has no Python).
CONNECT_HOST="${K3S_CONNECT_HOST:-}" \
  ALTCHA_PYTHON="docker exec -i $K3S_NAME kubectl -n $NAMESPACE exec -i $deployment -c api -- python" \
  "$(dirname "$0")/public-smoke.sh" "$BASE_URL" || failed=1

# The edge rate limit on the public form's API (the chart's second Ingress with the
# Traefik middleware from dev/k3s/public-ratelimit.yaml, when k3s-install.sh set it up):
# a burst gets Traefik's own 429, the rest of the app is unaffected.
if kubectl -n "$NAMESPACE" get ingress -o name -l "app.kubernetes.io/instance=$RELEASE" | grep -q -- '-public$'; then
  limited=0
  for _ in $(seq 1 80); do
    out="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code} %{content_type}' \
      "$BASE_URL/api/v1/public/projects/customer-innovation" 2>/dev/null || true)"
    if [[ "$out" == 429* ]] && [[ "$out" != *json* ]]; then limited=$((limited + 1)); fi
  done
  health="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code}' "$BASE_URL/api/v1/branding" || true)"
  if [ "$limited" -gt 0 ] && [ "$health" = "200" ]; then
    ok "edge rate limit on /api/v1/public: $limited of 80 burst requests got Traefik's 429; /api/v1/branding still 200"
  else
    fail "edge rate limit on /api/v1/public: $limited of 80 limited (want some), /api/v1/branding $health"
  fi
fi

if [ "${SSO:-0}" = "1" ]; then
  CONNECT_HOST="${K3S_CONNECT_HOST:-}" "$(dirname "$0")/sso-smoke.sh" "$BASE_URL" || failed=1
fi

if [ "${SMTP:-0}" = "1" ]; then
  mailpit_script="$(cd "$(dirname "$0")" && pwd)/k3s-mailpit.sh"
  CONNECT_HOST="${K3S_CONNECT_HOST:-}" MAILPIT_URL="http://mailpit.localhost:$K3S_HTTP_PORT" \
    MAILPIT_STOP="$mailpit_script scale 0" MAILPIT_START="$mailpit_script scale 1" \
    "$(dirname "$0")/email-smoke.sh" "$BASE_URL" || failed=1
fi

if [ "${MCP:-0}" = "1" ]; then
  RELEASE="$RELEASE" NAMESPACE="$NAMESPACE" CONNECT_HOST="${K3S_CONNECT_HOST:-}" \
    MCP_CLIENT_HOOK="$(dirname "$0")/k3s-mcp-client.sh" \
    "$(dirname "$0")/mcp-smoke.sh" "$BASE_URL" || failed=1
  # The API's NetworkPolicy: with ingressFrom set, a namespace it doesn't admit can't
  # reach /mcp (kagent's can: above).
  policy_from="$(kubectl -n "$NAMESPACE" get networkpolicy \
    -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=api" \
    -o jsonpath='{.items[0].spec.ingress[0].from}' 2>/dev/null || true)"
  if [ -n "$policy_from" ]; then
    RELEASE="$RELEASE" NAMESPACE="$NAMESPACE" MCP_KEY=none MCP_EXPECT=blocked \
      MCP_CLIENT_NAMESPACE=mcp-outsider "$(dirname "$0")/k3s-mcp-client.sh" || failed=1
  else
    ok "networkPolicy.ingressFrom is empty: any namespace may reach /mcp (not checked)"
  fi
fi

if [ "${AI:-0}" = "1" ]; then
  here="$(cd "$(dirname "$0")" && pwd)"
  export RELEASE NAMESPACE
  # The agent the chart's kagent.examples renders, <fullname>-evaluator: registered under
  # that name, its Secret is the one the example's RemoteMCPServer reads, and the fake
  # answers where kagent would serve that Agent.
  fullname="${deployment##*/}"
  fullname="${fullname%-api}"
  CONNECT_HOST="${K3S_CONNECT_HOST:-}" AI_AGENT_NAMESPACE="$NAMESPACE" \
    AI_AGENT_NAME="${AI_AGENT_NAME:-$fullname-evaluator}" \
    AI_KEY_HOOK="$here/k3s-fake-agent.sh key" \
    AI_OBSERVATIONS="$here/k3s-fake-agent.sh observations" \
    "$here/ai-smoke.sh" "$BASE_URL" || failed=1
  if kubectl get crd agents.kagent.dev >/dev/null 2>&1; then
    "$here/k3s-kagent-crds.sh" check || failed=1
    agents="$(kubectl -n "$NAMESPACE" get agents.kagent.dev,remotemcpservers.kagent.dev \
      -l "app.kubernetes.io/instance=$RELEASE" -o name 2>/dev/null | tr '\n' ' ')"
    if [ -n "$agents" ]; then
      ok "the chart's example kagent resources exist: $agents"
    else
      fail "no example kagent resources (kagent.examples) in $NAMESPACE"
    fi
  fi
  # kagent's agent pods (label app.kubernetes.io/managed-by: kagent) in the agents'
  # namespace (by default the release's) reach /mcp; other pods there don't.
  policy_from="$(kubectl -n "$NAMESPACE" get networkpolicy \
    -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=api" \
    -o jsonpath='{.items[0].spec.ingress[0].from}' 2>/dev/null || true)"
  if grep -q 'app.kubernetes.io/managed-by' <<<"$policy_from"; then
    MCP_KEY=none MCP_EXPECT=unauthorized MCP_CLIENT_NAMESPACE="$NAMESPACE" \
      MCP_CLIENT_LABELS=app.kubernetes.io/managed-by=kagent "$here/k3s-mcp-client.sh" || failed=1
    MCP_KEY=none MCP_EXPECT=blocked MCP_CLIENT_NAMESPACE="$NAMESPACE" \
      "$here/k3s-mcp-client.sh" || failed=1
  else
    fail "the API's NetworkPolicy doesn't admit kagent's agent pods ($policy_from)"
  fi
fi

log "helm test $RELEASE"
helm test "$RELEASE" --namespace "$NAMESPACE" --logs --hide-notes || failed=1

[ $failed -eq 0 ] || die "smoke test failed"
log "smoke test passed"
