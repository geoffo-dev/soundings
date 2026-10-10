# Phase 9 summary: continuous delivery (release 0.2.0)

**Status:** built on 2026-10-09, verified for release 0.2.0 on 2026-10-10, waiting for
the product owner's review ([RELEASE-NOTES.md](../RELEASE-NOTES.md)).
**Scope (the product owner, 2026-10-09):** every push to main deploys staging and every
`vX.Y.Z` tag deploys production after an approval, from a self-managed, on-prem GitLab
and from GitHub Actions, into an on-prem cluster, air-gapped at run time, least
privilege, with a rollback; neither CI may hold a credential that reaches the cluster
from outside. Decisions: [decisions.md](../decisions.md) ("Phase 9 (product owner,
2026-10-09)" and "Phase 9 (product owner answers, 2026-10-09)"); architecture:
[ADR 0017](../adr/0017-continuous-delivery.md); research:
[gitlab-cd](../research/gitlab-cd.md), [github-cd](../research/github-cd.md); how to set
it up: [operator guide, "Continuous delivery"](../operator-guide.md#continuous-delivery-phase-9);
test plan with both run logs: [phase-9.md](../test-plans/phase-9.md).

Commits: `e8d739c` (research), `45f8b28` (the build), `281d3ff` (the live GitLab run's
fixes and the local CI harness), `14c97b5` (the review fixes), plus the 0.2.0 release
verification (the Premium setup, `.gitlab/CODEOWNERS`, the docs).

## Design

```
push to main:  checks ─ build (sha-<8>) ─ scan ─ e2e/k3s ─▶ staging (automatic)
tag vX.Y.Z:    release check ─ checks ─ build (X.Y.Z, X.Y) ─ scan ─ e2e/k3s ─▶ staging
               ─▶ release (SBOM, chart) ─▶ [gate] ─▶ production (staging's digest)
```

| Part | What | Where |
|---|---|---|
| One deploy script | `scripts/deploy.sh deploy\|rollback\|smoke\|status\|template <env>` and `check-release vX.Y.Z`, the same for both CIs and people: render check (schema, the image not replaced, the migration Job's deadline below `HELM_TIMEOUT`), wait for a deploy in progress, refuse another CI's release, an older run's or an older `X.Y.Z`'s deploy, an image with older migrations; `helm upgrade --install --atomic --wait --cleanup-on-fail` by digest; `helm test`; the smoke (every pod on the digest, the app's version for `X.Y.Z`, `scripts/deploy-smoke.sh`: health, readiness, the SPA and its script, the branding from the database, 401 anonymously and on `/mcp`, no public `/metrics`); a failed test or smoke rolls back itself; every revision labelled with its migration head, who deployed it and from which run | `scripts/deploy.sh`, `scripts/deploy-smoke.sh`, `deploy/environments/` (staging, production, `cluster-setup.yaml`, `k3s.values.yaml`) |
| GitLab self-managed | `.gitlab-ci.yml`: build with rootless BuildKit (or `docker buildx` on dind, `IMAGE_BUILDER=dind`), Trivy gate and SBOM, `deploy:staging`, `release:check`, `release:publish` (generic package registry), `deploy:production` (manual, blocking, on protected `v*` tags), `rollback:*`, `migrations:lint`; through the GitLab agent for Kubernetes only, one agent per environment (`ci_access`: this project, its environment, protected refs only), each bound to the `soundings-deployer` ClusterRole in its namespace (`rbac.create=false`, no impersonation); deploy jobs on a protected runner tagged `soundings-deploy` | `.gitlab-ci.yml`, `.gitlab/agents/`, `deploy/gitlab-agent/`, `.gitlab/CODEOWNERS` |
| GitHub Actions | `ci.yml` (checks, image, scan, release), `deploy-env.yml` (the deploy job on ARC runners in the network, whose pods have no rights; each environment deploys with `KUBECONFIG_DATA`, a namespaced token of `soundings-ci-deployer`), `deploy.yml` (manual production gate for Pro/Team: `SOUNDINGS_PRODUCTION_DEPLOYERS`, immutable releases only); actions pinned by SHA, least-privilege permissions, no third-party actions, Dependabot with a cooldown | `.github/workflows/`, `deploy/ci/` (`arc-rbac.yaml`, `arc-values.yaml`, `deploy-runner.Dockerfile`), `scripts/lib/ci-kubeconfig.sh` |
| Checks | `make check-workflows` (actionlint 1.7.12, zizmor 1.30.1, gitlab-ci-local 4.75.1 with ten rule scenarios), `make check-migrations` (expand/contract lint for 0016 on), `scripts/deploy.sh template` in `make check-helm` | `Makefile`, `scripts/lib/check-gitlab-ci.sh`, `scripts/lib/check-migrations.py` |
| Rehearsals | `make k3s-deploy` (the script in the tools image as a deployer bound in one namespace, on the local k3s); `scripts/ci-local/` (GitLab CE 19.4.1 with registry and KAS, a runner, k3s, both agents: the pipeline itself) | `scripts/lib/k3s-deploy.sh`, `scripts/ci-local/` |

## The live GitLab run (2026-10-09)

On a self-managed GitLab CE 19.4.1 in Docker (`scripts/ci-local/`), with its registry and
agent server on https and a throwaway CA, a Docker-executor runner and k3s with both
agents installed from `deploy/gitlab-agent/` (connected in 39 s, no ClusterRoleBinding):

- **Push to main** (CD-02 to CD-05): rootless BuildKit on an unprivileged runner, 110 s
  cold and 11-60 s afterwards, `ci-N` and `sha-X` one digest; the Trivy gate with the
  SBOM; staging deployed through the agent in 60 s with `helm test` and the smoke; a
  second push upgraded it by digest.
- **Broken deploys** (CD-06, CD-07): bad values: `--atomic` rolled back and the previous
  release answered all 212 probes meanwhile; a release that passes `helm test` but fails
  the smoke: the script rolled it back; a rollback played during a deploy waited on
  `resource_group`.
- **Tag `v0.2.0`** (CD-08, CD-09): `0.2.0` and `0.2` one digest, the app reports 0.2.0,
  the release with its SBOM and chart; the pipeline stopped at `deploy:production`; a
  Developer's play was 403, a Maintainer's deployed staging's digest in 51 s.
- **Least privilege** (CD-10), from CI jobs on a protected and an unprotected branch:
  kube-system, the other environment, namespaces, `default`, exec and RoleBindings
  refused for both agents; production's context only on protected refs.
- **Rollback** (CD-11) 44 s and 24 s; **dind** (CD-12) after F7; GitHub's deploy step
  (CD-15) in a pod on the same k3s: staging as the ARC ServiceAccount, production with
  `KUBECONFIG_DATA`.

It found eight defects, all fixed and re-run: **F1** cosign pinned to a `-dev` digest;
**F2** the staging agent lacked `protected_branches_only` (any pushed branch got the
staging context and its Secrets); **F3** a world-readable kubeconfig; **F4** the manual
rollback targeted the release the script had just rolled back (failed revisions are now
labelled and skipped); **F5** unbounded smoke retries (a broken release served up to 5
minutes; now about 1); **F6** GitHub couldn't set `DEPLOY_VALUES` / `HELM_TIMEOUT`;
**F7** dind and GitHub builds with an internal CA (base-image registries, BuildKit's
token fetch, DNS on dind's network); **F8** Helm copied the other CI's label onto a
rollback.

## The review (2026-10-09)

| Finding | Outcome |
|---|---|
| **H1** the Free production gate could be bypassed from main (the agent can't tell main from a tag) | Documented: on Free only release managers may merge into protected branches; on Premium protected environments close it (GitLab drops every other user's job for the environment, any action: 19.4's source). **The product owner runs Premium or Ultimate** (2026-10-09): the operator guide now leads with protected environments for staging and production, one required approval for production, pipeline variables for Maintainers only and Code Owner approval on main (`.gitlab/CODEOWNERS`, a placeholder group); Free is an appendix |
| **H2** the staging runner had standing rights | Fixed: runner pods get none; each environment deploys with `KUBECONFIG_DATA` (`scripts/lib/ci-kubeconfig.sh`; CD-23) |
| **H3** cache poisoning | Fixed: protected refs build from scratch and write the cache, other pipelines only read it; GitHub builds with no cache |
| **M1** deploy jobs on any runner | Fixed: a protected runner tagged `DEPLOY_RUNNER_TAG`; GitHub's build keeps no login and removes its builder |
| **M2** pipeline variables override gates | Fixed and documented: Maintainer minimum role; production refuses `CD_ONLY`; `SCAN_SEVERITY` must include CRITICAL |
| **M3** wrong migration label after a rollback | Fixed: a restored revision carries the database's head (CD-18) |
| **M4** a schema break not caught | Fixed: a restored release that fails its smoke fails loudly ("may be down", CD-19); the smoke reads the app's tables; the migration Job's deadline below `HELM_TIMEOUT` (CD-22); the migration lint (CD-25) |
| **M5, M6** staging's branch rules, `CI_BUILD_CA` on GitHub | Fixed |
| **M7** any writer could deploy production on GitHub | Fixed: `SOUNDINGS_PRODUCTION_DEPLOYERS`, immutable releases, the image's repository and version checked |
| **M8** internet at run time | Fixed: mirrors for the k3s job, images by digest, no apt in the fake agent's job; the guide states exactly what needs mirrors |
| **L2-L4** run order, concurrent deploys, timeouts | Fixed (CD-17, CD-20, 90-minute jobs); the rehearsal found **F9** (a waiting deploy rewrote the restored revision's labels), fixed |
| **L5, L6, L10** Trivy's CA and telemetry, GitHub's builder, an unreadable version | Fixed (CD-21) |
| **L7, L8** the runner image's age, registry variables | Documented |
| **L9** unfixed CRITICAL findings reported, not gated | Kept; **confirmed by the product owner** (2026-10-09) |
| **L1, L11, L12** rollback jobs `action: access`, `DEPLOY_IMAGE` alpine/k8s, GitHub's 30-day token | Kept, with reasons ([decisions](../decisions.md#phase-9-product-owner-2026-10-09)) |

## Release verification (2026-10-10)

@@RELEASE_VERIFICATION@@

## What is not verified

- **GitLab Premium's protected environments and deployment approvals**: GitLab CE is the
  Free tier; the setup is from GitLab 19.4's documentation and source.
- **The GitLab-specific changes after the live run** (cache flags by protected ref,
  `DEPLOY_RUNNER_TAG`, the 90-minute timeouts, production refusing `CD_ONLY`, the
  `migrations:lint` job): gitlab-ci-local's schema and rule checks and reading only.
  @@CILOCAL@@
- **The Kubernetes executor** (the Docker executor ran both build paths), **cosign**
  signing (its image's blobs on ghcr.io can't be fetched here) and the default
  `DEPLOY_IMAGE` (alpine/k8s, 1.3 GB, didn't fit the disk).
- **GitHub**: no runner can register here; the workflows lint clean and the deploy step
  ran in the cluster as a runner would, but not GitHub's runners, GHCR, ARC itself,
  environments with required reviewers or `deploy.yml`'s `gh release download`.
- The pipeline's long jobs (lint, tests, e2e, the k3s job) were skipped in the live run
  (`CD_ONLY`); every command they run passes on the build machine.
- A real kagent (as in 0.1.0: the fake agent and kagent's CRDs only).
