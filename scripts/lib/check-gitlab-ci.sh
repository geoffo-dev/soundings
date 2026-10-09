#!/usr/bin/env bash
# Check .gitlab-ci.yml offline (make check-workflows): gitlab-ci-local validates it against
# GitLab's CI schema and evaluates the rules, then this script checks which delivery jobs
# each kind of pipeline gets. It runs in a throwaway git repository holding only the
# pipeline (nothing is written to the working tree, no job runs, no Docker).
#
#   scripts/lib/check-gitlab-ci.sh [gitlab-ci-local version]
set -euo pipefail

VERSION="${1:-4.75.1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/repo/e2e"
cp "$REPO_ROOT/.gitlab-ci.yml" "$work/repo/"
echo '{}' >"$work/repo/e2e/package.json" # the e2e jobs' `exists:` rule
git -C "$work/repo" init -q -b main
git -C "$work/repo" -c user.email=ci@example.invalid -c user.name=ci add -A
git -C "$work/repo" -c user.email=ci@example.invalid -c user.name=ci commit -qm pipeline

failed=0
# expect "<what>" "<jobs that must be there>" "<jobs that must not>" [gitlab-ci-local --variable args]
expect() {
  local what="$1" want="$2" unwanted="$3" listed job
  shift 3
  if ! listed="$(cd "$work/repo" && npx --yes "gitlab-ci-local@$VERSION" --list "$@" 2>"$work/err")"; then
    cat "$work/err" >&2
    echo "  FAIL $what: gitlab-ci-local refused the pipeline" >&2
    failed=1
    return
  fi
  jobs="$(awk 'f && NF { print $1 } /^name / { f = 1 }' <<<"$listed")"
  for job in $want; do
    grep -qxF "$job" <<<"$jobs" || { echo "  FAIL $what: no $job" >&2; failed=1; }
  done
  for job in $unwanted; do
    if grep -qxF "$job" <<<"$jobs"; then echo "  FAIL $what: unexpected $job" >&2; failed=1; fi
  done
  echo "  ok  $what"
}

deploy_jobs="deploy:staging rollback:staging deploy:production rollback:production release:publish chart:package"
echo "==> .gitlab-ci.yml (gitlab-ci-local $VERSION)" >&2
expect "main, delivery off: checks only" "image:build image:trivy e2e k3s:install-upgrade" \
  "$deploy_jobs image:build:dind release:check"
expect "main, SOUNDINGS_DEPLOY=staging: staging" "deploy:staging rollback:staging" \
  "deploy:production rollback:production release:publish" \
  --variable "SOUNDINGS_DEPLOY=staging"
expect "feature branch: no delivery" "image:build image:trivy" "$deploy_jobs" \
  --variable "SOUNDINGS_DEPLOY=staging production" --variable CI_COMMIT_BRANCH=feature-x
expect "vX.Y.Z tag: staging, release, gated production" \
  "release:check deploy:staging chart:package release:publish deploy:production rollback:production" "" \
  --variable "SOUNDINGS_DEPLOY=staging production" --variable CI_COMMIT_TAG=v1.2.3 --variable CI_COMMIT_BRANCH=
expect "vX.Y.Z tag, production without staging: no production deploy" "release:publish" "deploy:production deploy:staging" \
  --variable "SOUNDINGS_DEPLOY=production" --variable CI_COMMIT_TAG=v1.2.3 --variable CI_COMMIT_BRANCH=
expect "IMAGE_BUILDER=dind" "image:build:dind" "image:build" --variable IMAGE_BUILDER=dind
expect "COSIGN_PRIVATE_KEY set: signing" "image:sign" "" --variable COSIGN_PRIVATE_KEY=/dev/null
checks="backend:lint backend:typecheck frontend:lint contract:openapi contract:types migrations:lint fake-agent:test backend:test frontend:test frontend:build e2e e2e:sso k3s:install-upgrade"
expect "main, every check by default" "$checks helm:lint" "" --variable "SOUNDINGS_DEPLOY=staging"
expect "CD_ONLY=1: build, scan gate and staging without the long checks" \
  "helm:lint image:build image:trivy deploy:staging rollback:staging" "$checks" \
  --variable "SOUNDINGS_DEPLOY=staging production" --variable CD_ONLY=1
expect "CD_ONLY=1 on a vX.Y.Z tag: release check, release and gate stay" \
  "release:check image:trivy deploy:staging release:publish deploy:production" "$checks" \
  --variable "SOUNDINGS_DEPLOY=staging production" --variable CD_ONLY=1 --variable CI_COMMIT_TAG=v1.2.3 --variable CI_COMMIT_BRANCH=
[ "$failed" = 0 ] || { echo "==> .gitlab-ci.yml FAILED" >&2; exit 1; }
echo "==> .gitlab-ci.yml passed" >&2
