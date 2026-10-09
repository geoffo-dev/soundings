#!/usr/bin/env bash
# Run Soundings' GitLab pipeline for real, on a throwaway self-managed GitLab in Docker:
# GitLab CE with its container registry and agent server (KAS) on https (a throwaway CA),
# a Docker-executor runner, and k3s with the two GitLab agents (agentk) connected to KAS,
# installed from deploy/gitlab-agent/ as an operator would. The project is
# platform/soundings, as .gitlab/agents/*/config.yaml name it. docs/test-plans/phase-9.md
# is the walkthrough and records a run; scripts/ci-local/README.md lists what it needs.
#
#   scripts/ci-local/ci-local.sh up                 ca, gitlab, bootstrap, project, runner, k3s,
#                                                   agents (each also on its own; idempotent)
#   scripts/ci-local/ci-local.sh push [-m msg] [--no-sync] [branch]
#                                                   commit a snapshot of this working tree
#                                                   (uncommitted changes included) to the local
#                                                   copy and push it (default branch main)
#   scripts/ci-local/ci-local.sh bump X.Y.Z         the release commit in the local copy
#                                                   (pyproject, uv.lock, Chart.yaml)
#   scripts/ci-local/ci-local.sh tag vX.Y.Z         tag the local copy's HEAD and push the tag
#   scripts/ci-local/ci-local.sh probe              agent-probe pipelines on a protected and an
#                                                   unprotected branch (what CI jobs can reach)
#   scripts/ci-local/ci-local.sh pipelines | jobs <pipeline> | wait <pipeline> | log <job id>
#   scripts/ci-local/ci-local.sh play <pipeline> <job name> [KEY=VALUE ...]
#   scripts/ci-local/ci-local.sh api <METHOD> <path> [curl args]   GitLab REST as the admin
#   scripts/ci-local/ci-local.sh kubectl <args>     cluster-admin kubectl in the k3s node
#   scripts/ci-local/ci-local.sh runner-mode rootless|privileged
#   scripts/ci-local/ci-local.sh github <staging|production> <deploy|rollback> [KEY=VALUE ...]
#                                                   GitHub's deploy step (deploy-env.yml) in a pod
#                                                   as an ARC runner inside the cluster would run it
#   scripts/ci-local/ci-local.sh status | guard | down [--images]
#
# Settings (environment):
#   CI_LOCAL_PREFIX      container/network name prefix         (default ci-local-)
#   CI_LOCAL_PORT        first of five host ports on 127.0.0.1: GitLab https, registry,
#                        (ssh, unused), k3s API, k3s ingress    (default 8910)
#   CI_LOCAL_DIR         state: CA, tokens, runner config, the repository copy
#                        (default .ci-local/<prefix without the dash>, git-ignored)
#   CI_LOCAL_MIRROR      Docker Hub mirror for GitLab, the runner, k3s and the pipeline's
#                        REGISTRY_MIRROR                         (default docker.io)
#   CI_LOCAL_EXTRA_CA    extra CA bundle every piece trusts, e.g. a TLS-intercepting
#                        proxy's (default $SSL_CERT_FILE when set)
#   CI_LOCAL_VARIABLES   extra project CI/CD variables, "KEY=VALUE;KEY=VALUE"
#   CD_ONLY=1            push/tag with -o ci.variable=CD_ONLY=1 (no lint/test/e2e/k3s jobs)
#   CI_LOCAL_PUSH_VARS   more pipeline variables for push/tag, "KEY=VALUE KEY=VALUE"
#                        (e.g. IMAGE_BUILDER=dind with runner-mode privileged)
#   CI_LOCAL_PATHS       push: the committed HEAD plus only these paths from the working tree
#                        (space-separated), e.g. while others have unfinished work elsewhere
#   CI_LOCAL_BUILDKIT_DIR  a host directory for the rootless BuildKit job's state (default: a
#                        Docker volume per job). Not a tmpfs: unprivileged overlayfs on tmpfs
#                        refuses directory renames (EXDEV) and apt/dpkg fail; an ext4 on a
#                        RAM-backed loop device works
#   CI_LOCAL_DEPLOY_TOOLS=1  build deploy/ci/deploy-runner.Dockerfile's tools target as
#                        <prefix>deploy-tools:local and make it the DEPLOY_IMAGE (the runner
#                        uses local images): 0.15 GB instead of alpine/k8s's 1.3 GB
#   AGENTK_IMAGE         agentk image the node pulls (default registry.gitlab.com's v19.4.1)
#   AGENTK_BINARY        build a local agentk image from this binary instead (no pull)
#   GITLAB_AGENT_CHART   the gitlab-agent chart: a directory or .tgz (default: v2.32.0's
#                        source archive from gitlab.com)
#   GITLAB_MEMORY, GITLAB_TMPFS, K3S_TMPFS, RUNNER_SHM   sizes (7g, 6g, 6g, 8g)
#
# GitLab's and k3s's state live in tmpfs (RAM): about 4.5 GB of memory for GitLab and 2-3 GB
# for k3s with both environments; the dind service's storage and Trivy's database are tmpfs
# per job too. Disk: the images (gitlab-ce alone takes 5.4 GB with Docker's containerd image
# store), each job's checkout, and BuildKit's state unless CI_LOCAL_BUILDKIT_DIR says where.
# RUNNER_SHM sizes the dind tmpfs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFIX="${CI_LOCAL_PREFIX:-ci-local-}"
PORT="${CI_LOCAL_PORT:-8910}"
WEB_PORT="$PORT"
REGISTRY_PORT=$((PORT + 1))
K3S_API_PORT=$((PORT + 3))
K3S_HTTP_PORT=$((PORT + 4))
DIR="${CI_LOCAL_DIR:-$REPO_ROOT/.ci-local/${PREFIX%-}}"
MIRROR="${CI_LOCAL_MIRROR:-docker.io}"
EXTRA_CA="${CI_LOCAL_EXTRA_CA-${SSL_CERT_FILE:-}}"

NET="${PREFIX}net"
GITLAB="${PREFIX}gitlab"
RUNNER="${PREFIX}runner"
K3S="${PREFIX}k3s"
GITLAB_HOST="$GITLAB"
GITLAB_URL="https://$GITLAB_HOST:$WEB_PORT"
REGISTRY_HOST="$GITLAB_HOST:$REGISTRY_PORT"
PROJECT_PATH="platform/soundings"
# The environments' hosts: network aliases of the k3s node, served by its Traefik ingress
# (scripts/ci-local/values/<env>.yaml name them in baseUrls).
STAGING_HOST="staging.soundings.test"
PRODUCTION_HOST="production.soundings.test"

