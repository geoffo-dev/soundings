#!/usr/bin/env bash
# Copy a local Docker image into the k3s node's containerd (no registry needed).
#
#   scripts/k3s-load-image.sh [image]        # default: soundings:dev
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

IMAGE="${1:-${IMAGE:-soundings:dev}}"
require_k3s
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image '$IMAGE' not found (run: make image)"

log "importing $IMAGE into k3s '$K3S_NAME'"
# --all-platforms keeps multi-platform images built here intact; an image pulled for one
# platform only (e.g. keycloak/keycloak) lacks the other platforms' blobs, so retry
# with just the node's platform, and then with an archive of only the image's own
# platform (Docker's containerd image store saves the whole index otherwise, e.g.
# axllent/mailpit).
platform="$(docker image inspect -f '{{.Os}}/{{.Architecture}}' "$IMAGE")"
if ! docker save "$IMAGE" | docker exec -i "$K3S_NAME" ctr -n k8s.io images import --all-platforms - >/dev/null 2>&1 &&
  ! docker save "$IMAGE" | docker exec -i "$K3S_NAME" ctr -n k8s.io images import - >/dev/null 2>&1; then
  docker save --platform "$platform" "$IMAGE" | docker exec -i "$K3S_NAME" ctr -n k8s.io images import - >/dev/null
fi
docker exec "$K3S_NAME" ctr -n k8s.io images ls -q | grep -F "${IMAGE%%:*}" >&2 || die "import failed"
