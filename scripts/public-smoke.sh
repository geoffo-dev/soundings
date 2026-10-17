#!/usr/bin/env bash
# Public submission, branding and proposal export smoke test against a running Soundings
# with the demo data (Customer Innovation's public form is on and moderated): the SPEC
# Phase 4 acceptance through the HTTP API, as an anonymous visitor and as the admin.
#
#   scripts/public-smoke.sh [BASE_URL]      # default http://localhost:8000
#
#   Anonymous, always (read-only):
#   1. The SPA serves /<slug>/submit and /track; GET /api/v1/branding (no-store); the
#      public project (name, intro, branding; nothing private); its logo with the
#      sandboxing CSP, nosniff, immutable caching and a 304 on If-None-Match; an unknown
#      form is 404; a non-JSON submission is 415.
#   With the dev login on (development and demo installs only; a real install's
#   moderators would otherwise find the test idea in their queue):
#   2. An anonymous submission with a solved ALTCHA (201, the tracking link once); the
#      same ALTCHA again is refused; the tracking link shows it waiting for review. The
#      submitter can't start a conversation (Phase 11): a reply before the team has
#      written is 409 awaiting_team, a non-JSON reply 415.
#   3. As a platform admin: approve it. Phase 11, messages with the submitter: a project
#      member is made its owner and, signed in as them, writes to the submitter (201;
#      audited as submission.message without the text); another member gets 403 and no
#      sign of the conversation, an anonymous caller 401; the tracking link shows the
#      message signed by nobody and offers a reply; the submitter replies (201); the
#      owner reads both in the submission panel, newest first. Then shortlist it, start
#      the proposal, write a section, export it as PDF (branded, rendered in the API
#      pod's child process) and Markdown, then a PDF with a 5,000-item list (bounded: 200
#      in time, no OOM kill); the tracking link follows the status. Clean-up (also on
#      failure): the idea is deleted, and its tracking link then answers 404.
#   With MAILPIT_URL (the app's SMTP server is that Mailpit), the submission also gives a
#   run-unique address, and Mailpit (filtered by recipient and time) must show: the
#   confirmation email without the tracking link; after the first confirmation
#   (tracking_link_emailed, not on a repeat) one "Your link to follow your idea" email
#   with /track#<token>; the team's message emailed (escaped HTML, signed by the team,
#   naming nobody, no Reply-To, Reply to /track?reply=1#<token>); "The submitter
#   replied" to the owner without the reply's text or the idea's title.
#
#   PUBLIC_SLUG    the project with the public form (default customer-innovation)
#   ALTCHA_PYTHON  command that runs a Python with the `altcha` package and reads the
#                  script from stdin, e.g. "docker exec -i soundings-demo-app python"
#                  (default: uv run --project backend python, the dev API's venv)
#   MAILPIT_URL    Mailpit's UI/API (unset: no email checks); http://<name>.localhost
#                  URLs go to localhost with that Host header (the k3s ingress)
#   MAIL_TIMEOUT   seconds to wait for each email (default 90; the worker sends it)
#   CONNECT_HOST   connect to this host instead of localhost (CI with docker:dind)
# Needs curl and jq.
# `test && ok ... || fail ...` is safe here: ok always succeeds.
# shellcheck disable=SC2015
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source-path=SCRIPTDIR source=lib/mailpit.sh
source "$repo/scripts/lib/mailpit.sh"

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
PUBLIC_SLUG="${PUBLIC_SLUG:-customer-innovation}"
ALTCHA_PYTHON="${ALTCHA_PYTHON:-uv run --quiet --project $repo/backend python}"
MAILPIT_URL="${MAILPIT_URL:-}"
MAIL_TIMEOUT="${MAIL_TIMEOUT:-90}"
command -v jq >/dev/null || { echo "public-smoke: jq is required" >&2; exit 1; }

curl_args=(--noproxy '*' --max-time 60)
if [ -n "${CONNECT_HOST:-}" ]; then
  for url in "$BASE_URL" ${MAILPIT_URL:+"$MAILPIT_URL"}; do
    port="$(sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#' <<<"$url")"
    port="${port:-80}"
    curl_args+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
    MAILPIT_CURL_ARGS+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
  done
