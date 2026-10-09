#!/usr/bin/env bash
# Deploy Soundings to one environment with Helm: the one script GitLab CI, GitHub Actions
# and people use (docs/operator-guide.md "Continuous delivery", ADR 0017).
#
#   scripts/deploy.sh deploy   <env> [helm args]  helm upgrade --install --atomic --wait with
#                                                 the image pinned by digest, helm test, then
#                                                 the cluster and HTTP smoke; any failure
#                                                 leaves the previous release running
#   scripts/deploy.sh rollback <env>              helm rollback to ROLLBACK_REVISION (default:
#                                                 the revision that ran before the current
#                                                 one), refused across a migration boundary
#                                                 unless DEPLOY_FORCE=1; then test and smoke
#   scripts/deploy.sh smoke    <env>              the checks alone, against the running release
#   scripts/deploy.sh status   <env>              helm history, the deploy labels and the pods
#   scripts/deploy.sh template <env> [helm args]  helm template with the environment's values
#                                                 (no cluster; a check of the values files)
#   scripts/deploy.sh check-release <vX.Y.Z>      the tag matches the versions in the repo
#
# <env> is staging or production (any name with a deploy/environments/<env>.values.yaml).
# Needs bash, helm 3.16+, kubectl, curl, grep, sed, awk (no jq). Inputs, all environment
# variables (CI variables in both CIs, the same names):
#
#   IMAGE_REPOSITORY  registry/path of the image, no tag (deploy)
#   IMAGE_DIGEST      sha256:<64 hex> (deploy): what runs; tags are only names
#   IMAGE_TAG         the tag it was pushed as (sha-1a2b3c4d, 1.2.3): the pods' version
#                     label; for X.Y.Z the smoke also checks the app reports that version
#   KUBE_NAMESPACE    default soundings-<env>; created by operators, never by this script
#   HELM_RELEASE      default soundings
#   KUBE_CONTEXT      kubeconfig context (GitLab agent: <agent project>:soundings-<env>);
#                     default: the current context, or in-cluster credentials (ARC runner)
#   KUBECONFIG_DATA   a whole kubeconfig as text (GitHub production environment secret);
#                     written to a private temporary file for this run only
#   DEPLOY_VALUES     values files, space-separated (default deploy/environments/<env>.values.yaml)
#   DEPLOY_URL        the smoke's base URL (default: the release's first baseUrls entry)
#   HELM_TIMEOUT      default 10m (each of upgrade, test and rollback; a whole deploy can take
#                     about 7 times it, so CI job timeouts are 90 minutes); the chart's migration
#                     Job must have a shorter migrations.activeDeadlineSeconds (checked)
#   ROLLBACK_REVISION rollback target revision (default: the newest earlier revision that
#                     passed its checks and runs something else than the current one)
#   MIGRATION_HEAD    the image's newest Alembic revision (default: read from this
#                     checkout's backend/app/migrations; set it when deploying an image
#                     built from another commit)
#   DRY_RUN=1         deploy: helm upgrade --dry-run=server (the API server validates it,
#                     nothing changes); rollback: say what would happen
#   DEPLOY_FORCE=1    allow a rollback across a migration boundary, a deploy of an image
#                     with older migrations, a deploy from an older pipeline than the running
#                     revision's (or of an older X.Y.Z), and taking over a release the other
#                     CI made
#
# Another deploy in progress (a pending Helm revision): waited for, up to what one deploy
# can take (3 x HELM_TIMEOUT from its start), then refused as stale.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="$REPO_ROOT/deploy/helm"
MIGRATIONS_DIR="$REPO_ROOT/backend/app/migrations/versions"
LABEL_HEAD="soundings.io/migration-head"
LABEL_BY="soundings.io/deployed-by"
# Set on a revision that deployed but failed helm test or the smoke (the script rolled it
# back): never a rollback target, although Helm lists it as superseded.
LABEL_VERIFY="soundings.io/verify"
# The CI run that made the revision (GitLab pipeline id, GitHub run id: both only grow), so
# a deploy from an older pipeline can't replace a newer one's (GitLab's "Prevent outdated
# deployment jobs" would also fail a tag's staging deploy whenever main deployed meanwhile).
LABEL_ORDER="soundings.io/pipeline"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}" >&2
  exit 2
}

ACTION="${1:-}"
[ -n "$ACTION" ] || usage
shift
case "$ACTION" in
  deploy | rollback | smoke | status | template | check-release) ;;
  -h | --help | help) usage ;;
  *) die "unknown action '$ACTION' (deploy, rollback, smoke, status, template, check-release)" ;;
esac