GITLAB_IMAGE="${GITLAB_IMAGE:-$MIRROR/gitlab/gitlab-ce:19.4.1-ce.0}"
RUNNER_IMAGE="${RUNNER_IMAGE:-$MIRROR/gitlab/gitlab-runner:v19.4.1}"
RUNNER_HELPER_IMAGE="${RUNNER_HELPER_IMAGE:-$MIRROR/gitlab/gitlab-runner-helper:x86_64-v19.4.1}"
K3S_IMAGE="${K3S_IMAGE:-$MIRROR/rancher/k3s:v1.31.4-k3s1}"
HELM_IMAGE="${HELM_IMAGE:-$MIRROR/alpine/helm:3.16.2}"
AGENTK_IMAGE="${AGENTK_IMAGE:-registry.gitlab.com/gitlab-org/cluster-integration/gitlab-agent/agentk:v19.4.1}"
AGENTK_BINARY="${AGENTK_BINARY:-}"
GITLAB_AGENT_CHART="${GITLAB_AGENT_CHART:-}"
GITLAB_MEMORY="${GITLAB_MEMORY:-7g}"
GITLAB_TMPFS="${GITLAB_TMPFS:-6g}"
K3S_TMPFS="${K3S_TMPFS:-6g}"
RUNNER_SHM="${RUNNER_SHM:-8g}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}" >&2; exit 2; }

running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
random() { local v; v="$(head -c 120 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"; printf '%s' "${v:0:$1}"; }
token() { cat "$DIR/token" 2>/dev/null || die "no admin token yet (run: $0 bootstrap)"; }

# curl to GitLab from the host: the published port, GitLab's name resolved to 127.0.0.1,
# the throwaway CA, never through a proxy.
gl_curl() {
  curl -sS --noproxy '*' --cacert "$DIR/tls/ca.crt" \
    --resolve "$GITLAB_HOST:$WEB_PORT:127.0.0.1" --resolve "$GITLAB_HOST:$REGISTRY_PORT:127.0.0.1" "$@"
}
api() { # METHOD path [curl args]
  local method="$1" path="$2"
  shift 2
  gl_curl --fail-with-body -X "$method" -H "PRIVATE-TOKEN: $(token)" "$GITLAB_URL/api/v4$path" "$@"
}
project_id() {
  [ -s "$DIR/project-id" ] || die "no project yet (run: $0 project)"
  cat "$DIR/project-id"
}
papi() { local method="$1" path="$2"; shift 2; api "$method" "/projects/$(project_id)$path" "$@"; }
graphql() { # query
  gl_curl --fail-with-body -H "Authorization: Bearer $(token)" -H 'Content-Type: application/json' \
    --data "$(jq -n --arg q "$1" '{query: $q}')" "$GITLAB_URL/api/graphql"
}

kc() { docker exec -i "$K3S" kubectl "$@"; }

# git against GitLab from the host (same name resolution and CA as gl_curl).
gl_git() {
  # GIT_SSL_CAINFO (set in some environments) would win over http.sslCAInfo.
  GIT_SSL_CAINFO="$DIR/tls/ca.crt" NO_PROXY="${NO_PROXY:-},$GITLAB_HOST" no_proxy="${no_proxy:-},$GITLAB_HOST" \
    git -C "$DIR/repo" -c http.sslCAInfo="$DIR/tls/ca.crt" \
    -c "http.curloptResolve=$GITLAB_HOST:$WEB_PORT:127.0.0.1" "$@"
}

# --- ca: a throwaway CA and GitLab's certificate (web, KAS and registry share it) -----------
cmd_ca() {
  mkdir -p "$DIR/tls"
  printf '*\n' >"$REPO_ROOT/.ci-local/.gitignore" 2>/dev/null || true
  if [ -s "$DIR/tls/gitlab.crt" ]; then
    log "CA exists ($DIR/tls)"
  else
    log "creating a throwaway CA and a certificate for $GITLAB_HOST"
    (
      cd "$DIR/tls"
      umask 077
      openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt -days 14 \
        -subj "/CN=${PREFIX}throwaway-ca" -addext basicConstraints=critical,CA:TRUE \
        -addext keyUsage=critical,keyCertSign,cRLSign 2>/dev/null
      openssl req -newkey rsa:2048 -nodes -keyout gitlab.key -out gitlab.csr -subj "/CN=$GITLAB_HOST" 2>/dev/null
      printf 'subjectAltName=DNS:%s,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n' \
        "$GITLAB_HOST" >ext.cnf
      openssl x509 -req -in gitlab.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 14 \
        -extfile ext.cnf -out gitlab.crt 2>/dev/null
      rm -f gitlab.csr ext.cnf
      chmod 644 ca.crt gitlab.crt gitlab.key
    )
  fi
  # What jobs, the runner, BuildKit and k3s trust: the throwaway CA plus CI_LOCAL_EXTRA_CA
  # (the pipeline's CI_BUILD_CA).
  { cat "$DIR/tls/ca.crt"; [ -z "$EXTRA_CA" ] || [ ! -f "$EXTRA_CA" ] || cat "$EXTRA_CA"; } >"$DIR/tls/ca-bundle.crt"
}

