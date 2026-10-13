#!/usr/bin/env bash
# Bid evaluation smoke test (Phase 10, contract-phase10) against a running Soundings with
# the demo data, the dev login and the worker (documents' text is read there):
#
#   scripts/bid-smoke.sh [BASE_URL]        # default http://localhost:8000
#
#   1. alice (platform admin) makes a test idea in BID_PROJECT, shortlists it and starts its
#      proposal; mateo (a member) sees no call and may not start one; alice starts the
#      call (a copy of the project's bid template), opens it once it has a deadline.
#   2. Two bids. Bid A gets a PDF and a DOCX for the required documents, a CSV for the
#      pricing schedule (a pricing document) and the confirmations met: qualified. Bid B
#      only its form of tender: its must-haves are flagged missing and "Reject" suggested.
#      Refused uploads: the same file twice (409), a macro-enabled .docm (415
#      macro_document), a file over 25 MiB with a Content-Length and chunked (413), a
#      name with a path separator (422), anonymous (401) and a member's (403).
#   3. The worker reads the documents' text: done for all three; one page of text; the
#      download is an attachment (nosniff, sandboxing CSP, private no-store, the same
#      bytes).
#   4. Bid B is rejected with a reason, reinstated, and rejected again.
#   5. Assessors per section (carol every section without the price, bob the first and the
#      price section), the call closed to new bids: carol (no price section) sees no price
#      and the pricing document only as "restricted", bob sees the price; neither sees
#      the rejected bid; mateo sees the call's summary only, anonymous 401. My work counts
#      what each owes.
#   6. Blind: bob submits the first section; carol, still owing it, sees no scores for it;
#      once she submits, both. Then everyone submits the rest.
#   7. The comparison (alice): bid A ranked first with the total worked out here from the
#      template and the scores given, the price score 5, the disagreement flag; bid B
#      rejected, no scores. The report (Markdown and PDF) for alice, 403 for carol.
#   8. AI (BID_AI, see below): an agent with the purpose "Assess bids", "Ask AI to assess"
#      on bid A (201, again 200 with the same run): its scores with quotes found in the
#      documents, never the pricing document (the fake agent's observations), left out of
#      the total until alice includes it; carol may not see it. A second agent (-invents)
#      gives a quote that is in no document: "not found".
#   9. Bid A is awarded.
#   Clean-up (also on failure): the test idea is deleted (with its call, bids and
#   documents); the smoke's agents are disabled (keys revoked).
#
#   BID_PROJECT       default customer-innovation (alice, bob, carol and mateo are in it)
#   BID_SMOKE_FILES   the demo's bid documents (default backend/app/seed/bids)
#   BID_AI            auto (default: when AI is on and AI_KEY_HOOK is set, or
#                     AI_FAKE_KEYS_DIR with a fake agent answering at AI_FAKE_URL), 1
#                     (required) or 0
#   AI_KEY_HOOK / AI_FAKE_KEYS_DIR / AI_OBSERVATIONS / AI_FAKE_URL / AI_AGENT_NAMESPACE /
#   AI_PROTOCOL       as for scripts/ai-smoke.sh
#   BID_AI_AGENT_NAME default bid-smoke-assessor (k3s: <fullname>-bid-assessor, the chart's
#                     example Agent); the second agent is <name>-invents
#   BID_UPLOAD_HEADER a response header the upload route's edge router adds ("Name: value",
#                     k3s: dev/k3s/uploads-route.yaml), proving that route matched
#   BID_SLOW_UPLOAD   1: also upload 800 kB at 10 kB/s (about 80 s, within the app's 120 s
#                     but past Traefik's default 60 s readTimeout: the proxy must allow it)
#   CONNECT_HOST      as for mcp-smoke.sh
# Needs curl, jq, base64 and sha256sum. Keys travel in files and stdin, never on a command
# line. `test && ok ... || fail ...` is safe here: ok always succeeds.
# shellcheck disable=SC2015
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
PROJECT="${BID_PROJECT:-customer-innovation}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILES="${BID_SMOKE_FILES:-$REPO_ROOT/backend/app/seed/bids}"
BID_AI="${BID_AI:-auto}"
AGENT_NS="${AI_AGENT_NAMESPACE:-soundings}"
AGENT_NAME="${BID_AI_AGENT_NAME:-bid-smoke-assessor}"
PROTOCOL="${AI_PROTOCOL:-kagent_v0_10}"
UPLOAD_MAX=$((25 * 1024 * 1024))
for tool in jq base64 sha256sum; do
  command -v "$tool" >/dev/null || { echo "bid-smoke: $tool is required" >&2; exit 1; }
done
[ -f "$FILES/northwind-form-of-tender.pdf" ] && [ -f "$FILES/northwind-technical-proposal.docx" ] ||
  { echo "bid-smoke: no demo bid documents in $FILES (BID_SMOKE_FILES)" >&2; exit 1; }

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
body() { jq -c "${1:-.}" "$work/body" 2>/dev/null || true; }
body_r() { jq -r "$1" "$work/body" 2>/dev/null || true; }
csrf() { awk '$6 ~ /soundings_csrf$/ { print $7 }' "$work/$1.jar"; }
in_days() { date -u -d "@$(($(date +%s) + $1 * 86400))" +%Y-%m-%dT%H:%M:%SZ; }