fi
work="$(mktemp -d)"
jar="$work/cookies"
owner_jar="$work/owner-cookies"
member_jar="$work/member-cookies"
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
# get URL [curl args...]: anonymous; prints "<status> <content type>", the body in
# $work/body and the headers in $work/headers.
get() {
  local url="$1"
  shift
  curl -sS "${curl_args[@]}" -D "$work/headers" -o "$work/body" -w '%{http_code} %{content_type}' \
    "$@" "$url" || true
}
header() { # NAME: the last response's header value (lower-case name match)
  awk -v name="$(tr '[:upper:]' '[:lower:]' <<<"$1")" -F': ' \
    'tolower($1) == name { sub(/\r$/, "", $2); print $2 }' "$work/headers"
}
# post_json PATH JSON [curl args...]: anonymous JSON POST to the API; prints the status.
post_json() {
  local path="$1" body="$2"
  shift 2
  curl -sS "${curl_args[@]}" -o "$work/body" -w '%{http_code}' -H 'Content-Type: application/json' \
    --data-binary "$body" "$@" "$API$path" || true
}
# app_as JAR [curl args...]: a request in the session whose cookies JAR holds.
app_as() {
  local cookies="$1"
  shift
  curl -sS "${curl_args[@]}" -b "$cookies" -c "$cookies" "$@"
}
app() { app_as "$jar" "$@"; }
csrf() { awk '$6 ~ /soundings_csrf$/ { print $7 }' "${1:-$jar}"; }
# write_as JAR METHOD PATH [JSON]: in that session, with its CSRF header; prints the
# status and leaves the body in $work/body. write METHOD PATH [JSON]: as the admin.
write_as() {
  local cookies="$1"
  shift
  local args=(-X "$1" -H "X-CSRF-Token: $(csrf "$cookies")" -o "$work/body" -w '%{http_code}')
  [ $# -lt 3 ] || args+=(-H 'Content-Type: application/json' -d "$3")
  app_as "$cookies" "${args[@]}" "$API$2" || true
}
write() { write_as "$jar" "$@"; }
# read_as JAR PATH: GET in that session; prints the status, the body in $work/body.
read_as() { app_as "$1" -o "$work/body" -w '%{http_code}' "$API$2" || true; }
# dev_login JAR USER_ID: sign in with the dev login into JAR.
dev_login() {
  local status
  status="$(app_as "$1" -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "{\"user_id\":\"$2\"}" "$API/auth/dev/login" || true)"
  [ "$status" = "200" ] || die "dev login as $2: $status"
}
# wait_mail ADDRESS SINCE SUBJECT_PREFIX: the ID of the newest message to ADDRESS since
# SINCE (Unix seconds) whose subject starts with SUBJECT_PREFIX, within MAIL_TIMEOUT.
wait_mail() {
  local deadline=$((SECONDS + MAIL_TIMEOUT)) id
  while :; do
    id="$(mailpit_to "$1" "$2" |
      jq -r --arg s "$3" '[.[] | select(.Subject | startswith($s))][0].ID // empty')"
    if [ -n "$id" ]; then
      printf '%s\n' "$id"
      return 0
    fi
    [ $SECONDS -lt $deadline ] || return 1
    sleep 2
  done
}
# count_mail ADDRESS SINCE SUBJECT_PREFIX: how many such messages Mailpit holds.
count_mail() {
  mailpit_to "$1" "$2" | jq --arg s "$3" '[.[] | select(.Subject | startswith($s))] | length'
}
# fetch_mail ID: the message in $work/mail.json, its headers in $work/mail-headers.json.
fetch_mail() {
  mailpit_message "$1" >"$work/mail.json" && mailpit_headers "$1" >"$work/mail-headers.json"
}
# mail_has TEXT...: every TEXT is in the fetched message's text part.
mail_has() {
  local text
  for text in "$@"; do
    jq -e --arg t "$text" '.Text | contains($t)' "$work/mail.json" >/dev/null || return 1
  done
}
no_reply_to() { jq -e 'has("Reply-To") | not' "$work/mail-headers.json" >/dev/null; }

idea_id="" token=""
cleanup() {
  if [ -n "$idea_id" ]; then
    status="$(write DELETE "/ideas/$idea_id")"
    if [ "$status" = "204" ]; then
      ok "clean-up: the test idea is deleted"
      if [ -n "$token" ]; then
        status="$(post_json /public/track "$(jq -n --arg t "$token" '{token: $t}')")"
        [ "$status" = "404" ] && ok "its tracking link now answers 404" ||
          fail "tracking link after the delete: $status (want 404)"
      fi
    else
      fail "clean-up: DELETE /ideas/$idea_id answered $status"
    fi
  fi
  rm -rf "$work"
}
trap cleanup EXIT

