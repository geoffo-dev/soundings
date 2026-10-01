#!/usr/bin/env bash
# Start a single-node k3s cluster in Docker (bundled Traefik ingress on K3S_HTTP_PORT).
#
#   scripts/k3s-up.sh                       # container "soundings-k3s"
#   K3S_NAME=my-k3s K3S_HTTP_PORT=8081 scripts/k3s-up.sh
#
# Image pulls inside the cluster go through K3S_REGISTRY_MIRROR (a Docker Hub mirror,
# default https://mirror.gcr.io; set it empty to pull from Docker Hub directly).
# K3S_EXTRA_CA (default: $SSL_CERT_FILE) is trusted for registry TLS when it exists, for
# networks with a TLS-intercepting proxy.
# Where the kernel refuses negative oom_score_adj even to privileged containers (some
# VM sandboxes), containerd is configured with restrict_oom_score_adj so pods can start.
# K3S_EVICTION_HARD (default imagefs.available<1Gi,nodefs.available<1Gi): the kubelet's
# disk eviction thresholds. Its defaults are percentages (5-15 % of the disk), which on a
# large, shared build disk evict every pod while gigabytes are still free.
# The kubeconfig is written to $K3S_DIR/kubeconfig (git-ignored):
#   export KUBECONFIG=$PWD/.k3s/soundings-k3s/kubeconfig
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

K3S_REGISTRY_MIRROR="${K3S_REGISTRY_MIRROR-https://mirror.gcr.io}"
K3S_EXTRA_CA="${K3S_EXTRA_CA-${SSL_CERT_FILE:-}}"
K3S_EVICTION_HARD="${K3S_EVICTION_HARD:-imagefs.available<1Gi,nodefs.available<1Gi}"
K3S_WAIT_SECONDS="${K3S_WAIT_SECONDS:-300}"

