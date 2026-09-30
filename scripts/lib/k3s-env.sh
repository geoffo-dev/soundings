# shellcheck shell=bash
# Shared settings for the scripts/k3s-*.sh helpers. Source it; do not run it.
#
#   K3S_NAME       container name                    (default soundings-k3s)
#   K3S_IMAGE      k3s image                         (default rancher/k3s:v1.31.4-k3s1)
#   K3S_API_PORT   host port for the Kubernetes API  (default 16443)
#   K3S_HTTP_PORT  host port for the ingress (80)    (default 18081)
#   K3S_BIND_ADDRESS  address the ports bind to      (default 127.0.0.1; 0.0.0.0 in CI)
#   K3S_DIR        state dir (kubeconfig, registries.yaml); git-ignored
#   HELM_IMAGE     helm runs from this image         (default alpine/helm:3.16.2)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K3S_NAME="${K3S_NAME:-soundings-k3s}"
K3S_IMAGE="${K3S_IMAGE:-rancher/k3s:v1.31.4-k3s1}"
K3S_API_PORT="${K3S_API_PORT:-16443}"
K3S_HTTP_PORT="${K3S_HTTP_PORT:-18081}"
K3S_BIND_ADDRESS="${K3S_BIND_ADDRESS:-127.0.0.1}"
K3S_DIR="${K3S_DIR:-$REPO_ROOT/.k3s/$K3S_NAME}"
HELM_IMAGE="${HELM_IMAGE:-alpine/helm:3.16.2}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

k3s_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$K3S_NAME" 2>/dev/null)" = "true" ]
}

require_k3s() {
  k3s_running || die "k3s container '$K3S_NAME' is not running (run scripts/k3s-up.sh)"
}

# kubectl inside the k3s container (no local kubectl needed).
kubectl() {
  docker exec -i "$K3S_NAME" kubectl "$@"
}

# helm from a container sharing the k3s container's network namespace, so the
# in-cluster kubeconfig (https://127.0.0.1:6443) works as is. The chart, dev/ and the
# kubeconfig travel through stdin rather than bind mounts, so this also works against a
# remote Docker daemon (docker:dind in CI). Paths are relative to the repo root.
helm() {
  tar -cf - -C "$REPO_ROOT" deploy/helm dev -C "$K3S_DIR" kubeconfig.internal |
    docker run --rm -i \
      --network "container:$K3S_NAME" \
      -e KUBECONFIG=/work/kubeconfig.internal \
      --entrypoint sh \
      "$HELM_IMAGE" -c 'mkdir -p /work && cd /work && tar -xf - && exec helm "$@"' helm "$@"
}
