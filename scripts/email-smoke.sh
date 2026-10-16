#!/usr/bin/env bash
# Email smoke test against a running Soundings with the demo data, the dev login, the
# worker and Mailpit as its SMTP server: the SPEC Phase 3 acceptance through the API.
#
#   scripts/email-smoke.sh [BASE_URL]      # default http://localhost:8000
#
#   1. Sign in (dev login) as a platform admin; Settings > Email says SMTP is configured.
#   2. Invite an evaluator to an idea: one email reaches them in Mailpit, with the idea
#      key in the subject, a link to <BASE_URL>/ideas/<KEY>?evaluate=1 (the evaluate
#      sheet) in the HTML and text parts, and List-Unsubscribe headers.
#   3. SMTP down: stop Mailpit ($MAILPIT_STOP), invite a second evaluator, and wait until
#      the outbox shows the email queued after a failed attempt. Start Mailpit again
#      ($MAILPIT_START): the email arrives, once.
#   Clean-up (also on failure): both evaluators removed again, so it can run repeatedly.
#
#   MAILPIT_URL    Mailpit's UI/API (default http://localhost:8025); http://<name>.localhost
#                  URLs go to localhost with that Host header (the k3s ingress)
#   MAILPIT_STOP / MAILPIT_START  shell commands that stop / start the SMTP server
#                  (default: docker stop / docker start $MAILPIT_CONTAINER); both empty
#                  (MAILPIT_OUTAGE=0) skips step 3
#   MAILPIT_CONTAINER  (default soundings-dev-mailpit-1, the dev compose service)
#   DELIVERY_TIMEOUT   seconds to wait for the email after Mailpit is back (default 180;
#                  the worker retries after 30 s, 1 min, 2 min, ...)
#   CONNECT_HOST   connect to this host instead of localhost (CI with docker:dind)
# Needs curl and jq.
set -euo pipefail
here="$(dirname "$0")"
# shellcheck source-path=SCRIPTDIR source=lib/mailpit.sh
source "$here/lib/mailpit.sh"

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
MAILPIT_URL="${MAILPIT_URL:-http://localhost:8025}"
MAILPIT_CONTAINER="${MAILPIT_CONTAINER:-soundings-dev-mailpit-1}"
MAILPIT_STOP="${MAILPIT_STOP-docker stop $MAILPIT_CONTAINER}"
MAILPIT_START="${MAILPIT_START-docker start $MAILPIT_CONTAINER}"
DELIVERY_TIMEOUT="${DELIVERY_TIMEOUT:-180}"
command -v jq >/dev/null || { echo "email-smoke: jq is required" >&2; exit 1; }

curl_args=(--noproxy '*' --max-time 30)
if [ -n "${CONNECT_HOST:-}" ]; then
  for url in "$BASE_URL" "$MAILPIT_URL"; do
    port="$(sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#' <<<"$url")"
    port="${port:-80}"
    curl_args+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
    MAILPIT_CURL_ARGS+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
  done
