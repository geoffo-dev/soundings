#!/usr/bin/env bash
# Single sign-on smoke test against a running Soundings + the dev Keycloak realm, driving
# the real code flow with curl (no browser): the SPEC acceptance for Phase 2 end to end.
#
#   scripts/sso-smoke.sh [BASE_URL]        # default http://localhost:8000
#
#   1. /auth/config says SSO on and break-glass off; POST /auth/break-glass is 404.
#   2. alice signs in through Keycloak (302 to the IdP with PKCE S256, login form,
#      callback, session cookie): /auth/me says auth_method "sso", platform admin.
#   3. As alice: a private project, a managed group mapped to /tools/members granting
#      it "member", and a check that discovery of the issuer works from the app.
#   4. carol signs in: the project is hers through the group (access source: group).
#   5. carol is removed from /tools/members in Keycloak, signs out (RP-initiated logout
#      back to /login?signed_out=1) and in again: the project is gone (404).
#   6. mallory (an unverified email naming Farah) is refused: /login?error=no_account.
#   Clean-up (also on failure): carol back in /tools/members, the group deleted, the
#   project archived.
#
# Needs: the demo data (alice platform admin with employee_no E1001, carol E1003), the
# app configured with the dev realm's issuer, groups and employee_no claims, curl, jq.
#   CONNECT_HOST  connect to this host instead of localhost (CI with docker:dind), for
#                 the app and for Keycloak on localhost / *.localhost; Host stays.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/keycloak.sh
source "$(dirname "$0")/lib/keycloak.sh"

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
command -v jq >/dev/null || { echo "sso-smoke: jq is required" >&2; exit 1; }

curl_args=(--noproxy '*' --max-time 30)
if [ -n "${CONNECT_HOST:-}" ]; then
  port="$(sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#' <<<"$BASE_URL")"
  port="${port:-80}"
  curl_args+=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
  KC_CURL_ARGS=(--connect-to "localhost:$port:$CONNECT_HOST:$port")
fi
work="$(mktemp -d)"
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
app() { curl -sS "${curl_args[@]}" "$@"; }

# sso_sign_in USER NAME: the browser's code flow for USER with jars $work/NAME.{app,kc};
# prints the final redirect (the `next` path, or /login?error=...).
sso_sign_in() {
  local user="$1" jar="$work/$2.app" kcjar="$work/$2.kc" out status authorize callback
  out="$(app -c "$jar" -b "$jar" -o /dev/null -w '%{http_code} %{redirect_url}' \
    "$API/auth/login?next=/work")"
  status="${out%% *}"
  authorize="${out#* }"
  [ "$status" = "302" ] || die "$user: GET /auth/login answered $status (want 302 to the IdP)"
  [[ "$authorize" == *"code_challenge_method=S256"* && "$authorize" == *"nonce="* ]] ||
    die "$user: the authorization request lacks PKCE S256 or a nonce"
  grep -q 'HttpOnly_.*soundings_oidc' "$jar" || die "$user: no HttpOnly soundings_oidc cookie"
  callback="$(kc_login "$authorize" "$user" password "$kcjar")" || die "$user: Keycloak sign-in failed"
  [[ "$callback" == "$API/auth/callback?"* ]] || die "$user: Keycloak redirected to $callback"
  app -c "$jar" -b "$jar" -o /dev/null -w '%{redirect_url}' "$callback"
}

csrf_of() { awk '$6 ~ /soundings_csrf$/ { print $7 }' "$work/$1.app"; }

as() { # as NAME METHOD PATH [curl args]: an API call in NAME's session (with CSRF)
  local name="$1" method="$2" path="$3"
  shift 3
  app -b "$work/$name.app" -X "$method" -H "X-CSRF-Token: $(csrf_of "$name")" \
    -H 'Content-Type: application/json' "$@" "$API$path"
}

slug="" group_id=""
cleanup() {
  set +e
  if [ -n "${KC_URL:-}" ]; then kc_group_add carol /tools/members 2>/dev/null; fi
  if [ -n "$group_id" ]; then as alice DELETE "/admin/groups/$group_id" -o /dev/null; fi
  if [ -n "$slug" ]; then
    as alice PATCH "/projects/$slug" -o /dev/null -d '{"archived": true}'
  fi
  rm -rf "$work"
}
trap cleanup EXIT

printf '\033[1;34m==>\033[0m SSO smoke test against %s\n' "$BASE_URL"

# 1. Configuration --------------------------------------------------------------------
config="$(app "$API/auth/config")"
if [ "$(jq -r '.sso, .break_glass' <<<"$config" | paste -sd ' ')" = "true false" ]; then
  ok "/auth/config: sso on, break-glass off ($config)"
else
  die "/auth/config: $config (want sso true, break_glass false)"
fi
status="$(app -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"wrong-password-0000"}' "$API/auth/break-glass")"
if [ "$status" = "404" ]; then
  ok "POST /auth/break-glass: 404 (off once SSO is configured)"
