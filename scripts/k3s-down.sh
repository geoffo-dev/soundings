#!/usr/bin/env bash
# Delete the local k3s cluster container and its state directory.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

if docker inspect "$K3S_NAME" >/dev/null 2>&1; then
  log "removing k3s container '$K3S_NAME'"
  docker rm -f -v "$K3S_NAME" >/dev/null
else
  log "k3s container '$K3S_NAME' does not exist"
fi
rm -rf "$K3S_DIR"