# as USER METHOD PATH [JSON]: REST in USER's session (dev login), CSRF header on writes;
# prints the status; body in $work/body, headers in $work/headers. USER "anon": no cookies.
as() {
  local method="$2" path="$3" args
  args=(-X "$method" -D "$work/headers" -o "$work/body" -w '%{http_code}')
  if [ "$1" != anon ]; then
    args+=(-b "$work/$1.jar" -c "$work/$1.jar")
    [ "$method" = GET ] || args+=(-H "X-CSRF-Token: $(csrf "$1")")
  fi
  [ $# -lt 4 ] || args+=(-H 'Content-Type: application/json' --data-binary "$4")
  : >"$work/body"
  curl -sS "${curl_args[@]}" "${args[@]}" "$API$path" 2>/dev/null || true
}
# upload USER BID FILE QUERY [CURL_ARGS...]: the raw file as the body (as the SPA sends
# it); prints the status (000 when the connection was cut while sending).
upload() {
  local user="$1" bid="$2" file="$3" query="$4" args
  shift 4
  args=(-X POST -D "$work/headers" -o "$work/body" -w '%{http_code}' --max-time 120
    -H 'Content-Type: application/octet-stream')
  if [ "$user" != anon ]; then
    args+=(-b "$work/$user.jar" -c "$work/$user.jar" -H "X-CSRF-Token: $(csrf "$user")")
  fi
  : >"$work/body"
  : >"$work/headers"
  curl -sS "${curl_args[@]}" "${args[@]}" "$@" --data-binary "@$file" \
    "$CALL/bids/$bid/documents?$query" 2>/dev/null || true
}
sign_in() { # USER: dev login as <USER>@example.com; prints the user's id
  local id status
  id="$(jq -r --arg email "$1@example.com" '.[] | select(.email == $email) | .id' "$work/users.json")"
  [ -n "$id" ] || die "dev login: no user $1@example.com"
  status="$(curl -sS "${curl_args[@]}" -c "$work/$1.jar" -o "$work/body" -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "{\"user_id\":\"$id\"}" "$API/auth/dev/login" || true)"
  [ "$status" = "200" ] || die "dev login as $1: $status"
  printf '%s' "$id"
}

agent_ids=()
cleanup() {
  local id status
  for id in ${agent_ids[@]+"${agent_ids[@]}"}; do
    as alice PATCH "/admin/ai-agents/$id" '{"enabled": false}' >/dev/null
  done
  if [ -n "${idea_id:-}" ]; then
    status="$(as alice DELETE "/ideas/$idea_id")"
    [ "$status" = "204" ] && ok "clean-up: the test idea is deleted with its call, bids and documents${agent_ids[0]:+; agents disabled (keys revoked)}" ||
      fail "clean-up: DELETE /ideas/$idea_id answered $status $(body)"
  fi
  rm -rf "$work"
}
trap cleanup EXIT

printf '\033[1;34m==>\033[0m bid smoke against %s (project %s)\n' "$BASE_URL" "$PROJECT" >&2
status="$(curl -sS "${curl_args[@]}" -o "$work/users.json" -w '%{http_code}' "$API/auth/dev/users" || true)"
[ "$status" = "200" ] || die "the bid smoke needs the dev login (/api/v1/auth/dev/users: $status)"
sign_in alice >/dev/null
bob_id="$(sign_in bob)"
carol_id="$(sign_in carol)"
sign_in mateo >/dev/null
[ "$(as alice GET "/projects/$PROJECT")" = "200" ] || die "GET /projects/$PROJECT as alice: $(body)"
project_id="$(body_r .id)"

# --- 1. The call ----------------------------------------------------------------------------
run="$(date +%s)-$RANDOM"
status="$(as alice POST "/projects/$PROJECT/ideas" "$(jq -nc --arg r "$run" \
  '{title: ("Bid smoke " + $r), summary: "Created by scripts/bid-smoke.sh; deleted at the end."}')")"
[ "$status" = "201" ] || die "create the test idea as alice: $status $(body)"
idea_id="$(body_r .id)"
idea_key="$(body_r .key)"
CALL="$API/ideas/$idea_key/bid-call"
call_path="/ideas/$idea_key/bid-call"
[ "$(as alice GET "$call_path")" = "200" ] && [ "$(body .summary)" = "null" ] &&
  [ "$(body .permissions.can_create)" = "false" ] &&
  ok "$idea_key (New): no call, and none can be started yet" || fail "a new idea's Bids tab: $(body)"
status="$(as alice POST "$call_path" '{"title": "Smoke call"}')"
[ "$status" = "409" ] && [ "$(body_r .code)" = "bid_call_not_available" ] &&
  ok "a call before the proposal: 409 bid_call_not_available" || fail "a call on a new idea: $status $(body_r .code)"
status="$(as alice POST "/ideas/$idea_id/status" '{"status": "shortlisted"}')"
[ "$status" = "200" ] || die "shortlist: $status $(body)"
status="$(as alice POST "/ideas/$idea_id/proposal")"
[ "$status" = "201" ] || die "start the proposal: $status $(body)"
[ "$(as mateo GET "$call_path")" = "200" ] && [ "$(body .permissions.can_create)" = "false" ] &&
  ok "mateo (member): the Bids tab, nothing to start" || fail "mateo's Bids tab: $(body)"
status="$(as mateo POST "$call_path" '{"title": "Not mine"}')"
[ "$status" = "403" ] && ok "mateo may not start a call: 403" || fail "mateo starts a call: $status $(body_r .code)"
status="$(as alice POST "$call_path" "$(jq -nc --arg r "$run" \
  '{title: ("Smoke supply " + $r), description: "scripts/bid-smoke.sh", currency: "GBP"}')")"
[ "$status" = "201" ] || die "create the call: $status $(body)"
cp "$work/body" "$work/call.json"
template="$(jq -c '.call.template' "$work/call.json")"
jq -e '.call.status == "draft" and (.call.template.sections | length) >= 1 and .call.template.price_question_id != null' \
  "$work/call.json" >/dev/null &&
  ok "the call: a draft with the project's template, $(jq -c '{sections: [.sections[] | .title + " " + (.weight | tostring) + "%"], must_haves: [.must_haves[] | .text + " (" + .kind + (if .pricing then ", pricing" else "" end) + ")"]}' <<<"$template")" ||
  die "the new call: $(jq -c '.call | {status, template: (.template | {sections: (.sections | length), price_question_id})}' "$work/call.json")"
status="$(as alice POST "$call_path" '{"title": "Twice"}')"
[ "$status" = "409" ] && [ "$(body_r .code)" = "bid_call_exists" ] && ok "a second call: 409 bid_call_exists" ||
  fail "a second call: $status $(body_r .code)"
status="$(as alice POST "$call_path/status" '{"status": "open"}')"
[ "$status" = "409" ] && [ "$(body_r .code)" = "bid_call_deadline_required" ] &&
  ok "open without a deadline: 409 bid_call_deadline_required" || fail "open without a deadline: $status $(body_r .code)"
status="$(as alice PUT "$call_path" "$(jq -nc --arg r "$run" --arg d "$(in_days 7)" \
  '{title: ("Smoke supply " + $r), description: "scripts/bid-smoke.sh", currency: "GBP", deadline_at: $d, ai_assessor_id: null}')")"
[ "$status" = "200" ] || die "set the deadline: $status $(body)"
status="$(as alice POST "$call_path/status" '{"status": "open"}')"
[ "$status" = "200" ] && [ "$(body_r .call.status)" = "open" ] && ok "the call is open (deadline $(body_r .call.deadline_at))" ||
  die "open the call: $status $(body)"

# The template's ids: required documents (not pricing), the pricing one, confirmations.
mapfile -t document_mhs < <(jq -r '.must_haves[] | select(.kind == "document" and (.pricing | not)) | .id' <<<"$template")
pricing_mh="$(jq -r '[.must_haves[] | select(.kind == "document" and .pricing) | .id][0] // empty' <<<"$template")"
mapfile -t confirmation_mhs < <(jq -r '.must_haves[] | select(.kind == "confirmation") | .id' <<<"$template")
[ "${#document_mhs[@]}" -ge 2 ] || die "the smoke needs two required-document must-haves (the default template has them): $template"

# --- 2. Bids and documents ------------------------------------------------------------------
status="$(as alice POST "$call_path/bids" '{"bidder": "Smoke Supplies Ltd", "contact_name": "Ada Smoke",
  "contact_email": "ada@smoke.example", "price": "98000.00", "notes": "bid-smoke A"}')"