printf '\033[1;34m==>\033[0m public submission, branding and export smoke against %s (form: %s)\n' \
  "$BASE_URL" "$PUBLIC_SLUG" >&2

# --- 1. Anonymous reads -------------------------------------------------------------------
for path in "/$PUBLIC_SLUG/submit" /track "/$PUBLIC_SLUG/verify" /verify; do
  out="$(get "$BASE_URL$path")"
  [[ "$out" == "200 text/html"* ]] && ok "$path: the SPA ($out)" || fail "$path: $out (want 200 text/html)"
done

out="$(get "$API/branding")"
if [[ "$out" == "200 application/json"* ]] && [ "$(header cache-control)" = "no-store" ] &&
  jq -e '.app_name and (.primary_color | test("^#[0-9a-f]{6}$"))' "$work/body" >/dev/null; then
  ok "/api/v1/branding: $(jq -c '{app_name, primary_color, font}' "$work/body") (no-store)"
else
  fail "/api/v1/branding: $out, cache-control '$(header cache-control)'"
fi

out="$(get "$API/public/projects/$PUBLIC_SLUG")"
[[ "$out" == "200 application/json"* ]] || die "public project $PUBLIC_SLUG: $out (is its public form on?)"
cp "$work/body" "$work/project.json"
# Only the name, intro, form settings and branding: no people, scores or team content.
private_keys="$(jq -r '[paths | map(strings) | .[] | select(test("^(id|key|members?|owner|evaluators?|scores?|aggregate|comments?|description_md|submitted_by|email)$"))] | unique | join(",")' "$work/project.json")"
if [ -z "$private_keys" ] && jq -e '.name and .branding.app_name' "$work/project.json" >/dev/null; then
  ok "public project: $(jq -c '{name, moderated, asks_for_email, email_required, font: .branding.font}' "$work/project.json")"
else
  fail "public project has unexpected fields: ${private_keys:-name/branding missing}"
fi

logo="$(jq -r '.branding.logo_url // empty' "$work/project.json")"
if [ -n "$logo" ]; then
  out="$(get "$BASE_URL$logo")"
  csp="$(header content-security-policy)" cache="$(header cache-control)" etag="$(header etag)"
  if [[ "$out" =~ ^200\ image/(svg\+xml|png) ]] && [[ "$csp" == *sandbox* ]] &&
    [ "$(header x-content-type-options)" = "nosniff" ] && [[ "$cache" == *immutable* ]] && [ -n "$etag" ]; then
    ok "logo $logo: $out; CSP '$csp'; $cache"
  else
    fail "logo $logo: $out; CSP '$csp'; cache '$cache'; nosniff '$(header x-content-type-options)'"
  fi
  out="$(get "$BASE_URL$logo" -H "If-None-Match: $etag")"
  [[ "$out" == 304* ]] && ok "logo with If-None-Match: 304" || fail "logo with If-None-Match: $out (want 304)"
else
  ok "the public project has no logo (its name is the wordmark)"
fi

out="$(get "$API/public/projects/no-such-form-$RANDOM")"
[[ "$out" == 404* ]] && ok "unknown public form: 404" || fail "unknown public form: $out (want 404)"
status="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code}' -H 'Content-Type: text/plain' \
  --data-binary '{"title":"x"}' "$API/public/projects/$PUBLIC_SLUG/submissions" || true)"
[ "$status" = "415" ] && ok "text/plain submission: 415" || fail "text/plain submission: $status (want 415)"

# --- 2. An anonymous submission (dev and demo installs only) ------------------------------
status="$(curl -sS "${curl_args[@]}" -o "$work/users.json" -w '%{http_code}' "$API/auth/dev/users" || true)"
if [ "$status" != "200" ]; then
  ok "dev login is off: no test submission (it would wait in a real moderation queue)"
  [ $failed -eq 0 ] || exit 1
  exit 0
fi

project_name="$(jq -r '.name' "$work/project.json")"
mail=0 submitter_email=""
if [ -n "$MAILPIT_URL" ]; then
  if ! jq -e '.asks_for_email' "$work/project.json" >/dev/null; then
    fail "MAILPIT_URL is set but the form asks for no address (is email set up on $BASE_URL?): no email checks"
  elif ! mailpit_wait 30; then
    fail "Mailpit does not answer on $MAILPIT_URL: no email checks"
  else
    mail=1
    submitter_email="public-smoke-$(date -u +%Y%m%d%H%M%S)-$RANDOM@example.org"
    ok "email checks through Mailpit $MAILPIT_URL (the submitter: $submitter_email)"
  fi