# k3s's generated containerd config (containerd 1.7, config version 2) plus
# restrict_oom_score_adj. Only used when needed (see below).
write_containerd_template() {
  cat > "$1" <<'TOML'
version = 2

[plugins."io.containerd.internal.v1.opt"]
  path = "/var/lib/rancher/k3s/agent/containerd"
[plugins."io.containerd.grpc.v1.cri"]
  stream_server_address = "127.0.0.1"
  stream_server_port = "10010"
  enable_selinux = false
  enable_unprivileged_ports = true
  enable_unprivileged_icmp = true
  device_ownership_from_security_context = false
  sandbox_image = "rancher/mirrored-pause:3.6"
  restrict_oom_score_adj = true

[plugins."io.containerd.grpc.v1.cri".containerd]
  snapshotter = "overlayfs"
  disable_snapshot_annotations = true

[plugins."io.containerd.grpc.v1.cri".cni]
  bin_dir = "/bin"
  conf_dir = "/var/lib/rancher/k3s/agent/etc/cni/net.d"

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
  runtime_type = "io.containerd.runc.v2"

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = false

[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/var/lib/rancher/k3s/agent/etc/containerd/certs.d"
TOML
}

if k3s_running; then
  log "k3s '$K3S_NAME' is already running"
  exit 0
fi
docker rm -f "$K3S_NAME" >/dev/null 2>&1 || true

mkdir -p "$K3S_DIR"
# Keep the state dir out of git without touching the root .gitignore.
printf '*\n' > "$REPO_ROOT/.k3s/.gitignore"

# Config files are staged under $K3S_DIR/rootfs and copied in with `docker cp` (not
# bind-mounted), so this also works against a remote Docker daemon (docker:dind in CI).
rootfs="$K3S_DIR/rootfs"
rm -rf "$rootfs"
mkdir -p "$rootfs/etc/rancher/k3s" "$rootfs/var/lib/rancher/k3s/agent/etc/containerd"
ca_config=""
if [ -n "$K3S_EXTRA_CA" ] && [ -f "$K3S_EXTRA_CA" ]; then
  cp "$K3S_EXTRA_CA" "$rootfs/etc/rancher/k3s/extra-ca.crt"
  ca_config="    tls:
      ca_file: /etc/rancher/k3s/extra-ca.crt"
fi

# Some sandboxes forbid lowering oom_score_adj even for privileged root; containerd's
# pod sandboxes use -998 and fail with "can't get final child's PID from pipe" there.
if ! docker run --rm --privileged --entrypoint sh "$K3S_IMAGE" -c 'echo -998 > /proc/self/oom_score_adj' 2>/dev/null; then
  log "negative oom_score_adj is not allowed here: enabling containerd restrict_oom_score_adj"
  write_containerd_template "$rootfs/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl"
fi

{
  if [ -n "$K3S_REGISTRY_MIRROR" ]; then
    printf 'mirrors:\n  docker.io:\n    endpoint:\n      - %s\n' "$K3S_REGISTRY_MIRROR"
  fi
  if [ -n "$ca_config" ]; then
    printf 'configs:\n'
    for host in "${K3S_REGISTRY_MIRROR#https://}" registry-1.docker.io; do
      [ -n "$host" ] && printf '  "%s":\n%s\n' "$host" "$ca_config"
    done
  fi
} > "$rootfs/etc/rancher/k3s/registries.yaml"

log "starting k3s '$K3S_NAME' ($K3S_IMAGE): API on $K3S_BIND_ADDRESS:$K3S_API_PORT, HTTP on $K3S_BIND_ADDRESS:$K3S_HTTP_PORT"
docker create --name "$K3S_NAME" --hostname "$K3S_NAME" \
  --privileged \
  --tmpfs /run --tmpfs /var/run \
  -p "$K3S_BIND_ADDRESS:$K3S_API_PORT:6443" \
  -p "$K3S_BIND_ADDRESS:$K3S_HTTP_PORT:80" \
  "$K3S_IMAGE" server \
    --disable=metrics-server \
    --kubelet-arg="eviction-hard=$K3S_EVICTION_HARD" \
    --tls-san=127.0.0.1 \
    --write-kubeconfig-mode=644 >/dev/null
docker cp "$rootfs/." "$K3S_NAME:/" >/dev/null
docker start "$K3S_NAME" >/dev/null

log "waiting for the node to be Ready"
deadline=$((SECONDS + K3S_WAIT_SECONDS))
until docker exec "$K3S_NAME" kubectl get nodes 2>/dev/null | grep -q ' Ready '; do
  [ $SECONDS -lt $deadline ] || { docker logs --tail 30 "$K3S_NAME" >&2; die "k3s did not become ready"; }
  sleep 2
done

docker exec "$K3S_NAME" cat /etc/rancher/k3s/k3s.yaml > "$K3S_DIR/kubeconfig.internal"
sed "s#https://127.0.0.1:6443#https://127.0.0.1:$K3S_API_PORT#" "$K3S_DIR/kubeconfig.internal" > "$K3S_DIR/kubeconfig"
chmod 600 "$K3S_DIR/kubeconfig" "$K3S_DIR/kubeconfig.internal"

log "waiting for CoreDNS and the Traefik ingress controller"
until docker exec "$K3S_NAME" kubectl -n kube-system get deploy/coredns deploy/traefik >/dev/null 2>&1; do
  [ $SECONDS -lt $deadline ] || die "system deployments did not appear"
  sleep 2
done
remaining=$((deadline - SECONDS)); [ $remaining -gt 10 ] || remaining=10
docker exec "$K3S_NAME" kubectl -n kube-system rollout status deploy/coredns --timeout="${remaining}s" >/dev/null
docker exec "$K3S_NAME" kubectl -n kube-system rollout status deploy/traefik --timeout="${remaining}s" >/dev/null

log "k3s is up. KUBECONFIG=$K3S_DIR/kubeconfig (from inside the container: docker exec $K3S_NAME kubectl ...)"
