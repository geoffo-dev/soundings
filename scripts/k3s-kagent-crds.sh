#!/usr/bin/env bash
# kagent's CRDs in the local k3s cluster (no controller, no model: there is neither here),
# so Soundings' kagent manifests can be validated by the API server itself.
#
#   scripts/k3s-kagent-crds.sh [install]   # kagent's CRDs at KAGENT_VERSION, server-side apply
#   scripts/k3s-kagent-crds.sh check       # server-side dry run of deploy/kagent/*.yaml and
#                                          # of the chart's kagent resources (kagent.examples)
#
#   KAGENT_VERSION   git tag of github.com/kagent-dev/kagent (default v0.10.2); its CRDs are
#                    helm/kagent-crds/templates/*.yaml, the files kagent's "kagent-crds"
#                    chart packages (the chart's OCI blobs on ghcr.io are not reachable
#                    from every network: this reads the tag with a shallow, sparse git
#                    clone into .k3s/kagent-<version>/ instead)
#   KAGENT_CRDS_DIR  use these CRD files instead (no clone)
#   NAMESPACE        where the release (and its example agents) live (default soundings)
set -euo pipefail
here="$(dirname "$0")"
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$here/lib/k3s-env.sh"

KAGENT_VERSION="${KAGENT_VERSION:-v0.10.2}"
NAMESPACE="${NAMESPACE:-soundings}"

crds_dir() {
  if [ -n "${KAGENT_CRDS_DIR:-}" ]; then
    printf '%s' "$KAGENT_CRDS_DIR"
    return
  fi
  local src="$REPO_ROOT/.k3s/kagent-$KAGENT_VERSION"
  if [ ! -d "$src/helm/kagent-crds/templates" ]; then
    log "fetching kagent $KAGENT_VERSION's CRDs (sparse git clone of github.com/kagent-dev/kagent)"
    rm -rf "$src"
    mkdir -p "$REPO_ROOT/.k3s"
    printf '*\n' >"$REPO_ROOT/.k3s/.gitignore"
    GIT_LFS_SKIP_SMUDGE=1 git clone --quiet --depth 1 --branch "$KAGENT_VERSION" \
      --filter=blob:none --sparse https://github.com/kagent-dev/kagent "$src" >&2
    git -C "$src" sparse-checkout set helm/kagent-crds/templates >&2
  fi
  printf '%s' "$src/helm/kagent-crds/templates"
}

install() {
  require_k3s
  local dir file
  dir="$(crds_dir)"
  for file in "$dir"/kagent.dev_*.yaml; do
    kubectl apply --server-side --force-conflicts -f - <"$file" >/dev/null
  done
  kubectl wait --for=condition=Established --timeout=60s crd/agents.kagent.dev \
    crd/remotemcpservers.kagent.dev crd/modelconfigs.kagent.dev >/dev/null
  log "kagent $KAGENT_VERSION CRDs installed:"
  kubectl get crd -o custom-columns='NAME:.metadata.name,VERSIONS:.spec.versions[*].name,STORED:.status.storedVersions' |
    grep -E '^NAME|kagent\.dev' >&2
}

# dry_run [NAMESPACE] < MANIFESTS: kubectl apply --dry-run=server -o json (objects without
# a namespace go to NAMESPACE); prints one line per object
# the API server accepted, with what it defaulted from the CRD's schema (an Agent's
# runtime, a RemoteMCPServer's terminateOnClose), so the schema demonstrably applied.
dry_run() {
  local json errors namespace=()
  [ $# -eq 0 ] || namespace=(--namespace "$1")
  errors="$(mktemp)"
  # (stderr apart: kubectl warns there, e.g. about objects Helm created without
  # kubectl's last-applied annotation, which a dry run of existing objects reports.)
  json="$(kubectl ${namespace[@]+"${namespace[@]}"} apply --dry-run=server -o json -f - 2>"$errors")" || {
    cat "$errors"
    rm -f "$errors"
    return 1
  }
  rm -f "$errors"
  jq -r '(if .kind == "List" then .items[] else . end)
    | "        \(.apiVersion) \(.kind) \(.metadata.namespace // "-")/\(.metadata.name)"
      + (if .kind == "Agent" then " (type \(.spec.type), runtime \(.spec.declarative.runtime // "-"))"
         elif .kind == "RemoteMCPServer" then " (terminateOnClose \(.spec.terminateOnClose))"
         else "" end)' <<<"$json"
}

check() {
  require_k3s
  kubectl get crd agents.kagent.dev >/dev/null 2>&1 || die "no kagent CRDs: run $0 install"
  command -v jq >/dev/null || die "jq is required"
  local failed=0 out file
  for namespace in "$NAMESPACE" kagent; do # the examples' namespaces must exist
    kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  done
  for file in "$REPO_ROOT"/deploy/kagent/*.yaml; do
    if out="$(dry_run <"$file")"; then
      printf '  ok  %s: accepted (server-side dry run)\n%s\n' "${file#"$REPO_ROOT"/}" "$out"
    else
      printf '  FAIL %s:\n%s\n' "${file#"$REPO_ROOT"/}" "$out" >&2
      failed=1
    fi
  done
  # The chart's example resources (both agents, their RemoteMCPServers, the shared one).
  if out="$(helm template soundings deploy/helm --namespace "$NAMESPACE" \
    --set kagent.enabled=true --set kagent.examples=true \
    --set kagent.agents.modelConfig=soundings-model --set kagent.mcp.keySecret=soundings-agent-key \
    --show-only templates/kagent-agents.yaml --show-only templates/kagent-mcp.yaml | dry_run "$NAMESPACE")"; then
    printf '  ok  chart kagent.examples: accepted (server-side dry run)\n%s\n' "$out"
  else
    printf '  FAIL chart kagent.examples:\n%s\n' "$out" >&2
    failed=1
  fi
  # And for real (they are only custom resources while no controller runs): create the
  # by-hand files' objects, read the kagent ones back, then delete what was created.
  local back
  for file in "$REPO_ROOT"/deploy/kagent/*.yaml; do
    if out="$(kubectl create -f - -o name <"$file" 2>&1)"; then
      back="$(kubectl get -f - -o jsonpath='{range .items[*]}{.kind}/{.metadata.namespace}/{.metadata.name} {end}' \
        <"$file" 2>/dev/null | tr ' ' '\n' | grep -vE '^(Secret/|$)' | tr '\n' ' ' || true)"
      printf '  ok  %s: created for real (%s objects); kagent ones read back: %s\n' \
        "${file#"$REPO_ROOT"/}" "$(wc -l <<<"$out" | tr -d ' ')" "${back% }"
      kubectl delete --wait=false -f - <"$file" >/dev/null 2>&1 || true
    else
      printf '  FAIL %s (create):\n%s\n' "${file#"$REPO_ROOT"/}" "$out" >&2
      kubectl delete --ignore-not-found --wait=false -f - <"$file" >/dev/null 2>&1 || true
      failed=1
    fi
  done
  [ $failed -eq 0 ] || die "kagent manifests refused by the $KAGENT_VERSION CRDs"
  log "every kagent manifest validated against kagent $KAGENT_VERSION's CRDs"
}

case "${1:-install}" in
  install) install ;;
  check) check ;;
  *) die "usage: $0 [install|check]" ;;
esac
