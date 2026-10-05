#!/usr/bin/env bash
# MCP server smoke test against a running Soundings with the demo data: the SPEC Phase 5
# acceptance ("an MCP client with a key can search ideas and submit an evaluation only in
# permitted projects; revoking the key cuts access immediately") as JSON-RPC over HTTP
# with curl, the way any MCP client talks to /mcp (streamable HTTP, stateless, JSON).
#
#   scripts/mcp-smoke.sh [BASE_URL]      # default http://localhost:8000
#
#   Anonymous, always (read-only):
#   1. GET /mcp is 405 (Allow: POST); POST /mcp without a key, and with a malformed one,
#      is 401 problem+json with WWW-Authenticate: Bearer; /.well-known/... (where MCP
#      clients look for OAuth) is the API's 404 problem+json, not the SPA.
#   With the dev login on (development and demo installs only):
#   2. alice (admin of Customer Innovation) creates a test idea there, invites herself
#      and carol to evaluate it and submits her own evaluation.
#   3. carol creates a key (read, evaluate, mcp; Customer Innovation only) and a read-only
#      key; her session cookie alone gets 401 at /mcp.
#   4. With the key: initialize (no session id), notifications/initialized, tools/list
#      (the nine tools), list_projects (Customer Innovation only), search_ideas and
#      get_idea (blind: no score, no evaluations, no aggregate while carol hasn't
#      submitted), get_rubric, submit_evaluation, then get_idea shows alice's evaluation
#      and the aggregate. Refused: an Internal Tools idea (not_found: outside the key's
#      projects although carol is a member), create_idea (insufficient_scope), a foreign
#      Origin (403 invalid_origin), the read-only key (403 insufficient_scope, c15).
#   5. MCP_CLIENT_HOOK, when set: a command run with MCP_KEY (and MCP_EXPECT=ok,
#      MCP_QUERY / MCP_EXPECT_KEY = the test idea) that connects another client, e.g.
#      scripts/k3s-mcp-client.sh from inside a cluster; again with
#      MCP_EXPECT=unauthorized after the revoke.
#   6. The audit log (as alice) has carol's mcp.call entries for the key, allowed and
#      denied, and the c15 refusal of the read-only key.
#   7. carol revokes the key: the very next tools/call is 401, and so is REST with it.
#   Clean-up (also on failure): both keys revoked, the test idea deleted.
#
#   CONNECT_HOST     connect to this host instead of localhost (CI with docker:dind)
#   MCP_PROJECT      slug of the permitted project (default customer-innovation)
#   MCP_OTHER_PROJECT  slug of a project carol is in but the key isn't (default internal-tools)
# Needs curl and jq. Keys travel in a header file, never on a command line.
# `test && ok ... || fail ...` is safe here: ok always succeeds.
# shellcheck disable=SC2015
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
MCP_URL="$BASE_URL/mcp"
MCP_PROJECT="${MCP_PROJECT:-customer-innovation}"
MCP_OTHER_PROJECT="${MCP_OTHER_PROJECT:-internal-tools}"
command -v jq >/dev/null || { echo "mcp-smoke: jq is required" >&2; exit 1; }

curl_args=(--noproxy '*' --max-time 30)
if [ -n "${CONNECT_HOST:-}" ]; then
  port="$(sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#' <<<"$BASE_URL")"
  port="${port:-80}"
  curl_args+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
fi
work="$(mktemp -d)"
chmod 700 "$work"
failed=0
ok() { printf '  ok  %s\n' "$*"; }
fail() {
  printf '  FAIL %s\n' "$*" >&2
  failed=1
}
die() {
  printf '  FAIL %s\n' "$*" >&2
  exit 1
}
header() { # NAME: the last response's header value (case-insensitive name)
  awk -v name="$(tr '[:upper:]' '[:lower:]' <<<"$1")" -F': ' \
    'tolower($1) == name { sub(/\r$/, "", $2); print $2 }' "$work/headers"
}
body_code() { jq -r '.code // empty' "$work/body" 2>/dev/null || true; }

