#!/usr/bin/env bash
# Rehearse continuous delivery on the local k3s (make k3s-deploy): scripts/deploy.sh as the
# CIs run it, as a deployer that may act only in the environment's namespace.
#
#   scripts/lib/k3s-deploy.sh deploy   staging soundings:dev   # load, resolve the digest, deploy
#   scripts/lib/k3s-deploy.sh rollback staging [soundings:0.1.0] # ROLLBACK_REVISION, DEPLOY_FORCE
#   scripts/lib/k3s-deploy.sh smoke    staging
#   scripts/lib/k3s-deploy.sh status   staging
#
# First run (idempotent): deploy/environments/cluster-setup.yaml (namespaces, the deployer
# ClusterRole), a ServiceAccount ci-deployers/soundings-<env> bound to it in
# soundings-<env> only (as the GitLab agent's or an ARC runner's is), and the Secrets the
# values name (random secret key and break-glass password). scripts/deploy.sh then runs in
# the deploy tools image (deploy/ci/deploy-runner.Dockerfile, target tools; DEPLOY_TOOLS_IMAGE)
# with a short-lived token of that ServiceAccount, the values
# deploy/environments/<env>.values.yaml + deploy/environments/k3s.values.yaml and the
# smoke through the k3s ingress on localhost:K3S_HTTP_PORT. The image is imported into the
# node and deployed by digest; MIGRATION_HEAD is read from the image itself. The kubelet
# deletes unused images when the disk is over 85 % full: give rollback the target's image
# again so the node has it.
#
#   K3S_NAME, K3S_API_PORT, K3S_HTTP_PORT   as for scripts/k3s-up.sh
#   DEPLOY_TOOLS_IMAGE                     default soundings-deploy-tools:dev (built if missing)
#   Anything scripts/deploy.sh reads (HELM_TIMEOUT, ROLLBACK_REVISION, DEPLOY_FORCE, DRY_RUN,
#   IMAGE_TAG, MIGRATION_HEAD, DEPLOY_URL) is passed through, and so is a CI's identity
#   (GITLAB_CI + CI_PIPELINE_ID, or GITHUB_ACTIONS + GITHUB_RUN_ID: deploy as that CI's run);
#   IMAGE_DIGEST replaces the image's digest (rehearse a deploy of an image the node can't
#   get); extra arguments go to helm.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=k3s-env.sh
source "$(dirname "${BASH_SOURCE[0]}")/k3s-env.sh"

ACTION="${1:?usage: scripts/lib/k3s-deploy.sh deploy|rollback|smoke|status <env> [image]}"
ENVIRONMENT="${2:?environment (staging or production)}"
shift 2
IMAGE=""
if [ "$ACTION" = deploy ]; then
  IMAGE="${1:?deploy needs a local image, e.g. soundings:dev}"
  shift