fi

out="$(get "$API/public/projects/$PUBLIC_SLUG/altcha")"
[[ "$out" == "200 application/json"* ]] || die "ALTCHA challenge: $out"
challenge_b64="$(base64 <"$work/body" | tr -d '\n')"
solver="import altcha, base64, json
c = altcha.Challenge.from_dict(json.loads(base64.b64decode('$challenge_b64')))
s = altcha.solve_challenge(c)
print(base64.b64encode(json.dumps(altcha.Payload(c, s).to_dict()).encode()).decode())"
started=$SECONDS
# shellcheck disable=SC2086 # ALTCHA_PYTHON is a command line
altcha_payload="$($ALTCHA_PYTHON - <<<"$solver" 2>"$work/solver.log" | tail -n 1)" ||
  die "solving the ALTCHA failed ($ALTCHA_PYTHON): $(tail -n 5 "$work/solver.log")"
ok "ALTCHA challenge solved ($(jq -r '.parameters.cost' "$work/body") iterations per attempt, $((SECONDS - started)) s)"

title="Smoke test: refill points in every store ($(date -u +%Y%m%dT%H%M%S)-$RANDOM)"
submission="$(jq -n --arg title "$title" --arg altcha "$altcha_payload" --arg email "$submitter_email" '{
  title: $title, summary: "Let customers refill their own containers at a station by the tills.",
  description_md: "Written by **scripts/public-smoke.sh**; deleted again at the end.",
  name: null, email: (if $email == "" then null else $email end), wants_updates: false,
  altcha: $altcha, website: ""}')"