# --- gitlab: GitLab CE on https, data in tmpfs ------------------------------------------------
cmd_gitlab() {
  [ -s "$DIR/tls/gitlab.crt" ] || cmd_ca
  docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
  if running "$GITLAB"; then
    log "GitLab is running ($GITLAB_URL)"
  else
    docker rm -f "$GITLAB" >/dev/null 2>&1 || true
    [ -s "$DIR/root-password" ] || (umask 077 && random 32 >"$DIR/root-password")
    local config
    # The memory-constrained settings of GitLab's docs (Linux package
    # doc/settings/memory_constrained_envs.md); KAS is on by default at /-/kubernetes-agent/.
    config="external_url '$GITLAB_URL'
registry_external_url 'https://$REGISTRY_HOST'
letsencrypt['enable'] = false
gitlab_rails['initial_root_password'] = '$(cat "$DIR/root-password")'
gitlab_rails['usage_ping_enabled'] = false
gitlab_rails['monitoring_whitelist'] = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']
puma['worker_processes'] = 0
sidekiq['concurrency'] = 10
prometheus_monitoring['enable'] = false
gitlab_rails['env'] = { 'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000' }
gitaly['env'] = { 'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000', 'GITALY_COMMAND_SPAWN_MAX_PARALLEL' => '2' }"
    # Writable copies: reconfigure moves and links the trusted certificates.
    rm -rf "$DIR/gitlab-ssl" "$DIR/gitlab-trusted-certs"
    mkdir -p "$DIR/gitlab-ssl" "$DIR/gitlab-trusted-certs"
    cp "$DIR/tls/gitlab.crt" "$DIR/gitlab-ssl/$GITLAB_HOST.crt"
    cp "$DIR/tls/gitlab.key" "$DIR/gitlab-ssl/$GITLAB_HOST.key"
    cp "$DIR/tls/ca.crt" "$DIR/gitlab-trusted-certs/${PREFIX}ca.crt"
    log "starting GitLab ($GITLAB_IMAGE) at $GITLAB_URL, registry $REGISTRY_HOST"
    docker run -d --name "$GITLAB" --hostname "$GITLAB_HOST" --network "$NET" \
      -p "127.0.0.1:$WEB_PORT:$WEB_PORT" -p "127.0.0.1:$REGISTRY_PORT:$REGISTRY_PORT" \
      --memory "$GITLAB_MEMORY" --shm-size 256m \
      --tmpfs /etc/gitlab:rw,size=64m --tmpfs "/var/opt/gitlab:rw,exec,size=$GITLAB_TMPFS" \
      --tmpfs /var/log/gitlab:rw,size=1g \
      -v "$DIR/gitlab-ssl:/etc/gitlab/ssl" -v "$DIR/gitlab-trusted-certs:/etc/gitlab/trusted-certs" \
      -e GITLAB_OMNIBUS_CONFIG="$config" "$GITLAB_IMAGE" >/dev/null
  fi
  log "waiting for GitLab's readiness (about 5 minutes on a first start)"
  local deadline=$((SECONDS + ${GITLAB_WAIT:-1200})) code
  until code="$(gl_curl -o /dev/null -w '%{http_code}' "$GITLAB_URL/-/readiness" 2>/dev/null)" && [ "$code" = 200 ]; do
    running "$GITLAB" || { docker logs --tail 40 "$GITLAB" >&2; die "GitLab stopped"; }
    [ $SECONDS -lt $deadline ] || die "GitLab not ready after ${GITLAB_WAIT:-1200} s (docker logs $GITLAB)"
    sleep 10
  done
  log "GitLab is ready: $GITLAB_URL (root / $DIR/root-password)"
}

# --- bootstrap: an admin token (Rails console; the API has no way to make the first one) -----
cmd_bootstrap() {
  if [ -s "$DIR/token" ] && api GET /user >/dev/null 2>&1; then
    log "admin token works"
    return
  fi
  log "creating an admin personal access token (gitlab-rails runner, about a minute)"
  local out
  out="$(docker exec "$GITLAB" gitlab-rails runner "
    t = User.find_by_username('root').personal_access_tokens.create!(
      name: 'ci-local', scopes: %w[api sudo create_runner k8s_proxy], expires_at: 7.days.from_now)
    puts 'TOKEN=' + t.token")"
  (umask 077 && sed -n 's/^TOKEN=//p' <<<"$out" | tail -n 1 >"$DIR/token")
  api GET /user >/dev/null || die "the new token doesn't work"
}

# --- project: group, project, protected tags, variables, deploy token, agents ---------------
upsert_variable() { # key value [environment scope] [type]; value @<file> reads a file
  local key="$1" value="$2" scope="${3:-*}" type="${4:-env_var}" data
  data="value=$value"
  [[ "$value" != @* ]] || data="value@${value#@}"
  if papi GET "/variables/$key?filter%5Benvironment_scope%5D=$(jq -rn --arg s "$scope" '$s|@uri')" >/dev/null 2>&1; then
    papi PUT "/variables/$key?filter%5Benvironment_scope%5D=$(jq -rn --arg s "$scope" '$s|@uri')" \
      --data-urlencode "$data" --data-urlencode "variable_type=$type" >/dev/null
  else
    papi POST /variables --data-urlencode "key=$key" --data-urlencode "$data" \
      --data-urlencode "environment_scope=$scope" --data-urlencode "variable_type=$type" \
      --data-urlencode "raw=true" >/dev/null
  fi
}

cmd_project() {
  local gid pid
  gid="$(api GET "/groups/platform" 2>/dev/null | jq -r '.id // empty' || true)"
  [ -n "$gid" ] || gid="$(api POST /groups --data name=platform --data path=platform --data visibility=private | jq -r .id)"
  pid="$(api GET "/projects/$(jq -rn --arg p "$PROJECT_PATH" '$p|@uri')" 2>/dev/null | jq -r '.id // empty' || true)"
  if [ -z "$pid" ]; then
    log "creating $PROJECT_PATH"
    pid="$(api POST /projects --data name=soundings --data path=soundings --data "namespace_id=$gid" \
      --data visibility=private --data initialize_with_readme=false | jq -r .id)"
  fi
  printf '%s\n' "$pid" >"$DIR/project-id"
  # Settings > CI/CD > General pipelines: "Prevent outdated deployment jobs" and job retries
  # for rollback deployments (the operator guide's settings), and a timeout for cold builds.
  papi PUT "" --data ci_forward_deployment_enabled=true --data ci_forward_deployment_rollback_allowed=true \
    --data build_timeout=7200 >/dev/null
  # Protected tags v* (create: Maintainers); main is protected by default once pushed.
  papi GET "/protected_tags/v%2A" >/dev/null 2>&1 ||
    papi POST /protected_tags --data-urlencode 'name=v*' --data create_access_level=40 >/dev/null

  log "CI/CD variables"
  upsert_variable REGISTRY_MIRROR "$MIRROR"
  upsert_variable CI_BUILD_CA "@$DIR/tls/ca-bundle.crt" '*' file
  upsert_variable SOUNDINGS_DEPLOY "staging production"
  upsert_variable STAGING_URL "http://$STAGING_HOST"
  upsert_variable PRODUCTION_URL "http://$PRODUCTION_HOST"
  local env
  for env in staging production; do
    upsert_variable DEPLOY_VALUES \
      "deploy/environments/$env.values.yaml deploy/environments/k3s.values.yaml scripts/ci-local/values/$env.yaml" "$env"
  done
  upsert_variable HELM_TIMEOUT 5m
  # Trivy's database in the runner's tmpfs instead of the job's checkout volume (disk).
  upsert_variable TRIVY_CACHE_DIR /trivy-cache
  if [ "${CI_LOCAL_DEPLOY_TOOLS:-}" = 1 ]; then
    if ! docker image inspect "${PREFIX}deploy-tools:local" >/dev/null 2>&1; then
      log "building ${PREFIX}deploy-tools:local (deploy/ci/deploy-runner.Dockerfile, target tools)"
      docker build -q -f "$REPO_ROOT/deploy/ci/deploy-runner.Dockerfile" --target tools \
        -t "${PREFIX}deploy-tools:local" "$REPO_ROOT/deploy/ci" >/dev/null
    fi
    upsert_variable DEPLOY_IMAGE "${PREFIX}deploy-tools:local"
  fi
  local pair
  IFS=';' read -r -a pairs <<<"${CI_LOCAL_VARIABLES:-}"
  for pair in ${pairs[@]+"${pairs[@]}"}; do
    [ -n "$pair" ] || continue
    upsert_variable "${pair%%=*}" "${pair#*=}"
  done

  # A deploy token the cluster pulls with (the operator guide's soundings-registry Secret).
  if [ ! -s "$DIR/deploy-token.json" ]; then
    (umask 077 && papi POST /deploy_tokens --data name=k3s-pull --data 'scopes[]=read_registry' >"$DIR/deploy-token.json")
  fi

  local agent id
  for env in staging production; do
    agent="soundings-$env"
    id="$(papi GET /cluster_agents | jq -r --arg n "$agent" '.[] | select(.name == $n) | .id')"
    [ -n "$id" ] || id="$(papi POST /cluster_agents --data "name=$agent" | jq -r .id)"
    if [ ! -s "$DIR/agent-$env.token" ]; then
      (umask 077 && papi POST "/cluster_agents/$id/tokens" --data name=k3s | jq -r .token >"$DIR/agent-$env.token")
    fi
  done
  log "project $PROJECT_PATH (id $pid): $GITLAB_URL/$PROJECT_PATH"
}

