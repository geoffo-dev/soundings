#!/usr/bin/env bash
# Soundings' fake kagent (dev/fake-agent) in the local k3s cluster, where kagent's
# controller would be: namespace kagent, Service kagent-controller, port 8083
# (dev/k3s/fake-agent.yaml). Then `make k3s-install AI=1` and `make k3s-smoke AI=1`.
#
#   scripts/k3s-fake-agent.sh [up]          # build the image if needed, import, deploy, wait
#   scripts/k3s-fake-agent.sh key           # stdin: the JSON scripts/ai-smoke.sh hands its
#                                           # AI_KEY_HOOK ({namespace, name, key,
#                                           # secret_manifest}): applies the Secret manifest
#                                           # in the agent's namespace (the operator's step)
#                                           # and gives the key to the fake (restarts it)
#   scripts/k3s-fake-agent.sh observations RUN_ID   # what the fake saw of a run (JSON)
#   scripts/k3s-fake-agent.sh down          # remove it (keeps the namespace when kagent's
#                                           # CRDs or other things live there)
#
#   FAKE_AGENT_IMAGE  (default soundings-fake-agent:dev; built from dev/fake-agent when
#                     missing)            RELEASE / NAMESPACE  the Soundings release
# Keys travel on stdin and in Secrets only, never on a command line or in logs.
set -euo pipefail
here="$(dirname "$0")"
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$here/lib/k3s-env.sh"

FAKE_AGENT_IMAGE="${FAKE_AGENT_IMAGE:-soundings-fake-agent:dev}"
RELEASE="${RELEASE:-soundings}"
NAMESPACE="${NAMESPACE:-soundings}"

mcp_url() {
  # The chart's Service: <fullname>.<namespace>.svc.cluster.local:<port>/mcp. Before the
  # release exists, assume the defaults (fullname = release name "soundings", port 80).
  local service
  service="$(kubectl -n "$NAMESPACE" get svc -l "app.kubernetes.io/instance=$RELEASE" \
    -o jsonpath='{range .items[*]}{.metadata.name} {.spec.ports[?(@.name=="http")].port}{"\n"}{end}' 2>/dev/null |
    awk 'NF == 2 { print; exit }')"
  [ -n "$service" ] || service="$RELEASE 80"
  printf 'http://%s.%s.svc.cluster.local:%s/mcp' "${service% *}" "$NAMESPACE" "${service#* }"
}

up() {
  require_k3s
  if ! docker image inspect "$FAKE_AGENT_IMAGE" >/dev/null 2>&1; then
    log "building $FAKE_AGENT_IMAGE (dev/fake-agent)"
    make -s -C "$REPO_ROOT/dev/fake-agent" image IMAGE="$FAKE_AGENT_IMAGE" >/dev/null
  fi
  "$here/k3s-load-image.sh" "$FAKE_AGENT_IMAGE" 2>/dev/null
  log "deploying the fake kagent as kagent/kagent-controller:8083 ($FAKE_AGENT_IMAGE)"
  sed -e "s#__IMAGE__#$FAKE_AGENT_IMAGE#g" -e "s#__MCP_URL__#$(mcp_url)#g" \
    "$REPO_ROOT/dev/k3s/fake-agent.yaml" | kubectl apply -f - >/dev/null
  # A new image under the same tag: start a new pod.
  kubectl -n kagent rollout restart deploy/kagent-controller >/dev/null
  kubectl -n kagent rollout status deploy/kagent-controller --timeout=120s >/dev/null
  log "the fake kagent is up: http://kagent-controller.kagent:8083 (MCP $(mcp_url))"
}

# key: stdin is {namespace, name, key, secret_manifest} (scripts/ai-smoke.sh AI_KEY_HOOK).
key() {
  require_k3s
  command -v jq >/dev/null || die "jq is required"
  local input namespace name
  input="$(cat)"
  namespace="$(jq -r .namespace <<<"$input")"
  name="$(jq -r .name <<<"$input")"
  [[ "$namespace" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || die "bad namespace"
  [[ "$name" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || die "bad name"
  # 1. What an operator does with the manifest registration shows once: apply it in the
  #    agent's namespace (the example Agents' RemoteMCPServers read it there).
  kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  jq -r .secret_manifest <<<"$input" | kubectl apply -f - >/dev/null
  # 2. The fake stands in for kagent's agent pods: its Secret gets the same header.
  # (Existing entries and the new key go through jq's stdin, never its arguments.)
  local entries
  entries="$(kubectl -n kagent get secret fake-agent-keys -o json 2>/dev/null | jq -c '{data: (.data // {})}' || true)"
  [ -n "$entries" ] || entries='{"data": {}}'
  printf '%s\n%s\n' "$entries" "$input" | jq -s -c --arg k "$namespace.$name" \
    '{apiVersion: "v1", kind: "Secret", type: "Opaque", metadata: {name: "fake-agent-keys", namespace: "kagent"},
      data: (.[0].data + {($k): ("Bearer " + .[1].key | @base64)})}' | kubectl apply -f - >/dev/null
  # Mounted Secrets update within a minute or so; a restart makes it immediate.
  kubectl -n kagent rollout restart deploy/kagent-controller >/dev/null
  kubectl -n kagent rollout status deploy/kagent-controller --timeout=120s >/dev/null
  log "agent $namespace/$name: Secret applied in $namespace, key given to the fake kagent"
}

observations() {
  require_k3s
  [[ "${1:-}" =~ ^[0-9a-f-]{36}$ ]] || die "usage: $0 observations RUN_ID"
  kubectl -n kagent exec -i deploy/kagent-controller -- python -c "
import sys, urllib.request
print(urllib.request.urlopen('http://127.0.0.1:8083/_fake/observations/' + sys.argv[1], timeout=5).read().decode())
" "$1"
}

down() {
  require_k3s
  log "removing the fake kagent"
  kubectl -n kagent delete deploy/kagent-controller svc/kagent-controller secret/fake-agent-keys \
    --ignore-not-found >/dev/null
  if [ -z "$(kubectl -n kagent get all,secrets,configmaps -o name 2>/dev/null | grep -v 'default-token\|kube-root-ca' || true)" ]; then
    kubectl delete namespace kagent --ignore-not-found --wait=false >/dev/null
  fi
}

case "${1:-up}" in
  up) up ;;
  key) key ;;
  observations) shift; observations "$@" ;;
  down) down ;;
  *) die "usage: $0 [up|key|observations RUN_ID|down]" ;;
esac