[ "$status" = "201" ] || die "enter bid A: $status $(body)"
bid_a="$(body_r .id)"
status="$(as alice POST "$call_path/bids" '{"bidder": "Smoke Partners LLP", "price": "120000.00"}')"
[ "$status" = "201" ] || die "enter bid B: $status $(body)"
bid_b="$(body_r .id)"
[ "$(as alice GET "$call_path/bids/$bid_a")" = "200" ] && [ "$(body_r .late)" = "false" ] && [ "$(body_r .price)" = "98000.00" ] &&
  ok "bids entered: A $(body '{status, late, price, must_haves}') and B" || fail "bid A as entered: $(body)"

pdf="$FILES/northwind-form-of-tender.pdf"
docx="$FILES/northwind-technical-proposal.docx"
csv="$work/pricing-schedule.csv"
printf 'item,amount\nBuild,90000.00\nFirst year support,8000.00\nTotal,98000.00\n' >"$csv"
extra_files=("$FILES/northwind-insurance-certificate.pdf" "$FILES/tessellate-form-of-tender.pdf" "$FILES/tessellate-insurance-certificate.pdf")
status="$(upload alice "$bid_a" "$pdf" "filename=form-of-tender.pdf&must_have_id=${document_mhs[0]}")"
[ "$status" = "201" ] && [ "$(body_r .type)" = "pdf" ] && [ "$(body_r .extraction.state)" = "pending" ] &&
  ok "upload a PDF for the first required document: 201, $(body '{filename, type, content_type, size_bytes, extraction: .extraction.state}')" ||
  die "upload the PDF: $status $(body)"
pdf_doc="$(body_r .id)"
[ -z "${BID_UPLOAD_HEADER:-}" ] || {
  wanted="${BID_UPLOAD_HEADER#*: }"
  [ "$(header "${BID_UPLOAD_HEADER%%:*}")" = "$wanted" ] && ok "the upload went through the upload route's own router ($BID_UPLOAD_HEADER)" ||
    fail "the upload response lacks '$BID_UPLOAD_HEADER' (the upload route's router didn't match)"
}
status="$(upload alice "$bid_a" "$docx" "filename=technical-proposal.docx&must_have_id=${document_mhs[1]}")"
[ "$status" = "201" ] && [ "$(body_r .type)" = "docx" ] && ok "upload a DOCX for the second required document: 201, $(body '{filename, type, content_type}')" ||
  die "upload the DOCX: $status $(body)"
docx_doc="$(body_r .id)"
for i in "${!document_mhs[@]}"; do
  [ "$i" -ge 2 ] || continue
  file="${extra_files[$(((i - 2) % ${#extra_files[@]}))]}"
  status="$(upload alice "$bid_a" "$file" "filename=required-$i.pdf&must_have_id=${document_mhs[$i]}")"
  [ "$status" = "201" ] || fail "upload for required document $i: $status $(body_r .code)"
done
if [ -n "$pricing_mh" ]; then
  status="$(upload alice "$bid_a" "$csv" "filename=pricing-schedule.csv&must_have_id=$pricing_mh")"
  [ "$status" = "201" ] && [ "$(body_r .type)" = "csv" ] && [ "$(body_r .pricing)" = "true" ] &&
    ok "upload a CSV pricing schedule: 201, a pricing document ($(body '{type, content_type, pricing}'))" ||
    die "upload the pricing schedule: $status $(body)"
  pricing_doc="$(body_r .id)"
fi
status="$(upload alice "$bid_a" "$pdf" "filename=again.pdf")"
[ "$status" = "409" ] && [ "$(body_r .code)" = "duplicate_document" ] && ok "the same file again: 409 duplicate_document" ||
  fail "the same file again: $status $(body_r .code)"
base64 -d >"$work/macro.docm" <<'EOF'
UEsDBBQAAAAIAKCNTV0k852C1AAAADUBAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbIWQwU7EMAxEfyXKFTUpHBBCbfcAyxH2
sHyAm7jdQONEibcsf4/LSlw52uN5M3K3u8RFrVhqSNTrW9NqheSSDzT3+v340jzo3dAdvzNWJadUe31izo/WVnfCCNWkjCTK
lEoElrHMNoP7hBntXdveW5eIkbjhjaGH7hknOC+s9hdZX2PHQFo9Xe+2qF5DzktwwCLblbyJtUnTFByadYRDSR/oWNuhe5Pq
JXhUByj8ClGs9isVb31y5yg4I9X+Z28W82eJ4EraE4wLigqBbjaIpNnfPww/UEsDBBQAAAAIAKCNTV3cRTrRdgAAAJwAAAAR
AAAAd29yZC9kb2N1bWVudC54bWxFzsENwjAMBdBVqg6AKw4copANGCIkpq1Ux5FtlLI9TTlweV9flqXvm8uc3oTFhp22oq7d
x8WsOgBNC1LUC1csx+3FQtGOKjM0llyFE6quZaYNrtN0A4prGYNv7sn507N2pGPhEZPwYKjmofeunNbT3w/894QvUEsDBBQA
AAAIAKCNTV3X11jaKQAAACcAAAATAAAAd29yZC92YmFQcm9qZWN0LmJpbrtwXvCBQl5+iUKiQlFqYo5CmJOjQkFRflZqcomC
RlJmim5xbn52qiYAUEsBAhQDFAAAAAgAoI1NXSTznYLUAAAANQEAABMAAAAAAAAAAAAAAIABAAAAAFtDb250ZW50X1R5cGVz
XS54bWxQSwECFAMUAAAACACgjU1d3EU60XYAAACcAAAAEQAAAAAAAAAAAAAAgAEFAQAAd29yZC9kb2N1bWVudC54bWxQSwEC
FAMUAAAACACgjU1d19dY2ikAAAAnAAAAEwAAAAAAAAAAAAAAgAGqAQAAd29yZC92YmFQcm9qZWN0LmJpblBLBQYAAAAAAwAD
AMEAAAAEAgAAAAA=
EOF
status="$(upload alice "$bid_a" "$work/macro.docm" "filename=terms.docm")"
[ "$status" = "415" ] && [ "$(body_r .code)" = "macro_document" ] && ok "a macro-enabled .docm (vbaProject.bin): 415 macro_document" ||
  fail "the .docm: $status $(body_r .code) (want 415 macro_document)"
