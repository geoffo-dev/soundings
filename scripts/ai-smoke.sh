#!/usr/bin/env bash
# AI assistance smoke test (SPEC Phase 6 acceptance: "Ask AI to evaluate" produces a
# badged, cited evaluation excluded from the aggregate by default) against a running
# Soundings with the demo data, the dev login, features.ai on and a kagent agent that
# answers at SOUNDINGS_KAGENT_URL: Soundings' fake agent (dev/fake-agent) locally, in the
# e2e stack (E2E_AI=1) or in k3s as kagent/kagent-controller (scripts/k3s-fake-agent.sh).
# Everything goes through the real API, worker, A2A and /mcp; only the model is missing.
#
#   scripts/ai-smoke.sh [BASE_URL]        # default http://localhost:8000
#
#   1. alice (platform admin) registers the agent AI_AGENT_NAMESPACE/AI_AGENT_NAME (or, on
#      a database that has it, enables it and rotates its key): the key once, with
#      Cache-Control no-store and a Secret manifest; the built A2A URL. The key goes to the
#      agent (AI_KEY_HOOK), then Test connection is ok (the card, streaming).
#   2. A test idea in AI_PROJECT: alice and carol invited, alice submits (aggregate n=1).
#   3. alice asks the AI to evaluate: 201, again 200 with the same run; carol, a pending
#      evaluator, watches its event stream from the start: the fixed steps up to "Done",
#      and nothing of the agent's evaluation (no rationale, no source, no score).
#   4. The run succeeded with its evaluation: AI, left out of the aggregate (n still 1),
#      a rationale and two sources per criterion; carol still sees no scores; including
#      it makes n 2, leaving it out again makes it 1.
#   5. "Ask AI to research": a research note with sources. Shortlisted with a proposal, "Draft
#      section" on Risks: an AI suggestion. With AI_SMOKE_CANCEL (default 1) a second,
#      "-slow" agent's run is cancelled and ends cancelled.
#   6. With no run open, the agent's key gets 403 insufficient_scope on REST and lists
#      nothing on /mcp.
#   Clean-up (also on failure): the test idea deleted, the agents disabled (their keys
#   revoked; the next run enables them and rotates the keys).
#
#   AI_KEY_HOOK       a command that gets {namespace, name, key, secret_manifest} as JSON
#                     on stdin and gives the key to the agent, e.g. "scripts/k3s-fake-agent.sh key"
#   AI_FAKE_KEYS_DIR  without a hook: write the key to <dir>/<namespace>.<name> (the fake's
#                     FAKE_AGENT_KEYS_DIR: make dev, the e2e stack)
#   AI_OBSERVATIONS   a command printing the fake's observations of a run (RUN_ID as its
#                     argument), e.g. "scripts/k3s-fake-agent.sh observations"; or
#   AI_FAKE_URL       the fake's base URL (GET /_fake/observations/RUN_ID). Optional.
#   AI_AGENT_NAMESPACE / AI_AGENT_NAME   default soundings / ai-smoke-evaluator
#   AI_PROTOCOL       the agents' protocol: kagent_v0_10 (default; A2A 0.3) or kagent_v1_0
#                     (A2A 1.0 at /agents/<ns>/<name>; kagent 1.0 is unreleased, so this
#                     proves Soundings' client against the fake only)
#   AI_PROJECT        default customer-innovation    CONNECT_HOST  as for mcp-smoke.sh
# Needs curl and jq. Keys travel in files and stdin, never on a command line.
# `test && ok ... || fail ...` is safe here: ok always succeeds.
# shellcheck disable=SC2015
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
AGENT_NS="${AI_AGENT_NAMESPACE:-soundings}"
AGENT_NAME="${AI_AGENT_NAME:-ai-smoke-evaluator}"
PROJECT="${AI_PROJECT:-customer-innovation}"
CANCEL="${AI_SMOKE_CANCEL:-1}"
PROTOCOL="${AI_PROTOCOL:-kagent_v0_10}"
command -v jq >/dev/null || { echo "ai-smoke: jq is required" >&2; exit 1; }

