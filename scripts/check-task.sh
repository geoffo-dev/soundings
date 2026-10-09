#!/usr/bin/env bash
# Checks for the areas touched in the working tree. Used as the Claude Code
# TaskCompleted hook: exit 2 (with the failing output on stderr) keeps a task open
# while its area is red.
#
#   scripts/check-task.sh                  # areas from `git status --porcelain`
#   scripts/check-task.sh backend helm     # explicit areas
#   CHECK_TASK_ALL=1 scripts/check-task.sh # every area
#
# Areas: backend (make -C backend check), frontend (npm --prefix frontend run check),
# helm (deploy/: helm lint + template, via the alpine/helm container, and each
# deploy/environments/<env>.values.yaml rendered by scripts/deploy.sh template),
# e2e (npm run check: tsc + prettier), scripts (bash -n, shellcheck when installed or its
# image is pulled; scripts/, scripts/lib/, scripts/ci-local/ and e2e/scripts/; the Python
# helpers compile), fake-agent (dev/fake-agent: make check, ruff + mypy + pytest),
# migrations (backend/app/migrations: the expand/contract check,
# scripts/lib/check-migrations.py), workflows (.github/, .gitlab-ci.yml, .gitlab/: make
# check-workflows, i.e. actionlint, zizmor and gitlab-ci-local).
# Areas whose directory or toolchain is missing are skipped with a note.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT" || exit 1
HELM_IMAGE="${HELM_IMAGE:-alpine/helm:3.16.2}"
SHELLCHECK_IMAGE="${SHELLCHECK_IMAGE:-koalaman/shellcheck:stable}"
TAIL_LINES="${CHECK_TASK_TAIL_LINES:-60}"

# The hook passes a JSON event on stdin; nothing in it changes what we check. Drain it
# without blocking when stdin is an idle pipe (manual runs).
if [ ! -t 0 ]; then
  while IFS= read -r -t 0.2 _; do :; done
fi

all_areas=(backend frontend helm e2e scripts fake-agent migrations workflows)
areas=()
if [ $# -gt 0 ]; then
  areas=("$@")
elif [ "${CHECK_TASK_ALL:-}" = "1" ]; then
  areas=("${all_areas[@]}")
else
  changed="$(git status --porcelain 2>/dev/null | cut -c4- | sed 's/.* -> //')"
  for area in "${all_areas[@]}"; do
    case "$area" in
      helm) pattern="deploy/" ;;
      fake-agent) pattern="dev/fake-agent/" ;;
      migrations) pattern="backend/app/migrations/" ;;
      workflows) pattern="(\.github/|\.gitlab-ci\.yml|\.gitlab/)" ;;
      *) pattern="$area/" ;;
    esac
    if grep -Eq "^\"?$pattern" <<<"$changed"; then areas+=("$area"); fi
  done
fi