status="$(upload alice "$bid_a" "$pdf" "filename=..%2Fescape.pdf")"
[ "$status" = "422" ] && ok "a file name with a path separator: 422" || fail "a name with '/': $status $(body_r .code)"
# Over 25 MiB: refused before it is read (Content-Length) or once the count passes it
# (chunked). The app closes the connection after its 413; a proxy still sending may then
# answer 502 instead (as for the 1 MiB limit, scripts/k3s-smoke.sh).
head -c $((UPLOAD_MAX + 1)) /dev/zero >"$work/big.pdf"
status="$(upload alice "$bid_a" "$work/big.pdf" "filename=big.pdf")"
[ "$status" = "413" ] && [ "$(body_r .code)" = "content_too_large" ] && ok "25 MiB + 1 byte with a Content-Length: 413 content_too_large" ||
  fail "25 MiB + 1 byte with a Content-Length: $status $(body_r .code) (want 413)"
status="$(upload alice "$bid_a" "$work/big.pdf" "filename=big.pdf" -H 'Transfer-Encoding: chunked')"
if [ "$status" = "413" ]; then
  ok "25 MiB + 1 byte chunked: 413 (counted as it streamed)"
elif [ "$status" = "502" ] || [ "$status" = "000" ]; then
  ok "25 MiB + 1 byte chunked: $status (the app cut the connection at the limit; the proxy saw it closed)"
else
  fail "25 MiB + 1 byte chunked: $status $(body_r .code) (want 413)"
fi
rm -f "$work/big.pdf"
head -c $((2 * 1024 * 1024)) /dev/zero >"$work/two-mib.pdf"
status="$(upload anon "$bid_a" "$work/two-mib.pdf" "filename=anon.pdf")"
[ "$status" = "401" ] && ok "an anonymous 2 MiB upload: 401 (before the body is read)" || fail "an anonymous upload: $status"
status="$(upload mateo "$bid_a" "$work/two-mib.pdf" "filename=member.pdf")"
[ "$status" = "403" ] && ok "a member's upload: 403" || fail "mateo's upload: $status $(body_r .code)"
rm -f "$work/two-mib.pdf"
if [ "${BID_SLOW_UPLOAD:-0}" = "1" ]; then
  head -c 800000 /dev/zero | tr '\0' 'a' >"$work/slow.txt"
  started="$(date +%s)"
  status="$(upload alice "$bid_a" "$work/slow.txt" "filename=slow-upload.txt" --limit-rate 10k --max-time 150)"
  took=$(($(date +%s) - started))
  [ "$status" = "201" ] && [ "$took" -ge 61 ] && ok "a slow upload (800 kB at 10 kB/s): 201 after ${took}s" ||
    fail "the slow upload: $status after ${took}s $(body_r .code) (want 201 after more than 60 s)"
  rm -f "$work/slow.txt"
fi
status="$(upload alice "$bid_b" "$FILES/quillfield-form-of-tender.pdf" "filename=form-of-tender.pdf&must_have_id=${document_mhs[0]}")"
[ "$status" = "201" ] || fail "bid B's form of tender: $status $(body)"

# --- 3. Extraction, text and download -------------------------------------------------------
states=""
for _ in $(seq 1 60); do
  [ "$(as alice GET "$call_path/bids/$bid_a")" = "200" ] || die "GET bid A: $(body)"
  states="$(body '[.documents[] | {type, state: .extraction.state, error: .extraction.error, chars: .extraction.chars}]')"
  jq -e 'all(.[]; .state != "pending")' <<<"$states" >/dev/null && break
  sleep 2
done
jq -e 'all(.[]; .state == "done" and .chars > 0)' <<<"$states" >/dev/null &&
  ok "the worker read every document's text: $states" || fail "extraction: $states (want every one done)"
status="$(as alice GET "$call_path/bids/$bid_a/documents/$pdf_doc/text?page=1")"
[ "$status" = "200" ] && [ "$(body_r .state)" = "done" ] && [ "$(body '.text | length')" -gt 20 ] &&
  ok "the PDF's text, page 1 of $(body_r .page_count): $(body_r '.text[0:60]' | tr '\n' ' ')..." ||
  fail "the PDF's text: $status $(body '{state, page_count}')"
curl -sS "${curl_args[@]}" -b "$work/alice.jar" -D "$work/headers" -o "$work/download" -w '%{http_code}' \
  "$CALL/bids/$bid_a/documents/$pdf_doc/content" >"$work/status" 2>/dev/null || true
status="$(cat "$work/status")"
want_sha="$(sha256sum <"$pdf" | cut -d' ' -f1)"
got_sha="$(sha256sum <"$work/download" | cut -d' ' -f1)"
[ "$status" = "200" ] && [[ "$(header content-disposition)" == attachment* ]] &&
  [ "$(header x-content-type-options)" = "nosniff" ] && [[ "$(header content-security-policy)" == *sandbox* ]] &&
  [[ "$(header cache-control)" == *private* ]] && [[ "$(header cache-control)" == *no-store* ]] &&
  [ "$(header content-type)" = "application/pdf" ] && [ "$got_sha" = "$want_sha" ] &&
  ok "the download: $(header content-disposition); nosniff; CSP '$(header content-security-policy)'; $(header cache-control); the same bytes" ||
  fail "the download: $status disposition '$(header content-disposition)' nosniff '$(header x-content-type-options)' csp '$(header content-security-policy)' cache '$(header cache-control)' type '$(header content-type)' sha $got_sha (want $want_sha)"

# --- Must-haves --------------------------------------------------------------------------
[ "$(as alice GET "$call_path/bids/$bid_a")" = "200" ] || die "GET bid A"
results="$(body '[.must_have_results[] | {kind: .must_have.kind, pricing: .must_have.pricing, result, automatic, docs: (.document_ids | length)}]')"
jq -e '[.[] | select(.kind == "document")] | all(.result == "met" and .automatic and .docs == 1)' <<<"$results" >/dev/null &&
  jq -e '[.[] | select(.kind == "confirmation")] | all(.result == "unchecked")' <<<"$results" >/dev/null &&
  ok "bid A's must-haves before a person decides: every required document met (automatic), confirmations unchecked" ||
  fail "bid A's must-haves: $results"