# --- push / bump / tag: a snapshot of the working tree in a local copy with its own history --
push_options() {
  local opts=() kv
  [ "${CD_ONLY:-}" != 1 ] || opts+=(-o ci.variable=CD_ONLY=1)
  for kv in ${CI_LOCAL_PUSH_VARS:-}; do opts+=(-o "ci.variable=$kv"); done
  printf '%s\n' ${opts[@]+"${opts[@]}"}
}

cmd_push() {
  local msg="" sync=1 branch=main
  while [ $# -gt 0 ]; do
    case "$1" in
      -m) msg="$2"; shift 2 ;;
      --no-sync) sync=0; shift ;;
      *) branch="$1"; shift ;;
    esac
  done
  if [ ! -d "$DIR/repo/.git" ]; then
    git init -q -b main "$DIR/repo"
    git -C "$DIR/repo" config user.name "ci-local"
    git -C "$DIR/repo" config user.email "ci-local@example.invalid"
    git -C "$DIR/repo" remote add origin "https://oauth2:$(token)@$GITLAB_HOST:$WEB_PORT/$PROJECT_PATH.git"
  fi
  if [ "$sync" = 1 ]; then
    find "$DIR/repo" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    local head dirty paths=()
    read -r -a paths <<<"${CI_LOCAL_PATHS:-}"
    if [ ${#paths[@]} -gt 0 ]; then
      git -C "$REPO_ROOT" archive HEAD | tar -xf - -C "$DIR/repo"
      (cd "$DIR/repo" && for f in "${paths[@]}"; do rm -rf "./$f"; done)
    fi
    (cd "$REPO_ROOT" && git ls-files -z -co --exclude-standard -- ${paths[@]+"${paths[@]}"} |
      while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done |
      tar --null -T - -cf -) | tar -xf - -C "$DIR/repo"
    head="$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD)"
    dirty="$(git -C "$REPO_ROOT" status --porcelain -- ${paths[@]+"${paths[@]}"} | wc -l | tr -d ' ')"
    msg="${msg:-snapshot of $(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)@$head (${dirty} uncommitted paths${paths[*]:+ in: ${paths[*]}})}"
  fi
  git -C "$DIR/repo" add -A
  git -C "$DIR/repo" commit -q --allow-empty -m "${msg:-ci-local change}"
  local sha opts
  sha="$(git -C "$DIR/repo" rev-parse HEAD)"
  mapfile -t opts < <(push_options)
  log "pushing ${sha:0:8} to $branch ${opts[*]}"
  gl_git push -q ${opts[@]+"${opts[@]}"} origin "HEAD:refs/heads/$branch"
  wait_pipeline_for "$sha"
}

wait_pipeline_for() { # sha: print the pipeline id once GitLab created it
  local id="" deadline=$((SECONDS + 120))
  while [ -z "$id" ] && [ $SECONDS -lt $deadline ]; do
    sleep 3
    id="$(papi GET "/pipelines?sha=$1&order_by=id&sort=desc" | jq -r '.[0].id // empty')"
  done
  [ -n "$id" ] || die "no pipeline for $1"
  log "pipeline $id: $GITLAB_URL/$PROJECT_PATH/-/pipelines/$id"
  printf '%s\n' "$id"
}

cmd_bump() { # X.Y.Z: what the release commit changes (docs/operator-guide.md "Releases")
  local v="${1:?version X.Y.Z}"
  [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be X.Y.Z"
  [ -d "$DIR/repo/.git" ] || die "push a snapshot first"
  sed -i "0,/^version = \".*\"/s//version = \"$v\"/" "$DIR/repo/backend/pyproject.toml"
  awk -v v="$v" '/^name = "soundings"$/ { print; f = 1; next } f && /^version = / { print "version = \"" v "\""; f = 0; next } { print }' \
    "$DIR/repo/backend/uv.lock" >"$DIR/repo/backend/uv.lock.new" && mv "$DIR/repo/backend/uv.lock.new" "$DIR/repo/backend/uv.lock"
  sed -i -E "s/^version: .*/version: $v/; s/^appVersion: .*/appVersion: \"$v\"/" "$DIR/repo/deploy/helm/Chart.yaml"
  (cd "$DIR/repo" && "$DIR/repo/scripts/deploy.sh" check-release "v$v")
  cmd_push --no-sync -m "release $v"
}

cmd_tag() {
  local tag="${1:?tag vX.Y.Z}" opts sha
  gl_git tag -a "$tag" -m "Soundings ${tag#v}"
  sha="$(git -C "$DIR/repo" rev-parse HEAD)"
  mapfile -t opts < <(push_options)
  log "pushing tag $tag (${sha:0:8}) ${opts[*]}"
  gl_git push -q ${opts[@]+"${opts[@]}"} origin "refs/tags/$tag"
  local id="" deadline=$((SECONDS + 120))
  while [ -z "$id" ] && [ $SECONDS -lt $deadline ]; do
    sleep 3
    id="$(papi GET "/pipelines?ref=$tag&order_by=id&sort=desc" | jq -r '.[0].id // empty')"
  done
  [ -n "$id" ] || die "no pipeline for $tag"
  log "pipeline $id: $GITLAB_URL/$PROJECT_PATH/-/pipelines/$id"
  printf '%s\n' "$id"
}

# --- probe: what a CI job reaches through each agent, on a protected and an unprotected ref --
cmd_probe() {
  [ -d "$DIR/repo/.git" ] || die "push a snapshot first"
  local branch protected ids=()
  for branch in ci-local-probe-protected ci-local-probe-unprotected; do
    protected=0
    [ "$branch" != ci-local-probe-protected ] || protected=1
    if [ "$protected" = 1 ] && ! papi GET "/protected_branches/$branch" >/dev/null 2>&1; then
      papi POST /protected_branches --data "name=$branch" --data push_access_level=40 --data merge_access_level=40 \
        --data allow_force_push=true >/dev/null
    fi
    git -C "$DIR/repo" checkout -q -B "$branch" main
    cp "$DIR/repo/scripts/ci-local/agent-probe.gitlab-ci.yml" "$DIR/repo/.gitlab-ci.yml"
    git -C "$DIR/repo" add -A
    git -C "$DIR/repo" commit -q --allow-empty -m "agent probe ($branch)"
    gl_git push -q -f origin "HEAD:refs/heads/$branch"
    ids+=("$(wait_pipeline_for "$(git -C "$DIR/repo" rev-parse HEAD)")")
    git -C "$DIR/repo" checkout -q main
  done
  local id
  for id in "${ids[@]}"; do cmd_wait "$id" || true; done
  for id in "${ids[@]}"; do
    papi GET "/pipelines/$id/jobs?per_page=50" | jq -r '.[] | "\(.id) \(.name)"' | while read -r job name; do
      printf '\n===== pipeline %s, %s =====\n' "$id" "$name"
      # Trace lines start with a timestamp and a stream marker (GitLab 17+).
      papi GET "/jobs/$job/trace" | sed -n 's/^[0-9T:.Z-]* [0-9A-Z+]* \{0,1\}\(PROBE .*\)$/\1/p'
    done
  done
}

# --- runner: Docker executor on this Docker daemon ------------------------------------------
write_runner_config() { # mode
  local mode="$1" privileged=false
  [ "$mode" != privileged ] || privileged=true
  mkdir -p "$DIR/runner"
  # rootless: no privileged containers; the rootless BuildKit job needs seccomp and AppArmor
  #   unconfined to create its user namespace (the operator guide's runner settings).
  # privileged: for IMAGE_BUILDER=dind and the dind test jobs.
  # No cache volumes (each job's checkout is a temporary volume); the dind service's storage
  # is a tmpfs, gone with the job; BuildKit's state: CI_LOCAL_BUILDKIT_DIR or a volume.
  local volumes=() host
  [ -z "${CI_LOCAL_BUILDKIT_DIR:-}" ] || volumes+=("\"${CI_LOCAL_BUILDKIT_DIR}:/home/user/.local/share/buildkit\"")
  if [ "$mode" = privileged ]; then
    # The dind service's daemon pulls the buildx builder image from the mirror and talks to
    # GitLab's registry: it trusts the CA through certs.d (runner volumes reach services).
    # (One directory: a volume spec can't name host:port paths.)
    for host in "${MIRROR/docker.io/registry-1.docker.io}" "$REGISTRY_HOST"; do
      mkdir -p "$DIR/runner/certs.d/$host"
      cp "$DIR/tls/ca-bundle.crt" "$DIR/runner/certs.d/$host/ca.crt"
    done
    volumes+=("\"$DIR/runner/certs.d:/etc/docker/certs.d:ro\"")
  fi
  local joined
  joined="$(IFS=,; printf '%s' "${volumes[*]}")"
  cat >"$DIR/runner/config.toml" <<TOML
concurrent = ${RUNNER_CONCURRENT:-2}
check_interval = 3
shutdown_timeout = 0

[[runners]]
  name = "${PREFIX}docker-$mode"
  url = "$GITLAB_URL"
  token = "$(cat "$DIR/runner.token")"
  executor = "docker"
  request_concurrency = 2
  tls-ca-file = "/etc/gitlab-runner/ca.crt"
  [runners.docker]
    image = "$MIRROR/library/alpine:3.20"
    helper_image = "$RUNNER_HELPER_IMAGE"
    privileged = $privileged
    security_opt = ["seccomp:unconfined", "apparmor:unconfined"]
    network_mode = "$NET"
    pull_policy = ["if-not-present"]
    disable_cache = true
    volumes = [$joined]
    shm_size = 268435456
    # Trivy's database (about 1 GB unpacked; the TRIVY_CACHE_DIR variable points here).
    [runners.docker.tmpfs]
      "/trivy-cache" = "rw,exec,size=3g,mode=1777"
    [runners.docker.services_tmpfs]
      "/var/lib/docker" = "rw,exec,size=$RUNNER_SHM"
TOML
  cp "$DIR/tls/ca-bundle.crt" "$DIR/runner/ca.crt"
  printf '%s\n' "$mode" >"$DIR/runner/mode"
}

cmd_runner() {
  if [ ! -s "$DIR/runner.token" ]; then
    log "registering an instance runner (POST /user/runners)"
    # Tagged soundings-deploy too (the deploy jobs' DEPLOY_RUNNER_TAG): one runner plays
    # both parts here; a site gives the deploy jobs a protected runner of their own.
    (umask 077 && api POST /user/runners --data runner_type=instance_type --data run_untagged=true \
      --data tag_list=soundings-deploy --data "description=${PREFIX}docker" | jq -r .token >"$DIR/runner.token")
  fi
  write_runner_config "$(cat "$DIR/runner/mode" 2>/dev/null || echo "${CI_LOCAL_RUNNER_MODE:-rootless}")"
  if ! running "$RUNNER"; then
    docker rm -f "$RUNNER" >/dev/null 2>&1 || true
    docker run -d --name "$RUNNER" --network "$NET" --restart unless-stopped \
      -v /var/run/docker.sock:/var/run/docker.sock -v "$DIR/runner:/etc/gitlab-runner" \
      "$RUNNER_IMAGE" >/dev/null
  fi
  log "runner $RUNNER ($(cat "$DIR/runner/mode")) is running"
}

cmd_runner_mode() {
  case "${1:-}" in rootless | privileged) ;; *) die "runner-mode rootless|privileged" ;; esac
  write_runner_config "$1"
  log "runner switched to $1 (the runner reloads config.toml by itself)"
}