# --- check-release: the tag, the app's version and the chart's version agree -------------
# The app reports the version in backend/pyproject.toml (its package metadata), so a
# release commit bumps it, backend/uv.lock (`uv lock`) and deploy/helm/Chart.yaml's
# version and appVersion to X.Y.Z before the vX.Y.Z tag is pushed.
if [ "$ACTION" = check-release ]; then
  tag="${1:-}"
  [[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]] || die "check-release needs a vX.Y.Z tag, got '${tag}'"
  want="${BASH_REMATCH[1]}"
  pyproject="$(sed -n '/^version = "/{s/^version = "\(.*\)"$/\1/p;q;}' "$REPO_ROOT/backend/pyproject.toml")"
  lock="$(awk '/^name = "soundings"$/ { found = 1; next } found && /^version = / { gsub(/"/, "", $3); print $3; exit }' "$REPO_ROOT/backend/uv.lock")"
  chart="$(sed -n 's/^version: *"\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$CHART/Chart.yaml")"
  app="$(sed -n 's/^appVersion: *"\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$CHART/Chart.yaml")"
  bad=0
  for pair in "backend/pyproject.toml version (what the app reports)=$pyproject" \
    "backend/uv.lock soundings version=$lock" "deploy/helm/Chart.yaml version=$chart" \
    "deploy/helm/Chart.yaml appVersion=$app"; do
    if [ "${pair##*=}" = "$want" ]; then
      printf '  ok  %s: %s\n' "${pair%=*}" "$want"
    else
      printf '  FAIL %s is "%s", the tag says %s\n' "${pair%=*}" "${pair##*=}" "$want" >&2
      bad=1
    fi
  done
  [ "$bad" = 0 ] || die "tag $tag doesn't match the repository: bump those to $want in a release commit (then 'uv lock' in backend/) and tag that commit"
  log "tag $tag matches the app's and the chart's version"
  exit 0
fi