for mh in ${confirmation_mhs[@]+"${confirmation_mhs[@]}"}; do
  status="$(as alice PUT "$call_path/bids/$bid_a/must-haves/$mh" '{"result": "met", "note": "Confirmed in the form of tender (bid-smoke)."}')"
  [ "$status" = "200" ] || fail "confirm must-have $mh: $status $(body)"
done
[ "$(as alice GET "$call_path/bids/$bid_a")" = "200" ] && [ "$(body_r .status)" = "qualified" ] &&
  ok "bid A: qualified ($(body .must_haves))" || fail "bid A after the confirmations: $(body '{status, must_haves}')"
[ "$(as alice GET "$call_path/bids/$bid_b")" = "200" ] || die "GET bid B"
[ "$(body_r .status)" = "received" ] && [ "$(body .permissions.reject_suggested)" = "true" ] &&
  [ "$(body '[.must_have_results[] | select(.result == "missing")] | length')" -ge 1 ] &&
  ok "bid B: flagged ($(body .must_haves)), Reject suggested" ||
  fail "bid B: $(body '{status, must_haves, reject_suggested: .permissions.reject_suggested}')"

# --- 4. Reject and reinstate ---------------------------------------------------------------
reason="No insurance certificate (bid-smoke)."
status="$(as alice PUT "$call_path/bids/$bid_b/rejection" "$(jq -nc --arg r "$reason" '{reason: $r}')")"
[ "$status" = "200" ] && [ "$(body_r .status)" = "rejected" ] && [ "$(body_r .rejection.reason)" = "$reason" ] &&
  ok "reject bid B with a reason: 200, rejected" || fail "reject bid B: $status $(body '{status, rejection}')"
status="$(as alice DELETE "$call_path/bids/$bid_b/rejection")"
[ "$status" = "200" ] && [ "$(body_r .status)" = "received" ] && [ "$(body_r .rejection.reinstated_at)" != "null" ] &&
  ok "reinstate it: received again, the rejection kept on record (reinstated $(body_r .rejection.reinstated_at))" ||
  fail "reinstate bid B: $status $(body '{status, rejection}')"
status="$(as alice PUT "$call_path/bids/$bid_b/rejection" "$(jq -nc --arg r "$reason" '{reason: $r}')")"
[ "$status" = "200" ] && [ "$(body_r .status)" = "rejected" ] && ok "and reject it again" || fail "reject bid B again: $status"

# --- 5. Assessors, assessing ---------------------------------------------------------------
first_section="$(jq -r '.sections[0].id' <<<"$template")"
assessors="$(jq -c --arg first "$first_section" --arg bob "$bob_id" --arg carol "$carol_id" --arg due "$(in_days 5)" \
  '{sections: [.sections[] | {section_id: .id, user_ids: ([if .has_price | not then $carol else empty end,
     if (.id == $first or .has_price) then $bob else empty end])}], due_at: $due}' <<<"$template")"
status="$(as alice PUT "$call_path/assessors" "$assessors")"
[ "$status" = "200" ] && ok "assessors: $(body '[.call.template.sections[] | .title + ": " + ([.assessors[].user.display_name] | join(", "))]')" ||
  die "set the assessors: $status $(body)"
status="$(as alice POST "$call_path/status" '{"status": "assessing"}')"
[ "$status" = "200" ] && [ "$(body_r .call.status)" = "assessing" ] && ok "the call is closed to new bids: assessing" ||
  die "close the call: $status $(body)"
status="$(as alice POST "$call_path/bids" '{"bidder": "Too late"}')"
[ "$status" = "409" ] && ok "a bid while assessing: 409 $(body_r .code)" || fail "a bid while assessing: $status"

[ "$(as carol GET "$call_path/bids/$bid_a")" = "200" ] &&
  [ "$(body .price)" = "null" ] && [ "$(body .price_hidden)" = "true" ] &&
  [ "$(jq --arg d "${pricing_doc:-none}" '[.documents[] | select(.id == $d)] | length' "$work/body")" = "0" ] &&
  { [ -z "$pricing_mh" ] || [ "$(body_r .restricted_document_count)" = "1" ]; } &&
  ok "carol (no price section): no price, the pricing document only counted ($(body '{price, price_hidden, documents: (.documents | length), restricted_document_count}'))" ||
  fail "carol's bid A: $(body '{price, price_hidden, documents: [.documents[].type], restricted_document_count}')"
if [ -n "${pricing_doc:-}" ]; then
  status="$(as carol GET "$call_path/bids/$bid_a/documents/$pricing_doc/text?page=1")"
  [ "$status" = "404" ] && ok "carol reads the pricing document's text: 404" || fail "carol and the pricing document: $status"
fi
[ "$(as bob GET "$call_path/bids/$bid_a")" = "200" ] && [ "$(body_r .price)" = "98000.00" ] &&
  ok "bob (price section): the price $(body_r .price) and $(body '.documents | length') documents" ||
  fail "bob's bid A: $(body '{price, price_hidden}')"
status="$(as carol GET "$call_path/bids/$bid_b")"
[ "$status" = "404" ] && [ "$(as carol GET "$call_path/bids")" = "200" ] && [ "$(body '[.items[].id]')" = "[\"$bid_a\"]" ] &&
  ok "the rejected bid: 404 for carol, not in her list" || fail "carol and the rejected bid: GET $status, list $(body '[.items[].bidder]')"
[ "$(as mateo GET "$call_path")" = "200" ] && [ "$(body .call)" = "null" ] && [ "$(body_r .summary.bid_count)" = "2" ] &&
  ok "mateo (member): the summary only, $(body '.summary | {title, status, bid_count}')" || fail "mateo's view of the call: $(body '{summary, call: (.call != null)}')"
