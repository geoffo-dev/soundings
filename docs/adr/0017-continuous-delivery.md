# ADR 0017: Continuous delivery from both CIs through one deploy script, without cluster credentials in the CI

- Status: Proposed · Date: 2026-10-09 · Research: [gitlab-cd](../research/gitlab-cd.md), [github-cd](../research/github-cd.md)

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
  to the previous revision. Each revision is labelled with the image's newest migration
  and the CI that deployed it; a manual rollback across a migration boundary, a deploy of
  older migrations and a take-over by the other CI are refused unless `DEPLOY_FORCE=1`.
- **Cluster access from inside**: GitLab through the agent for Kubernetes (agentk dials
  out; one agent per environment, `ci_access` limited to the project and environment,
  production on protected refs; its ServiceAccount bound only in its namespace, no
  impersonation, so it works on Free). GitHub through self-hosted runners in the network
  (ARC): staging as the runner pod's ServiceAccount, production with a namespaced token in
  the production environment's secret (runner labels are not access control below
  Enterprise). One `soundings-deployer` ClusterRole of namespaced rules, bound per namespace.
- **Flow**: tag pipelines rebuild (the image's version label), deploy that image to
  staging, then production deploys the digest staging ran. Gates: GitLab Free a protected
  manual job on a protected tag, Premium deployment approvals (same YAML); GitHub
  environment reviewers, or a manual `deploy` workflow on the tag where the plan has none.
  `resource_group` / `concurrency` serialise per environment; pull-request runs alone cancel.
- **One CI per environment** (`SOUNDINGS_DEPLOY` lists what a CI deploys; empty = checks only).
- **Builds**: rootless BuildKit (unprivileged Kubernetes runners) or buildx on dind; kaniko
  is gone. Tags: `ci-<pipeline>` (GitLab tests), `sha-<8>` on main, `X.Y.Z` and `X.Y` on tags.
  Trivy gate (`SCAN_SEVERITY`) and a CycloneDX SBOM on the release; cosign with a key optional.
- **Supply chain**: actions pinned by commit SHA, tools by image digest, Dependabot with a
  cooldown, `make check-workflows` (actionlint, zizmor, gitlab-ci-local).

## Consequences

- Rollback restores pods, not the database: migrations must stay expand/contract
  compatible with the previous release (operator guide, "Migrations and rollback").
- A tag's production image differs from main's staging image (rebuilt), but it is the
  digest that passed staging. A vX.Y.Z tag requires the repo's versions to say X.Y.Z.
- The GitLab path needs GitLab on https (kubectl sends the agent token only over TLS).
- Not yet run against a real GitLab or GitHub; the script, RBAC and build steps were
  rehearsed on k3s and in containers (Phase 9 build report).
