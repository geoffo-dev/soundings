# ADR 0017: Continuous delivery from both CIs through one deploy script, without cluster credentials in the CI

- Status: Proposed · Date: 2026-10-09 (review fixes the same day) · Research: [gitlab-cd](../research/gitlab-cd.md), [github-cd](../research/github-cd.md)

## Context

The product owner (Phase 9) wants every push to main deployed to staging and every vX.Y.Z
tag deployed to production after an approval, from a self-managed, on-prem GitLab and from
GitHub Actions, into an on-prem cluster, air-gapped at run time, least privilege, with a
rollback. Neither CI may hold a credential that reaches the cluster from outside.

## Decision

- **One script**, `scripts/deploy.sh deploy|rollback|smoke|status|template <env>`, for both
  CIs and people: `helm upgrade --install --atomic --wait` with the image **pinned by
  digest**, values from `deploy/environments/<env>.values.yaml` (no secrets: `existingSecret`
  references), `helm test`, then the production-safe smoke (`scripts/deploy-smoke.sh` plus
  the pods' digest and the app's reported version); a failure after the upgrade rolls back
  to the previous revision, and the job says whether that restored release passes its
  smoke. Each revision is labelled with the database's migration head (a restored one with
  the newer of the two), the CI and the CI run that deployed it; a manual rollback across
  a migration boundary, a deploy of older migrations, a deploy from an older run (or of an
  older `X.Y.Z`) and a take-over by the other CI are refused unless `DEPLOY_FORCE=1`. A
  deploy waits for another one in progress; the migration Job must end before
  `HELM_TIMEOUT`.
- **Cluster access from inside**: GitLab through the agent for Kubernetes (agentk dials
  out; one agent per environment, `ci_access` limited to the project, the environment and
  protected refs; its ServiceAccount bound only in its namespace, no impersonation, so it
  works on Free; deploy jobs only on a protected runner, `DEPLOY_RUNNER_TAG`). The agent
  can't tell `main` from a tag, so on Free the people who may merge into protected
  branches must be the release managers; Premium's protected environments drop anyone
  else's job for the environment. GitHub through self-hosted runners in the network (ARC)
  whose pods have no rights: each environment's deploy uses a namespaced token in that
  environment's secret `KUBECONFIG_DATA` (runner labels are not access control below
  Enterprise). One `soundings-deployer` ClusterRole of namespaced rules, bound per namespace.
- **Flow**: tag pipelines rebuild (the image's version label), deploy that image to
  staging, then production deploys the digest staging ran. Gates: GitLab Free a protected
  manual job on a protected tag, Premium deployment approvals (same YAML); GitHub
  environment reviewers, or a manual `deploy` workflow on the tag where the plan has none
  (an allow-list of deployers, immutable releases). `resource_group` / `concurrency`
  serialise per environment (on GitHub, main's deploys, a release's and rollbacks queue
  apart and the script waits); pull-request runs alone cancel. Pipeline variables are for
  Maintainers; production refuses a pipeline that skipped the checks.
- **One CI per environment** (`SOUNDINGS_DEPLOY` lists what a CI deploys; empty = checks only).
- **Builds**: rootless BuildKit (unprivileged Kubernetes runners) or buildx on dind; kaniko
  is gone. Tags: `ci-<pipeline>` (GitLab tests), `sha-<8>` on main, `X.Y.Z` and `X.Y` on tags.
  Release builds never read the registry layer cache (protected refs write it, others read
  it; GitHub uses none). Trivy gate (`SCAN_SEVERITY`, always including CRITICAL) and a
  CycloneDX SBOM on the release; cosign with a key optional, enforced in the cluster if at all.
- **Supply chain**: actions pinned by commit SHA, release-path images by digest (test-only
  images by tag), Dependabot with a cooldown, `make check-workflows` (actionlint, zizmor,
  gitlab-ci-local), and an expand/contract lint of new migrations.

## Consequences

- Rollback restores pods, not the database: migrations must stay expand/contract
  compatible with the previous release (operator guide, "Rollback, and migrations";
  `scripts/lib/check-migrations.py` flags drops, renames and new NOT NULLs).
- A tag's production image differs from main's staging image (rebuilt), but it is the
  digest that passed staging. A vX.Y.Z tag requires the repo's versions to say X.Y.Z.
- The GitLab path needs GitLab on https (kubectl sends the agent token only over TLS).
- On GitLab Free the production gate is only as strong as who may merge into protected
  branches; GitHub Pro/Team has no second approver. Both are documented, not hidden.
- GitHub keeps a 30-day namespaced token per environment (renewed by hand); API-server
  OIDC trust is the alternative where the API server can reach the issuer.
- Run end to end on a self-managed GitLab CE 19.4.1 with its agents and k3s
  (`scripts/ci-local/`, docs/test-plans/phase-9.md); GitHub's deploy step ran in the
  cluster as a runner would, not on GitHub's service.
