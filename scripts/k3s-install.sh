#!/usr/bin/env bash
# helm upgrade --install Soundings into the local k3s cluster (helm runs in a container).
#
#   scripts/k3s-install.sh                          # values: dev/k3s-values.yaml
#   VALUES=deploy/helm/ci/gateway-values.yaml scripts/k3s-install.sh --set foo=bar
#
#   SSO=1 scripts/k3s-install.sh                    # + dev/k3s-sso-values.yaml (Keycloak)
#   SMTP=1 scripts/k3s-install.sh                   # + dev/k3s-smtp-values.yaml (Mailpit)
#
#   RELEASE    release name (default soundings)     NAMESPACE  (default soundings)
#   VALUES     values file under deploy/helm/ or dev/ TIMEOUT   helm --timeout (default 10m)
#   SSO        1: single sign-on against the cluster's Keycloak (scripts/k3s-keycloak.sh
#              first): adds dev/k3s-sso-values.yaml and the issuer for K3S_HTTP_PORT
#   SMTP       1: email to the cluster's Mailpit (scripts/k3s-mailpit.sh first): adds
#              dev/k3s-smtp-values.yaml (SMTP, time zone, egress NetworkPolicies)
# Extra arguments are passed to helm.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

RELEASE="${RELEASE:-soundings}"
NAMESPACE="${NAMESPACE:-soundings}"
VALUES="${VALUES:-dev/k3s-values.yaml}"
TIMEOUT="${TIMEOUT:-10m}"
SSO="${SSO:-0}"
SMTP="${SMTP:-0}"

require_k3s
case "$VALUES" in
  deploy/helm/* | dev/*) ;;
  *) die "VALUES must be a file under deploy/helm/ or dev/ (relative to the repo root)" ;;
esac
[ -f "$REPO_ROOT/$VALUES" ] || die "values file '$VALUES' not found"

# Namespace enforcing the Restricted Pod Security Standard: pods that do not meet it
# are rejected, so the install doubles as a check of the chart's security settings.
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl label namespace "$NAMESPACE" --overwrite \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/warn=restricted >/dev/null

sso_args=()
values_label="$VALUES"
if [ "$SSO" = "1" ]; then
  kubectl -n keycloak get deploy/keycloak >/dev/null 2>&1 ||
    die "SSO=1 needs Keycloak in the cluster first: scripts/k3s-keycloak.sh (make k3s-keycloak)"
  sso_args=(--values dev/k3s-sso-values.yaml
    --set "oidc.issuer=http://keycloak.localhost:$K3S_HTTP_PORT/realms/soundings")
  values_label="$VALUES + dev/k3s-sso-values.yaml"
fi
smtp_args=()
if [ "$SMTP" = "1" ]; then
  kubectl -n mailpit get deploy/mailpit >/dev/null 2>&1 ||
    die "SMTP=1 needs Mailpit in the cluster first: scripts/k3s-mailpit.sh (make k3s-mailpit)"
  smtp_args=(--values dev/k3s-smtp-values.yaml)
  values_label="$values_label + dev/k3s-smtp-values.yaml"
fi

log "helm upgrade --install $RELEASE (namespace $NAMESPACE, values $values_label)"
helm upgrade --install "$RELEASE" deploy/helm \
  --namespace "$NAMESPACE" \
  --values "$VALUES" \
  ${sso_args[@]+"${sso_args[@]}"} \
  ${smtp_args[@]+"${smtp_args[@]}"} \
  --set "baseUrls[0]=http://localhost:$K3S_HTTP_PORT" \
  --wait --timeout "$TIMEOUT" \
  "$@"

kubectl -n "$NAMESPACE" get pods -o wide
