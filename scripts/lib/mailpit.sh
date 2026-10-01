# shellcheck shell=bash
# Mailpit HTTP API helpers (curl + jq). Source it; do not run it.
#
#   MAILPIT_URL        Mailpit's base URL, e.g. http://mailpit.localhost:18081 (required)
#   MAILPIT_CURL_ARGS  extra curl arguments (array), e.g. (--connect-to h:p:docker:p)
#
# A URL on http://<name>.localhost:<port> is requested from http://localhost:<port> with
# the original Host header (the k3s ingress routes by Host).

if ! declare -p MAILPIT_CURL_ARGS >/dev/null 2>&1; then MAILPIT_CURL_ARGS=(); fi

# mailpit_curl PATH [curl args...]
mailpit_curl() {
  local path="$1" url="$MAILPIT_URL"
  shift
  local extra=()
  if [[ "$url" =~ ^http://([a-z0-9-]+\.localhost)(:[0-9]+)?/?$ ]]; then
    extra=(-H "Host: ${BASH_REMATCH[1]}")
    url="http://localhost${BASH_REMATCH[2]}"
  fi
  curl -sS --noproxy '*' --max-time 10 ${MAILPIT_CURL_ARGS[@]+"${MAILPIT_CURL_ARGS[@]}"} \
    ${extra[@]+"${extra[@]}"} "$@" "${url%/}$path"
}

# mailpit_wait SECONDS: until Mailpit answers /readyz.
mailpit_wait() {
  local deadline=$((SECONDS + ${1:-60}))
  until mailpit_curl /readyz -f -o /dev/null 2>/dev/null; do
    [ $SECONDS -lt $deadline ] || return 1
    sleep 1
  done
}

# mailpit_clear: delete every message.
mailpit_clear() {
  mailpit_curl /api/v1/messages -f -o /dev/null -X DELETE
}

# mailpit_to ADDRESS [SINCE]: the messages to ADDRESS (exactly), received at or after
# SINCE (Unix seconds, default 0), as a JSON array of {ID, Subject, Created, ...},
# newest first; [] when Mailpit is unreachable.
mailpit_to() {
  mailpit_curl /api/v1/search -f -G --data-urlencode "query=to:\"$1\"" 2>/dev/null |
    jq -c --arg to "$1" --argjson since "${2:-0}" '[.messages // [] | .[]
      | select(any(.To[]; (.Address | ascii_downcase) == ($to | ascii_downcase)))
      | select((.Created | sub("\\.[0-9]+"; "") | fromdateiso8601) >= $since)]' \
      2>/dev/null || echo '[]'
}

# mailpit_wait_to ADDRESS SINCE SECONDS: until a message to ADDRESS received at or after
# SINCE arrives (prints them, as mailpit_to), or SECONDS pass (status 1).
mailpit_wait_to() {
  local deadline=$((SECONDS + ${3:-30})) found
  while :; do
    found="$(mailpit_to "$1" "$2")"
    if [ "$(jq length <<<"$found")" -gt 0 ]; then
      printf '%s\n' "$found"
      return 0
    fi
    [ $SECONDS -lt $deadline ] || return 1
    sleep 2
  done
}

# mailpit_message ID: the full message as JSON (Subject, From, To, HTML, Text, ...).
mailpit_message() {
  mailpit_curl "/api/v1/message/$1" -f
}

# mailpit_headers ID: the message's headers as JSON ({"List-Unsubscribe": [...], ...}).
mailpit_headers() {
  mailpit_curl "/api/v1/message/$1/headers" -f
}