fi
work="$(mktemp -d)"
jar="$work/cookies"
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
app() { curl -sS "${curl_args[@]}" -b "$jar" -c "$jar" "$@"; }
csrf() { awk '$6 ~ /soundings_csrf$/ { print $7 }' "$jar"; }
# write METHOD PATH [JSON]: a state-changing request with the CSRF header; prints
# "<status>" and leaves the body in $work/body.json.
write() {
  local args=(-X "$1" -H "X-CSRF-Token: $(csrf)" -o "$work/body.json" -w '%{http_code}')
  [ $# -lt 3 ] || args+=(-H 'Content-Type: application/json' -d "$3")
  app "${args[@]}" "$API$2"
}

key="" invited=()
mailpit_down=0
cleanup() {
  if [ "$mailpit_down" = "1" ] && [ -n "$MAILPIT_START" ]; then
    bash -c "$MAILPIT_START" >/dev/null 2>&1 || true
  fi
  for user_id in ${invited[@]+"${invited[@]}"}; do
    write DELETE "/ideas/$key/evaluators/$user_id" >/dev/null 2>&1 || true
  done
  if [ -f "$jar" ]; then write POST /auth/logout >/dev/null 2>&1 || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

printf '==> email smoke test against %s (Mailpit %s)\n' "$BASE_URL" "$MAILPIT_URL" >&2

# --- 1. Sign in as a platform admin; email is configured --------------------------------
app -f -o "$work/users.json" "$API/auth/dev/users" 2>/dev/null ||
  die "the dev login is off on $BASE_URL (GET /auth/dev/users): this test needs it"
admin_id="$(jq -r '[.[] | select(.is_platform_admin)][0].id // empty' "$work/users.json")"
[ -n "$admin_id" ] || die "no platform admin among the dev login users (demo data loaded?)"
status="$(app -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$admin_id\"}" "$API/auth/dev/login")"
[ "$status" = "200" ] || die "dev login as the platform admin: $status"
app -f -o "$work/email.json" "$API/admin/email" || die "GET /admin/email failed"
if [ "$(jq -r .configured "$work/email.json")" = "true" ]; then
  ok "Settings > Email: SMTP $(jq -r '"\(.host):\(.port) (\(.security)), links \(.links_base_url)"' "$work/email.json")"
else
  die "Settings > Email says SMTP is not configured"
fi
mailpit_wait 30 || die "Mailpit does not answer on $MAILPIT_URL"

# --- An idea the admin may invite evaluators to, and two people to invite --------------
app -f -o "$work/projects.json" "$API/projects"
for slug in $(jq -r '.[].slug' "$work/projects.json"); do
  app -f -o "$work/ideas.json" "$API/projects/$slug/ideas?limit=100"
  app -f -o "$work/people.json" "$API/users?project=$slug&limit=100"
  for idea in $(jq -r '.items[].key' "$work/ideas.json"); do
    app -f -o "$work/idea.json" "$API/ideas/$idea"
    jq -e '.permissions.can_invite_evaluators and .evaluation_open' "$work/idea.json" >/dev/null || continue
    # Members or admins of the project, not the admin, the owner or already invited,
    # with an address that can receive mail.
    jq -c --arg me "$admin_id" --slurpfile idea "$work/idea.json" '[.items[]
      | select(.project_role == "member" or .project_role == "admin")
      | select(.id != $me and .id != ($idea[0].owner.id // ""))
      | select(.id as $id | $idea[0].evaluators | map(.user.id) | index($id) | not)
      | select(.email | endswith(".invalid") | not)
      | {id, email, display_name}][0:2]' "$work/people.json" >"$work/candidates.json"
    if [ "$(jq length "$work/candidates.json")" = "2" ]; then
      key="$idea"
      break 2
    fi
  done
done
[ -n "$key" ] || die "no idea open for evaluation with two people left to invite"
ok "idea $key: inviting $(jq -r 'map(.display_name) | join(" and ")' "$work/candidates.json")"

# invite N: invite the N-th candidate (0 or 1); prints their address.
invite() {
  local user_id
  user_id="$(jq -r ".[$1].id" "$work/candidates.json")"
  status="$(write POST "/ideas/$key/evaluators" "{\"user_ids\":[\"$user_id\"]}")"
  [ "$status" = "200" ] || die "POST /ideas/$key/evaluators: $status $(cat "$work/body.json")"
  invited+=("$user_id")
}
address() { jq -r ".[$1].email" "$work/candidates.json"; }

# --- 2. Invite: one branded email with the evaluate link -------------------------------
first="$(address 0)"
since="$(date +%s)"
invite 0
if found="$(mailpit_wait_to "$first" "$since" 60)"; then
  id="$(jq -r '.[0].ID' <<<"$found")"
  mailpit_message "$id" >"$work/message.json"
  mailpit_headers "$id" >"$work/headers.json"
  subject="$(jq -r .Subject "$work/message.json")"
  link="$BASE_URL/ideas/$key?evaluate=1"
  if [[ "$subject" == *"[$key]"* ]]; then ok "email to the evaluator: \"$subject\""; else fail "subject \"$subject\" lacks [$key]"; fi
  if jq -e --arg link "$link" '(.HTML | contains($link)) and (.Text | contains($link))' "$work/message.json" >/dev/null; then
    ok "HTML and text parts link to the evaluate sheet ($link)"
  else
    fail "the email does not link to $link in both parts"
  fi
  if jq -e '."List-Unsubscribe" and ."List-Unsubscribe-Post"' "$work/headers.json" >/dev/null; then
    ok "List-Unsubscribe and List-Unsubscribe-Post headers"
  else
    fail "no List-Unsubscribe / List-Unsubscribe-Post headers"
  fi
else
  fail "no email to the invited evaluator within 60 s (is the worker running?)"
fi

# --- 3. SMTP down: queued, then delivered once when it is back --------------------------
if [ "${MAILPIT_OUTAGE:-1}" = "0" ] || [ -z "$MAILPIT_STOP" ] || [ -z "$MAILPIT_START" ]; then
  ok "outage check skipped (MAILPIT_OUTAGE=0 or no stop/start commands)"
else
  second="$(address 1)"
  second_id="$(jq -r '.[1].id' "$work/candidates.json")"
  bash -c "$MAILPIT_STOP" >/dev/null
  mailpit_down=1
  since="$(date +%s)"
  invite 1
  queued=""
  for _ in $(seq 1 30); do
    queued="$(app -f "$API/admin/email/outbox?status=queued&limit=50" |
      jq -c --arg id "$second_id" '[.items[] | select(.recipient.id == $id and .attempts >= 1 and .last_error != null)][0] // empty')"
    [ -z "$queued" ] || break
    sleep 2
  done
  if [ -n "$queued" ]; then
    ok "SMTP down: queued after $(jq -r .attempts <<<"$queued") attempt(s), last error \"$(jq -r .last_error <<<"$queued")\""
  else
    fail "SMTP down: the outbox shows no queued email with a failed attempt within 60 s"
  fi
  bash -c "$MAILPIT_START" >/dev/null
  mailpit_down=0
  mailpit_wait 60 || die "Mailpit did not come back on $MAILPIT_URL"
  start=$SECONDS
  if mailpit_wait_to "$second" "$since" "$DELIVERY_TIMEOUT" >/dev/null; then
    ok "SMTP back: delivered $((SECONDS - start)) s after Mailpit restarted"
    sleep 5 # a duplicate would arrive right behind it
    count="$(mailpit_to "$second" "$since" | jq length)"
    if [ "$count" = "1" ]; then ok "delivered once"; else fail "delivered $count times"; fi
  else
    fail "SMTP back: no email within ${DELIVERY_TIMEOUT} s"
  fi
fi

[ $failed -eq 0 ] || exit 1
printf '==> email smoke test passed\n' >&2