connect_args=()
if [ -n "${CONNECT_HOST:-}" ]; then
  port="$(sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#' <<<"$BASE_URL")"
  port="${port:-80}"
  connect_args=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
fi
curl_args=(--noproxy '*' --max-time 30 ${connect_args[@]+"${connect_args[@]}"})
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
# body [FILTER]: the last body through jq (compact); body_r FILTER: raw output.
body() { jq -c "${1:-.}" "$work/body" 2>/dev/null || true; }
body_r() { jq -r "$1" "$work/body" 2>/dev/null || true; }

# as USER METHOD PATH [JSON]: REST in USER's session (dev login), CSRF header on writes;
# prints the status; body in $work/body, headers in $work/headers.
as() {
  local method="$2" path="$3" jar="$work/$1.jar"
  local args=(-b "$jar" -c "$jar" -X "$method" -D "$work/headers" -o "$work/body" -w '%{http_code}')
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

# --- agents ----------------------------------------------------------------------------
agent_ids=()
cleanup() {
  local id
  for id in ${agent_ids[@]+"${agent_ids[@]}"}; do
    as alice PATCH "/admin/ai-agents/$id" '{"enabled": false}' >/dev/null
  done
  if [ -n "${idea_id:-}" ]; then
    status="$(as alice DELETE "/ideas/$idea_id")"
    [ "$status" = "204" ] && ok "clean-up: the test idea is deleted; agents disabled (keys revoked)" ||
      fail "clean-up: DELETE /ideas/$idea_id answered $status"
  fi
  rm -rf "$work"
}
trap cleanup EXIT

# provision NAME PURPOSES_JSON: register the agent (or enable it and rotate its key), give
# the key to it, wait for Test connection. Sets $agent_id; the response in $work/agent.json.
provision() {
  local name="$1" purposes="$2" status existing
  status="$(as alice POST /admin/ai-agents "$(jq -nc --arg ns "$AGENT_NS" --arg n "$name" \
    --argjson p "$purposes" --arg pid "$project_id" --arg d "AI smoke ${name#ai-smoke-}" \
    --arg proto "$PROTOCOL" '{display_name: $d, description: "scripts/ai-smoke.sh", namespace: $ns,
      name: $n, protocol: $proto, purposes: $p, project_ids: [$pid]}')")"
  if [ "$status" = "409" ] && [ "$(body .code)" = '"agent_taken"' ]; then
    [ "$(as alice GET /admin/ai-agents)" = "200" ] || die "GET /admin/ai-agents: $status"
    existing="$(jq -r --arg ns "$AGENT_NS" --arg n "$name" \
      '.items[] | select(.namespace == $ns and .name == $n) | .id' "$work/body")"
    [ -n "$existing" ] || die "agent $AGENT_NS/$name is taken but not listed"
    status="$(as alice PATCH "/admin/ai-agents/$existing" "$(jq -nc --argjson p "$purposes" \
      --arg pid "$project_id" --arg proto "$PROTOCOL" \
      '{enabled: true, protocol: $proto, purposes: $p, project_ids: [$pid]}')")"
    [ "$status" = "200" ] || die "enable $AGENT_NS/$name: $status $(body)"
    status="$(as alice POST "/admin/ai-agents/$existing/key")"
    [ "$status" = "201" ] || die "rotate the key of $AGENT_NS/$name: $status $(body)"
    ok "agent $AGENT_NS/$name existed: enabled ($PROTOCOL), key rotated$( [ "$(body_r .revoked_key_id)" = null ] || printf ' (key %s revoked)' "$(body_r .revoked_key_id)")"
  elif [ "$status" = "201" ]; then
    ok "agent $AGENT_NS/$name registered ($(body_r .agent.protocol)): service account $(body .agent.service_account.display_name)"
  else
    die "register $AGENT_NS/$name: $status $(body)"
  fi
  cp "$work/body" "$work/agent.json"
  agent_id="$(jq -r .agent.id "$work/agent.json")"
  agent_ids+=("$agent_id")
  local secret manifest
  secret="$(jq -r .key.secret "$work/agent.json")"
  manifest="$(jq -r .secret_manifest "$work/agent.json")"
  [ "$(header cache-control)" = "no-store" ] && [[ "$secret" == sdg_* ]] &&
    grep -q "name: soundings-agent-$name" <<<"$manifest" && grep -qF "Bearer $secret" <<<"$manifest" &&
    ok "the key, once (Cache-Control: no-store), scopes $(jq -c .key.key.scopes "$work/agent.json"), with a Secret manifest soundings-agent-$name" ||
    fail "the key response: cache-control '$(header cache-control)', manifest $(grep -c 'Bearer sdg_' <<<"$manifest") keys"
  unset secret manifest
  # The key to the agent: the hook, or the fake's keys directory.
  jq -c '{namespace: .agent.namespace, name: .agent.name, key: .key.secret, secret_manifest}' \
    "$work/agent.json" >"$work/key.json"
  if [ -n "${AI_KEY_HOOK:-}" ]; then
    # shellcheck disable=SC2086 # a command line, split on purpose
    $AI_KEY_HOOK <"$work/key.json" || die "AI_KEY_HOOK failed"
  elif [ -n "${AI_FAKE_KEYS_DIR:-}" ]; then
    mkdir -p "$AI_FAKE_KEYS_DIR"
    (umask 077 && jq -r '"Bearer " + .key' "$work/key.json" >"$AI_FAKE_KEYS_DIR/$AGENT_NS.$name")
  else
    die "set AI_KEY_HOOK or AI_FAKE_KEYS_DIR: the agent needs its key"
  fi
  rm -f "$work/key.json"
  jq 'del(.key.secret, .secret_manifest)' "$work/agent.json" >"$work/agent.tmp" && mv "$work/agent.tmp" "$work/agent.json"
  local a2a_url test_out
  a2a_url="$(jq -r .agent.a2a_url "$work/agent.json")"
  # (Test connection allows 10 calls per admin a minute: a few tries, a few seconds apart.)
  for _ in $(seq 1 5); do
    status="$(as alice POST "/admin/ai-agents/$agent_id/test")"
    [ "$status" = "200" ] && [ "$(body .ok)" = "true" ] && break
    sleep 3
  done
  test_out="$(body '{ok, http_status, url, card: (.card | {name, streaming, protocol_versions, skills: [.skills[].id]}), error_code}')"
  [ "$(body .ok)" = "true" ] && [ "$(body .card.streaming)" = "true" ] &&
    [ "$(body .url)" = "\"${a2a_url%/}/.well-known/agent-card.json\"" ] &&
    ok "test connection: $test_out (A2A URL $a2a_url, built from the agent's namespace and name)" ||
    fail "test connection: $status $test_out (A2A URL $a2a_url)"
}

# events RUN_ID USER [LAST_EVENT_ID]: the run's SSE stream as USER until the server ends
# it (after the final event) or 150 s; the raw stream in $work/stream, status printed.
events() {
  local extra=()
  [ $# -lt 3 ] || extra=(-H "Last-Event-ID: $3")
  curl -sS --noproxy '*' --max-time 150 -N ${connect_args[@]+"${connect_args[@]}"} \
    -b "$work/$2.jar" -D "$work/headers" -o "$work/stream" -w '%{http_code}' \
    -H 'Accept: text/event-stream' ${extra[@]+"${extra[@]}"} \
    "$API/ideas/$idea_id/ai-runs/$1/events" || true
}

# wait_run RUN_ID: poll get_ai_run until it is final (at most 150 s); the run in $work/body.
wait_run() {
  local state
  for _ in $(seq 1 75); do
    [ "$(as alice GET "/ideas/$idea_id/ai-runs/$1")" = "200" ] || die "GET run $1: $(body)"
    state="$(body_r .status)"
    case "$state" in succeeded | failed | cancelled | timed_out) return 0 ;; esac
    sleep 2
  done
  die "run $1 still $state after 150 s"
}
observations() { # RUN_ID: the fake's view of the run, or nothing
  if [ -n "${AI_OBSERVATIONS:-}" ]; then
    # shellcheck disable=SC2086 # a command line, split on purpose
    $AI_OBSERVATIONS "$1" 2>/dev/null || true
  elif [ -n "${AI_FAKE_URL:-}" ]; then
    curl -sS --noproxy '*' --max-time 10 "${AI_FAKE_URL%/}/_fake/observations/$1" 2>/dev/null || true
  fi
}

printf '\033[1;34m==>\033[0m AI smoke against %s (agent %s/%s)\n' "$BASE_URL" "$AGENT_NS" "$AGENT_NAME" >&2

status="$(curl -sS "${curl_args[@]}" -o "$work/users.json" -w '%{http_code}' "$API/auth/dev/users" || true)"
[ "$status" = "200" ] || die "the AI smoke needs the dev login (/api/v1/auth/dev/users: $status)"
alice_id="$(sign_in alice)"
carol_id="$(sign_in carol)"

# --- 1. The agent -------------------------------------------------------------------------
[ "$(as alice GET /admin/ai-agents)" = "200" ] || die "GET /admin/ai-agents as alice: $(body)"
settings="$(body .settings)"
[ "$(jq -r .enabled <<<"$settings")" = "true" ] ||
  die "AI assistance is off (features.ai / SOUNDINGS_AI_ENABLED): $settings"
ok "AI settings in effect: $(jq -c '{kagent_url, kagent_token_set, default_protocol, run_timeout_seconds, max_concurrent_runs, agent_namespaces}' <<<"$settings")"
[ "$(as alice GET "/projects/$PROJECT")" = "200" ] || die "GET /projects/$PROJECT as alice"
project_id="$(body_r .id)"
criteria="$(body '[.rubric[].id]')"
provision "$AGENT_NAME" '["evaluate", "research", "draft_section"]'
evaluator_id="$agent_id"
evaluator_user="$(jq -r .agent.service_account.id "$work/agent.json")"

# --- 2. The test idea ---------------------------------------------------------------------
run="$(date +%s)-$RANDOM"
status="$(as alice POST "/projects/$PROJECT/ideas" "$(jq -nc --arg r "$run" \
  '{title: ("AI smoke " + $r), summary: "Created by scripts/ai-smoke.sh; deleted at the end."}')")"
[ "$status" = "201" ] || die "create the test idea as alice: $status $(body)"
idea_id="$(body_r .id)"
idea_key="$(body_r .key)"
status="$(as alice POST "/ideas/$idea_id/evaluators" "$(jq -nc --arg a "$alice_id" --arg c "$carol_id" '{user_ids: [$a, $c]}')")"
[ "$status" = "200" ] || die "invite alice and carol: $status $(body)"
status="$(as alice PUT "/ideas/$idea_id/evaluations/me" "$(jq -nc --argjson c "$criteria" \
  '{scores: [$c[] | {criterion_id: ., score: 4}], recommendation: "go", submit: true}')")"
[ "$status" = "200" ] || die "alice submits: $status $(body)"
[ "$(as alice GET "/ideas/$idea_id")" = "200" ] || die "GET the idea"
n_before="$(body_r .aggregate.count)"
overall_before="$(body_r .aggregate.overall)"
ok "test idea $idea_key: alice and carol invited, alice submitted (aggregate $overall_before, n=$n_before)"

# --- 3. Ask AI to evaluate ----------------------------------------------------------------
[ "$(as alice GET "/ideas/$idea_id/ai-runs")" = "200" ] || die "list_idea_ai_runs: $(body)"
listed="$(body '{ai_enabled, agents: [.agents[].id], can: .permissions.can_request_evaluation, blocked: .permissions.request_evaluation_blocked_by}')"
jq -e --arg id "$evaluator_id" '.ai_enabled and (.agents | index($id)) and .can' <<<"$listed" >/dev/null &&
  ok "the idea's AI runs: $listed" || fail "list_idea_ai_runs: $listed"
request='{"agent_id": "'"$evaluator_id"'"}'
status="$(as alice POST "/ideas/$idea_id/ai-runs/evaluation" "$request")"
[ "$status" = "201" ] || die "request_ai_evaluation: $status $(body)"
run_id="$(body_r .id)"
status="$(as alice POST "/ideas/$idea_id/ai-runs/evaluation" "$request")"
[ "$status" = "200" ] && [ "$(body_r .id)" = "$run_id" ] &&
  ok "Ask AI to evaluate: 201 run $run_id; asked again while active: 200, the same run" ||
  fail "the repeated request: $status $(body_r .id) (want 200 $run_id)"
ai_row=""
[ "$(as alice GET "/ideas/$idea_id")" = "200" ] &&
  ai_row="$(jq -c --arg u "$evaluator_user" '.evaluators[] | select(.user.id == $u) | {name: .user.display_name, is_ai, state}' "$work/body")"
[ "$(jq -r .is_ai <<<"${ai_row:-{\}}")" = "true" ] && ok "the evaluators list: the agent assigned, $ai_row" ||
  fail "the agent in the evaluators list: ${ai_row:-none} ($(jq -c '[.evaluators[] | {name: .user.display_name, is_ai, state}]' "$work/body"))"

# carol (invited, not submitted) watches the run from the start.
stream_status="$(events "$run_id" carol)"
steps="$(sed -n 's/^data: //p' "$work/stream" | jq -s -c '[.[].message]' 2>/dev/null || echo '[]')"
last="$(sed -n 's/^data: //p' "$work/stream" | tail -n 1 | jq -c '{seq, type, final}' 2>/dev/null || echo '{}')"
if [ "$stream_status" = "200" ] && [[ "$(header content-type)" == text/event-stream* ]] &&
  jq -e 'index("Read the rubric") and index("Read the idea") and index("Saved its evaluation") and index("Evaluation submitted") and index("Done")' <<<"$steps" >/dev/null &&
  [ "$(jq -r .final <<<"$last")" = "true" ]; then
  ok "carol's event stream (pending evaluator): $steps"
else
  fail "carol's event stream: $stream_status $(header content-type) $steps $last"
fi
if grep -qiE 'fake-rationale|example\.org/fake-agent|"score"|"recommendation"|rationale' "$work/stream"; then
  fail "carol's event stream carries the agent's evaluation (blind evaluation)"
else
  ok "carol's event stream: no rationale, source, score or recommendation"
fi
last_seq="$(jq -r .seq <<<"$last")"
reconnect="$(events "$run_id" carol "$last_seq")"
[ "$reconnect" = "204" ] && ok "reconnect after the final event (Last-Event-ID $last_seq): 204" ||
  fail "reconnect after the final event: $reconnect (want 204)"

# --- 4. The evaluation --------------------------------------------------------------------
wait_run "$run_id"
evaluation_id="$(body_r .result.evaluation_id)"
[ "$(body_r .status)" = "succeeded" ] && [ "$evaluation_id" != "null" ] &&
  ok "run $run_id: succeeded, $(body '{started_at, finished_at, event_count, result}')" ||
  fail "run $run_id: $(body '{status, error, result}')"
[ "$(as alice GET "/ideas/$idea_id/evaluations")" = "200" ] || die "list_evaluations as alice: $(body)"
ai_eval="$(jq -c --arg id "$evaluation_id" '.items[] | select(.id == $id)' "$work/body")"
summary="$(jq -c '{is_ai, include_in_aggregate, recommendation, scores: (.scores | length),
  rationale: ([.scores[] | select(.comment | startswith("fake-rationale"))] | length),
  sources: ([.scores[].sources | length] | unique), hosts: ([.scores[].sources[].host] | unique)}' <<<"$ai_eval")"
