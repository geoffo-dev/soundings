#!/usr/bin/env bash
# Mailpit inside the local k3s cluster (dev/k3s/mailpit.yaml), so the release can send
# real email: then `make k3s-install SMTP=1` and `make k3s-smoke SMTP=1`.
#
#   scripts/k3s-mailpit.sh [up]       # deploy (or update) and wait until it answers
#   scripts/k3s-mailpit.sh scale N    # 0: "the SMTP server is down"; 1: back up (empty)
#   scripts/k3s-mailpit.sh down       # remove it (namespace mailpit)
#
# SMTP: mailpit.mailpit.svc.cluster.local:1025 (plain; dev/k3s-smtp-values.yaml).
# Inbox and API: http://mailpit.localhost:$K3S_HTTP_PORT/ through the ingress.
#
#   MAILPIT_IMAGE     (default axllent/mailpit:latest; imported from the local Docker
#                     when it has it, else pulled by the node)
#   K3S_CONNECT_HOST  as for k3s-smoke.sh (CI with docker:dind)
set -euo pipefail
here="$(dirname "$0")"
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$here/lib/k3s-env.sh"
# shellcheck source-path=SCRIPTDIR source=lib/mailpit.sh
source "$here/lib/mailpit.sh"

MAILPIT_IMAGE="${MAILPIT_IMAGE:-axllent/mailpit:latest}"
MAILPIT_URL="http://mailpit.localhost:$K3S_HTTP_PORT"
if [ -n "${K3S_CONNECT_HOST:-}" ]; then
  MAILPIT_CURL_ARGS=(--connect-to "localhost:$K3S_HTTP_PORT:$K3S_CONNECT_HOST:$K3S_HTTP_PORT")
fi

up() {
  require_k3s
  if docker image inspect "$MAILPIT_IMAGE" >/dev/null 2>&1 &&
    ! docker exec "$K3S_NAME" ctr -n k8s.io images ls -q | grep -qF "${MAILPIT_IMAGE%%:*}:${MAILPIT_IMAGE##*:}"; then
    "$here/k3s-load-image.sh" "$MAILPIT_IMAGE"
  fi
  log "deploying Mailpit ($MAILPIT_IMAGE)"
  sed -e "s#__IMAGE__#$MAILPIT_IMAGE#g" "$REPO_ROOT/dev/k3s/mailpit.yaml" | kubectl apply -f - >/dev/null
  scale 1
  log "Mailpit is up: SMTP mailpit.mailpit.svc.cluster.local:1025, inbox $MAILPIT_URL/"
  log "next: make k3s-install SMTP=1 && make k3s-smoke SMTP=1"
}

# scale N: set the replicas and wait until it is gone (0) or answers through the ingress.
scale() {
  require_k3s
  kubectl -n mailpit scale deploy/mailpit --replicas="$1" >/dev/null
  if [ "$1" = "0" ]; then
    kubectl -n mailpit wait --for=delete pod -l app.kubernetes.io/name=mailpit --timeout=60s >/dev/null 2>&1 || true
  else
    kubectl -n mailpit rollout status deploy/mailpit --timeout=120s >/dev/null
    mailpit_wait 60 || die "Mailpit does not answer on $MAILPIT_URL"
  fi
}

down() {
  require_k3s
  log "removing Mailpit (namespace mailpit)"
  kubectl delete namespace mailpit --ignore-not-found >/dev/null
}

case "${1:-up}" in
  up) up ;;
  scale) [[ "${2:-}" =~ ^[0-9]+$ ]] || die "usage: $0 scale N"; scale "$2" ;;
  down) down ;;
  *) die "usage: $0 [up|scale N|down]" ;;
esac
