#!/usr/bin/env bash
# Keycloak with the dev realm inside the local k3s cluster, for single sign-on through
# the ingress (dev/k3s/keycloak.yaml). Then `make k3s-install SSO=1` and
# `make k3s-smoke SSO=1`.
#
#   scripts/k3s-keycloak.sh [up]      # deploy (or update) and wait until it serves the realm
#   scripts/k3s-keycloak.sh down      # remove Keycloak, the DNS rewrite and the client Secret
#
# Issuer: http://keycloak.localhost:$K3S_HTTP_PORT/realms/soundings, the same URL for
# the browser on the host (*.localhost is loopback; the ingress routes the host
# keycloak.localhost to Keycloak) and for the app's pods (CoreDNS rewrites the name to
# Keycloak's Service, which listens on that port too). Admin console:
# http://keycloak.localhost:$K3S_HTTP_PORT/admin/ (admin / admin).
#
#   KEYCLOAK_IMAGE  (default keycloak/keycloak:26.0; imported from the local Docker
#                   when it has it, else pulled by the node)
#   NAMESPACE       the app's namespace (default soundings): gets the Secret
#                   soundings-oidc (client-secret) that dev/k3s-sso-values.yaml uses
#   K3S_CONNECT_HOST  as for k3s-smoke.sh (CI with docker:dind)
# Needs jq.
set -euo pipefail
here="$(dirname "$0")"
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$here/lib/k3s-env.sh"
# shellcheck source-path=SCRIPTDIR source=lib/keycloak.sh
source "$here/lib/keycloak.sh"

KEYCLOAK_IMAGE="${KEYCLOAK_IMAGE:-keycloak/keycloak:26.0}"
NAMESPACE="${NAMESPACE:-soundings}"
KC_URL="http://keycloak.localhost:$K3S_HTTP_PORT"
if [ -n "${K3S_CONNECT_HOST:-}" ]; then
  KC_CURL_ARGS=(--connect-to "localhost:$K3S_HTTP_PORT:$K3S_CONNECT_HOST:$K3S_HTTP_PORT")
fi
REALM_FILE="$REPO_ROOT/dev/keycloak/realm-soundings.json"
# Resolves keycloak.localhost inside the cluster (k3s's CoreDNS imports *.override keys
# of this ConfigMap into its main server block). `answer auto` rewrites the reply back,
# so resolvers see an answer for the name they asked.
DNS_OVERRIDE="rewrite name exact keycloak.localhost keycloak.keycloak.svc.cluster.local answer auto"

restart_coredns() {
  kubectl -n kube-system rollout restart deploy/coredns >/dev/null
  kubectl -n kube-system rollout status deploy/coredns --timeout=120s >/dev/null
}

up() {
  require_k3s
  command -v jq >/dev/null || die "jq is required"

  if docker image inspect "$KEYCLOAK_IMAGE" >/dev/null 2>&1 &&
    ! docker exec "$K3S_NAME" ctr -n k8s.io images ls -q | grep -qF "${KEYCLOAK_IMAGE%%:*}:${KEYCLOAK_IMAGE##*:}"; then
    "$here/k3s-load-image.sh" "$KEYCLOAK_IMAGE"
  fi

  log "deploying Keycloak ($KEYCLOAK_IMAGE) for $KC_URL"
  kubectl create namespace keycloak --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  jq -n --rawfile realm "$REALM_FILE" '{apiVersion: "v1", kind: "ConfigMap",
    metadata: {name: "keycloak-realm", namespace: "keycloak"},
    data: {"realm-soundings.json": $realm}}' | kubectl apply -f - >/dev/null
  realm_sha="$(sha256sum "$REALM_FILE" | cut -c1-16)"
  sed -e "s#__PORT__#$K3S_HTTP_PORT#g" -e "s#__IMAGE__#$KEYCLOAK_IMAGE#g" \
    -e "s#__REALM_SHA__#$realm_sha#g" "$REPO_ROOT/dev/k3s/keycloak.yaml" |
    kubectl apply -f - >/dev/null

  current="$(kubectl -n kube-system get configmap coredns-custom \
    -o jsonpath='{.data.keycloak\.override}' 2>/dev/null || true)"
  if [ "$current" != "$DNS_OVERRIDE" ]; then
    log "CoreDNS: keycloak.localhost -> keycloak.keycloak.svc.cluster.local"
    kubectl -n kube-system create configmap coredns-custom \
      --from-literal=keycloak.override="$DNS_OVERRIDE" --dry-run=client -o yaml |
      kubectl apply -f - >/dev/null
    restart_coredns
  fi

  log "waiting for Keycloak (first start: about a minute)"
  kubectl -n keycloak rollout status deploy/keycloak --timeout=300s >/dev/null
  kc_wait 120 || die "the realm does not answer on $KC_URL"
  # The realm allows http://localhost:18081/*; another K3S_HTTP_PORT needs its own URI.
  kc_add_origin "http://localhost:$K3S_HTTP_PORT"

  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$NAMESPACE" create secret generic soundings-oidc \
    --from-literal=client-secret=soundings-dev-secret --dry-run=client -o yaml |
    kubectl apply -f - >/dev/null
  log "Keycloak is up: issuer $KC_URL/realms/soundings, admin console $KC_URL/admin/ (admin/admin)"
  log "next: make k3s-install SSO=1 && make k3s-smoke SSO=1"
}

down() {
  require_k3s
  log "removing Keycloak, its DNS rewrite and the soundings-oidc Secret"
  kubectl delete namespace keycloak --ignore-not-found >/dev/null
  kubectl -n "$NAMESPACE" delete secret soundings-oidc --ignore-not-found >/dev/null
  if kubectl -n kube-system get configmap coredns-custom >/dev/null 2>&1; then
    kubectl -n kube-system delete configmap coredns-custom >/dev/null
    restart_coredns
  fi
}

case "${1:-up}" in
  up) up ;;
  down) down ;;
  *) die "usage: $0 [up|down]" ;;
esac