jq -e --argjson n "$(jq length <<<"$criteria")" '.is_ai and (.include_in_aggregate | not) and .scores == $n and .rationale == $n and .sources == [2]' <<<"$summary" >/dev/null &&
  ok "the AI evaluation (alice, the owner's view): $summary" || fail "the AI evaluation: $summary"
[ "$(as alice GET "/ideas/$idea_id")" = "200" ] || die "GET the idea"
ai_row="$(jq -c --arg u "$evaluator_user" '.evaluators[] | select(.user.id == $u) | {is_ai, state}' "$work/body")"
[ "$ai_row" = '{"is_ai":true,"state":"submitted"}' ] && ok "the evaluators list after the run: $ai_row" ||
  fail "the agent's evaluator row after the run: ${ai_row:-none}"
[ "$(body_r .aggregate.count)" = "$n_before" ] && [ "$(body_r .aggregate.overall)" = "$overall_before" ] &&
  ok "left out of the aggregate by default: $overall_before, n=$n_before unchanged" ||
  fail "the aggregate after the AI evaluation: $(body '.aggregate | {overall, count}') (want $overall_before, n=$n_before)"
[ "$(as carol GET "/ideas/$idea_id")" = "200" ] && blind="$(body '{score_hidden, aggregate}')"
[ "$(as carol GET "/ideas/$idea_id/evaluations")" = "200" ] && blind_list="$(body '{items: (.items | length), score_hidden}')"
[ "$blind" = '{"score_hidden":true,"aggregate":null}' ] && [ "$blind_list" = '{"items":0,"score_hidden":true}' ] &&
  ok "carol still sees no scores: idea $blind, evaluations $blind_list" ||
  fail "carol after the AI evaluation: idea $blind, evaluations $blind_list"