elif [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  IMAGE="$1"
  shift
fi
DEPLOY_TOOLS_IMAGE="${DEPLOY_TOOLS_IMAGE:-soundings-deploy-tools:dev}"
NAMESPACE="soundings-$ENVIRONMENT"
SA_NAMESPACE="ci-deployers"
require_k3s

if ! docker image inspect "$DEPLOY_TOOLS_IMAGE" >/dev/null 2>&1; then
  log "building $DEPLOY_TOOLS_IMAGE (deploy/ci/deploy-runner.Dockerfile, target tools)"
  docker build -q -f "$REPO_ROOT/deploy/ci/deploy-runner.Dockerfile" --target tools \
    -t "$DEPLOY_TOOLS_IMAGE" "$REPO_ROOT/deploy/ci" >/dev/null
fi

# --- what operators do once ----------------------------------------------------------------
kubectl apply -f - <"$REPO_ROOT/deploy/environments/cluster-setup.yaml" >/dev/null
kubectl create namespace "$SA_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$SA_NAMESPACE" create serviceaccount "soundings-$ENVIRONMENT" --dry-run=client -o yaml |
  kubectl apply -f - >/dev/null
kubectl -n "$NAMESPACE" create rolebinding soundings-deployer --clusterrole=soundings-deployer \
  --serviceaccount="$SA_NAMESPACE:soundings-$ENVIRONMENT" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
random() { local value; value="$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"; printf '%s' "${value:0:$1}"; }
if ! kubectl -n "$NAMESPACE" get secret soundings-app >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" create secret generic soundings-app --from-literal="secret-key=$(random 48)" >/dev/null
fi
if ! kubectl -n "$NAMESPACE" get secret soundings-break-glass >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" create secret generic soundings-break-glass \
    --from-literal=username=admin --from-literal="password=$(random 24)" >/dev/null
fi

# A kubeconfig with an hour's token of that ServiceAccount (nothing else in the cluster).
kubeconfig="$K3S_DIR/deployer-$ENVIRONMENT.kubeconfig"
token="$(kubectl -n "$SA_NAMESPACE" create token "soundings-$ENVIRONMENT" --duration=1h)"
ca="$(sed -n '/certificate-authority-data:/{s/^ *certificate-authority-data: *//p;q;}' "$K3S_DIR/kubeconfig.internal")"
umask 077
cat >"$kubeconfig" <<KUBECONFIG
apiVersion: v1
kind: Config
clusters:
  - name: k3s
    cluster:
      server: https://127.0.0.1:$K3S_API_PORT
      certificate-authority-data: $ca
users:
  - name: soundings-$ENVIRONMENT
    user:
      token: $token
contexts:
  - name: soundings-$ENVIRONMENT
    context: {cluster: k3s, user: soundings-$ENVIRONMENT, namespace: $NAMESPACE}
current-context: soundings-$ENVIRONMENT
KUBECONFIG

# --- the image: imported into the node, deployed by the digest containerd has for it ------
image_env=()
if [ -n "$IMAGE" ]; then
  "$REPO_ROOT/scripts/k3s-load-image.sh" "$IMAGE" >/dev/null 2>&1 || die "importing $IMAGE failed"
  repo="${IMAGE%:*}"
  tag="${IMAGE##*:}"
  [[ "$repo" == */* ]] || repo="library/$repo"
  [[ "${repo%%/*}" == *.* ]] || repo="docker.io/$repo"
  listing="$(docker exec "$K3S_NAME" ctr -n k8s.io images ls "name==$repo:$tag")"
  digest="$(awk 'NR == 2 { print $3 }' <<<"$listing")"
  [[ "$digest" == sha256:* ]] || die "no digest for $repo:$tag in the node"
  # Also name it by digest, as a pull by digest would: the kubelet then finds it locally.
  docker exec "$K3S_NAME" ctr -n k8s.io images tag --force "$repo:$tag" "$repo@$digest" >/dev/null
  head="$(docker run --rm --entrypoint sh "$IMAGE" -c \
    'ls /app/venv/lib/python3*/site-packages/app/migrations/versions/' |
    sed -n 's/^[0-9]*_\([0-9]\{4\}\)_.*\.py$/\1/p' | sort | tail -n 1)"
  if [ "$ACTION" = deploy ]; then
    image_env=(-e "IMAGE_REPOSITORY=$repo" -e "IMAGE_DIGEST=${IMAGE_DIGEST:-$digest}" -e "IMAGE_TAG=${IMAGE_TAG:-$tag}"
      -e "MIGRATION_HEAD=${MIGRATION_HEAD:-$head}")
  fi
  log "$IMAGE is $repo@$digest (migrations $head)"
fi

pass=()
for name in HELM_TIMEOUT ROLLBACK_REVISION DEPLOY_FORCE DRY_RUN EXPECTED_VERSION \
  GITLAB_CI CI_PIPELINE_ID CI_JOB_ID GITHUB_ACTIONS GITHUB_RUN_ID; do
  [ -z "${!name:-}" ] || pass+=(-e "$name=${!name}")
done

log "scripts/deploy.sh $ACTION $ENVIRONMENT as $SA_NAMESPACE/soundings-$ENVIRONMENT (in $DEPLOY_TOOLS_IMAGE)"
exec docker run --rm --network host \
  -v "$REPO_ROOT:/repo:ro" -w /repo \
  -v "$kubeconfig:/tmp/kubeconfig:ro" -e KUBECONFIG=/tmp/kubeconfig -e HOME=/tmp \
  -e NO_PROXY=localhost,127.0.0.1 -e no_proxy=localhost,127.0.0.1 \
  -e "DEPLOY_VALUES=deploy/environments/$ENVIRONMENT.values.yaml deploy/environments/k3s.values.yaml" \
  -e "DEPLOY_URL=${DEPLOY_URL:-http://localhost:$K3S_HTTP_PORT}" \
  ${image_env[@]+"${image_env[@]}"} ${pass[@]+"${pass[@]}"} \
  "$DEPLOY_TOOLS_IMAGE" bash scripts/deploy.sh "$ACTION" "$ENVIRONMENT" \
  --set "baseUrls[0]=http://localhost:$K3S_HTTP_PORT" "$@"