since=$(($(date +%s) - 2))
status="$(post_json "/public/projects/$PUBLIC_SLUG/submissions" "$submission")"
[ "$status" = "201" ] || die "anonymous submission: $status $(head -c 300 "$work/body")"
token="$(jq -r '.tracking_token' "$work/body")"
tracking_url="$(jq -r '.tracking_url' "$work/body")"
if [ ${#token} -eq 43 ] && [ "$tracking_url" = "$BASE_URL/track#$token" ]; then
  ok "anonymous submission: 201, held for $(jq -r '.held_for' "$work/body"), tracking link $BASE_URL/track#…"
else
  fail "anonymous submission: token length ${#token}, tracking_url '${tracking_url%%#*}#…'"
fi
if [ $mail -eq 1 ]; then
  jq -e '.email_sent == true' "$work/body" >/dev/null && ok "the receipt: a confirmation email is on its way" ||
    fail "the receipt with an address: email_sent $(jq -r '.email_sent' "$work/body") (want true)"
fi
status="$(post_json "/public/projects/$PUBLIC_SLUG/submissions" "$submission")"
[ "$status" = "422" ] && [ "$(jq -r '.code' "$work/body")" = "challenge_failed" ] &&
  ok "the same ALTCHA solution again: 422 challenge_failed" ||
  fail "the same ALTCHA solution again: $status $(jq -r '.code // empty' "$work/body") (want 422 challenge_failed)"

track() { # prints "<held_for> <status>" for the tracking link
  local status
  status="$(post_json /public/track "$(jq -n --arg t "$token" '{token: $t}')")"
  [ "$status" = "200" ] || { echo "status-$status"; return; }
  jq -r '"\(.held_for) \(.status)"' "$work/body"
}
state="$(track)"
if [ "$state" = "moderation new" ] && [ "$(jq -r '.title' "$work/body")" = "$title" ]; then
  ok "tracking link: waiting for review (moderation, new), the title as sent"
else
  fail "tracking link: '$state' (want 'moderation new')"
fi

# The public never starts a conversation (Phase 11): no Messages section, no reply box,
# a reply is 409 awaiting_team; and a reply that isn't JSON is 415 before anything else.
reply_body() { jq -n --arg t "$token" --arg b "$1" '{token: $t, body: $b}'; }
if jq -e '.messages == [] and .can_reply == false and .reply_blocked == "awaiting_team"' \
  "$work/body" >/dev/null; then
  ok "tracking link: no messages yet, no reply box (awaiting_team)"
else
  fail "tracking link before the team writes: $(jq -c '{messages, can_reply, reply_blocked}' "$work/body")"
fi
status="$(post_json /public/track/messages "$(reply_body "Is anyone there? I'd like to add a detail.")")"
[ "$status" = "409" ] && [ "$(jq -r '.code' "$work/body")" = "awaiting_team" ] &&
  ok "a reply before the team has written: 409 awaiting_team" ||
  fail "a reply before the team has written: $status $(jq -r '.code // empty' "$work/body") (want 409 awaiting_team)"
status="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code}' -H 'Content-Type: text/plain' \
  --data-binary "$(reply_body "Plain text")" "$API/public/track/messages" || true)"
[ "$status" = "415" ] && ok "text/plain reply: 415" || fail "text/plain reply: $status (want 415)"

# --- 2b. Email (MAILPIT_URL): the confirmation, then the tracking link once ---------------
if [ $mail -eq 1 ]; then
  if id="$(wait_mail "$submitter_email" "$since" "Confirm your idea for")"; then
    fetch_mail "$id"
    verify="$(jq -r '.Text' "$work/mail.json" | grep -oE '/verify#[A-Za-z0-9_.-]+' | head -n 1 | cut -d '#' -f 2 || true)"
    if jq -e --arg t "$token" '(.Text + .HTML) | (contains("/track#") or contains($t)) | not' \
      "$work/mail.json" >/dev/null &&
      mail_has "Once you confirm, we'll email you a private link to follow your idea." && [ -n "$verify" ]; then
      ok "confirmation email: \"$(jq -r .Subject "$work/mail.json")\", no tracking link, says the link follows"
    else
      fail "confirmation email: tracking link present, the new sentence or the confirm link missing"
    fi
  else
    fail "no confirmation email to $submitter_email within ${MAIL_TIMEOUT} s (is the worker running?)"
    verify=""
  fi
  if [ -n "$verify" ]; then
    status="$(post_json /public/verify-email "$(jq -n --arg t "$verify" '{token: $t}')")"
    [ "$status" = "200" ] && jq -e '.tracking_link_emailed == true' "$work/body" >/dev/null &&
      ok "first confirmation: 200, tracking_link_emailed" ||
      fail "first confirmation: $status $(jq -c '{tracking_link_emailed, code}' "$work/body" 2>/dev/null)"
    status="$(post_json /public/verify-email "$(jq -n --arg t "$verify" '{token: $t}')")"
    [ "$status" = "200" ] && jq -e '.tracking_link_emailed == false' "$work/body" >/dev/null &&
      ok "the same confirmation again: 200, no second link email" ||
      fail "repeated confirmation: $status $(jq -c '{tracking_link_emailed, code}' "$work/body" 2>/dev/null)"
    if id="$(wait_mail "$submitter_email" "$since" "Your link to follow your idea for")"; then
      fetch_mail "$id"
      if mail_has "/track#$token" "See where your idea stands" "Keep this link private" \
        "Stop emails about this idea" &&
        jq -e --arg t "/track#$token" '.HTML | contains($t)' "$work/mail.json" >/dev/null && no_reply_to; then
        ok "tracking-link email: \"$(jq -r .Subject "$work/mail.json")\" with /track#…, no Reply-To"
      else
        fail "tracking-link email: the link, its fixed lines or the missing Reply-To don't hold"
      fi
    else
      fail "no tracking-link email to $submitter_email within ${MAIL_TIMEOUT} s"
    fi
  fi
  status="$(post_json /public/track "$(jq -n --arg t "$token" '{token: $t}')")"
  [ "$status" = "200" ] && jq -e '.email_verified and .team_messages_emailed' "$work/body" >/dev/null &&
    ok "tracking link: address confirmed, the team's messages will be emailed" ||
    fail "tracking link after confirming: $status $(jq -c '{email_verified, team_messages_emailed}' "$work/body" 2>/dev/null)"
fi

# --- 3. Moderation, messages, proposal and export as the platform admin -------------------
user_id="$(jq -r '(map(select(.is_platform_admin)) + .)[0].id' "$work/users.json")"
dev_login "$jar" "$user_id"
# The queue is oldest first; earlier runs or specs may have left ideas in it.
cursor=""
for _ in $(seq 1 25); do
  status="$(app -o "$work/queue.json" -w '%{http_code}' -G --data-urlencode "limit=200" \
    ${cursor:+--data-urlencode "cursor=$cursor"} "$API/projects/$PUBLIC_SLUG/moderation" || true)"
  idea_id="$(jq -r --arg t "$title" '.items[]? | select(.title == $t) | .id' "$work/queue.json" 2>/dev/null || true)"
  key="$(jq -r --arg t "$title" '.items[]? | select(.title == $t) | .key' "$work/queue.json" 2>/dev/null || true)"
  cursor="$(jq -r '.next_cursor // empty' "$work/queue.json" 2>/dev/null || true)"
  [ -z "$idea_id" ] && [ -n "$cursor" ] || break
done
[ -n "$idea_id" ] || die "moderation queue ($status): the test idea is not in it"
ok "moderation queue: $key waiting ($(jq -r '.total' "$work/queue.json") in all)"

status="$(write POST "/ideas/$idea_id/submission/approve")"
[ "$status" = "200" ] && ok "approve: 200" || fail "approve: $status $(head -c 200 "$work/body")"

# --- 3a. Messages with the submitter (Phase 11) -------------------------------------------
# Two members of the project who can sign in with the dev login: the owner-to-be (the
# rule's +Own overlay) and a member who sees the idea but not the conversation.
app -f -o "$work/people.json" -G --data-urlencode "project=$PUBLIC_SLUG" --data-urlencode "limit=100" \
  "$API/users" || die "GET /users?project=$PUBLIC_SLUG failed"
jq -c --slurpfile dev "$work/users.json" '[.items[] | select(.project_role == "member")
  | select(.id as $id | $dev[0] | any(.id == $id and (.is_platform_admin | not)))
  | {id, display_name, email}][0:2]' "$work/people.json" >"$work/members.json"
[ "$(jq length "$work/members.json")" = "2" ] || die "two members of $PUBLIC_SLUG with a dev login are needed"
owner_id="$(jq -r '.[0].id' "$work/members.json")"
owner_name="$(jq -r '.[0].display_name' "$work/members.json")"
owner_email="$(jq -r '.[0].email' "$work/members.json")"
member_id="$(jq -r '.[1].id' "$work/members.json")"
status="$(write PUT "/ideas/$idea_id/owner" "{\"user_id\":\"$owner_id\"}")"
[ "$status" = "200" ] || die "make $owner_name the owner: $status $(head -c 200 "$work/body")"
dev_login "$owner_jar" "$owner_id"
dev_login "$member_jar" "$member_id"
if [ $mail -eq 1 ]; then want_delivery=email want_emailed=true; else want_delivery=tracking_page want_emailed=false; fi

status="$(read_as "$owner_jar" "/ideas/$idea_id/submission")"
if [ "$status" = "200" ] && jq -e --arg d "$want_delivery" '.permissions.can_message and
  .messages.count == 0 and .messages.delivery == $d and .messages.blocked == null' "$work/body" >/dev/null; then
  ok "owner $owner_name: can message the submitter (delivery $want_delivery)"
else
  fail "the owner's submission panel: $status $(jq -c '{permissions, messages}' "$work/body" 2>/dev/null)"
fi
team_text="Thanks for the idea! Which stores did you have in mind?
We'd like to try <b>two</b> first."
reply_text="The ones by the station, ideally.
Happy to help."
mail_since=$(($(date +%s) - 2))
status="$(write_as "$owner_jar" POST "/ideas/$idea_id/submission/messages" "$(jq -n --arg b "$team_text" '{body: $b}')")"
message_id="$(jq -r '.id // empty' "$work/body" 2>/dev/null || true)"
if [ "$status" = "201" ] && jq -e --arg b "$team_text" --arg o "$owner_id" --argjson e "$want_emailed" \
  '.direction == "team" and .body == $b and .author.id == $o and .emailed == $e' "$work/body" >/dev/null; then
  ok "the owner's message to the submitter: 201 (emailed: $want_emailed)"
else
  fail "the owner's message: $status $(head -c 300 "$work/body")"
fi

status="$(read_as "$member_jar" "/ideas/$idea_id/submission/messages")"
[ "$status" = "403" ] && ok "another member: the conversation is 403" ||
  fail "another member reading the conversation: $status (want 403)"
status="$(read_as "$member_jar" "/ideas/$idea_id/submission")"
[ "$status" = "200" ] && jq -e '.messages == null and .permissions.can_message == false' "$work/body" >/dev/null &&
  ok "another member: the submission panel shows no conversation" ||
  fail "another member's submission panel: $status $(jq -c '{permissions, messages}' "$work/body" 2>/dev/null)"
status="$(curl -sS "${curl_args[@]}" -o /dev/null -w '%{http_code}' "$API/ideas/$idea_id/submission/messages" || true)"
[ "$status" = "401" ] && ok "anonymous: the conversation is 401" || fail "anonymous conversation: $status (want 401)"

status="$(post_json /public/track "$(jq -n --arg t "$token" '{token: $t}')")"
if [ "$status" = "200" ] && jq -e --arg b "$team_text" '(.messages | length) == 1 and .messages[0].direction == "team"
  and .messages[0].body == $b and (.messages[0] | has("author") | not) and .can_reply and .reply_blocked == null' \
  "$work/body" >/dev/null && ! grep -qF -e "$owner_name" -e "$owner_email" "$work/body"; then
  ok "tracking link: the team's message (signed by no one), a reply box"
else
  fail "tracking link after the team wrote: $status $(jq -c '{messages, can_reply, reply_blocked}' "$work/body" 2>/dev/null)"
fi
status="$(post_json /public/track/messages "$(reply_body "$reply_text")")"
if [ "$status" = "201" ] && jq -e --arg b "$reply_text" '(.messages | length) == 2
  and .messages[1].direction == "submitter" and .messages[1].body == $b' "$work/body" >/dev/null; then
  ok "the submitter's reply: 201, the page shows both messages"
else
  fail "the submitter's reply: $status $(head -c 300 "$work/body")"
fi

status="$(read_as "$owner_jar" "/ideas/$idea_id/submission/messages")"
if [ "$status" = "200" ] && jq -e --arg r "$reply_text" --arg m "$message_id" \
  '[.items[].direction] == ["submitter", "team"] and .items[0].body == $r and .items[0].author == null
   and .items[1].id == $m' "$work/body" >/dev/null; then
  ok "the owner's panel: the reply above the message (newest first)"
else
  fail "the owner's panel: $status $(jq -c '[.items[]? | {direction, body}]' "$work/body" 2>/dev/null)"
fi
status="$(read_as "$owner_jar" "/ideas/$idea_id/submission")"
[ "$status" = "200" ] && jq -e '.messages.count == 2 and .messages.last_direction == "submitter"' "$work/body" >/dev/null &&
  ok "the owner's submission summary: 2 messages, they replied last" ||
  fail "the owner's submission summary: $status $(jq -c '.messages' "$work/body" 2>/dev/null)"

status="$(app -o "$work/audit.json" -w '%{http_code}' -G --data-urlencode "action=submission.message" \
  --data-urlencode "target_id=$idea_id" "$API/admin/audit" || true)"
if [ "$status" = "200" ] && jq -e --arg o "$owner_id" --arg m "$message_id" '(.items | length) == 1
  and .items[0].actor_id == $o and .items[0].details.message_id == $m' "$work/audit.json" >/dev/null &&
  ! grep -qF "Which stores" "$work/audit.json"; then
  ok "audit log: one submission.message entry by the owner, without the text"
else
  fail "audit log for submission.message: $status $(jq -c '[.items[]? | {action, actor_id, details}]' "$work/audit.json" 2>/dev/null)"
fi

if [ $mail -eq 1 ]; then
  if id="$(wait_mail "$submitter_email" "$mail_since" "A message about your idea for")"; then
    fetch_mail "$id"
    if mail_has "We'd like to try <b>two</b> first." "Which stores did you have in mind?" \
      "The $project_name team" "Replies to this email aren't read: reply on your tracking page." \
      "/track#$token" "/track?reply=1#$token" "remove your email address on your tracking page" &&
      jq -e '(.HTML | contains("&lt;b&gt;two&lt;/b&gt;")) and (.HTML | contains("<b>two</b>") | not)' \
        "$work/mail.json" >/dev/null &&
      ! jq -r '.Text + .HTML' "$work/mail.json" | grep -qiF -e "$owner_name" -e "$owner_email" && no_reply_to; then
      ok "message email: \"$(jq -r .Subject "$work/mail.json")\", escaped, signed by the team, naming no one, no Reply-To"
    else
      fail "message email: its text, escaping, signature or the missing Reply-To don't hold (or it names the owner)"
    fi
  else
    fail "no message email to $submitter_email within ${MAIL_TIMEOUT} s"
  fi
  if id="$(wait_mail "$owner_email" "$mail_since" "[$key] The submitter replied")"; then
    fetch_mail "$id"
    if mail_has "The person who sent $key through the public form replied to the team." "?submission=1" &&
      jq -e --arg s "[$key] The submitter replied" '.Subject == $s' "$work/mail.json" >/dev/null &&
      ! jq -r '.Text + .HTML' "$work/mail.json" | grep -qF -e "by the station" -e "$submitter_email"; then
      ok "\"$(jq -r .Subject "$work/mail.json")\" to the owner, without the reply's text or the title"
    else
      fail "the owner's \"submitter replied\" email: fixed words or link missing, or it carries the reply"
    fi
  else
    fail "no \"The submitter replied\" email to the owner ($owner_email) within ${MAIL_TIMEOUT} s"
  fi
  links="$(count_mail "$submitter_email" "$since" "Your link to follow your idea for")"
  [ "$links" = "1" ] && ok "one tracking-link email in all" || fail "$links tracking-link emails (want 1)"
fi

status="$(write POST "/ideas/$idea_id/status" '{"status": "shortlisted"}')"
[ "$status" = "200" ] && ok "shortlist: 200" || fail "shortlist: $status $(head -c 200 "$work/body")"
status="$(write POST "/ideas/$idea_id/proposal")"
[ "$status" = "201" ] || die "start the proposal: $status $(head -c 300 "$work/body")"
version="$(jq -r '.proposal.sections[] | select(.key == "problem") | .version' "$work/body")"
risks_version="$(jq -r '.proposal.sections[] | select(.key == "risks") | .version' "$work/body")"
ok "proposal started: $(jq -r '.proposal.sections | length' "$work/body") sections, idea now $(jq -r '.proposal.idea.status' "$work/body")"
section="$(jq -n --argjson v "$version" '{base_version: $v,
  body_md: "Customers ask for **refills** in 3 of 10 store surveys.\n\n| Store | Requests |\n|---|---|\n| Leeds | 120 |\n| Ελληνικά | 7 |\n"}')"