[ "$(as carol GET "/ideas/$idea_id/ai-runs/$run_id")" = "200" ] && ! grep -qiE 'fake-rationale|example\.org/fake-agent' "$work/body" &&
  ok "carol's view of the run (polling fallback): $(body '[.events[].message] | length') events, no agent text" ||
  fail "carol's view of the run: $(head -c 300 "$work/body")"
include() { as alice PUT "/ideas/$idea_id/evaluations/$evaluation_id/include-in-aggregate" "{\"include\": $1}"; }
status="$(include true)"
[ "$status" = "200" ] && [ "$(body_r .include_in_aggregate)" = "true" ] && [ "$(as alice GET "/ideas/$idea_id")" = "200" ] &&
  [ "$(body_r .aggregate.count)" = "$((n_before + 1))" ] &&
  ok "the owner includes it: aggregate $(body_r .aggregate.overall), n=$(body_r .aggregate.count)" ||
  fail "include: $status $(body '.aggregate | {overall, count}')"
status="$(include false)"
[ "$status" = "200" ] && [ "$(as alice GET "/ideas/$idea_id")" = "200" ] &&
  [ "$(body_r .aggregate.count)" = "$n_before" ] && [ "$(body_r .aggregate.overall)" = "$overall_before" ] &&
  ok "and leaves it out again: $overall_before, n=$n_before" || fail "exclude: $status $(body '.aggregate | {overall, count}')"