# --- k3s: one node on the ci-local network, state in tmpfs, pulling from GitLab's registry ---
cmd_k3s() {
  if running "$K3S"; then
    log "k3s is running"
  else
    docker rm -f "$K3S" >/dev/null 2>&1 || true
    mkdir -p "$DIR/k3s"
    cp "$DIR/tls/ca-bundle.crt" "$DIR/k3s/ca.crt"
    {
      printf 'mirrors:\n  docker.io:\n    endpoint:\n      - https://%s\n' "${MIRROR/docker.io/registry-1.docker.io}"
      printf 'configs:\n'
      local host
      for host in "${MIRROR/docker.io/registry-1.docker.io}" "$REGISTRY_HOST"; do
        printf '  "%s":\n    tls:\n      ca_file: /etc/ci-local/ca.crt\n' "$host"
      done
    } >"$DIR/k3s/registries.yaml"
    # k3s's containerd config (containerd 1.7) with discard_unpacked_layers (half the image
    # storage) and restrict_oom_score_adj (some VM sandboxes refuse negative values).
    cat >"$DIR/k3s/config.toml.tmpl" <<'TOML'
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
  discard_unpacked_layers = true

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
    log "starting k3s ($K3S_IMAGE): API 127.0.0.1:$K3S_API_PORT, ingress 127.0.0.1:$K3S_HTTP_PORT and $STAGING_HOST, $PRODUCTION_HOST in $NET"
    # The template goes in after the tmpfs is mounted, hence the shell entrypoint.
    docker create --name "$K3S" --hostname "$K3S" --privileged --network "$NET" \
      --network-alias "$STAGING_HOST" --network-alias "$PRODUCTION_HOST" \
      --tmpfs /run --tmpfs /var/run --tmpfs "/var/lib/rancher/k3s:rw,exec,size=$K3S_TMPFS" \
      --tmpfs /var/lib/kubelet:rw,exec --tmpfs /var/lib/cni:rw,exec --tmpfs /var/log:rw \
      -p "127.0.0.1:$K3S_API_PORT:6443" -p "127.0.0.1:$K3S_HTTP_PORT:80" \
      -v "$DIR/k3s:/etc/ci-local:ro" \
      --entrypoint /bin/sh "$K3S_IMAGE" -c '
        mkdir -p /var/lib/rancher/k3s/agent/etc/containerd &&
        cp /etc/ci-local/config.toml.tmpl /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl &&
        exec /bin/k3s server --disable=metrics-server --private-registry=/etc/ci-local/registries.yaml \
          "--kubelet-arg=eviction-hard=imagefs.available<256Mi,nodefs.available<256Mi" \
          --tls-san=127.0.0.1 --write-kubeconfig-mode=644' >/dev/null
    docker start "$K3S" >/dev/null
  fi
  local deadline=$((SECONDS + 300))
  until docker exec "$K3S" kubectl get nodes 2>/dev/null | grep -q ' Ready '; do
    [ $SECONDS -lt $deadline ] || { docker logs --tail 30 "$K3S" >&2; die "k3s did not become ready"; }
    sleep 3
  done
  until kc -n kube-system get deploy/coredns deploy/traefik >/dev/null 2>&1; do
    [ $SECONDS -lt $deadline ] || die "k3s system deployments did not appear"
    sleep 3
  done
  kc -n kube-system rollout status deploy/coredns --timeout=240s >/dev/null
  kc -n kube-system rollout status deploy/traefik --timeout=240s >/dev/null
  docker exec "$K3S" cat /etc/rancher/k3s/k3s.yaml >"$DIR/kubeconfig.internal"
  chmod 600 "$DIR/kubeconfig.internal"
  log "k3s is ready"
}

