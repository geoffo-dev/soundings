# shellcheck shell=bash
# Keycloak admin REST API helpers for the dev realm (curl + jq). Source it; do not run it.
#
#   KC_URL          Keycloak base URL, e.g. http://keycloak.localhost:18081 (required)
#   KC_REALM        realm (default soundings)       KC_CLIENT_ID  client (default soundings)
#   KC_ADMIN_USER / KC_ADMIN_PASSWORD               master-realm admin (default admin/admin)
#   KC_CURL_ARGS    extra curl arguments (array), e.g. (--connect-to h:p:docker:p)
#
# Requests to http://<name>.localhost:<port> go to http://localhost:<port> with the
# original Host header: curl keeps Keycloak's Secure cookies only for "localhost", and
# the k3s ingress routes by Host.

KC_REALM="${KC_REALM:-soundings}"
KC_CLIENT_ID="${KC_CLIENT_ID:-soundings}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:-admin}"
if ! declare -p KC_CURL_ARGS >/dev/null 2>&1; then KC_CURL_ARGS=(); fi
_kc_token=""

# kc_curl URL [curl args...]: curl with the *.localhost rewrite described above.
kc_curl() {
  local url="$1" host rest
  shift
  local extra=()
  if [[ "$url" =~ ^http://([a-z0-9-]+\.localhost(:[0-9]+)?)(/.*)?$ ]]; then
    host="${BASH_REMATCH[1]}"
    rest="${BASH_REMATCH[3]}"
    url="http://localhost${BASH_REMATCH[2]}${rest}"
    extra=(-H "Host: $host")
  fi
  curl -sS --noproxy '*' --max-time 30 ${KC_CURL_ARGS[@]+"${KC_CURL_ARGS[@]}"} \
    ${extra[@]+"${extra[@]}"} "$@" "$url"
}

# kc_wait SECONDS: until the realm's discovery document answers.
kc_wait() {
  local deadline=$((SECONDS + ${1:-180}))
  until kc_curl "$KC_URL/realms/$KC_REALM/.well-known/openid-configuration" -f -o /dev/null 2>/dev/null; do
    [ $SECONDS -lt $deadline ] || return 1
    sleep 2
  done
}

kc_token() {
  if [ -z "$_kc_token" ]; then
    _kc_token="$(kc_curl "$KC_URL/realms/master/protocol/openid-connect/token" -f \
      --data-urlencode grant_type=password --data-urlencode client_id=admin-cli \
      --data-urlencode "username=$KC_ADMIN_USER" --data-urlencode "password=$KC_ADMIN_PASSWORD" |
      jq -r .access_token)" || return 1
  fi
  printf '%s' "$_kc_token"
}

# kc_api METHOD PATH [curl args...]: admin API call under /admin/realms/$KC_REALM.
kc_api() {
  local method="$1" path="$2" token
  shift 2
  token="$(kc_token)" || return 1
  kc_curl "$KC_URL/admin/realms/$KC_REALM$path" -f -X "$method" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' "$@"
}

kc_user_id() {
  kc_api GET "/users?exact=true&username=$1" | jq -er '.[0].id'
}

kc_group_id() {
  kc_api GET "/group-by-path$1" | jq -er .id
}

# kc_group_add USERNAME /group/path   and   kc_group_remove USERNAME /group/path
kc_group_add() {
  kc_api PUT "/users/$(kc_user_id "$1")/groups/$(kc_group_id "$2")" -o /dev/null
}

kc_group_remove() {
  kc_api DELETE "/users/$(kc_user_id "$1")/groups/$(kc_group_id "$2")" -o /dev/null
}

kc_groups_of() {
  kc_api GET "/users/$(kc_user_id "$1")/groups" | jq -r '.[].path'
}

# kc_add_origin ORIGIN: allow ORIGIN/* as redirect and post-logout redirect URI of the
# client (idempotent). The dev realm lists the usual dev ports; other ports need this.
kc_add_origin() {
  local origin="$1" id client updated
  id="$(kc_api GET "/clients?clientId=$KC_CLIENT_ID" | jq -er '.[0].id')" || return 1
  client="$(kc_api GET "/clients/$id")" || return 1
  updated="$(jq --arg uri "$origin/*" '
    .redirectUris = ((.redirectUris // []) + [$uri] | unique)
    | .attributes["post.logout.redirect.uris"] =
        ((.attributes["post.logout.redirect.uris"] // "") | split("##")
         | map(select(length > 0)) | . + [$uri] | unique | join("##"))' <<<"$client")"
  [ "$updated" = "$client" ] && return 0
  kc_api PUT "/clients/$id" -o /dev/null --data-binary "$updated"
}

# Keycloak's cookies, kept by hand in JAR (one "name=value" per line): it marks them
# Secure even over http, and curl keeps Secure cookies from http only for "localhost".
_kc_cookie_header() {
  [ -s "$1" ] && printf 'Cookie: %s' "$(paste -sd ';' "$1" | sed 's/;/; /g')"
}

_kc_keep_cookies() { # JAR HEADERS_FILE
  local jar="$1" line name value
  touch "$jar"
  while IFS= read -r line; do
    line="${line%$'\r'}"
    line="${line#*: }"
    line="${line%%;*}"
    name="${line%%=*}"
    value="${line#*=}"
    grep -v "^$name=" "$jar" >"$jar.tmp" || true
    [ -n "$value" ] && printf '%s=%s\n' "$name" "$value" >>"$jar.tmp"
    mv "$jar.tmp" "$jar"
  done < <(grep -i '^set-cookie:' "$2" || true)
}

# kc_browse JAR URL [curl args...]: a request with JAR's cookies, keeping new ones.
kc_browse() {
  local jar="$1" url="$2" headers status
  shift 2
  headers="$(mktemp)"
  local cookie=()
  if [ -s "$jar" ]; then cookie=(-H "$(_kc_cookie_header "$jar")"); fi
  kc_curl "$url" -D "$headers" ${cookie[@]+"${cookie[@]}"} "$@"
  status=$?
  _kc_keep_cookies "$jar" "$headers"
  rm -f "$headers"
  return $status
}

# kc_login AUTHORIZATION_URL USERNAME PASSWORD JAR: play the browser at Keycloak's login
# form; prints where Keycloak redirects back to the app (the callback URL with code and
# state). A JAR with a live Keycloak session is redirected without the form.
kc_login() {
  local url="$1" username="$2" password="$3" jar="$4" page action status location
  page="$(kc_browse "$jar" "$url" -w '\n%{http_code} %{redirect_url}')" || return 1
  status="$(tail -n 1 <<<"$page")"
  if [[ "$status" == 302* || "$status" == 303* ]]; then
    printf '%s\n' "${status#* }"
    return 0
  fi
  action="$(grep -o 'id="kc-form-login"[^>]*action="[^"]*"' <<<"$page" |
    sed -e 's/.*action="//' -e 's/"$//' -e 's/&amp;/\&/g')"
  [ -n "$action" ] || { echo "Keycloak login form not found (status $status)" >&2; return 1; }
  location="$(kc_browse "$jar" "$action" -o /dev/null -w '%{redirect_url}' \
    --data-urlencode "username=$username" --data-urlencode "password=$password")" || return 1
  [ -n "$location" ] || { echo "Keycloak did not sign $username in" >&2; return 1; }
  printf '%s\n' "$location"
}