if [ ${#areas[@]} -eq 0 ]; then
  echo "check-task: no changes in backend/, frontend/, deploy/, e2e/, scripts/, dev/fake-agent/ or the CI files; nothing to check"
  exit 0
fi

have() { command -v "$1" >/dev/null 2>&1; }
docker_ok() { have docker && docker info >/dev/null 2>&1; }

failures=()
logdir="$(mktemp -d)"
trap 'rm -rf "$logdir"' EXIT

# run NAME COMMAND...: run quietly, remember the output of failures.
run() {
  local name="$1" start=$SECONDS
  shift
  if "$@" >"$logdir/$name.log" 2>&1; then
    printf 'check-task: %-10s ok (%ss)\n' "$name" $((SECONDS - start))
  else
    printf 'check-task: %-10s FAILED (%ss)\n' "$name" $((SECONDS - start))
    failures+=("$name")
  fi
}

skip() { printf 'check-task: %-10s skipped (%s)\n' "$1" "$2"; }

check_backend() {
  [ -f backend/Makefile ] || { skip backend "no backend/Makefile"; return; }
  have uv || { skip backend "uv not installed"; return; }
  run backend make -C backend check
}

check_frontend() {
  [ -f frontend/package.json ] || { skip frontend "no frontend/package.json"; return; }
  have npm || { skip frontend "npm not installed"; return; }
  [ -d frontend/node_modules ] || { skip frontend "run: npm --prefix frontend ci"; return; }
  run frontend npm --prefix frontend run check
}

# shellcheck disable=SC2329  # invoked through run()
helm_checks() {
  local values
  docker run --rm -v "$REPO_ROOT/deploy/helm:/chart:ro" -w /chart "$HELM_IMAGE" lint . --strict --quiet || return 1
  for values in deploy/helm/ci/*-values.yaml; do
    [ -e "$values" ] || continue
    echo "--- $values"
    docker run --rm -v "$REPO_ROOT/deploy/helm:/chart:ro" -w /chart "$HELM_IMAGE" \
      lint . --strict --quiet -f "ci/$(basename "$values")" || return 1
    # `helm lint` only reports template `fail` calls as INFO; `helm template` errors.
    docker run --rm -v "$REPO_ROOT/deploy/helm:/chart:ro" -w /chart "$HELM_IMAGE" \
      template check . -f "ci/$(basename "$values")" >/dev/null || return 1
  done
  # The delivery environments' values, as scripts/deploy.sh renders them (with the local
  # k3s overlay too, as make k3s-deploy and scripts/ci-local use it).
  local env overlay
  for values in deploy/environments/*.values.yaml; do
    env="$(basename "$values" .values.yaml)"
    [ "$env" != k3s ] || continue
    for overlay in "" deploy/environments/k3s.values.yaml; do
      echo "--- $values${overlay:+ + $overlay}"
      docker run --rm -v "$REPO_ROOT:/repo:ro" -w /repo -e "DEPLOY_VALUES=$values${overlay:+ $overlay}" \
        --entrypoint bash "$HELM_IMAGE" scripts/deploy.sh template "$env" >/dev/null || return 1
    done
  done
}

check_helm() {
  [ -f deploy/helm/Chart.yaml ] || { skip helm "no deploy/helm/Chart.yaml"; return; }
  docker_ok || { skip helm "docker not available"; return; }
  run helm helm_checks
}

check_e2e() {
  [ -f e2e/package.json ] || { skip e2e "no e2e/package.json"; return; }
  have npm || { skip e2e "npm not installed"; return; }
  [ -d e2e/node_modules ] || { skip e2e "run: npm --prefix e2e ci"; return; }
  if grep -q '"check"' e2e/package.json; then
    run e2e npm --prefix e2e run check # tsc + prettier
  elif grep -q '"typecheck"' e2e/package.json; then
    run e2e npm --prefix e2e run typecheck
  else
    run e2e npx --prefix e2e tsc --noEmit -p e2e
  fi
}

# shellcheck disable=SC2329  # invoked through run()
scripts_checks() {
  local f
  local files=(scripts/*.sh scripts/lib/*.sh scripts/ci-local/*.sh)
  # The e2e stack scripts (platform-owned, under e2e/) too, when present.
  for f in e2e/scripts/*.sh; do [ -e "$f" ] && files+=("$f"); done
  for f in "${files[@]}"; do
    [ -e "$f" ] || continue
    bash -n "$f" || return 1
  done
  for f in scripts/lib/*.py; do
    [ -e "$f" ] || continue
    python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$f" || return 1
  done
  if have shellcheck; then
    shellcheck -x "${files[@]}"
  elif docker_ok && docker image inspect "$SHELLCHECK_IMAGE" >/dev/null 2>&1; then
    docker run --rm -v "$REPO_ROOT:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" -x "${files[@]}"
  else
    echo "shellcheck not available (install it, or docker pull $SHELLCHECK_IMAGE)"
  fi
}

check_scripts() {
  run scripts scripts_checks
}

check_migrations() {
  [ -d backend/app/migrations/versions ] || { skip migrations "no backend/app/migrations/versions"; return; }
  have python3 || { skip migrations "python3 not installed"; return; }
  run migrations python3 scripts/lib/check-migrations.py
}

check_workflows() {
  docker_ok || { skip workflows "docker not available (actionlint)"; return; }
  have uvx || { skip workflows "uvx not installed (zizmor)"; return; }
  have npx || { skip workflows "npx not installed (gitlab-ci-local)"; return; }
  run workflows make --no-print-directory check-workflows
}

check_fake_agent() {
  [ -f dev/fake-agent/Makefile ] || { skip fake-agent "no dev/fake-agent/Makefile"; return; }
  have uv || { skip fake-agent "uv not installed"; return; }
  run fake-agent make -C dev/fake-agent check
}

for area in "${areas[@]}"; do
  case "$area" in
    backend) check_backend ;;
    frontend) check_frontend ;;
    helm | deploy) check_helm ;;
    e2e) check_e2e ;;
    scripts) check_scripts ;;
    fake-agent) check_fake_agent ;;
    migrations) check_migrations ;;
    workflows) check_workflows ;;
    *) echo "check-task: unknown area '$area' (known: ${all_areas[*]})" >&2; exit 1 ;;
  esac
done

if [ ${#failures[@]} -gt 0 ]; then
  {
    echo "Checks failed for: ${failures[*]}. Fix them before completing the task."
    for name in "${failures[@]}"; do
      echo
      echo "===== $name (last $TAIL_LINES lines) ====="
      tail -n "$TAIL_LINES" "$logdir/$name.log"
    done
  } >&2
  exit 2
fi
exit 0
