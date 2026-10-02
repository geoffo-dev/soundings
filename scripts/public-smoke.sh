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
#      same ALTCHA again is refused; the tracking link shows it waiting for review.
#   3. As a platform admin: approve it, shortlist it, start the proposal, write a section,
#      export it as PDF (branded, rendered in the API pod's child process) and Markdown,
#      then a PDF with a 5,000-item list (bounded: 200 in time, no OOM kill); the
#      tracking link follows the status. Clean-up (also on failure): the idea is
#      deleted, and its tracking link then answers 404.
#
#   PUBLIC_SLUG    the project with the public form (default customer-innovation)
#   ALTCHA_PYTHON  command that runs a Python with the `altcha` package and reads the
#                  script from stdin, e.g. "docker exec -i soundings-demo-app python"
#                  (default: uv run --project backend python, the dev API's venv)
#   CONNECT_HOST   connect to this host instead of localhost (CI with docker:dind)
# Needs curl and jq.
# `test && ok ... || fail ...` is safe here: ok always succeeds.
# shellcheck disable=SC2015
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
PUBLIC_SLUG="${PUBLIC_SLUG:-customer-innovation}"
ALTCHA_PYTHON="${ALTCHA_PYTHON:-uv run --quiet --project $repo/backend python}"
command -v jq >/dev/null || { echo "public-smoke: jq is required" >&2; exit 1; }

curl_args=(--noproxy '*' --max-time 60)
if [ -n "${CONNECT_HOST:-}" ]; then
  port="$(sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#' <<<"$BASE_URL")"
  port="${port:-80}"
  curl_args+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
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
app() { curl -sS "${curl_args[@]}" -b "$jar" -c "$jar" "$@"; }
csrf() { awk '$6 ~ /soundings_csrf$/ { print $7 }' "$jar"; }
# write METHOD PATH [JSON]: as the signed-in admin, with the CSRF header; prints the
# status and leaves the body in $work/body.
write() {
  local args=(-X "$1" -H "X-CSRF-Token: $(csrf)" -o "$work/body" -w '%{http_code}')
  [ $# -lt 3 ] || args+=(-H 'Content-Type: application/json' -d "$3")
  app "${args[@]}" "$API$2" || true
}

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
submission="$(jq -n --arg title "$title" --arg altcha "$altcha_payload" '{
  title: $title, summary: "Let customers refill their own containers at a station by the tills.",
  description_md: "Written by **scripts/public-smoke.sh**; deleted again at the end.",
  name: null, email: null, wants_updates: false, altcha: $altcha, website: ""}')"
status="$(post_json "/public/projects/$PUBLIC_SLUG/submissions" "$submission")"
[ "$status" = "201" ] || die "anonymous submission: $status $(head -c 300 "$work/body")"
token="$(jq -r '.tracking_token' "$work/body")"
tracking_url="$(jq -r '.tracking_url' "$work/body")"
if [ ${#token} -eq 43 ] && [ "$tracking_url" = "$BASE_URL/track#$token" ]; then
  ok "anonymous submission: 201, held for $(jq -r '.held_for' "$work/body"), tracking link $BASE_URL/track#…"
else
  fail "anonymous submission: token length ${#token}, tracking_url '${tracking_url%%#*}#…'"
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

# --- 3. Moderation, proposal and export as the platform admin ------------------------------
user_id="$(jq -r '(map(select(.is_platform_admin)) + .)[0].id' "$work/users.json")"
status="$(app -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$user_id\"}" "$API/auth/dev/login" || true)"
[ "$status" = "200" ] || die "dev login: $status"
status="$(app -o "$work/queue.json" -w '%{http_code}' "$API/projects/$PUBLIC_SLUG/moderation" || true)"
idea_id="$(jq -r --arg t "$title" '.items[]? | select(.title == $t) | .id' "$work/queue.json" 2>/dev/null || true)"
key="$(jq -r --arg t "$title" '.items[]? | select(.title == $t) | .key' "$work/queue.json" 2>/dev/null || true)"
[ -n "$idea_id" ] || die "moderation queue ($status): the test idea is not in it"
ok "moderation queue: $key waiting ($(jq -r '.total' "$work/queue.json") in all)"

status="$(write POST "/ideas/$idea_id/submission/approve")"
[ "$status" = "200" ] && ok "approve: 200" || fail "approve: $status $(head -c 200 "$work/body")"
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