# helm in a container that shares the k3s node's network (the in-cluster kubeconfig works);
# the chart, the repo's deploy/ files and the CA travel through stdin.
ci_helm() { # chart-dir helm-args...
  local chart="$1"
  shift
  tar -cf - -C "$(dirname "$chart")" "$(basename "$chart")" -C "$REPO_ROOT" deploy/gitlab-agent \
    -C "$DIR" kubeconfig.internal tls/ca.crt |
    docker run --rm -i --network "container:$K3S" -e KUBECONFIG=/work/kubeconfig.internal \
      --entrypoint sh "$HELM_IMAGE" -c 'mkdir -p /work && cd /work && tar -xf - && exec helm "$@"' helm "$@"
}

agent_chart() { # prints the chart directory
  local dir="$DIR/gitlab-agent-chart"
  if [ -n "$GITLAB_AGENT_CHART" ] && [ -d "$GITLAB_AGENT_CHART" ]; then
    printf '%s\n' "$GITLAB_AGENT_CHART"
    return
  fi
  if [ ! -f "$dir/gitlab-agent/Chart.yaml" ]; then
    rm -rf "$dir" && mkdir -p "$dir/gitlab-agent"
    if [ -n "$GITLAB_AGENT_CHART" ]; then
      tar -xzf "$GITLAB_AGENT_CHART" -C "$dir/gitlab-agent" --strip-components 1
    else
      log "downloading the gitlab-agent chart v2.32.0 (source archive from gitlab.com)"
      curl -sS --fail --max-time 120 -o "$dir/chart.tar.gz" \
        "https://gitlab.com/api/v4/projects/gitlab-org%2Fcharts%2Fgitlab-agent/repository/archive.tar.gz?sha=v2.32.0"
      tar -xzf "$dir/chart.tar.gz" -C "$dir/gitlab-agent" --strip-components 1
      # The source has the conditional ingress-nginx dependency (off by default) but not
      # its chart; the packaged chart on charts.gitlab.io carries it.
      sed -i '/^dependencies:/,$d' "$dir/gitlab-agent/Chart.yaml"
    fi
  fi
  printf '%s\n' "$dir/gitlab-agent"
}