# --- Sessions (dev login) ------------------------------------------------------------------
# as USER METHOD PATH [JSON]: a REST call in USER's session (cookie jar $work/USER.jar),
# with the CSRF header on writes; prints the status, body in $work/body.
as() {
  local method="$2" path="$3" jar="$work/$1.jar"
  local args=(-b "$jar" -c "$jar" -X "$method" -o "$work/body" -w '%{http_code}')
  if [ "$method" != GET ]; then
    args+=(-H "X-CSRF-Token: $(awk '$6 ~ /soundings_csrf$/ { print $7 }' "$jar")")
  fi
  [ $# -lt 4 ] || args+=(-H 'Content-Type: application/json' --data-binary "$4")
  curl -sS "${curl_args[@]}" "${args[@]}" "$API$path" || true
}
sign_in() { # USER: dev login as <USER>@example.com
  local id
  id="$(jq -r --arg email "$1@example.com" '.[] | select(.email == $email) | .id' "$work/users.json")"
  [ -n "$id" ] || die "dev login: no user $1@example.com"
  status="$(curl -sS "${curl_args[@]}" -c "$work/$1.jar" -o "$work/body" -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "{\"user_id\":\"$id\"}" "$API/auth/dev/login" || true)"
  [ "$status" = "200" ] || die "dev login as $1: $status"
  printf '%s' "$id"
}

# --- MCP over HTTP --------------------------------------------------------------------------
proto=2025-11-25
# post [AUTH_FILE] JSON [curl args...]: POST /mcp; prints the status; body in $work/body,
# headers in $work/headers. AUTH_FILE ("" for none) holds the Authorization header line.
post() {
  local auth="$1" body="$2"
  shift 2
  local args=()
  [ -z "$auth" ] || args+=(-H "@$auth")
  curl -sS "${curl_args[@]}" -D "$work/headers" -o "$work/body" -w '%{http_code}' \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -H "MCP-Protocol-Version: $proto" ${args[@]+"${args[@]}"} "$@" --data-binary "$body" \
    "$MCP_URL" || true
}
key_file() { # NAME SECRET: a header file for a key
  printf 'Authorization: Bearer %s\n' "$2" >"$work/$1.auth"
  printf '%s' "$work/$1.auth"
}
request() { # METHOD [PARAMS_JSON]: a JSON-RPC request (stateless: ids needn't be unique)
  local params="${2:-}"
  [ -n "$params" ] || params='{}'
  jq -nc --arg m "$1" --argjson p "$params" '{jsonrpc: "2.0", id: 1, method: $m, params: $p}'
}
# tool NAME ARGUMENTS_JSON: tools/call with $key_auth; prints "<status> <isError>" and
# leaves the JSON-RPC response in $work/body.
tool() {
  local status
  status="$(post "$key_auth" "$(request tools/call "$(jq -nc --arg n "$1" --argjson a "$2" \
    '{name: $n, arguments: $a}')")")"
  printf '%s %s' "$status" "$(jq -r 'if .result == null then "none" else (.result.isError // false) end' \
    "$work/body" 2>/dev/null || echo none)"
}
result() { jq -c ".result.structuredContent | ${1:-.}" "$work/body" 2>/dev/null || true; }
tool_code() { jq -r '.result.structuredContent.code // empty' "$work/body" 2>/dev/null || true; }

alice_jar_ready=0 idea_id="" key_id="" read_key_id=""
cleanup() {
  if [ -n "$key_id$read_key_id" ]; then
    for id in $key_id $read_key_id; do as carol DELETE "/me/api-keys/$id" >/dev/null; done
  fi
  if [ -n "$idea_id" ] && [ "$alice_jar_ready" = 1 ]; then
    status="$(as alice DELETE "/ideas/$idea_id")"
    [ "$status" = "204" ] && ok "clean-up: the test idea is deleted" ||
      fail "clean-up: DELETE /ideas/$idea_id answered $status"
  fi
  rm -rf "$work"
}
trap cleanup EXIT

printf '\033[1;34m==>\033[0m MCP smoke against %s\n' "$MCP_URL" >&2

# --- 1. Anonymous ---------------------------------------------------------------------------
status="$(curl -sS "${curl_args[@]}" -D "$work/headers" -o "$work/body" -w '%{http_code}' "$MCP_URL" || true)"
[ "$status" = "405" ] && [ "$(header allow)" = "POST" ] && ok "GET /mcp: 405, Allow: POST" ||
  fail "GET /mcp: $status, Allow '$(header allow)' (want 405, POST)"

status="$(post "" "$(request initialize)")"
challenge="$(header www-authenticate)"
[ "$status" = "401" ] && [[ "$(header content-type)" == application/problem+json* ]] &&
  [[ "$challenge" == Bearer* ]] && [ "$(header cache-control)" = "no-store" ] &&
  ok "POST /mcp without a key: 401 problem+json, WWW-Authenticate: $challenge" ||
  fail "POST /mcp without a key: $status $(header content-type) '$challenge' (want 401 problem+json, Bearer, no-store)"
anonymous_body="$(jq -c 'del(.request_id)' "$work/body" 2>/dev/null || true)"

printf 'Authorization: Bearer sdg_notakey\n' >"$work/bad.auth"
status="$(post "$work/bad.auth" "$(request initialize)")"
[ "$status" = "401" ] && [ "$(jq -c 'del(.request_id)' "$work/body" 2>/dev/null)" = "$anonymous_body" ] &&
  ok "POST /mcp with a malformed key: the same 401" ||
  fail "POST /mcp with a malformed key: $status (want the same 401 as without a key)"

status="$(curl -sS "${curl_args[@]}" -D "$work/headers" -o "$work/body" -w '%{http_code}' \
  "$BASE_URL/.well-known/oauth-protected-resource" || true)"
[ "$status" = "404" ] && [[ "$(header content-type)" == application/problem+json* ]] &&
  ok "/.well-known/oauth-protected-resource: 404 problem+json (keys are issued in the app)" ||
  fail "/.well-known/oauth-protected-resource: $status $(header content-type) (want 404 problem+json)"

# --- 2. The test idea (dev login only) ------------------------------------------------------
status="$(curl -sS "${curl_args[@]}" -o "$work/users.json" -w '%{http_code}' "$API/auth/dev/users" || true)"
if [ "$status" != "200" ]; then
  ok "dev login is off (/api/v1/auth/dev/users $status): key and tool checks skipped"
  [ $failed -eq 0 ] || exit 1
  exit 0
fi
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
run="$(date +%s)-$RANDOM"
alice_id="$(sign_in alice)"
alice_jar_ready=1
carol_id="$(sign_in carol)"

[ "$(as alice GET "/projects/$MCP_PROJECT")" = "200" ] || die "GET /projects/$MCP_PROJECT as alice"
project_id="$(jq -r .id "$work/body")"
criteria="$(jq -c '[.rubric[].id]' "$work/body")"
[ "$(as carol GET "/projects/$MCP_OTHER_PROJECT/ideas?limit=1")" = "200" ] ||
  die "carol can't list $MCP_OTHER_PROJECT in the app"
other_key="$(jq -r '.items[0].key' "$work/body")"

status="$(as alice POST "/projects/$MCP_PROJECT/ideas" "$(jq -nc --arg r "$run" \
  '{title: ("MCP smoke " + $r), summary: "Created by scripts/mcp-smoke.sh; deleted at the end."}')")"
[ "$status" = "201" ] || die "create the test idea as alice: $status $(cat "$work/body")"
idea_id="$(jq -r .id "$work/body")"
idea_key="$(jq -r .key "$work/body")"
status="$(as alice POST "/ideas/$idea_id/evaluators" "$(jq -nc --arg a "$alice_id" --arg c "$carol_id" '{user_ids: [$a, $c]}')")"
[ "$status" = "200" ] || die "invite alice and carol to evaluate $idea_key: $status $(cat "$work/body")"
status="$(as alice PUT "/ideas/$idea_id/evaluations/me" "$(jq -nc --argjson c "$criteria" \
  '{scores: [$c[] | {criterion_id: ., score: 4}], recommendation: "go", submit: true}')")"
[ "$status" = "200" ] || die "alice submits her evaluation of $idea_key: $status $(cat "$work/body")"
ok "test idea $idea_key in $MCP_PROJECT: alice and carol invited, alice's evaluation submitted"

# --- 3. carol's keys --------------------------------------------------------------------------
status="$(as carol POST /me/api-keys "$(jq -nc --arg r "$run" --arg p "$project_id" \
  '{name: ("mcp-smoke " + $r), scopes: ["evaluate", "mcp"], project_ids: [$p]}')")"
[ "$status" = "201" ] || die "carol creates a key: $status $(cat "$work/body")"
key_id="$(jq -r .key.id "$work/body")"
secret="$(jq -r .secret "$work/body")"
scopes="$(jq -c .key.scopes "$work/body")"
prefix="$(jq -r .key.prefix "$work/body")"
key_auth="$(key_file key "$secret")"
unset secret
[ "$scopes" = '["read","evaluate","mcp"]' ] && [[ "$prefix" == sdg_* ]] &&
  ok "carol's key $prefix…: scopes $scopes (read added to evaluate), $MCP_PROJECT only" ||
  fail "carol's key: scopes $scopes, prefix $prefix (want read added, sdg_ prefix)"
status="$(as carol POST /me/api-keys "$(jq -nc --arg r "$run" '{name: ("mcp-smoke read " + $r), scopes: ["read"]}')")"
[ "$status" = "201" ] || die "carol creates a read-only key: $status"
read_key_id="$(jq -r .key.id "$work/body")"
read_auth="$(key_file read "$(jq -r .secret "$work/body")")"
: >"$work/body"

status="$(post "" "$(request initialize)" -b "$work/carol.jar")"
[ "$status" = "401" ] && ok "/mcp with carol's session cookie only: 401" ||
  fail "/mcp with a session cookie only: $status (want 401: /mcp takes keys only)"

# --- 4. The MCP session with the key --------------------------------------------------------
status="$(post "$key_auth" "$(request initialize "$(jq -nc --arg v "$proto" \
  '{protocolVersion: $v, capabilities: {}, clientInfo: {name: "mcp-smoke", version: "1"}}')")")"
server="$(jq -r '.result.serverInfo.name // empty' "$work/body" 2>/dev/null || true)"
negotiated="$(jq -r '.result.protocolVersion // empty' "$work/body" 2>/dev/null || true)"
if [ "$status" = "200" ] && [ "$server" = "soundings" ] && [ -z "$(header mcp-session-id)" ] &&
  jq -e '.result.instructions | length > 0' "$work/body" >/dev/null 2>&1; then
  ok "initialize: server $server $(jq -r .result.serverInfo.version "$work/body"), protocol $negotiated, instructions, no session id (stateless)"
  proto="$negotiated"
else
  die "initialize: $status $(head -c 300 "$work/body")"
fi
status="$(post "$key_auth" '{"jsonrpc":"2.0","method":"notifications/initialized"}')"
[ "$status" = "202" ] && ok "notifications/initialized: 202" || fail "notifications/initialized: $status (want 202)"

status="$(post "$key_auth" "$(request tools/list)")"
tools="$(jq -c '[.result.tools[].name] | sort' "$work/body" 2>/dev/null || echo '[]')"
want='["add_comment","create_idea","get_idea","get_proposal","get_rubric","list_projects","propose_proposal_section","search_ideas","submit_evaluation"]'
[ "$status" = "200" ] && [ "$tools" = "$want" ] &&
  jq -e '[.result.tools[] | select(.inputSchema and .outputSchema)] | length == 9' "$work/body" >/dev/null &&
  ok "tools/list: the nine tools, each with input and output schemas" ||
  fail "tools/list: $status $tools"

out="$(tool list_projects '{}')"
projects="$(result '[.projects[].slug]')"
[ "$out" = "200 false" ] && [ "$projects" = "[\"$MCP_PROJECT\"]" ] &&
  ok "list_projects: $projects (the key's project only)" || fail "list_projects: $out $projects"

out="$(tool search_ideas "$(jq -nc --arg q "$idea_key" '{query: $q}')")"
found="$(result "[.items[] | select(.key == \"$idea_key\") | {score, score_hidden, my_evaluation_state}]")"
[ "$out" = "200 false" ] && [ "$found" = '[{"score":null,"score_hidden":true,"my_evaluation_state":"invited"}]' ] &&
  ok "search_ideas $idea_key: found, blind ($found)" || fail "search_ideas $idea_key: $out $found"

out="$(tool get_idea "$(jq -nc --arg i "$idea_key" '{idea: $i}')")"
blind="$(result '.idea | {aggregate, evaluation_count, evaluations: (.evaluations | length), score_hidden}')"
[ "$out" = "200 false" ] && [ "$blind" = '{"aggregate":null,"evaluation_count":0,"evaluations":0,"score_hidden":true}' ] &&
  ok "get_idea before submitting: no aggregate, no evaluations ($blind)" || fail "get_idea before submitting: $out $blind"

out="$(tool get_rubric "$(jq -nc --arg i "$idea_key" '{idea: $i}')")"
rubric="$(result '[.criteria[].id]')"
[ "$out" = "200 false" ] && [ "$(jq -c 'sort' <<<"$rubric")" = "$(jq -c 'sort' <<<"$criteria")" ] &&
  ok "get_rubric: $(jq length <<<"$rubric") criteria" || fail "get_rubric: $out $rubric"

out="$(tool submit_evaluation "$(jq -nc --arg i "$idea_key" --argjson c "$rubric" \
  '{idea: $i, scores: [$c[] | {criterion_id: ., score: 2}], recommendation: "maybe",
    comment: "Submitted by scripts/mcp-smoke.sh through MCP."}')")"
state="$(result '.evaluation.state')"
[ "$out" = "200 false" ] && [ "$state" = '"submitted"' ] &&
  ok "submit_evaluation: $state" || fail "submit_evaluation: $out $(result)"

out="$(tool get_idea "$(jq -nc --arg i "$idea_key" '{idea: $i}')")"
after="$(result '.idea | {aggregate: (.aggregate != null), evaluation_count, score_hidden,
  others: [.evaluations[].evaluator.display_name], mine: .my_evaluation.state}')"
[ "$out" = "200 false" ] &&
  [ "$after" = '{"aggregate":true,"evaluation_count":1,"score_hidden":false,"others":["Alice Anders"],"mine":"submitted"}' ] &&
  ok "get_idea after submitting: alice's evaluation and the aggregate ($after)" ||
  fail "get_idea after submitting: $out $after $(result '.idea | {evaluators, evaluations}')"

out="$(tool get_idea "$(jq -nc --arg i "$other_key" '{idea: $i}')")"
[ "$out" = "200 true" ] && [ "$(tool_code)" = "not_found" ] &&
  ok "get_idea $other_key ($MCP_OTHER_PROJECT, carol's in the app): not_found outside the key's projects" ||
  fail "get_idea $other_key: $out $(tool_code) (want not_found)"
out="$(tool create_idea "$(jq -nc --arg p "$MCP_PROJECT" '{project: $p, title: "Not allowed", summary: "No write scope."}')")"
[ "$out" = "200 true" ] && [ "$(tool_code)" = "insufficient_scope" ] &&
  ok "create_idea without the write scope: insufficient_scope" ||
  fail "create_idea: $out $(tool_code) (want insufficient_scope)"

status="$(post "$key_auth" "$(request tools/list)" -H 'Origin: https://evil.example')"
[ "$status" = "403" ] && [ "$(body_code)" = "invalid_origin" ] &&
  ok "a foreign Origin: 403 invalid_origin (DNS rebinding)" ||
  fail "a foreign Origin: $status $(body_code) (want 403 invalid_origin)"
status="$(post "$read_auth" "$(request tools/list)")"
[ "$status" = "403" ] && [ "$(body_code)" = "insufficient_scope" ] &&
  [[ "$(header www-authenticate)" == *insufficient_scope* ]] &&
  ok "the read-only key: 403 insufficient_scope ($(header www-authenticate))" ||
  fail "the read-only key: $status $(body_code) (want 403 insufficient_scope, c15)"

# --- 5. Another client (e.g. inside the cluster) --------------------------------------------
if [ -n "${MCP_CLIENT_HOOK:-}" ]; then
  # shellcheck disable=SC2086 # a command line, split on purpose
  MCP_KEY="$(sed 's/^Authorization: Bearer //' "$key_auth")" MCP_EXPECT=ok MCP_QUERY="$idea_key" \
    MCP_EXPECT_KEY="$idea_key" $MCP_CLIENT_HOOK || fail "MCP_CLIENT_HOOK with the key"
fi

# --- 6. The audit trail ---------------------------------------------------------------------
status="$(as alice GET "/admin/audit?action=mcp.call&actor_id=$carol_id&since=$started&limit=100")"
if [ "$status" = "200" ]; then
  trail="$(jq -c --arg k "$key_id" --arg r "$read_key_id" '{
      allow: [.items[] | select(.details.api_key_id == $k and .details.decision == "allow")] | length,
      deny: [.items[] | select(.details.api_key_id == $k and .details.decision == "deny")] | length,
      c15: [.items[] | select(.details.api_key_id == $r and .details.rule == "mcp.connect")] | length,
      tools: [.items[] | select(.details.api_key_id == $k) | .details.tool] | unique}' "$work/body")"
  jq -e '.allow >= 6 and .deny >= 2 and .c15 >= 1' <<<"$trail" >/dev/null &&
    ok "audit log: carol's mcp.call entries $trail" || fail "audit log: $trail"
