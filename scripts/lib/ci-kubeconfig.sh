#!/usr/bin/env bash
# Print the kubeconfig GitHub's deploy job uses (the environment secret KUBECONFIG_DATA): a
# token of soundings-ci-deployer, which deploy/ci/arc-rbac.yaml binds to soundings-deployer
# in soundings-<env> only, for the API server as pods inside the cluster reach it (the ARC
# runners). Run it as an operator (cluster-admin) and paste the output into the GitHub
# environment's secret; mint a new one before the token expires.
#
#   scripts/lib/ci-kubeconfig.sh staging|production [duration, default 720h]
#
#   KUBECTL   the kubectl command (default kubectl; e.g. "docker exec -i <k3s> kubectl")
#   SERVER    the API server URL the runner uses (default https://kubernetes.default.svc)
#   NAMESPACE default soundings-<env>
set -euo pipefail

env="${1:?usage: scripts/lib/ci-kubeconfig.sh staging|production [duration]}"
duration="${2:-720h}"
[[ "$env" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || { echo "error: environment '$env'" >&2; exit 2; }
[[ "$duration" =~ ^[0-9]+[hms]$ ]] || { echo "error: duration '$duration' (e.g. 720h)" >&2; exit 2; }
read -r -a kubectl <<<"${KUBECTL:-kubectl}"
namespace="${NAMESPACE:-soundings-$env}"
server="${SERVER:-https://kubernetes.default.svc}"

# The cluster's CA as every namespace publishes it (what in-cluster clients trust).
ca="$("${kubectl[@]}" -n "$namespace" get configmap kube-root-ca.crt -o jsonpath='{.data.ca\.crt}' | base64 | tr -d '\n')"
[ -n "$ca" ] || { echo "error: no kube-root-ca.crt in $namespace (does the namespace exist?)" >&2; exit 1; }
token="$("${kubectl[@]}" -n "$namespace" create token soundings-ci-deployer --duration="$duration")"
echo "# KUBECONFIG_DATA for the GitHub environment \"$env\": soundings-ci-deployer in $namespace, valid $duration" >&2
cat <<YAML
apiVersion: v1
kind: Config
clusters:
  - name: soundings-$env
    cluster:
      server: $server
      certificate-authority-data: $ca
users:
  - name: soundings-ci-deployer
    user:
      token: $token
contexts:
  - name: soundings-$env
    context: {cluster: soundings-$env, user: soundings-ci-deployer, namespace: $namespace}
current-context: soundings-$env
YAML