status="$(as mateo GET "$call_path/bids")"
[ "$status" = "403" ] && ok "mateo lists the bids: 403" || fail "mateo lists the bids: $status"
status="$(as anon GET "$call_path")"
[ "$status" = "401" ] && ok "anonymous: 401" || fail "anonymous GET of the call: $status"
[ "$(as carol GET /me/work/counts)" = "200" ] && carol_due="$(body_r .bid_assessments_due)"
[ "$(as bob GET /me/work/counts)" = "200" ] && bob_due="$(body_r .bid_assessments_due)"
carol_sections="$(jq '[.sections[] | select(.has_price | not)] | length' <<<"$template")"
bob_sections="$(jq --arg first "$first_section" '[.sections[] | select(.id == $first or .has_price)] | length' <<<"$template")"
[ "${carol_due:-0}" -ge "$carol_sections" ] && [ "${bob_due:-0}" -ge "$bob_sections" ] &&
  [ "$(as carol GET /me/work)" = "200" ] && [ "$(jq --arg i "$idea_key" '[.bids_to_assess[] | select(.idea.key == $i)] | length' "$work/body")" = "1" ] &&
  ok "My work: carol owes $carol_due bid assessments, bob $bob_due; carol's \"Bids to assess\" lists the call" ||
  fail "My work: carol ${carol_due:-?} (want >= $carol_sections), bob ${bob_due:-?} (want >= $bob_sections)"

# answers SECTION_ID SCORE: every score question SCORE, a comment for comment questions.
answers() {
  jq -c --arg s "$1" --argjson v "$2" '{answers: [.sections[] | select(.id == $s) | .questions[] |
    if .type == "score" then {question_id: .id, score: $v} elif .type == "comment" then {question_id: .id, comment: "bid-smoke comment"} else empty end], submit: true}' <<<"$template"
}
assess() { # USER SECTION_ID SCORE
  local status
  status="$(as "$1" PUT "$call_path/bids/$bid_a/sections/$2/assessment" "$(answers "$2" "$3")")"
  [ "$status" = "200" ] && [ "$(body_r .state)" = "submitted" ] || fail "$1 submits section $2: $status $(body)"
}

# --- 6. Blind --------------------------------------------------------------------------------
assess bob "$first_section" 4
status="$(as carol GET "$call_path/bids/$bid_a/sections/$first_section/assessments")"
[ "$status" = "200" ] && [ "$(body .hidden)" = "true" ] && [ "$(body '.assessments | length')" = "0" ] &&
  [ "$(body '[.questions[] | select(.mean != null)] | length')" = "0" ] &&
  ok "blind: carol, who still owes the first section, sees no scores there (hidden; bob has submitted)" ||
  fail "carol before submitting: $status $(body '{hidden, assessments: (.assessments | length), questions}')"
status="$(as carol GET "$call_path/comparison")"
[ "$status" = "403" ] && ok "carol (an assessor) and the comparison: 403" || fail "carol's comparison: $status"
for section in $(jq -r '.sections[] | select(.has_price | not) | .id' <<<"$template"); do
  if [ "$section" = "$first_section" ]; then assess carol "$section" 2; else assess carol "$section" 5; fi
done
status="$(as carol GET "$call_path/bids/$bid_a/sections/$first_section/assessments")"
[ "$status" = "200" ] && [ "$(body .hidden)" = "false" ] && [ "$(body '.assessments | length')" = "2" ] &&
  [ "$(body '[.questions[] | select(.type == "score") | .disagreement] | all')" = "true" ] &&
  ok "after submitting, carol sees both assessments: means $(body '[.questions[] | select(.type == "score") | .mean]'), disagreement flagged, section $(body_r .section_score)" ||
  fail "carol after submitting: $status $(body '{hidden, assessments: (.assessments | length), questions}')"
for section in $(jq -r --arg first "$first_section" '.sections[] | select(.has_price and .id != $first) | .id' <<<"$template"); do
  status="$(as bob PUT "$call_path/bids/$bid_a/sections/$section/assessment" "$(jq -c --arg q "$(jq -r .price_question_id <<<"$template")" \
    '.answers += [{question_id: $q, score: 3}]' <<<"$(answers "$section" 4)")")"
  [ "$status" = "422" ] && [ "$(body_r .code)" = "not_assessable" ] && ok "a score for the price question: 422 not_assessable" ||
    fail "scoring the price question: $status $(body_r .code)"
  assess bob "$section" 4
done
ok "every assessor has submitted every section of bid A"

# --- 7. The comparison and the report ---------------------------------------------------------
# The total, worked out from the template and the scores above (contract-phase10 section 8):
# per question the mean of its scores (price: 5, the only scored price), per section the
# weighted mean on 0-5 as 0-100, the total the sections' weighted sum.
expected="$(jq --arg first "$first_section" '[.sections[] | . as $sec |
  [.questions[] | select(.type != "comment") | {w: .weight, m: (if .type == "price" then 5 else
    ([if ($sec.id == $first or $sec.has_price) then 4 else empty end,
      if ($sec.has_price | not) then (if $sec.id == $first then 2 else 5 end) else empty end] | add / length) end)}] as $qs |
  ($sec.weight / 100) * (([$qs[] | .w * .m] | add) / ([$qs[] | .w] | add) * 20)] | add' <<<"$template")"
comparison() {
  [ "$(as alice GET "$call_path/comparison")" = "200" ] || die "the comparison: $(body)"
  jq -c --arg a "$bid_a" '.rows[] | select(.bid.id == $a)' "$work/body"
}
row_a="$(comparison)"
row_b="$(jq -c --arg b "$bid_b" '.rows[] | select(.bid.id == $b)' "$work/body")"
jq -e --argjson want "$expected" '.rank == 1 and .price_score == 5 and ((.total - $want) | if . < 0 then -. else . end) < 0.051 and
  ([.sections[] | select(.disagreement)] | length) >= 1 and (.ai_included | not)' <<<"$row_a" >/dev/null &&
  [ "$(body .ranking_hidden)" = "false" ] && [ "$(body .complete)" = "true" ] &&
  ok "the comparison: bid A ranked 1, total $(jq .total <<<"$row_a") (worked out: $(printf '%.2f' "$expected")), price score 5, sections $(jq -c '[.sections[] | .score]' <<<"$row_a"), disagreement flagged, complete" ||
  fail "the comparison: A $row_a (want rank 1, total $expected), ranking_hidden $(body .ranking_hidden), complete $(body .complete)"
jq -e '.bid.status == "rejected" and .total == null and .rank == null and all(.sections[]; .score == null)' <<<"$row_b" >/dev/null &&
  ok "bid B (rejected): listed without scores or a rank" || fail "bid B in the comparison: $row_b"
total_before="$(jq .total <<<"$row_a")"
curl -sS "${curl_args[@]}" -b "$work/alice.jar" -D "$work/headers" -o "$work/report.md" -w '%{http_code}' \
  "$CALL/report/markdown" >"$work/status" 2>/dev/null || true