else
  fail "GET /admin/audit?action=mcp.call as alice: $status $(head -c 200 "$work/body")"
fi

# --- 7. Revoke ------------------------------------------------------------------------------
status="$(as carol DELETE "/me/api-keys/$key_id")"
[ "$status" = "204" ] || fail "carol revokes the key: $status"
out="$(tool search_ideas '{}')"
[[ "$out" == 401* ]] && [[ "$(header www-authenticate)" == Bearer* ]] &&
  ok "after the revoke, the next tools/call: 401" || fail "after the revoke: $out (want 401)"
status="$(curl -sS "${curl_args[@]}" -H "@$key_auth" -o /dev/null -w '%{http_code}' "$API/auth/me" || true)"
[ "$status" = "401" ] && ok "after the revoke, REST with the key: 401" ||
  fail "after the revoke, GET /api/v1/auth/me with the key: $status (want 401)"
if [ -n "${MCP_CLIENT_HOOK:-}" ]; then
  # shellcheck disable=SC2086
  MCP_KEY="$(sed 's/^Authorization: Bearer //' "$key_auth")" MCP_EXPECT=unauthorized \
    $MCP_CLIENT_HOOK || fail "MCP_CLIENT_HOOK with the revoked key"
fi

if [ -n "$idea_id" ]; then
  status="$(as alice DELETE "/ideas/$idea_id")"
  [ "$status" = "204" ] && ok "clean-up: the test idea is deleted" ||
    fail "clean-up: DELETE /ideas/$idea_id answered $status"
  idea_id=""
fi
[ $failed -eq 0 ] || exit 1
printf '\033[1;34m==>\033[0m MCP smoke passed\n' >&2