# --- agents: what deploy/gitlab-agent/README.md tells operators to do -----------------------
cmd_agents() {
  running "$K3S" || die "k3s is not running (run: $0 k3s)"
  local repo tag
  if [ -n "$AGENTK_BINARY" ]; then
    repo="${PREFIX}agentk"
    tag=local
    if ! docker image inspect "$repo:$tag" >/dev/null 2>&1; then
      log "building $repo:$tag from $AGENTK_BINARY"
      local ctx
      ctx="$(mktemp -d)"
      cp "$AGENTK_BINARY" "$ctx/agentk"
      mkdir -m 1777 "$ctx/tmp"
      # Like the official image (distroless, nonroot): a static binary, a writable /tmp as
      # HOME for its kube cache.
      printf 'FROM scratch\nCOPY agentk /usr/bin/agentk\nCOPY tmp /tmp\nENV HOME=/tmp\nUSER 65532:65532\nENTRYPOINT ["/usr/bin/agentk"]\n' >"$ctx/Dockerfile"
      docker build -q -t "$repo:$tag" "$ctx" >/dev/null
      rm -rf "$ctx"
    fi
    docker save "$repo:$tag" | docker exec -i "$K3S" ctr -n k8s.io images import - >/dev/null
    repo="docker.io/library/$repo"
  else
    repo="${AGENTK_IMAGE%:*}"
    tag="${AGENTK_IMAGE##*:}"
  fi

  log "cluster setup: deploy/environments/cluster-setup.yaml and deploy/gitlab-agent/rbac.yaml"
  kc apply -f - <"$REPO_ROOT/deploy/environments/cluster-setup.yaml" >/dev/null
  kc apply -f - <"$REPO_ROOT/deploy/gitlab-agent/rbac.yaml" >/dev/null
  local env ns user pass
  user="$(jq -r .username "$DIR/deploy-token.json")"
  pass="$(jq -r .token "$DIR/deploy-token.json")"
  for env in staging production; do
    ns="soundings-$env"
    # The Secrets the values files name (operators create them; never in the repository).
    kc -n "$ns" get secret soundings-app >/dev/null 2>&1 ||
      kc -n "$ns" create secret generic soundings-app --from-literal="secret-key=$(random 48)" >/dev/null
    kc -n "$ns" get secret soundings-break-glass >/dev/null 2>&1 ||
      kc -n "$ns" create secret generic soundings-break-glass --from-literal=username=admin \
        --from-literal="password=$(random 24)" >/dev/null
    kc -n "$ns" create secret docker-registry soundings-registry --docker-server="$REGISTRY_HOST" \
      --docker-username="$user" --docker-password="$pass" --dry-run=client -o yaml | kc apply -f - >/dev/null
    kc -n "gitlab-agent-$env" create secret generic "soundings-$env-agent-token" \
      --from-literal="token=$(cat "$DIR/agent-$env.token")" --dry-run=client -o yaml | kc apply -f - >/dev/null
  done

  local chart gitlab_ip
  chart="$(agent_chart)"
  # Pods can't use Docker's DNS: GitLab's address goes into the agent pods' /etc/hosts.
  gitlab_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$GITLAB")"
  for env in staging production; do
    log "installing agent soundings-$env (deploy/gitlab-agent/values.yaml, rbac.create=false)"
    ci_helm "$chart" upgrade --install "soundings-$env-agent" "./$(basename "$chart")" \
      --namespace "gitlab-agent-$env" -f deploy/gitlab-agent/values.yaml \
      --set "serviceAccount.name=soundings-$env-agent" --set "config.secretName=soundings-$env-agent-token" \
      --set "config.kasAddress=wss://$GITLAB_HOST:$WEB_PORT/-/kubernetes-agent/" \
      --set-file config.kasCaCert=tls/ca.crt \
      --set "image.repository=$repo" --set "image.tag=$tag" --set image.pullPolicy=IfNotPresent \
      --set replicas=1 --set "hostAliases[0].ip=$gitlab_ip" --set "hostAliases[0].hostnames[0]=$GITLAB_HOST" \
      --wait --timeout 5m >/dev/null
  done
  log "waiting for both agents to connect to KAS"
  local deadline=$((SECONDS + 300)) connected
  while :; do
    connected="$(graphql "{ project(fullPath: \"$PROJECT_PATH\") { clusterAgents { nodes { name connections { nodes { connectedAt } } } } } }" |
      jq -r '[.data.project.clusterAgents.nodes[] | select((.connections.nodes | length) > 0) | .name] | sort | join(" ")')"
    [ "$connected" != "soundings-production soundings-staging" ] || break
    [ $SECONDS -lt $deadline ] || die "agents not connected (connected: '${connected}'); kubectl -n gitlab-agent-staging logs deploy/soundings-staging-agent-gitlab-agent-v2"
    sleep 5
  done
  log "agents connected: $connected"
}

# --- github: .github/workflows/deploy-env.yml's deploy step, as a runner in the cluster -----
# A pod without any rights (ARC's default ServiceAccount, in arc-soundings-<env>) and
# KUBECONFIG_DATA from scripts/lib/ci-kubeconfig.sh (a token of soundings-ci-deployer in
# soundings-<env>, deploy/ci/arc-rbac.yaml), as the operator guide says.
# The step's script is read from the workflow file; its inputs (IMAGE_REPOSITORY,
# IMAGE_DIGEST, IMAGE_TAG, ROLLBACK_REVISION, DEPLOY_FORCE ...) come as KEY=VALUE.
# The pod runs the deploy tools image (<prefix>deploy-tools:local) in the runner image's
# place: the same script, helm and kubectl.
cmd_github() {
  local env="${1:?staging or production}" op="${2:?deploy or rollback}"
  shift 2
  local ns="arc-soundings-$env" pod="github-runner" sa=default host
  [ "$env" = production ] && host="$PRODUCTION_HOST" || host="$STAGING_HOST"
  kc apply -f - <"$REPO_ROOT/deploy/ci/arc-rbac.yaml" >/dev/null
  if ! docker exec "$K3S" ctr -n k8s.io images ls -q | grep -q "${PREFIX}deploy-tools:local"; then
    docker save "${PREFIX}deploy-tools:local" | docker exec -i "$K3S" ctr -n k8s.io images import - >/dev/null
  fi
  local traefik
  traefik="$(kc -n kube-system get svc traefik -o jsonpath='{.spec.clusterIP}')"
  kc -n "$ns" delete pod "$pod" --ignore-not-found --wait >/dev/null
  kc apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: $pod, namespace: $ns}
spec:
  serviceAccountName: $sa
  hostAliases: [{ip: "$traefik", hostnames: ["$host"]}]
  containers:
    - name: runner
      image: docker.io/library/${PREFIX}deploy-tools:local
      imagePullPolicy: Never
      command: [sleep, "3600"]
YAML
  kc -n "$ns" wait --for=condition=Ready "pod/$pod" --timeout=120s >/dev/null
  tar -cf - -C "$REPO_ROOT" scripts/deploy.sh scripts/deploy-smoke.sh scripts/ci-local/values deploy/helm \
    deploy/environments backend/app/migrations/versions | kc -n "$ns" exec -i "$pod" -- sh -c 'mkdir -p /work && tar -xf - -C /work'
  local script
  script="$(awk '/^        run: \|$/ { f = 1; next } f && /^          / { sub(/^          /, ""); print; next } f { exit }' \
    "$REPO_ROOT/.github/workflows/deploy-env.yml")"
  local vars=(GITHUB_ACTIONS=true "GITHUB_RUN_ID=ci-local-$RANDOM" RUNNER_TEMP=/tmp GITHUB_STEP_SUMMARY=/tmp/summary.md
    "OPERATION=$op" "ENVIRONMENT=$env" "DEPLOY_URL=http://$host" CI_BUILD_CA= KUBE_CONTEXT= KUBE_NAMESPACE= KUBECONFIG_DATA=
    "DEPLOY_VALUES=deploy/environments/$env.values.yaml deploy/environments/k3s.values.yaml scripts/ci-local/values/$env.yaml")
  vars+=("KUBECONFIG_DATA=$(KUBECTL="docker exec -i $K3S kubectl" "$REPO_ROOT/scripts/lib/ci-kubeconfig.sh" "$env" 1h 2>/dev/null)")
  vars+=("$@")
  log "deploy-env.yml's step: $op $env in pod $ns/$pod (ServiceAccount $sa)"
  kc -n "$ns" exec "$pod" -- env "${vars[@]}" bash -c "cd /work && { $script
}; status=\$?; echo '--- GITHUB_STEP_SUMMARY'; cat /tmp/summary.md 2>/dev/null; exit \$status"
}