status="$(write PUT "/ideas/$idea_id/proposal/sections/problem" "$section")"
[ "$status" = "200" ] && ok "section saved (version $(jq -r '.version' "$work/body"))" ||
  fail "save a section: $status $(head -c 200 "$work/body")"

started=$SECONDS
out="$(app -D "$work/headers" -o "$work/proposal.pdf" -w '%{http_code} %{content_type}' \
  "$API/ideas/$idea_id/proposal/pdf" || true)"
disposition="$(header content-disposition)"
if [[ "$out" == "200 application/pdf"* ]] && [ "$(head -c 5 "$work/proposal.pdf")" = "%PDF-" ] &&
  [[ "$disposition" == *"filename=\"$key-proposal.pdf\""* ]]; then
  ok "PDF export: $(wc -c <"$work/proposal.pdf" | tr -d ' ') bytes in $((SECONDS - started)) s ($disposition)"
else
  fail "PDF export: $out, $(head -c 200 "$work/proposal.pdf"), disposition '$disposition'"
fi
if [ -n "${PDF_OUT:-}" ]; then cp "$work/proposal.pdf" "$PDF_OUT"; fi
out="$(app -D "$work/headers" -o "$work/proposal.md" -w '%{http_code} %{content_type}' \
  "$API/ideas/$idea_id/proposal/markdown" || true)"