seen="$(observations "$run_id")"
if [ -n "$seen" ]; then
  jq -e '.message_checks == {"has_url": false, "has_api_key": false} and (.a2a_requests[0].x_user_id == "soundings")
    and (.a2a_requests[0].method == "message/stream" or .a2a_requests[0].method == "SendStreamingMessage")' <<<"$seen" >/dev/null &&
    ok "the fake agent saw: $(jq -c '{layout: .a2a_requests[0].layout, methods: [.a2a_requests[].method], a2a_version: .a2a_requests[0].a2a_version, message_checks, tools: [.tool_calls[] | .tool + ":" + (.error_code // "ok")]}' <<<"$seen")" ||
    fail "the fake agent's observations: $seen"
fi

# --- 5. Research, draft, cancel -----------------------------------------------------------
status="$(as alice POST "/ideas/$idea_id/ai-runs/research" "$request")"
[ "$status" = "201" ] || die "request_ai_research: $status $(body)"
research_id="$(body_r .id)"
wait_run "$research_id"
note_id="$(body_r .result.note_id)"
[ "$(body_r .status)" = "succeeded" ] && [ "$(as alice GET "/ideas/$idea_id/research-notes/$note_id")" = "200" ] &&
  [ "$(body '.sources | length')" = "3" ] &&
  ok "Ask AI to research: succeeded, note $(body '{agent: .agent.display_name, chars: (.body_md | length), sources: (.sources | length)}')" ||
  fail "Ask AI to research: $(body '{status, error, result}')"
