#!/usr/bin/env bash
# helm upgrade --install Soundings into the local k3s cluster (helm runs in a container).
#
#   scripts/k3s-install.sh                          # values: dev/k3s-values.yaml
#   VALUES=deploy/helm/ci/gateway-values.yaml scripts/k3s-install.sh --set foo=bar
#
#   RELEASE    release name (default soundings)     NAMESPACE  (default soundings)
#   VALUES     values file under deploy/helm/ or dev/ TIMEOUT   helm --timeout (default 10m)
# Extra arguments are passed to helm.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

RELEASE="${RELEASE:-soundings}"
NAMESPACE="${NAMESPACE:-soundings}"
VALUES="${VALUES:-dev/k3s-values.yaml}"
TIMEOUT="${TIMEOUT:-10m}"

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

log "helm upgrade --install $RELEASE (namespace $NAMESPACE, values $VALUES)"
helm upgrade --install "$RELEASE" deploy/helm \
  --namespace "$NAMESPACE" \
  --values "$VALUES" \
  --set "baseUrls[0]=http://localhost:$K3S_HTTP_PORT" \
  --wait --timeout "$TIMEOUT" \
  "$@"

kubectl -n "$NAMESPACE" get pods -o wide
