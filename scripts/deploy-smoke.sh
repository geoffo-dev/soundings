#!/usr/bin/env bash
# Production-safe smoke test of a running Soundings over HTTP: no sign-in, no demo data,
# no writes. scripts/deploy.sh runs it after every deploy and rollback (after its cluster
# checks: the pods run the deployed digest, the app reports the release's version); run
# it by hand against any environment:
#
#   scripts/deploy-smoke.sh https://ideas.staging.example.internal
#
# Checks: /healthz and /readyz answer 200; the SPA loads (index.html and the script it
# references); the API refuses an anonymous caller (401 problem+json); /mcp refuses a
# request without an API key (401 with a Bearer challenge); /metrics is not served on
# the public URL. The URL's host must be one of the release's baseUrls (the app answers
# no other host). A private CA: SSL_CERT_FILE or CURL_CA_BUNDLE (the CI's CI_BUILD_CA);
# proxies: HTTPS_PROXY / NO_PROXY as curl reads them.
#
#   SMOKE_ATTEMPTS  tries per check, 2 s apart (default 30: an ingress may need a minute);
#                   once one check has used them all, the others get one try each, so a
#                   broken release is rolled back within about a minute, not one per check
set -euo pipefail

BASE_URL="${1:-${DEPLOY_URL:-}}"
[ -n "$BASE_URL" ] || { echo "usage: scripts/deploy-smoke.sh <base-url>" >&2; exit 2; }
BASE_URL="${BASE_URL%/}"
[[ "$BASE_URL" =~ ^https?://[^/]+$ ]] || { echo "error: '$BASE_URL' is not an origin (scheme://host[:port])" >&2; exit 2; }
ATTEMPTS="${SMOKE_ATTEMPTS:-30}"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
curl_args=(--silent --show-error --max-time 10)
[ -z "${CURL_CA_BUNDLE:-}" ] || curl_args+=(--cacert "$CURL_CA_BUNDLE")

failed=0
ok() { printf '  ok  %s\n' "$*"; }
fail() { printf '  FAIL %s\n' "$*" >&2; failed=1; }

# request NAME METHOD PATH [curl args]: "<status> <content type>" in $workdir/NAME.meta,
# the body in $workdir/NAME.body and the headers in $workdir/NAME.headers.
request() {
  local name="$1" method="$2" path="$3"
  shift 3
  curl "${curl_args[@]}" -X "$method" -o "$workdir/$name.body" -D "$workdir/$name.headers" \
    -w '%{http_code} %{content_type}' "$@" "$BASE_URL$path" >"$workdir/$name.meta" 2>"$workdir/$name.err" ||
    printf '000 -' >"$workdir/$name.meta"
}

# expect NAME METHOD PATH STATUS TYPE_PREFIX [curl args]: retried while the ingress warms up.
expect() {
  local name="$1" method="$2" path="$3" want_status="$4" want_type="$5" meta=""
  shift 5
  for _ in $(seq 1 "$ATTEMPTS"); do
    request "$name" "$method" "$path" "$@"
    meta="$(cat "$workdir/$name.meta")"
    if [ "${meta%% *}" = "$want_status" ] && [[ "${meta#* }" == "$want_type"* ]]; then
      ok "$method $path -> $meta"
      return 0
    fi
    sleep 2
  done
  fail "$method $path -> ${meta:-nothing} ($(head -c 200 "$workdir/$name.err" 2>/dev/null)), want $want_status $want_type"
  ATTEMPTS=1
  return 1
}

echo "==> smoke test of $BASE_URL (read-only, anonymous)" >&2
expect healthz GET /healthz 200 application/json || true
expect readyz GET /readyz 200 application/json || true

# The SPA: index.html with its root element, and the module script it loads.
if expect index GET / 200 text/html; then
  if grep -q 'id="root"' "$workdir/index.body"; then
    ok "index.html has the app's root element"
  else
    fail "index.html has no root element"
  fi
  script="$(grep -o 'src="/assets/[^"]*\.js"' "$workdir/index.body" | sed -n 's/^src="//; s/"$//; p; q' || true)"
  if [ -z "$script" ]; then
    fail "index.html references no /assets/*.js script"
  else
    expect script GET "$script" 200 "" || true
    grep -q 'javascript' "$workdir/script.meta" || fail "$script is not served as JavaScript"
  fi
fi

# The API refuses anonymous callers.
expect me GET /api/v1/auth/me 401 application/problem+json || true

# The MCP server refuses a request without an API key and asks for a bearer key.
if expect mcp POST /mcp 401 application/problem+json \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"ping"}'; then
  if grep -qi '^www-authenticate: *bearer' "$workdir/mcp.headers"; then
    ok "/mcp asks for a bearer key"
  else
    fail "/mcp answered 401 without a Bearer challenge"
  fi
fi

# Prometheus metrics live on their own port, never behind the public URL.
request metrics GET /metrics
if grep -q '^# TYPE' "$workdir/metrics.body" 2>/dev/null; then
  fail "/metrics is served on the public URL"
else
  ok "/metrics is not served on the public URL ($(cut -d' ' -f1 "$workdir/metrics.meta"))"
fi

if [ "$failed" != 0 ]; then
  echo "==> smoke test of $BASE_URL FAILED" >&2
  exit 1
fi
echo "==> smoke test of $BASE_URL passed" >&2