[ "$(cat "$work/status")" = "200" ] && [[ "$(header content-type)" == text/markdown* ]] &&
  grep -q 'Smoke Supplies Ltd' "$work/report.md" && grep -q 'Smoke Partners LLP' "$work/report.md" && grep -qF "$reason" "$work/report.md" &&
  ok "the report (Markdown): $(wc -c <"$work/report.md" | tr -d ' ') bytes, both bids, the rejection's reason" ||
  fail "the Markdown report: $(cat "$work/status") $(header content-type) $(head -c 200 "$work/report.md")"
curl -sS "${curl_args[@]}" --max-time 60 -b "$work/alice.jar" -D "$work/headers" -o "$work/report.pdf" -w '%{http_code}' \
  "$CALL/report/pdf" >"$work/status" 2>/dev/null || true
[ "$(cat "$work/status")" = "200" ] && [ "$(header content-type)" = "application/pdf" ] && [ "$(head -c 5 "$work/report.pdf")" = "%PDF-" ] &&
  ok "the report (PDF): $(wc -c <"$work/report.pdf" | tr -d ' ') bytes, $(header content-disposition)" ||
  fail "the PDF report: $(cat "$work/status") $(header content-type)"
status="$(as carol GET "$call_path/report/markdown")"
[ "$status" = "403" ] && ok "the report for carol (an assessor): 403" || fail "carol's report: $status"

# --- 8. The AI assessor --------------------------------------------------------------------
ai_on="false"
if [ "$BID_AI" != "0" ] && [ "$(as alice GET /admin/ai-agents)" = "200" ]; then
  ai_on="$(body_r .settings.enabled)"
fi
if [ "$BID_AI" = "1" ] && [ "$ai_on" != "true" ]; then
  die "BID_AI=1 but AI assistance is off (features.ai / SOUNDINGS_AI_ENABLED)"
fi
ai_ready=""
if [ "$BID_AI" = "1" ] || [ -n "${AI_KEY_HOOK:-}" ]; then
  ai_ready=1
elif [ -n "${AI_FAKE_KEYS_DIR:-}" ] && [ -n "${AI_FAKE_URL:-}" ] &&
  curl -sS --noproxy '*' --max-time 5 -o /dev/null "${AI_FAKE_URL%/}/healthz" 2>/dev/null; then
  ai_ready=1