if [[ "$out" == "200 text/markdown"* ]] && grep -q "Refill\|refill" "$work/proposal.md" &&
  grep -q '| Leeds | 120 |' "$work/proposal.md"; then
  ok "Markdown export: $(wc -l <"$work/proposal.md" | tr -d ' ') lines ($(header content-disposition))"
else
  fail "Markdown export: $out"
fi

# A section of 5,000 list items (20,000 characters: what used to take the renderer past its
# 20 s limit and out of memory) prints its first part and a "too long" note, in time.
hostile="$(jq -n --argjson v "$risks_version" '{base_version: $v, body_md: ("- a\n" * 5000)}')"
status="$(write PUT "/ideas/$idea_id/proposal/sections/risks" "$hostile")"
[ "$status" = "200" ] || fail "save a 5,000-item list: $status $(head -c 200 "$work/body")"
started=$SECONDS
out="$(app -o "$work/hostile.pdf" -w '%{http_code} %{content_type}' \
  "$API/ideas/$idea_id/proposal/pdf" || true)"
if [[ "$out" == "200 application/pdf"* ]] && [ "$(head -c 5 "$work/hostile.pdf")" = "%PDF-" ]; then
  ok "PDF export with a 5,000-item list: $(wc -c <"$work/hostile.pdf" | tr -d ' ') bytes in $((SECONDS - started)) s"
else
  fail "PDF export with a 5,000-item list: $out after $((SECONDS - started)) s (want 200, the layout is bounded)"
fi

state="$(track)"
[ "$state" = "null proposal" ] && ok "tracking link: with the team, status proposal" ||
  fail "tracking link: '$state' (want 'null proposal')"

[ $failed -eq 0 ] || exit 1
printf '\033[1;34m==>\033[0m public submission, branding and export smoke passed\n' >&2