ENVIRONMENT="${1:-}"
[ -n "$ENVIRONMENT" ] || usage
shift
[[ "$ENVIRONMENT" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || die "environment '$ENVIRONMENT': use a lowercase name such as staging or production"

KUBE_NAMESPACE="${KUBE_NAMESPACE:-soundings-$ENVIRONMENT}"
HELM_RELEASE="${HELM_RELEASE:-soundings}"
KUBE_CONTEXT="${KUBE_CONTEXT:-}"
DEPLOY_VALUES="${DEPLOY_VALUES:-deploy/environments/$ENVIRONMENT.values.yaml}"
DEPLOY_URL="${DEPLOY_URL:-}"
HELM_TIMEOUT="${HELM_TIMEOUT:-10m}"
ROLLBACK_REVISION="${ROLLBACK_REVISION:-}"
DRY_RUN="${DRY_RUN:-0}"
DEPLOY_FORCE="${DEPLOY_FORCE:-0}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-}"
IMAGE_DIGEST="${IMAGE_DIGEST:-}"
IMAGE_TAG="${IMAGE_TAG:-}"

# A Helm duration (10m, 1h30m, 600s) in seconds.
seconds_of() {
  local rest="$1" total=0
  [[ "$rest" =~ ^([0-9]+[hms])+$ ]] || return 1
  while [[ "$rest" =~ ^([0-9]+)([hms])(.*)$ ]]; do
    case "${BASH_REMATCH[2]}" in
      h) total=$((total + 10#${BASH_REMATCH[1]} * 3600)) ;;
      m) total=$((total + 10#${BASH_REMATCH[1]} * 60)) ;;
      s) total=$((total + 10#${BASH_REMATCH[1]})) ;;
    esac
    rest="${BASH_REMATCH[3]}"
  done
  printf '%s\n' "$total"
}
HELM_TIMEOUT_SECONDS="$(seconds_of "$HELM_TIMEOUT")" ||
  die "HELM_TIMEOUT '$HELM_TIMEOUT': use a duration such as 10m, 1h30m or 900s"

# Who is deploying: each environment is deployed by one CI (operator guide).
if [ "${GITLAB_CI:-}" = "true" ]; then
  DEPLOYED_BY=gitlab
  DEPLOY_ORIGIN="GitLab pipeline ${CI_PIPELINE_ID:-?} job ${CI_JOB_ID:-?}"
  DEPLOY_ORDER="${CI_PIPELINE_ID:-}"
elif [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  DEPLOYED_BY=github
  DEPLOY_ORIGIN="GitHub run ${GITHUB_RUN_ID:-?}"
  DEPLOY_ORDER="${GITHUB_RUN_ID:-}"
else
  DEPLOYED_BY=manual
  DEPLOY_ORIGIN="by hand ($(id -un 2>/dev/null || echo someone))"
  DEPLOY_ORDER=""
fi
[[ "$DEPLOY_ORDER" =~ ^[0-9]{1,30}$ ]] || DEPLOY_ORDER=""

values_args=()
for file in $DEPLOY_VALUES; do
  case "$file" in /*) path="$file" ;; *) path="$REPO_ROOT/$file" ;; esac
  [ -f "$path" ] || die "values file '$file' not found (DEPLOY_VALUES)"
  values_args+=(--values "$path")
done

# --- template: no cluster needed --------------------------------------------------------
image_args() {
  # registry/path split for the chart's image.registry + image.repository.
  local first="${IMAGE_REPOSITORY%%/*}" registry="" path="$IMAGE_REPOSITORY"
  if [[ "$IMAGE_REPOSITORY" == */* ]] && [[ "$first" == *.* || "$first" == *:* || "$first" == localhost ]]; then
    registry="$first"
    path="${IMAGE_REPOSITORY#*/}"
  fi
  printf '%s\n' --set-string "image.registry=$registry" --set-string "image.repository=$path" \
    --set-string "image.tag=$IMAGE_TAG" --set-string "image.digest=$IMAGE_DIGEST"
}

check_image_inputs() {
  [ -n "$IMAGE_REPOSITORY" ] || die "IMAGE_REPOSITORY is not set (registry/path of the image, without a tag)"
  [[ "$IMAGE_REPOSITORY" != *@* && "${IMAGE_REPOSITORY##*/}" != *:* ]] ||
    die "IMAGE_REPOSITORY '$IMAGE_REPOSITORY' carries a tag or digest: pass those in IMAGE_TAG and IMAGE_DIGEST"
  [[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] ||
    die "IMAGE_DIGEST must be sha256:<64 hex> (got '${IMAGE_DIGEST}'): deploys pin the image by digest"
  [[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$ ]] ||
    die "IMAGE_TAG must be the tag the image was pushed as, e.g. sha-1a2b3c4d or 1.2.3 (got '${IMAGE_TAG}')"
}

if [ "$ACTION" = template ]; then
  # Placeholders unless given, so the values files can be checked anywhere.
  IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-registry.example.internal/platform/soundings}"
  IMAGE_DIGEST="${IMAGE_DIGEST:-sha256:$(printf '0%.0s' $(seq 64))}"
  IMAGE_TAG="${IMAGE_TAG:-template}"
  check_image_inputs
  mapfile -t img < <(image_args)
  exec helm template "$HELM_RELEASE" "$CHART" --namespace "$KUBE_NAMESPACE" \
    "${values_args[@]}" "${img[@]}" "$@"
fi

# --- cluster access ---------------------------------------------------------------------
command -v helm >/dev/null || die "helm is not installed (the CI deploy images have it)"
command -v kubectl >/dev/null || die "kubectl is not installed (the CI deploy images have it)"
command -v curl >/dev/null || die "curl is not installed"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
chmod 700 "$work"
if [ -n "${KUBECONFIG_DATA:-}" ]; then
  kubeconfig_file="$work/kubeconfig"
  (umask 077 && printf '%s\n' "$KUBECONFIG_DATA" > "$kubeconfig_file")
  export KUBECONFIG="$kubeconfig_file"
fi
helm_ctx=(--namespace "$KUBE_NAMESPACE")
kube_ctx=(--namespace "$KUBE_NAMESPACE")
if [ -n "$KUBE_CONTEXT" ]; then
  helm_ctx+=(--kube-context "$KUBE_CONTEXT")
  kube_ctx+=(--context "$KUBE_CONTEXT")
fi
hl() { helm "${helm_ctx[@]}" "$@"; }
kc() { kubectl "${kube_ctx[@]}" "$@"; }

# Helm keeps each revision as a Secret (HELM_DRIVER=configmap: a ConfigMap) labelled
# owner=helm, name, version (the revision) and status; deploys add the two labels above.
store_kind="secret"
[ "${HELM_DRIVER:-secret}" != configmap ] || store_kind="configmap"
case "${HELM_DRIVER:-secret}" in secret | secrets | configmap) ;; *) die "HELM_DRIVER '${HELM_DRIVER}' is not supported here (secret or configmap)" ;; esac

# "<revision> <status>" lines, oldest first.
revisions() {
  kc get "$store_kind" -l "owner=helm,name=$HELM_RELEASE" \
    -o jsonpath='{range .items[*]}{.metadata.labels.version}{" "}{.metadata.labels.status}{"\n"}{end}' |
    sort -n
}
revision_label() { # revision label
  local key="${2//./\\.}"
  kc get "$store_kind" "sh.helm.release.v1.$HELM_RELEASE.v$1" -o "jsonpath={.metadata.labels.$key}" 2>/dev/null || true
}
deployed_revision() { revisions | awk '$2 == "deployed" { r = $1 } END { print r }'; }
pending_revision() { revisions | awk '$2 ~ /^pending/ { r = $1 " " $2 } END { print r }'; }
verify_failed() { [ "$(revision_label "$1" "$LABEL_VERIFY")" = failed ]; }
# The newer of two migration heads (zero-padded sequence numbers; empty = unknown).
newer_head() { if [[ "$1" < "$2" ]]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
# A revision that puts older content back (Helm's --atomic, the script's rollback, a manual
# rollback) gets its target's labels from Helm. Relabel it: it is this CI's now, checked
# again, made by this run, and its migration head is the database's, which a rollback never
# lowers: the newer of the target's and the one that ran (else the next deploy of older
# migrations, or a rollback further back, would no longer be refused).
label_restored() { # revision database-head
  local labels=("$LABEL_BY=$DEPLOYED_BY" "$LABEL_VERIFY-")
  [ -z "${2:-}" ] || labels+=("$LABEL_HEAD=$2")
  [ -z "$DEPLOY_ORDER" ] || labels+=("$LABEL_ORDER=$DEPLOY_ORDER")
  kc label "$store_kind" "sh.helm.release.v1.$HELM_RELEASE.v$1" "${labels[@]}" --overwrite >/dev/null 2>&1 ||
    warn "could not label revision $1 (${labels[*]})"
}
# Did a failed upgrade's migration Job leave the database alone? Only when it failed: Helm
# deletes a Job that succeeded, and one still running could yet commit (the deadline check
# below keeps it shorter than HELM_TIMEOUT). With the bundled Postgres the api pods migrate
# in an init container: assume it ran.
migration_failed() {
  [ "$(kc get jobs -l "app.kubernetes.io/instance=$HELM_RELEASE,app.kubernetes.io/component=migrate" \
    -o jsonpath='{.items[*].status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)" = True ]
}
mark_verify_failed() { # revision
  kc label "$store_kind" "sh.helm.release.v1.$HELM_RELEASE.v$1" "$LABEL_VERIFY=failed" --overwrite >/dev/null 2>&1 ||
    warn "could not label revision $1 as failed ($LABEL_VERIFY): don't roll back to it"
}
# The rollback target for <revision>: the newest older revision that deployed, passed its
# checks and runs other content. "Rollback to N" revisions (Helm's --atomic, helm rollback,
# this script) run N's content, so after an automatic rollback the target is the release
# before the one that is running again, not a copy of it.
previous_revision() {
  local failed
  failed="$(kc get "$store_kind" -l "owner=helm,name=$HELM_RELEASE,$LABEL_VERIFY=failed" \
    -o jsonpath='{range .items[*]}{.metadata.labels.version}{" "}{end}' 2>/dev/null || true)"
  hl history "$HELM_RELEASE" --max 1000 2>/dev/null | awk -F'\t' -v cur="$1" -v failed=" $failed " '
    NR == 1 { next }
    { rev = $1 + 0; status = $3; desc = $6; gsub(/ +$/, "", status); gsub(/^ +| +$/, "", desc)
      same[rev] = rev
      if (desc ~ /^Rollback to [0-9]+$/) { t = substr(desc, 13) + 0; same[rev] = (t in same) ? same[t] : t }
      st[rev] = status }
    END {
      for (r = cur - 1; r > 0; r--) {
        if (!(r in st) || st[r] != "superseded" || index(failed, " " r " ")) continue
        if (same[r] == same[cur]) continue
        print r; exit
      }
    }'
}

preflight() {
  local out
  local contexts
  contexts="$(kubectl config get-contexts -o name 2>/dev/null || true)"
  if [ -n "$KUBE_CONTEXT" ] && ! grep -qxF "$KUBE_CONTEXT" <<<"$contexts"; then
    die "no kubeconfig context '$KUBE_CONTEXT' (have: $(tr '\n' ' ' <<<"$contexts"))
  GitLab: the agent soundings-$ENVIRONMENT must be connected, and its ci_access must name this
  project and the environment '$ENVIRONMENT' (production: on a protected branch or tag)."
  fi
  # Reading the namespace's default ServiceAccount proves both that the namespace exists
  # and that this identity may read in it (namespace-scoped RBAC can't read Namespaces).
  if ! out="$(kc get serviceaccount default -o name 2>&1)"; then
    die "can't use namespace '$KUBE_NAMESPACE'${KUBE_CONTEXT:+ (context $KUBE_CONTEXT)}: $out
  Operators create the namespace and the deployer's RBAC (deploy/environments/cluster-setup.yaml)."
  fi
  [ "$ACTION" != status ] && [ "$ACTION" != smoke ] || return 0
  # Another deploy in progress (a person, the other CI's queue, a rollback job): wait for it
  # as long as one deploy can take (upgrade hooks, wait and --atomic's rollback), counted from
  # when it started; older than that, it was killed half way and needs a forced rollback.
  local pending seen="" started=0 now created limit=$((3 * HELM_TIMEOUT_SECONDS)) waited=0
  while :; do
    pending="$(pending_revision)"
    if [ -z "$pending" ]; then
      [ "$waited" = 1 ] || break
      # It is done: give it a moment to label the revision it left (Helm rewrites a
      # revision's labels from what it read when the next upgrade supersedes it).
      log "the other deploy finished"
      sleep 15
      waited=0
      continue
    fi
    local msg="release $HELM_RELEASE in $KUBE_NAMESPACE is ${pending#* } (revision ${pending%% *})"
    if [ "$ACTION" = rollback ] && [ "$DEPLOY_FORCE" = 1 ]; then
      warn "$msg; DEPLOY_FORCE=1: rolling back anyway"
      return 0
    fi
    now="$(date -u +%s)"
    if [ "$pending" != "$seen" ]; then
      # When that revision was written (its Helm Secret); unknown: from now.
      created="$(kc get "$store_kind" "sh.helm.release.v1.$HELM_RELEASE.v${pending%% *}" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null || true)"
      started="$(date -u -d "$(sed 's/T/ /; s/Z$//' <<<"$created")" +%s 2>/dev/null || echo "$now")"
      [ "$started" -le "$now" ] || started="$now"
      seen="$pending"
    fi
    if [ $((now - started)) -ge "$limit" ]; then
      die "$msg for $(((now - started) / 60)) minutes, longer than a deploy takes (3 x HELM_TIMEOUT): it was killed half way. Recover with: DEPLOY_FORCE=1 scripts/deploy.sh rollback $ENVIRONMENT"
    fi
    [ "$waited" = 1 ] || log "$msg: another deploy is running; waiting for it (at most $(((limit - now + started + 59) / 60)) minutes)"
    waited=1
    sleep 10
  done
}

# The other CI made the running release: each environment is deployed by one CI only.
guard_other_ci() {
  local current="$1" by
  [ -n "$current" ] || return 0
  by="$(revision_label "$current" "$LABEL_BY")"
  if [ "$DEPLOYED_BY" != manual ] && [ -n "$by" ] && [ "$by" != manual ] && [ "$by" != "$DEPLOYED_BY" ]; then
    if [ "$DEPLOY_FORCE" = 1 ]; then
      warn "revision $current of $ENVIRONMENT was deployed by $by; DEPLOY_FORCE=1: $DEPLOYED_BY takes over"
    else
      die "revision $current of $ENVIRONMENT was deployed by $by, and this is $DEPLOYED_BY: deploy each environment from one CI only (SOUNDINGS_DEPLOY). DEPLOY_FORCE=1 takes it over."
    fi
  fi
}

# The newest Alembic revision in this checkout: revision ids are zero-padded sequence
# numbers (0001, 0002, ...), each file naming its down_revision.
checkout_migration_head() {
  [ -d "$MIGRATIONS_DIR" ] || return 0
  local revs downs
  revs="$(sed -n 's/^revision[^=]*= *["'\'']\([^"'\'']*\)["'\''].*/\1/p' "$MIGRATIONS_DIR"/*.py 2>/dev/null | sort -u)"
  downs="$(sed -n 's/^down_revision[^=]*= *["'\'']\([^"'\'']*\)["'\''].*/\1/p' "$MIGRATIONS_DIR"/*.py 2>/dev/null | sort -u)"
  comm -23 <(printf '%s\n' "$revs") <(printf '%s\n' "$downs") | tail -n 1
}

# What the release runs: "<image> <version label>" from the api Deployment.
release_image() {
  kc get deploy -l "app.kubernetes.io/instance=$HELM_RELEASE,app.kubernetes.io/component=api" \
    -o jsonpath='{.items[0].spec.template.spec.containers[0].image}{" "}{.items[0].metadata.labels.app\.kubernetes\.io/version}' 2>/dev/null || true
}

# Base URL for the HTTP smoke: DEPLOY_URL, else the release's first baseUrls entry.
release_url() {
  if [ -n "$DEPLOY_URL" ]; then
    printf '%s\n' "${DEPLOY_URL%/}"
    return
  fi
  local urls
  urls="$(kc get configmap -l "app.kubernetes.io/instance=$HELM_RELEASE" \
    -o jsonpath='{range .items[*]}{.data.SOUNDINGS_BASE_URLS}{"\n"}{end}' 2>/dev/null || true)"
  awk -F, 'NF && $1 != "" { print $1; exit }' <<<"$urls"
}

# --- smoke: the cluster side, then scripts/deploy-smoke.sh over HTTP ---------------------
smoke() {
  local want_digest="${1:-}" failed=0 image tag digest url version line
  log "smoke: $ENVIRONMENT ($HELM_RELEASE in $KUBE_NAMESPACE)"
  read -r image tag < <(release_image) || true
  [ -n "${image:-}" ] || { printf '  FAIL no api Deployment for release %s\n' "$HELM_RELEASE" >&2; return 1; }
  digest="${image##*@}"
  [[ "$digest" == sha256:* ]] || digest=""
  if [ -z "$digest" ]; then
    printf '  FAIL the release runs %s, not pinned by digest\n' "$image" >&2
    failed=1
  elif [ -n "$want_digest" ] && [ "$digest" != "$want_digest" ]; then
    printf '  FAIL the release runs %s, not %s\n' "$digest" "$want_digest" >&2
    failed=1
  else
    printf '  ok  release image %s\n' "$image"
  fi

  local deployment
  for deployment in $(kc get deploy -l "app.kubernetes.io/instance=$HELM_RELEASE" -o name); do
    if kc rollout status "$deployment" --timeout=180s >/dev/null 2>&1; then
      printf '  ok  %s rolled out\n' "$deployment"
    else
      printf '  FAIL %s is not rolled out\n' "$deployment" >&2
      failed=1
    fi
  done

  # Every running api and worker container runs that digest (terminating pods skipped).
  local pods name component phase deleting images running=0 api_pod=""
  pods="$(kc get pods -l "app.kubernetes.io/instance=$HELM_RELEASE,app.kubernetes.io/component in (api,worker)" \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.labels.app\.kubernetes\.io/component}{" "}{.status.phase}{" "}{.metadata.deletionTimestamp}{"|"}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}')"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    read -r name component phase deleting <<<"${line%%|*}"
    images="${line#*|}"
    [ "$phase" = Running ] && [ -z "${deleting:-}" ] || continue
    running=$((running + 1))
    [ "$component" != api ] || [ -n "$api_pod" ] || api_pod="$name"
    for image in $images; do
      if [ -z "$digest" ] || [[ "$image" != *"@$digest" ]]; then
        printf '  FAIL pod %s runs %s\n' "$name" "$image" >&2
        failed=1
      fi
    done
  done <<<"$pods"
  if [ "$running" -gt 0 ]; then
    printf '  ok  %s running api/worker pods on that digest\n' "$running"
  else
    printf '  FAIL no running api/worker pods\n' >&2
    failed=1
  fi

  # The version the app reports (its startup log line, at logLevel INFO or DEBUG) must be
  # the release's for X.Y.Z tags; for sha- tags it is printed only.
  line=""
  local logs=""
  [ -z "$api_pod" ] || logs="$(kc logs "$api_pod" -c api 2>/dev/null || true)"
  line="$(grep -m 1 '"message": *"api starting"' <<<"$logs" || true)"
  version="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' <<<"$line")"
  local want_version="${EXPECTED_VERSION:-}"
  if [ -z "$want_version" ] && [[ "${tag:-}" =~ ^v?([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    want_version="${BASH_REMATCH[1]}"
  fi
  if [ -z "$version" ] && [ -n "$want_version" ]; then
    printf "  FAIL no startup line with the app's version in pod %s's log: release %s not confirmed (keep logLevel at INFO or DEBUG)\n" "${api_pod:-?}" "$want_version" >&2
    failed=1
  elif [ -z "$version" ]; then
    warn "no startup line with the app's version in pod ${api_pod:-?}'s log (logLevel above INFO?): version not shown"
  elif [ -n "$want_version" ] && [ "$version" != "$want_version" ]; then
    printf '  FAIL the app reports version %s, the image tag is %s\n' "$version" "$tag" >&2
    failed=1
  else
    printf '  ok  the app reports version %s (image tag %s)\n' "$version" "${tag:-?}"
  fi

  url="$(release_url)"
  if [ -z "$url" ]; then
    printf '  FAIL no URL to test (set DEPLOY_URL)\n' >&2
    failed=1
  elif ! "$REPO_ROOT/scripts/deploy-smoke.sh" "$url"; then
    failed=1
  fi
  return "$failed"
}

# helm test, then smoke; "<what failed>" on stdout when something did.
verify() {
  local want_digest="$1"
  log "helm test $HELM_RELEASE"
  if ! hl test "$HELM_RELEASE" --timeout "$HELM_TIMEOUT" --logs --hide-notes >&2; then
    echo "helm test"
    return
  fi
  smoke "$want_digest" >&2 || echo "the smoke test"
}

summary() { # title, lines...
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  { printf '### %s\n\n' "$1"; shift; printf '%s\n' "$@"; } >>"$GITHUB_STEP_SUMMARY" || true
}

case "$ACTION" in
  smoke)
    preflight
    smoke "${IMAGE_DIGEST:-}"
    ;;

  status)
    preflight
    hl history "$HELM_RELEASE" --max 10 || true
    printf '\nREVISION STATUS MIGRATION-HEAD DEPLOYED-BY PIPELINE CHECKS\n'
    while read -r rev status; do
      printf '%s %s %s %s %s %s\n' "$rev" "$status" "$(revision_label "$rev" "$LABEL_HEAD")" "$(revision_label "$rev" "$LABEL_BY")" \
        "$(revision_label "$rev" "$LABEL_ORDER")" "$(verify_failed "$rev" && echo failed || echo -)"
    done < <(revisions | tail -n 10)
    printf '\n'
    kc get pods -l "app.kubernetes.io/instance=$HELM_RELEASE" -o wide
    ;;

  deploy)
    check_image_inputs
    head="${MIGRATION_HEAD:-$(checkout_migration_head)}"
    [ -n "$head" ] || die "no migration head: set MIGRATION_HEAD (the image's newest Alembic revision)"
    [[ "$head" =~ ^[A-Za-z0-9_.-]{1,63}$ ]] || die "MIGRATION_HEAD '$head' is not a label value"
    want_ref="$IMAGE_REPOSITORY:$IMAGE_TAG@$IMAGE_DIGEST"
    mapfile -t img < <(image_args)

    # Render first (no cluster): the values must pass the chart's schema and must not
    # replace the image's registry (global.imageRegistry would)...
    rendered="$(helm template "$HELM_RELEASE" "$CHART" --namespace "$KUBE_NAMESPACE" \
      "${values_args[@]}" "${img[@]}" "$@")" ||
      die "the chart doesn't render with $DEPLOY_VALUES"
    # (one document of the render, by its template's path)
    rendered_doc() { awk -v src="soundings/templates/$1" '/^# Source: / { p = ($3 == src) } p' <<<"$rendered"; }
    api_doc="$(rendered_doc deployment-api.yaml)"
    grep -Eq "image: \"?(docker\.io/(library/)?)?$(sed 's/[.[\*^$/]/\\&/g' <<<"${want_ref#docker.io/}")\"?\$" <<<"$api_doc" ||
      die "the chart would run '$(grep -m 1 'image:' <<<"$api_doc" | sed 's/^ *image: *//')', not $want_ref: don't set global.imageRegistry in $DEPLOY_VALUES (set postgresql.image.registry for the bundled Postgres instead)"
    # ...and the migration Job (external database) must end before Helm gives up on it:
    # after HELM_TIMEOUT Helm rolls the release back, and a Job still running could then
    # migrate the database under the restored release.
    job_deadline="$(rendered_doc job-migrate.yaml | sed -n 's/^  activeDeadlineSeconds: *\([0-9]*\)$/\1/p' | head -n 1)"
    if [ -n "$job_deadline" ] && [ "$job_deadline" -ge "$HELM_TIMEOUT_SECONDS" ]; then
      die "the migration Job may run ${job_deadline}s (migrations.activeDeadlineSeconds), HELM_TIMEOUT is ${HELM_TIMEOUT_SECONDS}s: after a timeout Helm rolls back while the Job could still migrate. Set migrations.activeDeadlineSeconds below HELM_TIMEOUT in the values (deploy/environments/*.values.yaml: 480), or raise HELM_TIMEOUT."
    fi

    preflight
    current="$(deployed_revision)"
    guard_other_ci "$current"
    current_head=""
    if [ -n "$current" ]; then
      current_head="$(revision_label "$current" "$LABEL_HEAD")"
      if [ -n "$current_head" ] && [[ "$head" < "$current_head" ]]; then
        if [ "$DEPLOY_FORCE" = 1 ]; then
          warn "the image's migrations end at $head, the database is at $current_head; DEPLOY_FORCE=1: deploying anyway"
        else
          die "the image's migrations end at $head but revision $current already migrated the database to $current_head: older code may not run on a newer schema (Helm and this script never migrate down). Deploy a newer image, or set DEPLOY_FORCE=1 if you know this one runs on it."
        fi
      fi
      # Never replace a newer pipeline's release with an older one's (a retried or slow old
      # job). A release (X.Y.Z) goes to staging whatever main built meanwhile, but never
      # replaces a newer release.
      read -r _ running_tag < <(release_image) || true
      older=""
      if [[ "$IMAGE_TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        if [[ "${running_tag:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && [ "$running_tag" != "$IMAGE_TAG" ] &&
          [ "$(printf '%s\n%s\n' "$IMAGE_TAG" "$running_tag" | sort -V | head -n 1)" = "$IMAGE_TAG" ]; then
          older="release $IMAGE_TAG is older than the $running_tag that revision $current runs"
        fi
      else
        current_order="$(revision_label "$current" "$LABEL_ORDER")"
        if [ -n "$DEPLOY_ORDER" ] && [ -n "$current_order" ] && [ "$(revision_label "$current" "$LABEL_BY")" = "$DEPLOYED_BY" ] &&
          [ "$DEPLOY_ORDER" -lt "$current_order" ]; then
          older="revision $current came from a newer run ($current_order) than this one ($DEPLOY_ORDER)"
        fi
      fi
      if [ -n "$older" ]; then
        [ "$DEPLOY_FORCE" = 1 ] || die "$older: not replacing it with older code (DEPLOY_FORCE=1 does; to go back, use the rollback)"
        warn "$older; DEPLOY_FORCE=1: deploying anyway"
      fi
    fi

    description="$IMAGE_TAG ${IMAGE_DIGEST:0:19} migrations $head, $DEPLOY_ORIGIN"
    log "deploy $want_ref to $ENVIRONMENT ($HELM_RELEASE in $KUBE_NAMESPACE${KUBE_CONTEXT:+, context $KUBE_CONTEXT}; migrations $head; previous revision ${current:-none})"
    if [ "$DRY_RUN" = 1 ]; then
      if ! out="$(hl upgrade --install "$HELM_RELEASE" "$CHART" "${values_args[@]}" "${img[@]}" \
        --dry-run=server --hide-notes --description "$description" "$@" 2>&1)"; then
        printf '%s\n' "$out" >&2
        die "the dry run failed: the API server refused the release"
      fi
      # What would be applied: kind and name of each object.
      awk '/^kind:/ { kind = $2 } /^  name:/ && kind { print "  " kind "/" $2; kind = "" }' <<<"$out"
      log "dry run: the API server accepted it; nothing changed"
      exit 0
    fi
    helm_labels="$LABEL_HEAD=$head,$LABEL_BY=$DEPLOYED_BY${DEPLOY_ORDER:+,$LABEL_ORDER=$DEPLOY_ORDER}"
    helm_err="$work/helm-upgrade.err"
    if ! hl upgrade --install "$HELM_RELEASE" "$CHART" "${values_args[@]}" "${img[@]}" \
      --atomic --cleanup-on-fail --wait --timeout "$HELM_TIMEOUT" --hide-notes \
      --description "$description" --labels "$helm_labels" "$@" 2> >(tee "$helm_err" >&2); then
      sleep 1 # tee's last lines
      if grep -q 'another operation (install/upgrade/rollback) is in progress' "$helm_err"; then
        die "another deploy of $ENVIRONMENT started at the same moment: this one changed nothing (run it again once that one is done)"
      fi
      hl history "$HELM_RELEASE" --max 5 >&2 || true
      if [ -n "$current" ]; then
        restored="$(deployed_revision)"
        db_head="$(newer_head "$current_head" "$head")"
        if migration_failed; then db_head="$current_head"; fi
        [ -z "$restored" ] || label_restored "$restored" "$db_head"
        log "checking that the previous release still serves"
        if ! smoke "" >&2; then
          summary "Deploy to $ENVIRONMENT failed: environment DOWN?" "The upgrade to \`$want_ref\` failed and Helm rolled back, but the restored release fails its smoke test."
          die "the upgrade to $IMAGE_TAG failed and Helm rolled back to revision $current's content, but THE RESTORED RELEASE FAILS ITS SMOKE TEST TOO: $ENVIRONMENT may be down (a schema the previous code can't use? migrations at ${db_head:-?}). See helm history, the pods and the events now."
        fi
        summary "Deploy to $ENVIRONMENT failed" "The upgrade to \`$want_ref\` failed and Helm rolled back: the previous release keeps running (helm history above)."
        die "the upgrade to $IMAGE_TAG failed and was rolled back: $ENVIRONMENT still runs the previous release (revision $current's content, migrations ${db_head:-?})"
      fi
      die "the first install of $ENVIRONMENT failed (nothing ran there before; see the events: kubectl -n $KUBE_NAMESPACE get events). With the bundled Postgres, delete its volume claim (data-$HELM_RELEASE-postgresql-0) before trying again: Helm keeps it, and a new install generates a new password."
    fi
    new_revision="$(deployed_revision)"
    problem="$(verify "$IMAGE_DIGEST")"
    if [ -n "$problem" ]; then
      if [ -n "$current" ]; then
        log "$problem failed: rolling back to revision $current"
        mark_verify_failed "$new_revision"
        hl rollback "$HELM_RELEASE" "$current" --wait --cleanup-on-fail --timeout "$HELM_TIMEOUT" ||
          die "$problem failed on revision $new_revision and the rollback to $current failed too: see helm history"
        # The new revision's migrations ran: the database is at the newer head.
        label_restored "$(deployed_revision)" "$(newer_head "$current_head" "$head")"
        if ! smoke "" >&2; then
          summary "Deploy to $ENVIRONMENT failed: environment DOWN?" "\`$want_ref\` failed $problem; rolled back to revision $current, which fails its smoke test too."
          die "$problem failed for $IMAGE_TAG on $ENVIRONMENT; rolled back to revision $current, but THE RESTORED RELEASE FAILS ITS SMOKE TEST TOO: $ENVIRONMENT may be down (the database is at migrations $(newer_head "$current_head" "$head")). See helm history and the pods now."
        fi
        summary "Deploy to $ENVIRONMENT failed" "\`$want_ref\` failed $problem; rolled back to revision $current."
        die "$problem failed for $IMAGE_TAG on $ENVIRONMENT: rolled back, the previous release (revision $current) is running again"
      fi
      mark_verify_failed "$new_revision"
      die "$problem failed for $IMAGE_TAG on $ENVIRONMENT's first install (revision $new_revision left in place to debug)"
    fi
    summary "Deployed to $ENVIRONMENT" "\`$want_ref\` is revision $new_revision of $HELM_RELEASE in $KUBE_NAMESPACE (migrations $head) at $(release_url)."
    log "deployed $IMAGE_TAG to $ENVIRONMENT: revision $new_revision, $(release_url)"
    ;;

  rollback)
    preflight
    current="$(deployed_revision)"
    if [ -z "$current" ]; then
      pending="$(pending_revision)"
      current="${pending%% *}"
    fi
    [ -n "$current" ] || die "release $HELM_RELEASE has no revision in $KUBE_NAMESPACE"
    target="${ROLLBACK_REVISION:-$(previous_revision "$current")}"
    [ -n "$target" ] || die "revision $current has no earlier revision that passed its checks and runs something else (helm history; ROLLBACK_REVISION to choose one)"
    [[ "$target" =~ ^[0-9]+$ ]] || die "ROLLBACK_REVISION must be a revision number (helm history)"
    [ "$target" != "$current" ] || die "revision $target is the one running"
    target_status="$(revisions | awk -v t="$target" '$1 == t { print $2 }')"
    [ "$target_status" = superseded ] ||
      die "revision $target is '${target_status:-missing}': roll back only to a revision that ran successfully (helm history)"
    if verify_failed "$target"; then
      [ "$DEPLOY_FORCE" = 1 ] || die "revision $target failed helm test or the smoke when it was deployed (label $LABEL_VERIFY=failed): choose another ROLLBACK_REVISION, or DEPLOY_FORCE=1"
      warn "revision $target failed its checks when deployed; DEPLOY_FORCE=1: rolling back to it anyway"
    fi
    guard_other_ci "$current"

    # Helm's rollback restores Kubernetes objects, not the database: refuse to put back
    # code that ran on another schema unless asked (the migration rule in the operator guide).
    current_head="$(revision_label "$current" "$LABEL_HEAD")"
    target_head="$(revision_label "$target" "$LABEL_HEAD")"
    if [ -z "$current_head" ] || [ -z "$target_head" ] || [ "$current_head" != "$target_head" ]; then
      reason="revision $target ran migrations ${target_head:-(unknown)} and revision $current runs ${current_head:-(unknown)}"
      if [ "$DEPLOY_FORCE" = 1 ]; then
        warn "$reason; DEPLOY_FORCE=1: rolling back across the migration boundary (the database stays as it is)"
      else
        die "refusing to roll back $ENVIRONMENT from revision $current to $target: $reason. A rollback restores the pods, not the database, and migrations only go forward. Roll forward with a fix, or set DEPLOY_FORCE=1 if revision $target's code runs on the current schema (a release's previous version does, by the expand/contract rule)."
      fi
    fi
    log "rollback $ENVIRONMENT from revision $current to $target (migrations ${target_head:-unknown})"
    if [ "$DRY_RUN" = 1 ]; then
      hl history "$HELM_RELEASE" --max 10
      log "dry run: nothing changed"
      exit 0
    fi
    hl rollback "$HELM_RELEASE" "$target" --wait --cleanup-on-fail --timeout "$HELM_TIMEOUT" ||
      die "helm rollback to revision $target failed: see helm history"
    # The database stays at the current head (a forced rollback doesn't migrate down).
    label_restored "$(deployed_revision)" "$(newer_head "$target_head" "$current_head")"
    manifest="$(hl get manifest "$HELM_RELEASE" --revision "$target")"
    target_digest="$(sed -n '/image: .*@sha256:/{s/.*@\(sha256:[0-9a-f]\{64\}\).*/\1/p;q;}' <<<"$manifest")"
    problem="$(verify "$target_digest")"
    if [ -n "$problem" ]; then
      mark_verify_failed "$(deployed_revision)"
      die "rolled back to revision $target, but $problem failed: see helm history and the pods"
    fi
    summary "Rolled back $ENVIRONMENT" "Revision $target's content is running again as revision $(deployed_revision)."
    log "rolled back $ENVIRONMENT to revision $target's content: now revision $(deployed_revision)"
    ;;
esac