status="$(as alice POST "/ideas/$idea_id/status" '{"status": "shortlisted"}')"
[ "$status" = "200" ] || fail "shortlist: $status $(body)"
status="$(as alice POST "/ideas/$idea_id/proposal")"
[ "$status" = "201" ] || fail "start the proposal: $status $(body)"
status="$(as alice POST "/ideas/$idea_id/ai-runs/section-draft" "$(jq -nc --arg a "$evaluator_id" '{agent_id: $a, section_key: "risks"}')")"
[ "$status" = "201" ] || die "request_ai_section_draft: $status $(body)"
draft_id="$(body_r .id)"
wait_run "$draft_id"
[ "$(body_r .status)" = "succeeded" ] && [ "$(body_r .result.suggestion_id)" != "null" ] &&
  ok "Draft section (Risks): succeeded, suggestion $(body_r .result.suggestion_id)" ||
  fail "Draft section: $(body '{status, error, result}')"

if [ "$CANCEL" = "1" ]; then
  provision "$AGENT_NAME-slow" '["evaluate"]'
  status="$(as alice POST "/ideas/$idea_id/ai-runs/evaluation" "{\"agent_id\": \"$agent_id\"}")"
  [ "$status" = "201" ] || die "request a slow run: $status $(body)"
  slow_id="$(body_r .id)"
  for _ in $(seq 1 30); do
    [ "$(as alice GET "/ideas/$idea_id/ai-runs/$slow_id")" = "200" ] && [ "$(body_r .status)" = "running" ] &&
      [ "$(body '[.events[].type] | index("agent_working")')" != "null" ] && break
    sleep 1
  done
  status="$(as alice POST "/ideas/$idea_id/ai-runs/$slow_id/cancel")"
  cancel_answer="$(body '{status, cancel_requested}')"
  wait_run "$slow_id"
  [ "$(body_r .status)" = "cancelled" ] &&
    ok "a slow run cancelled while running: cancel $status $cancel_answer, then $(body '[.events[].type]')" ||
    fail "the slow run: cancel $status $cancel_answer, then $(body '{status, error}')"
  seen="$(observations "$slow_id")"
  [ -z "$seen" ] || { [ "$(jq -r .cancel_requests <<<"$seen")" -ge 1 ] &&
    ok "the fake agent got tasks/cancel ($(jq -c '[.a2a_requests[].method]' <<<"$seen"))" ||
    fail "the fake agent saw no cancel: $seen"; }