fi
if [ "$ai_on" = "true" ] && [ -n "$ai_ready" ]; then
  [ -n "${AI_KEY_HOOK:-}${AI_FAKE_KEYS_DIR:-}" ] || die "BID_AI=1: set AI_KEY_HOOK or AI_FAKE_KEYS_DIR (the agent needs its key)"
  provision() { # NAME: register (or enable and re-key) an assess_bid agent; sets $agent_id
    local name="$1" status existing
    status="$(as alice POST /admin/ai-agents "$(jq -nc --arg ns "$AGENT_NS" --arg n "$name" --arg pid "$project_id" \
      --arg proto "$PROTOCOL" '{display_name: ("Bid smoke " + $n), description: "scripts/bid-smoke.sh", namespace: $ns,
        name: $n, protocol: $proto, purposes: ["assess_bid"], project_ids: [$pid]}')")"
    if [ "$status" = "409" ] && [ "$(body_r .code)" = "agent_taken" ]; then
      [ "$(as alice GET /admin/ai-agents)" = "200" ] || die "GET /admin/ai-agents"
      existing="$(jq -r --arg ns "$AGENT_NS" --arg n "$name" '.items[] | select(.namespace == $ns and .name == $n) | .id' "$work/body")"
      [ -n "$existing" ] || die "agent $AGENT_NS/$name is taken but not listed"
      status="$(as alice PATCH "/admin/ai-agents/$existing" "$(jq -nc --arg pid "$project_id" --arg proto "$PROTOCOL" \
        '{enabled: true, protocol: $proto, purposes: ["assess_bid"], project_ids: [$pid]}')")"
      [ "$status" = "200" ] || die "enable $AGENT_NS/$name: $status $(body)"
      status="$(as alice POST "/admin/ai-agents/$existing/key")"
      [ "$status" = "201" ] || die "rotate the key of $AGENT_NS/$name: $status $(body)"
    elif [ "$status" != "201" ]; then
      die "register $AGENT_NS/$name: $status $(body)"
    fi
    cp "$work/body" "$work/agent.json"
    agent_id="$(jq -r .agent.id "$work/agent.json")"
    agent_ids+=("$agent_id")
    jq -c '{namespace: .agent.namespace, name: .agent.name, key: .key.secret, secret_manifest}' "$work/agent.json" >"$work/key.json"
    rm -f "$work/agent.json"
    if [ -n "${AI_KEY_HOOK:-}" ]; then
      # shellcheck disable=SC2086 # a command line, split on purpose
      $AI_KEY_HOOK <"$work/key.json" || die "AI_KEY_HOOK failed"
    else
      mkdir -p "$AI_FAKE_KEYS_DIR"
      (umask 077 && jq -r '"Bearer " + .key' "$work/key.json" >"$AI_FAKE_KEYS_DIR/$AGENT_NS.$name")
    fi
    rm -f "$work/key.json"
    for _ in $(seq 1 5); do
      [ "$(as alice POST "/admin/ai-agents/$agent_id/test")" = "200" ] && [ "$(body .ok)" = "true" ] && break
      sleep 3
    done
    [ "$(body .ok)" = "true" ] && ok "agent $AGENT_NS/$name (Assess bids): registered, key given, test connection ok (skills $(body '[.card.skills[].id]'))" ||
      fail "agent $AGENT_NS/$name: test connection $(body '{ok, error_code}')"
  }
  wait_run() { # RUN_ID: poll until final (150 s); the run in $work/body
    local state=""
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
  ask_ai() { # AGENT_ID: "Ask AI to assess" bid A and wait; sets $ai_run, the run in $work/body
    local status
    status="$(as alice POST "$call_path/bids/$bid_a/ai-assessment" "{\"agent_id\": \"$1\"}")"
    [ "$status" = "201" ] || die "Ask AI to assess: $status $(body)"
    ai_run="$(body_r .id)"
  }
  provision "$AGENT_NAME"
  assessor_id="$agent_id"
  ask_ai "$assessor_id"
  status="$(as alice POST "$call_path/bids/$bid_a/ai-assessment" "{\"agent_id\": \"$assessor_id\"}")"
  [ "$status" = "200" ] && [ "$(body_r .id)" = "$ai_run" ] && ok "Ask AI to assess bid A: 201 run $ai_run; again while active: 200, the same run" ||
    fail "the repeated request: $status $(body_r .id) (want 200 $ai_run)"
  wait_run "$ai_run"
  ai_assessment="$(body_r .result.bid_ai_assessment_id)"
  [ "$(body_r .status)" = "succeeded" ] && [ "$(body_r .bid_id)" = "$bid_a" ] && [ "$ai_assessment" != "null" ] &&
    ok "the assess run: succeeded, $(body '{kind, automatic, steps: [.events[].message]}')" ||
    fail "the assess run: $(body '{status, error, result}')"
  [ "$(as alice GET "$call_path/bids/$bid_a/ai-assessments")" = "200" ] || die "list the AI assessments: $(body)"
  item="$(jq -c --arg id "$ai_assessment" '.items[] | select(.id == $id)' "$work/body")"
  score_questions="$(jq '[.sections[].questions[] | select(.type == "score")] | length' <<<"$template")"
  jq -e --argjson n "$score_questions" --arg pricing "${pricing_mh:-none}" '(.included | not) and .quotes_not_found == 0 and
    (.scores | length) == $n and all(.scores[]; (.evidence | length) == 1 and all(.evidence[]; .found)) and
    ([.findings[] | select(.must_have_id == $pricing)] | length) == 0 and all(.scores[]; .rationale | startswith("fake-rationale"))' <<<"$item" >/dev/null &&
    ok "its assessment: $(jq -c '{included, scores: [.scores[].score], quotes_found: ([.scores[].evidence[] | select(.found)] | length), quotes_not_found, findings: [.findings[].finding]}' <<<"$item"); no finding for the pricing must-have" ||
    fail "the AI assessment: $item"
  seen="$(observations "$ai_run")"
  if [ -n "$seen" ]; then
    jq -e --arg pricing "${pricing_doc:-none}" --arg pdf "$pdf_doc" --arg docx "$docx_doc" '.assess != null and
      (.assess.documents_listed | index($pricing) | not) and (.assess.documents_read | index($pdf)) and
      (.assess.documents_read | index($docx)) and .assess.quotes_not_found == 0 and .message_checks.has_url == false and
      .message_checks.has_api_key == false' <<<"$seen" >/dev/null &&
      ok "the fake agent saw: $(jq -c '{tools: [.tool_calls[] | .tool + ":" + (.error_code // "ok")], listed: (.assess.documents_listed | length), read: (.assess.documents_read | length), pages: .assess.pages_read}' <<<"$seen"), never the pricing document" ||
      fail "the fake agent's observations: $(jq -c '{assess, message_checks}' <<<"$seen")"
  fi
  status="$(as carol GET "$call_path/bids/$bid_a/ai-assessments")"
  [ "$status" = "403" ] && ok "carol (an assessor) and the AI's assessment: 403" || fail "carol and the AI's assessment: $status"
  [ "$(jq .total <<<"$(comparison)")" = "$total_before" ] && ok "left out of the total: still $total_before" ||
    fail "the total with the AI left out: $(jq .total <<<"$(comparison)") (want $total_before)"
  status="$(as alice PUT "$call_path/bids/$bid_a/ai-assessments/$ai_assessment/include-in-totals" '{"include": true}')"
  row_a="$(comparison)"
  [ "$status" = "200" ] && [ "$(jq .ai_included <<<"$row_a")" = "true" ] &&
    ok "alice includes it: total $(jq .total <<<"$row_a") (was $total_before), ai_included" || fail "include: $status $row_a"
  status="$(as alice PUT "$call_path/bids/$bid_a/ai-assessments/$ai_assessment/include-in-totals" '{"include": false}')"
  row_a="$(comparison)"
  [ "$status" = "200" ] && [ "$(jq .total <<<"$row_a")" = "$total_before" ] && [ "$(jq .ai_included <<<"$row_a")" = "false" ] &&
    ok "and leaves it out again: $total_before" || fail "exclude: $status $row_a"
  provision "$AGENT_NAME-invents"
  ask_ai "$agent_id"
  wait_run "$ai_run"
  invented="$(body_r .result.bid_ai_assessment_id)"
  [ "$(as alice GET "$call_path/bids/$bid_a/ai-assessments")" = "200" ] || die "list the AI assessments"
  item="$(jq -c --arg id "$invented" '.items[] | select(.id == $id)' "$work/body")"
  jq -e '.quotes_not_found >= 1 and ([.scores[].evidence[] | select(.found | not) | .quote] | any(contains("fake-invented-quote")))' <<<"$item" >/dev/null &&
    ok "-invents: $(jq -c '{quotes_not_found, not_found: [.scores[].evidence[] | select(.found | not) | .quote[0:40]]}' <<<"$item") (\"Not found in the document\")" ||
    fail "the invented quote: $item"
elif [ "$BID_AI" != "0" ]; then
  ok "AI checks skipped (AI on: $ai_on; no agent to hand a key to: AI_KEY_HOOK, or AI_FAKE_KEYS_DIR with the fake at AI_FAKE_URL; BID_AI=1 requires them)"
fi

# --- 9. The award ------------------------------------------------------------------------------
status="$(as alice POST "$call_path/award" "$(jq -nc --arg b "$bid_a" '{bid_id: $b, reason: "Best value (bid-smoke)."}')")"
[ "$status" = "200" ] && [ "$(body_r .call.status)" = "awarded" ] && [ "$(body_r .call.awarded_bid.id)" = "$bid_a" ] &&
  ok "bid A is awarded: the call is $(body_r .call.status), read-only" || fail "the award: $status $(body '{status: .call.status, awarded_bid: .call.awarded_bid}')"
status="$(as alice POST "$call_path/bids" '{"bidder": "After the award"}')"
[ "$status" = "409" ] && [ "$(body_r .code)" = "bid_call_finished" ] && ok "a write after the award: 409 bid_call_finished" ||
  fail "a bid after the award: $status $(body_r .code)"
[ "$(as mateo GET "/ideas/$idea_key")" = "200" ] && [ "$(body_r .bid_call.status)" = "awarded" ] && [ "$(body '.bid_call | has("awarded_bid")')" = "false" ] &&
  ok "mateo's idea page: the call's summary ($(body '.bid_call | {status, bid_count}')), no bidder named" ||
  fail "mateo's idea page: $(body .bid_call)"

[ $failed -eq 0 ] || exit 1
printf '\033[1;34m==>\033[0m bid smoke passed\n' >&2
