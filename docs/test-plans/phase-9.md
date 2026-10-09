# Test plan: Phase 9 (continuous delivery)

Owner: platform (live verification). Source of truth: the product owner's decisions in
[decisions.md](../decisions.md) ("Phase 9 (product owner, 2026-10-09)"),
[ADR 0017](../adr/0017-continuous-delivery.md), [operator-guide.md "Continuous
delivery"](../operator-guide.md#continuous-delivery-phase-9) and the research in
[gitlab-cd.md](../research/gitlab-cd.md) and [github-cd.md](../research/github-cd.md). Each
row has an ID; the run log below cites it.

How it is run: [`scripts/ci-local/`](../../scripts/ci-local/README.md) stands up a
self-managed GitLab CE 19.4.1 (registry and KAS on https with a throwaway CA), a
Docker-executor runner and k3s with the two GitLab agents installed from
`deploy/gitlab-agent/`, pushes a snapshot of the working tree to `platform/soundings` and
drives the pipeline through GitLab's API. GitHub Actions can't run here (no runner can
register: GitHub's release downloads are blocked); its deploy job's steps run through the
same `scripts/deploy.sh` against the same k3s (CD-15).

## Cases

| ID | What | Pass when |
|---|---|---|
| CD-01 | Infrastructure as an operator sets it up | GitLab on https with KAS; `rbac.create=false` agents from `deploy/gitlab-agent/values.yaml` connected; no kubeconfig or cluster credential stored in GitLab |
| CD-02 | Push to main builds the image (rootless BuildKit, unprivileged runner) | `ci-<pipeline>` and `sha-<8>` pushed as one digest to GitLab's registry; `image.env` carries the digest; the Dockerfile's `build_ca` secret and build args work |
| CD-03 | The scan gate | Trivy scans the digest before any deploy; the gate fails the pipeline at `SCAN_SEVERITY`; the CycloneDX SBOM is an artifact |
| CD-04 | Staging deploys automatically through the agent | `deploy:staging` runs `scripts/deploy.sh` with the injected context into `soundings-staging` only; helm upgrade by digest, helm test, the production-safe smoke; the environment shows with its URL |
| CD-05 | A second push upgrades staging by digest | a new Helm revision with the new digest, pods on it |
| CD-06 | A broken deploy rolls back | the job fails, Helm (or the script) rolls back, the previous release keeps serving |
| CD-07 | Deploys serialise per environment | a second pipeline's deploy waits on `resource_group: staging` |
| CD-08 | A version tag | `release:check`, `X.Y.Z` and `X.Y` tags of one digest, the app reports X.Y.Z, staging first, then the release (SBOM and chart in the package registry) |
| CD-09 | The production gate (Free) | `deploy:production` waits (manual, blocking); a Developer can't run it; a Maintainer runs it through the API; it deploys the digest staging ran into `soundings-production` |
| CD-10 | Least privilege of the agents' CI access | a job's context reaches its namespace only: kube-system, the other environment, namespaces, exec and RBAC are refused; production's context only on protected refs; no context without an environment |
| CD-11 | The manual rollback job | `rollback:staging` / `rollback:production` restore the previous revision (and refuse across a migration boundary) |
| CD-12 | The dind build path | `IMAGE_BUILDER=dind` on a privileged runner pushes the same tags |
| CD-13 | Signing (optional) | `image:sign` with a key signs the digest (only when `COSIGN_PRIVATE_KEY` is set) |
| CD-14 | `CD_ONLY` keeps every check by default | without it, every lint/test/e2e/k3s job is in the pipeline; with it, only release check, chart lint, build, scan and delivery |
| CD-15 | GitHub Actions | workflows lint clean; `deploy-env.yml`'s step (`scripts/deploy.sh`) deploys staging as the ARC ServiceAccount and production with `KUBECONFIG_DATA`; the one-CI-per-environment guard |
| CD-16 | Teardown | every container, volume, image and the cluster removed; disk back |

## Run log: 2026-10-09, GitLab CE 19.4.1 in Docker

Set-up (`scripts/ci-local/ci-local.sh up`, prefix `p9-live-`, ports 8910-8914): GitLab CE
19.4.1 (`gitlab/gitlab-ce` through the Docker Hub mirror, pulled in 51 s, ready after about
3.5 minutes, 3.4-4 GiB) on `https://p9-live-gitlab:8910` with its registry on 8911 and KAS
at `/-/kubernetes-agent/`, a throwaway CA; runner 19.4.1 (Docker executor, `rootless` mode:
not privileged, seccomp and AppArmor unconfined); k3s v1.31.4 on the same network; agentk
built from the agent's v19.4.1 source (registry.gitlab.com's image layers are not
reachable here) in a `FROM scratch` image; GitLab's `gitlab-agent` chart 2.32.0 (source
archive) installed twice with `deploy/gitlab-agent/values.yaml` (`rbac.create=false`) after
`cluster-setup.yaml` and `rbac.yaml`: both agents connected within 39 s, no
ClusterRoleBinding for either. Variables: `REGISTRY_MIRROR=mirror.gcr.io`, `CI_BUILD_CA` (the
throwaway CA and this sandbox's TLS-proxy CA), `SOUNDINGS_DEPLOY="staging production"`,
the two URLs, `DEPLOY_VALUES` per environment (the environment's file, `k3s.values.yaml`,
`scripts/ci-local/values/<env>.yaml`), `HELM_TIMEOUT=5m`, `DEPLOY_IMAGE` = the
`deploy-runner.Dockerfile` tools target (alpine/k8s's 1.3 GB didn't fit the disk),
`TRIVY_CACHE_DIR` in a tmpfs. Every push had `-o ci.variable=CD_ONLY=1`; the snapshot was
the committed `HEAD` plus the Phase 9 paths from the working tree (`CI_LOCAL_PATHS`: the
product team's unfinished frontend change didn't compile at the time).

| Case | Pipeline (jobs, durations) | Result |
|---|---|---|
| CD-01 | set-up above | pass |
| CD-02 | #2: `image:build` 110 s cold (rootless BuildKit, unprivileged): `ci-2` and `sha-5e79f143` one digest, 122 MB, cache in `cache:buildkit`; later builds 11-60 s | pass |
| CD-03 | #2: `image:trivy` 48 s, database from `mirror.gcr.io/aquasec/trivy-db:2`, gate `HIGH,CRITICAL` (fixed) passed, CycloneDX artifact | pass |
| CD-04 | #2: `deploy:staging` 60 s: context `platform/soundings:soundings-staging`, first install by digest, `helm test`, smoke (cluster checks, 9 HTTP checks); environment `staging` (tier staging, `http://staging.soundings.test`) | pass |
| CD-05 | #5: build 16 s, staging revision 2 on the new digest | pass |
| CD-06 | #8: values the app rejects: `--atomic` timed out at 5 m, revision 4 "Rollback to 2", the script smoked the previous release, job failed saying so; 212/212 probes from inside the network got 200 meanwhile. #9 and #11: a release on another host (helm test passes, smoke 404): the script rolled back (revision 6, 9); the bad release served 404 for 68 s (#9), then 69 s with the bounded retries (#11) | pass after F4, F5 |
| CD-07 | `rollback:staging` played during #10's `deploy:staging`: `waiting_for_resource` for 40 s, then ran | pass |
| CD-08 | #12 release commit (`ci-local.sh bump 0.2.0`; `uv sync --locked` took the bumped lock), #13 tag `v0.2.0`: `release:check` 16 s, build 19 s (`0.2.0`, `0.2`, `ci-13`: one digest `2bdee200`), scan 46 s, staging 41 s (app says 0.2.0), `chart:package` 17 s, `release:publish` 4 s (release v0.2.0, SBOM and chart in the generic package registry, digest in the notes) | pass |
| CD-09 | #13 stopped at `deploy:production` (pipeline status `manual`); a Developer's `POST /jobs/64/play`: 403; root's: 51 s, first install of staging's digest in `soundings-production`, app says 0.2.0 | pass (Free gate) |
| CD-10 | probe pipelines #6 (protected branch) and #7 (unprotected): every kube-system, other-environment, namespace, `default`, exec and RoleBinding attempt Forbidden for both agents; production's context only on the protected ref; none without an environment; after F2, none for staging on the unprotected ref (#4 had one) | pass after F2 |
| CD-11 | `rollback:staging` 44 s (revision 9 to 6's content); `rollback:production` refused with one revision, then 24 s after a re-deploy; refused across a migration boundary: covered by the build stage (not re-run) | pass |
| CD-12 | `IMAGE_BUILDER=dind`, `runner-mode privileged`: #14-#18 failed (F7), #19: `image:build:dind` 62 s with registry cache hits, scan, staging | pass after F7 |
| CD-13 | not run: cosign's image is on ghcr.io, whose blob host this sandbox can't reach | not run |
| CD-14 | `scripts/lib/check-gitlab-ci.sh` (three new scenarios); #20 created without `CD_ONLY` lists all 12 check jobs (cancelled before running) | pass |
| CD-15 | see "GitHub" below | partly |
| CD-16 | `ci-local.sh down --images`, loop device and state removed: no `p9-live-*` container, volume, network or image left; disk 9.0 GB free before (8.6 after removing `soundings:dev`/`0.1.0`), 8.4 GB after (the product team's database volumes grew meanwhile) | pass |

#21, the last pipeline (every fix, rootless build, `DEPLOY_FORCE=1` because GitHub had taken
staging over): build 12 s, scan 25 s, staging 31 s, success.

### Defects the live run found (fixed)

| ID | Where | Defect | Fix |
|---|---|---|---|
| F1 | both CIs | `COSIGN_IMAGE`'s digest is ghcr's `cosign:v3.1.3-dev`; GitHub labelled it `v3.1.3` | pinned to `v3.1.3`'s index digest `9e5c2f2e…` (hash of the manifest) |
| F2 | `.gitlab/agents/soundings-staging/config.yaml` | no `protected_branches_only`: a job with `environment: staging` on any pushed branch got the staging context (and could read the namespace's Secrets) | `protected_branches_only: true` |
| F3 | `.gitlab-ci.yml` `.deploy` | Helm warned twice per call that the injected `KUBECONFIG` is world-readable | `chmod 600 "$KUBECONFIG"` |
| F4 | `scripts/deploy.sh` | after the script rolled back a release that failed its smoke, the manual rollback targeted that release (Helm lists it as superseded); after an automatic rollback it targeted a copy of the running content | failed revisions get `soundings.io/verify=failed` and are skipped; "Rollback to N" counts as N's content; `status` shows it |
| F5 | `scripts/deploy-smoke.sh` | 30 tries per check: a broken release could serve 5 minutes before the rollback | after one check uses its tries, the others get one |
| F6 | `deploy-env.yml` | `DEPLOY_VALUES`, `HELM_TIMEOUT` couldn't be set on GitHub | passed from `vars` (empty = default) |
| F7 | `image:build:dind`, GitHub `image` | with an internal CA: the buildx builder trusted it only for the push registry (base images from the mirror failed); BuildKit fetches registry tokens through the client (GitLab's `/jwt/auth`), which didn't trust it; on dind's bridge the builder resolved names through 8.8.8.8 | CA for the base images' registries too, `SSL_CERT_FILE` for the client, `--driver-opt network=host` (GitLab) |
| F8 | `scripts/deploy.sh` | Helm copies the target's labels onto a rollback revision: a CI taking over with a rollback left the other CI's name on it | rollbacks relabel `deployed-by` and clear `verify` |

### GitHub (CD-15)

No runner can register here (GitHub's release downloads are blocked), so no workflow ran on
GitHub. What ran: actionlint 1.7.12, zizmor 1.30.1 (no findings) and the GitLab check after
every change; `ci-local.sh github` ran `deploy-env.yml`'s step script (read from the file) in
a pod on the same k3s: staging as the ARC scale set's ServiceAccount (`deploy/ci/arc-rbac.yaml`,
in-cluster credentials) refused to take over GitLab's release, then with `DEPLOY_FORCE=1`
deployed 0.2.0 (52 s, step summary written); production from a pod whose own ServiceAccount
can do nothing, with `KUBECONFIG_DATA` built as the operator guide says, rolled back (10 s,
and again after F8: the takeover now sticks, GitLab's next rollback is refused). Not run:
the `image` job's buildx on GitHub's runners (the same commands as `image:build:dind`, which
ran), GHCR, ARC itself, environments with required reviewers, `deploy.yml`'s
`gh release download`, Dependabot.

### Not verified here

Premium's protected environments and deployment approvals (CE is Free); `access_as`
impersonation; the Kubernetes executor (the Docker executor ran both build paths); the
default `DEPLOY_IMAGE` (alpine/k8s) in a live job; cosign (CD-13); the lint/test/e2e/k3s jobs
(skipped by `CD_ONLY`, unchanged by Phase 9). The agentk binary reports version v0.0.0, so
KAS warns about it on every request.