fi

# --- 6. The agent's key outside a run -----------------------------------------------------
status="$(as alice POST "/admin/ai-agents/$evaluator_id/key")"
[ "$status" = "201" ] || fail "rotate the evaluator's key for the last check: $status"
printf 'Authorization: Bearer %s\n' "$(body_r .key.secret)" >"$work/agent.auth"
: >"$work/body"
rest="$(curl -sS "${curl_args[@]}" -H "@$work/agent.auth" -o "$work/body" -w '%{http_code}' "$API/projects" || true)"
[ "$rest" = "403" ] && [ "$(body_r .code)" = "insufficient_scope" ] &&
  ok "the agent's key on REST: 403 insufficient_scope (MCP only)" || fail "the agent's key on REST: $rest $(body_r .code)"
mcp="$(curl -sS "${curl_args[@]}" -H "@$work/agent.auth" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-11-25' -o "$work/body" -w '%{http_code}' \
  --data-binary '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_projects","arguments":{}}}' \
  "$BASE_URL/mcp" || true)"
[ "$mcp" = "200" ] && [ "$(body '.result.structuredContent.projects')" = "[]" ] &&
  ok "the agent's key on /mcp with no run open: list_projects lists nothing" ||
  fail "the agent's key on /mcp: $mcp $(head -c 300 "$work/body")"
rm -f "$work/agent.auth"

[ $failed -eq 0 ] || exit 1
printf '\033[1;34m==>\033[0m AI smoke passed\n' >&2