# --- pipelines -------------------------------------------------------------------------------
cmd_pipelines() {
  papi GET "/pipelines?per_page=${1:-10}" |
    jq -r '.[] | [.id, .status, .ref, .sha[0:8], .source, .created_at] | @tsv'
}

jobs_table() {
  papi GET "/pipelines/$1/jobs?per_page=100&include_retried=false" |
    jq -r 'sort_by(.id) | .[] | [.id, .stage, .name, .status, ((.duration // 0) | floor | tostring) + "s"] | @tsv'
}
table() { awk -F'\t' '{ printf "%-6s %-12s %-22s %-9s %s\n", $1, $2, $3, $4, $5 }'; }
cmd_jobs() { jobs_table "${1:?pipeline id}" | table; }

cmd_wait() { # pipeline: until it finishes or waits for a person (manual)
  local id="${1:?pipeline id}" status last="" table deadline=$((SECONDS + ${CI_LOCAL_WAIT:-7200}))
  while :; do
    status="$(papi GET "/pipelines/$id" | jq -r .status)"
    table="$(jobs_table "$id")"
    if [ "$table" != "$last" ]; then
      printf '\n[%s] pipeline %s: %s\n' "$(date +%H:%M:%S)" "$id" "$status" >&2
      table <<<"$table" >&2
      last="$table"
    fi
    case "$status" in
      success | failed | canceled | skipped | manual | blocked) break ;;
    esac
    [ $SECONDS -lt $deadline ] || die "pipeline $id still $status"
    sleep 10
  done
  printf '%s\n' "$status"
  [ "$status" = success ] || [ "$status" = manual ] || [ "$status" = blocked ]
}

cmd_play() { # pipeline job-name [KEY=VALUE ...]
  local id="${1:?pipeline id}" name="${2:?job name}" job args=()
  shift 2
  job="$(papi GET "/pipelines/$id/jobs?per_page=100" | jq -r --arg n "$name" '[.[] | select(.name == $n)] | max_by(.id) | .id // empty')"
  [ -n "$job" ] || die "no job '$name' in pipeline $id"
  local kv
  for kv in "$@"; do
    args+=(--data-urlencode "job_variables_attributes[][key]=${kv%%=*}" --data-urlencode "job_variables_attributes[][value]=${kv#*=}")
  done
  papi POST "/jobs/$job/play" ${args[@]+"${args[@]}"} | jq -r '"played \(.name) (job \(.id)): \(.status)"'
}

cmd_log() { papi GET "/jobs/${1:?job id}/trace"; }

# --- guard: stop the run before it starves the machine ---------------------------------------
cmd_guard() {
  local min_disk_mb="${GUARD_MIN_DISK_MB:-1500}" min_mem_mb="${GUARD_MIN_MEM_MB:-1000}" disk mem
  log "guard: stops job containers and the runner below ${min_disk_mb} MB disk or ${min_mem_mb} MB memory"
  while :; do
    disk="$(df -Pm /var/lib/docker 2>/dev/null | awk 'NR == 2 { print $4 }')"
    mem="$(awk '/^MemAvailable:/ { print int($2 / 1024) }' /proc/meminfo)"
    if [ "${disk:-0}" -lt "$min_disk_mb" ] || [ "${mem:-0}" -lt "$min_mem_mb" ]; then
      warn "$(date +%T) disk ${disk} MB, memory ${mem} MB: stopping the runner and its jobs"
      docker stop -t 5 "$RUNNER" >/dev/null 2>&1 || true
      docker ps -q --filter "network=$NET" --filter label=com.gitlab.gitlab-runner.managed=true |
        xargs -r docker rm -f >/dev/null 2>&1 || true
    fi
    sleep "${GUARD_INTERVAL:-10}"
  done
}

cmd_status() {
  docker ps -a --filter "name=^$PREFIX" --format '{{.Names}}\t{{.Status}}' || true
  docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' "$GITLAB" "$K3S" "$RUNNER" 2>/dev/null || true
  df -h /var/lib/docker | tail -n 1
  awk '/^MemAvailable:/ { printf "memory available: %d MB\n", $2 / 1024 }' /proc/meminfo
}

cmd_down() {
  log "removing ${PREFIX}* containers, job containers and volumes, the network"
  docker ps -aq --filter "network=$NET" | xargs -r docker rm -f -v >/dev/null 2>&1 || true
  docker rm -f -v "$RUNNER" "$GITLAB" "$K3S" >/dev/null 2>&1 || true
  docker volume ls -q --filter label=com.gitlab.gitlab-runner.managed=true |
    xargs -r docker volume rm >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  if [ "${1:-}" = --images ]; then
    log "removing the images this run used"
    # Ours, then the pipeline's job images (.gitlab-ci.yml's defaults through the mirror).
    local image
    for image in "$GITLAB_IMAGE" "$RUNNER_IMAGE" "$RUNNER_HELPER_IMAGE" "${PREFIX}agentk:local" "${PREFIX}deploy-tools:local" \
      $(sed -n -E 's/^  (BUILDKIT_IMAGE|BUILDKIT_DIND_IMAGE|TRIVY_IMAGE|DEPLOY_IMAGE|GLAB_IMAGE|DOCKER_IMAGE|DIND_IMAGE): \$\{REGISTRY_MIRROR\}//p' "$REPO_ROOT/.gitlab-ci.yml" |
        sed "s#^#$MIRROR#"); do
      # name:tag@digest: Docker keeps it as name:tag and/or name@digest.
      docker image rm "$image" "${image%@*}" "${image%%:*}@${image##*@}" >/dev/null 2>&1 || true
    done
  fi
  rm -rf "$DIR"
  log "ci-local is gone (state $DIR removed)"
}

cmd_up() {
  cmd_ca
  cmd_gitlab
  cmd_bootstrap
  cmd_project
  cmd_runner
  cmd_k3s
  cmd_agents
  log "up: push the working tree with: CD_ONLY=1 $0 push"
}

ACTION="${1:-}"
[ -n "$ACTION" ] || usage
shift
mkdir -p "$DIR"
case "$ACTION" in
  up | ca | gitlab | bootstrap | project | runner | k3s | agents | push | bump | tag | probe | \
    pipelines | jobs | wait | play | log | guard | status | down)
    "cmd_$ACTION" "$@" ;;
  runner-mode) cmd_runner_mode "$@" ;;
  github) cmd_github "$@" ;;
  api) api "$@" ;;
  kubectl) kc "$@" ;;
  -h | --help | help) usage ;;
  *) die "unknown command '$ACTION' (see $0 --help)" ;;
esac