else
  fail "POST /auth/break-glass: $status (want 404)"
fi

# 2. alice through Keycloak --------------------------------------------------------------
landed="$(sso_sign_in alice alice)"
me="$(app -b "$work/alice.app" "$API/auth/me")"
if [ "$(jq -r '.auth_method, .email, .is_platform_admin' <<<"$me" | paste -sd ' ')" = \
  "sso alice@example.com true" ] && [[ "$landed" == */work ]]; then
  ok "alice: code flow + PKCE through Keycloak, back on /work, /auth/me auth_method sso"
else
  die "alice: landed on '$landed', /auth/me: $me"
fi

# 3. Arrange as alice ----------------------------------------------------------------------
sso="$(as alice GET /admin/sso)"
issuer="$(jq -r .issuer <<<"$sso")"
KC_URL="${issuer%/realms/*}"
if [ "$(jq -r '.discovery.status' <<<"$sso")" = "ok" ]; then
  ok "admin/sso: discovery of $issuer ok (end session: $(jq -r .discovery.end_session_supported <<<"$sso"))"
else
  fail "admin/sso: discovery $(jq -c .discovery <<<"$sso")"
fi
kc_group_add carol /tools/members # a clean start even after an interrupted run
run="$(printf '%05X' $(((RANDOM << 15 ^ RANDOM ^ $(date +%s)) % 1048576)))"
project="$(as alice POST /projects -d "{\"name\": \"SSO smoke $run\", \"slug\": \"sso-smoke-${run,,}\", \"key\": \"S$run\", \"visibility\": \"private\"}")"
slug="$(jq -er .slug <<<"$project")" || die "create project: $project"
group="$(as alice POST /admin/groups -d "{\"name\": \"SSO smoke $run\", \"sync_mode\": \"managed\", \"idp_values\": [\"/tools/members\"]}")"
group_id="$(jq -er .id <<<"$group")" || die "create group: $group"
grant="$(as alice POST "/projects/$slug/groups" -d "{\"group_id\": \"$group_id\", \"role\": \"member\"}")"
jq -e '.role == "member"' >/dev/null <<<"$grant" || die "grant: $grant"
ok "alice: private project $slug, managed group mapped to /tools/members granted member"

# 4. carol gets the project through the group ---------------------------------------
sso_sign_in carol carol >/dev/null
status="$(app -b "$work/carol.app" -o "$work/project.json" -w '%{http_code}' "$API/projects/$slug")"
access="$(as alice GET "/projects/$slug/access?q=carol")"
if [ "$status" = "200" ] && [ "$(jq -r .my_role "$work/project.json")" = "member" ] &&
  jq -e --arg g "$group_id" '.items[0].sources | any(.kind == "group" and .group.id == $g)' \
    >/dev/null <<<"$access"; then
  ok "carol: signed in with SSO, member of $slug through the group"
else
  fail "carol: project $status $(jq -c '{my_role}' "$work/project.json" 2>/dev/null), access $access"
fi

# 5. Out of the IdP group: gone at the next sign-in ---------------------------------
kc_group_remove carol /tools/members
out="$(app -b "$work/carol.app" -c "$work/carol.app" -o /dev/null -w '%{http_code} %{redirect_url}' \
  -X POST "$API/auth/logout/redirect")"
end_session="${out#* }"
if [ "${out%% *}" = "303" ] && [[ "$end_session" == "$issuer/protocol/openid-connect/logout?"* ]]; then
  back="$(kc_browse "$work/carol.kc" "$end_session" -o /dev/null -w '%{redirect_url}')"
  if [ "$back" = "$BASE_URL/login?signed_out=1" ]; then
    ok "carol: signed out at Keycloak too, back on /login?signed_out=1"
  else
    fail "carol: Keycloak's end-session answered with a redirect to '$back'"
  fi
else
  fail "carol: POST /auth/logout/redirect: $out (want 303 to Keycloak's end-session endpoint)"
fi
rm -f "$work/carol.app"
sso_sign_in carol carol >/dev/null
status="$(app -b "$work/carol.app" -o /dev/null -w '%{http_code}' "$API/projects/$slug")"
if [ "$status" = "404" ]; then
  ok "carol: removed from /tools/members in Keycloak: $slug is 404 at the next sign-in"
else
  fail "carol: $slug answered $status after the group was removed (want 404)"
fi

# 6. An unverified email links nobody --------------------------------------------------
landed="$(sso_sign_in mallory mallory)"
if [[ "$landed" == */login\?error=no_account* ]]; then
  ok "mallory (unverified farah@example.com): /login?error=no_account"
else
  fail "mallory: landed on '$landed' (want /login?error=no_account)"
fi

[ $failed -eq 0 ] || exit 1
printf '\033[1;34m==>\033[0m SSO smoke test passed\n'
