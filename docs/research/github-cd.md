# Research R9: GitHub Actions delivery to an on-prem cluster, and supply-chain hygiene (verified 2026-10-09)

> Phase 9 research by a researcher subagent. It feeds the GitHub half of continuous
> delivery: build and push, staging on `main`, production on `vX.Y.Z` tags behind a
> gate, and one deploy script that both CIs share. **Read** means read in a primary
> source. **Run** means run here. Anything not run here says **Not verified**.

**How the sources were read.** docs.github.com and docs.docker.com are blocked by this
sandbox's proxy. Their sources are public, so they were read directly:

- GitHub's docs: `github/docs` at commit `be38ec5` (2026-10-09), sparse clone of
  `content/actions`, `content/packages`, `data/reusables`, `data/features` and Dependabot.
  Liquid `{% ifversion fpt %}` blocks were resolved by hand: **fpt** means github.com
  Free, Pro and Team; **ghec** means Enterprise Cloud; **ghes** means Enterprise Server.
- Docker's docs: `docker/docs@main`.
- Action READMEs and `action.yml` files: `raw.githubusercontent.com` at the tags listed
  below.
- Commit SHAs: `git ls-remote`, dereferenced (`^{}`) to commits, not tag objects.
- Image digests: `mirror.gcr.io` manifests. `gh api` is limited to this session's repos,
  so release dates are not recorded here.
- Kubernetes: `kubernetes/website@main`.
- Trivy: the `aquasecurity/trivy@v0.75.0` docs and advisory GHSA-69fq-xp46-6x23.
- cosign: `sigstore/cosign@v3.1.3` source and docs.

## Versions (latest on 2026-10-09)

Copy these pins as they are. The trailing comment is what Dependabot updates.

```yaml
actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1            # v7.0.1
docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069  # v4.4.1
docker/login-action@dbcb813823bdd20940b903addbd779551569679f         # v4.6.0
docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302      # v6.2.0
docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc    # v7.4.0 (runs on node24)
actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9     # v7.0.2
actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333   # v8.0.2
actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97        # v7.0.0
actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1          # v7.1.0
actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6              # v4.2.2 (Enterprise Cloud or public repos only)
# actionlint v1.7.12 is commit 914e7df21a07ef503a81201c76d2b11c789d3fca; it ships no action.yml (§5).
# Not recommended here (see section 4): aquasecurity/trivy-action v0.36.0 @ed142fd0…,
# aquasecurity/setup-trivy v0.3.1, anchore/sbom-action v0.24.3, sigstore/cosign-installer v4.1.2,
# azure/setup-helm v5.0.1. Each of these downloads its tool from GitHub releases at run time.
```

| Thing | Version | Pin by digest (through `mirror.gcr.io`, i.e. Docker Hub) |
|---|---|---|
| Trivy | 0.75.0 (repo uses 0.67.2) | `aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa` |
| syft | v1.54.1 | `anchore/syft:v1.54.1@sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa` |
| actionlint | 1.7.12 | `rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667` |
| BuildKit SBOM scanner | stable-1 | `docker/buildkit-syft-scanner:stable-1@sha256:ae4f3b554449e7e25548e7d8ccc029d17357348e30c6e3df01b92bc93654d6a9` |
| BuildKit | v0.25.1 / rootless | `moby/buildkit:v0.25.1@sha256:79cc…c1b6`, `moby/buildkit:rootless@sha256:65ec…3855` |
| Helm | 3.22.0 and 4.3.0 (repo uses 3.16.2) | `alpine/helm:3.16.2@sha256:a19a2968fd672336d39771f6c899781424d725229148656dbc2a1e305003cdec`; `/usr/bin/helm` is the official static binary |
| cosign | v3.1.3 | `ghcr.io/sigstore/cosign/cosign` (ghcr: mirror it yourself) |
| zizmor | 1.30.1 | PyPI wheels (manylinux x86_64/aarch64, musllinux) |
| ARC charts | `gha-runner-scale-set(-controller)` 0.15.0 | `oci://ghcr.io/actions/actions-runner-controller-charts/…`; images `ghcr.io/actions/gha-runner-scale-set-controller:0.15.0`, `ghcr.io/actions/actions-runner:2.338.0` |
| Runner app | v2.338.0 | the ARC runner image builds it; it has curl, jq, git, the docker CLI and buildx 0.37.2, but no helm or kubectl |

## Summary

1. **Deploy jobs run on runners inside the network.** Use Actions Runner Controller (ARC)
   runner scale sets in the cluster, one per environment. Each runner pod's
   ServiceAccount is the deploy identity, bound by a namespaced Role to `soundings-<env>`
   only. Runners connect *out* to GitHub on 443. The Kubernetes API is never exposed, and
   GitHub stores no cluster credential (§1).
2. **A runner label is not an access control.** Any workflow that can use the runner
   group can target the production scale set. Only Enterprise Cloud/Server can restrict
   a runner group to named workflows. On other plans, people with write access could
   bypass the production approval this way. The doc offers two hardenings (§1.5):
   - a credential released only by the `production` environment;
   - GitHub OIDC trusted by the API server.
3. **Approvals need Enterprise for private repos.** Required reviewers, wait timers and
   admin-bypass control work on **public repos or Enterprise** only. Environments,
   environment secrets and variables, and branch/tag deployment policies work on private
   repos from **Pro/Team** up.
   - Enterprise or public repo: use required reviewers + "prevent self-review" + a `v*`
     tag policy.
   - Team: a `workflow_dispatch` "Deploy production" run on the tag, plus the environment's
     tag policy and a tag ruleset (§2). This is the same shape as the protected manual job
     on GitLab Free.
4. **Serialise deploys** with job-level `concurrency: {group: soundings-deploy-<env>,
   cancel-in-progress: false}`. Never cancel a running `helm upgrade`. Also make
   `ci.yml`'s workflow-level `cancel-in-progress` apply to pull requests only, or a push
   to main will cancel an in-flight deploy (§2.6).
5. **Build with `docker/build-push-action` on a GitHub-hosted runner** and push to
   `ghcr.io` with `GITHUB_TOKEN` (`packages: write`). Use `vars` to switch to another
   registry or a self-hosted build runner.
   - Tags: `sha-<8 chars>` (GitLab's `CI_COMMIT_SHORT_SHA` length), `X.Y.Z` and `X.Y`, no
     `latest`.
   - The CA goes in through `secret-files: build_ca=…`.
   - Cache: registry cache.
   - BuildKit provenance works offline. BuildKit SBOM attestations need the scanner image
     from a mirror.
   - GitHub artifact attestations need Sigstore and the internet, and Enterprise Cloud
     for private repos (§3).
6. **Pin every action by commit SHA**, and turn on the repo or org policy that *requires*
   it. Dependabot (`github-actions` + `docker`, default 3-day cooldown) keeps the pins
   current. Give each job least-privilege `permissions`, and set
   `persist-credentials: false`.
   - Why: the March 2026 Trivy compromise force-pushed 76 of 77 `trivy-action` tags.
     SHA pins and digest-pinned images were not affected.
   - Run Trivy and syft from **digest-pinned images**, not their actions (§4).
7. **cosign with a key works offline** in v3.1.3:
   `--use-signing-config=false --tlog-upload=false` with `--key` (read in the source;
   **Not verified** by running). Verify with `--insecure-ignore-tlog=true` (§4.6).
8. **Validate workflows offline here.** actionlint 1.7.12 installs with
   `go install …@v1.7.12` through proxy.golang.org (run), or from the Docker Hub image.
   The pip and npm packages don't work. zizmor 1.30.1 from PyPI runs fully offline (run).
   On today's `ci.yml`:
   - actionlint is clean, except 3 shellcheck SC2086 notes;
   - zizmor reports 24 unpinned `uses:` and 9 `persist-credentials` findings;
   - actionlint 1.7.12 rejects the new `concurrency.queue` key (§5).

---

## 1. Self-hosted runners for deploys

### 1.1 Routing: labels, groups, scale-set names

- A job goes to an online, idle runner that matches **all** of its `runs-on` labels and
  its group. If none matches, the job stays queued for up to 24 hours. It does not fail
  at once (reference/runners/self-hosted-runners.md, "Routing precedence"). Registered
  runners get `self-hosted`, an OS and an architecture label, plus any custom labels.
- `runs-on: {group: <runner group>, labels: [...]}` needs both to match.
- `runs-on` may use the `vars` context: `runs-on: ${{ vars.X || 'default' }}`, or
  `fromJSON(vars.X)` for an array (contexts.md, run here with actionlint).
- **ARC:** `runs-on: <scale set name>`. The name is the Helm release name unless
  `runnerScaleSetName` is set, and is unique within its runner group.
  - Since chart 0.14.0 a scale set can also carry labels (0.13.1 has no such key). GitHub's page calls the
    values key `runnerScaleSetLabels`, but the 0.15.0 chart's key is **`scaleSetLabels`**.
    The chart renders it into the CRD field `runnerScaleSetLabels`. Read in
    `charts/gha-runner-scale-set/{values.yaml,templates/autoscalingrunnerset.yaml}` at tag
    `gha-runner-scale-set-0.15.0`.

### 1.2 Network: outbound only

Runners make **outbound** HTTPS (443) connections to GitHub. Nothing connects in.

- Essential: `github.com`, `api.github.com`, `*.actions.githubusercontent.com`.
- Downloading actions: `codeload.github.com`.
- Logs, artifacts and caches: `results-receiver.actions.githubusercontent.com` and
  `*.blob.core.windows.net`.
- OIDC tokens: `*.actions.githubusercontent.com`.
- Runner self-updates: `objects.githubusercontent.com`, `github-releases.…`, among others.
- ghcr: `ghcr.io`, `*.pkg.github.com`, `pkg-containers.githubusercontent.com`.

Source: data/reusables/actions/runner-essential-communications.md.

So the cluster's API server and ingress stay private. The runner namespace needs egress
to GitHub and to the API server and nothing else. Two consequences:

- **"No public internet at run time" holds only on GitHub Enterprise Server.** With
  github.com, runners must reach GitHub. That is egress to GitHub only, not an opening
  into the cluster.
- **Keep the deploy job's `uses:` down to `actions/checkout`.** Every other action is
  another download from codeload and another supply-chain dependency. Put the logic in
  `scripts/deploy.sh`.

### 1.3 Security of self-hosted runners

From reference/security/secure-use.md, "Hardening for self-hosted runners":

- Self-hosted runners "can be persistently compromised by untrusted code in a workflow".
  They "should almost never be used for public repositories", because any user can open a
  pull request.
- On private repos, "anyone who can fork the repository and open a pull request
  (generally those with read access…)" can compromise them. Environments with required
  reviewers protect environment *secrets*, but "these workflows are not run in an
  isolated environment and are still susceptible to the same risks when run on a
  self-hosted runner".
- Runner groups are the boundary.
  - Org owners restrict a group to **selected repositories**.
  - Public repos can't use a group unless that is explicitly allowed.
  - On Enterprise (ghec/ghes) a group can also be restricted to **selected workflows**:
    `org/repo/.github/workflows/x.yml@refs/heads/main`. Only jobs defined directly in
    those files get access.
  - Plan availability: the docs disagree. One reusable says the Team plan; the
    manage-access page says Team or Free. Check your org's settings page.
- Use **ephemeral / just-in-time runners** (one job each). ARC's runners are ephemeral
  JIT runners: one pod per job, deleted afterwards (concepts/runners/actions-runner-controller.md).
- Deploy jobs never run on `pull_request` events, and fork pull requests never reach the
  deploy runner group. Keep "Run workflows from fork pull requests" off for private repos.

### 1.4 ARC in the cluster

The parts (all read):

- Two Helm charts, 0.15.0:
  - `gha-runner-scale-set-controller`: install once, e.g. in `arc-systems`.
  - `gha-runner-scale-set`: one release per scale set, in a different namespace from the
    controller (GitHub's stated security practice).
- GitHub only supports the Helm install of these "autoscaling runner sets". The legacy
  community ARC is out of scope, and GitHub Support may decline cases with template or
  ServiceAccount customisation (support-for-arc.md).
- **Authentication:** a GitHub App, recommended for repo or org scope, stored in a
  pre-created Secret passed as `githubConfigSecret: <name>`. Never put it in plain values.
  - App permissions for an org-level scale set: Organization "Self-hosted runners:
    Read and write" and Repository "Metadata: Read-only".
  - Registering at repo scope also needs "Administration: Read and write".
  - Enterprise-level runners need a classic PAT.
- **Air-gapped install.** Copy these into the internal registry:
  - the two OCI charts, e.g. `helm pull oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set --version 0.15.0`
    then `helm push` to Harbor, or `oras copy`;
  - the controller image (the listener uses the same image);
  - the runner image.

  Then set `image.repository` / `imagePullSecrets` on the controller and
  `template.spec.containers[name=runner].image` on the scale set. The container **must**
  be named `runner` (deploy-runner-scale-sets.md, "Using a private container registry").
  - TLS-intercepting proxies and private CAs: `githubServerTLS.certificateFrom.configMapKeyRef`
    with `runnerMountPath`.
  - Outbound proxy: `proxy.http/https/noProxy`.
- **Container mode:** leave `containerMode` unset. The deploy job runs `helm` and `curl`
  directly in the runner container.
  - `dind` needs `privileged: true`.
  - `kubernetes` mode gives the runner SA rights to create pods in its own namespace.
  - Neither is needed for deploys.
- **The runner image has no helm.** Build a small `soundings-deploy-runner` image without
  downloading from get.helm.sh:
  ```dockerfile
  FROM ${MIRROR}/actions/actions-runner:2.338.0
  COPY --from=${MIRROR}/alpine/helm:3.22.0 /usr/bin/helm /usr/local/bin/helm
  ```
  kubectl is optional: `helm` covers upgrade, test, rollback and history.
- **The pod's ServiceAccount is the deploy identity.**
  - Without `template.spec.serviceAccountName`, the chart gives runner pods a
    **no-permission** ServiceAccount it creates itself.
  - Set `template.spec.serviceAccountName: soundings-deployer` and bind that SA. Read in
    `templates/autoscalingrunnerset.yaml` lines 254-258 and
    `no_permission_serviceaccount.yaml` at 0.15.0.
  - helm and kubectl use client-go, which falls back to in-cluster config (the mounted SA
    token, `KUBERNETES_SERVICE_HOST`) when there is no kubeconfig. So no kubeconfig or
    Secret is needed. The script must pass `--namespace` explicitly: in-cluster, the
    default is the runner's own namespace. **Not verified** here (no ARC run).
- **One scale set per environment**, in its own namespace, with its own SA:
  - `arc-soundings-staging` / scale set `soundings-staging`: SA bound in `soundings-staging`;
  - `arc-soundings-production` / `soundings-production`: SA bound in `soundings-production`.

  A staging job then physically cannot touch production. Settings for both:
  - `minRunners: 0` and `maxRunners: 1`. One runner also serialises deploys at the
    infrastructure level.
  - `runnerGroup: soundings-deploy`, restricted to the Soundings repository.

The deployer Role is namespaced in `soundings-<env>`. It covers what the chart creates,
plus Helm's release Secrets and `helm test`:

```yaml
rules:
  - apiGroups: [""]
    resources: [configmaps, secrets, services, serviceaccounts, persistentvolumeclaims, pods]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [""]
    resources: [pods/log, events]
    verbs: [get, list, watch]
  - apiGroups: [apps]
    resources: [deployments, statefulsets]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [apps]
    resources: [replicasets]
    verbs: [get, list, watch]
  - apiGroups: [batch]
    resources: [jobs]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [networking.k8s.io]
    resources: [ingresses, networkpolicies]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [policy]
    resources: [poddisruptionbudgets]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [autoscaling]
    resources: [horizontalpodautoscalers]
    verbs: [get, list, watch, create, update, patch, delete]
  # only if enabled in values: gateway.networking.k8s.io/httproutes, monitoring.coreos.com/servicemonitors
```

The RoleBinding in `soundings-<env>` names the runner namespace's SA as its subject.
Cross-namespace subjects are allowed. Notes on this Role:

- The chart creates no Role or RoleBinding, so the deployer needs no `bind` or `escalate`.
- `secrets` access is inherent to Helm, which stores releases as Secrets. It also means
  the deployer can read operator-created `existingSecret`s in its namespace. Accept that,
  or move those Secrets elsewhere through an external-secrets operator.
- kagent `Agent` / `RemoteMCPServer` examples go into the kagent namespace. Keep
  `kagent.examples` off in CD values, or add a second Role there.
- The chart's NetworkPolicy admits only the ingress controller (and kagent). So run the
  smoke test through the public URL rather than the Service, or allow the runner
  namespace.

### 1.5 Where the credential lives: three modes, one script

`scripts/deploy.sh` should not care how it is authenticated. It uses whatever kubeconfig
or in-cluster config it finds, plus optional `KUBE_CONTEXT` (the GitLab agent sets a
context).

| Mode | How | Stored credential | Gate on production | Needs |
|---|---|---|---|---|
| **A. ARC SA** (recommended default) | Runner pod SA bound to the namespace | none | Environment rules gate the *job*, but any workflow in the repo can target the production scale set: an Enterprise runner-group workflow restriction, or trusted writers | ARC |
| **B. Environment secret** | Runner SA has no rights. A namespaced deployer token or kubeconfig is a `production` **environment secret** (`KUBECONFIG_DATA`). The script writes it to a 0600 temp file | Yes, in GitHub, but usable only inside the network (the API server is not exposed) | The secret is released only to jobs that pass the environment's tag policy (and reviewers where available). A branch workflow gets nothing | Pro/Team+ for private repos |
| **C. GitHub OIDC → API server** | `permissions: id-token: write`. The job fetches a JWT and helm uses `--kube-token`. The API server trusts `https://token.actions.githubusercontent.com` through `AuthenticationConfiguration` (`--authentication-config`; beta and on by default since 1.30, GA in 1.34). A CEL rule `claims.repository == 'org/soundings' && claims.environment == 'production'` maps to a user bound to the Role | none | GitHub issues `environment: production` only to jobs that passed its protection rules | Control-plane flags; the API server must reach the issuer for discovery and JWKS (`discoveryURL` may point at an internal copy, but keys rotate). On GitHub Enterprise Server the issuer is internal (`https://HOST/_services/token`) |

Sources: reference/security/oidc.md (claims; `sub` = `repo:ORG/REPO:environment:NAME`;
repos created after 2026-07-15 use the immutable form `repo:org@ID/repo@ID:…`) and
kubernetes/website authentication.md plus the feature-gate page
`StructuredAuthenticationConfiguration`. A kubeconfig on a GitHub-hosted runner, or an
API server exposed to the internet, is out (product-owner decision).

**Recommendation:** document A as the default. Offer B as the hardening for
non-Enterprise orgs that don't trust every writer with production. Mention C for
clusters whose administrators can set API-server flags. The script and the workflows are
the same in all three. Only the scale set's SA and an optional secret differ.

## 2. Environments

### 2.1 What each plan gets

Sources: reference/workflows-and-actions/deployments-and-environments.md and
gated-features/environments.md.

| Feature | Public repo (any plan) | Private, Free | Private, Pro/Team | Private, Enterprise Cloud / Server |
|---|---|---|---|---|
| Environments, env secrets, env variables | yes | **no** | yes | yes |
| Deployment branch and tag policies | yes | no | yes | yes |
| Required reviewers, wait timer | yes | no | **no** | yes |
| Disallow admin bypass | yes | no | no | yes |
| Custom protection rules (GitHub Apps) | yes | no | no | yes |
| Runner groups restricted to workflows | no | no | no | yes |
| Rulesets: tag protection, branch rules | yes | no | yes | yes |
| Artifact attestations | yes | no | no | Enterprise Cloud |

### 2.2 Protection rules

- **Required reviewers**: up to six users or teams, each needing at least read access.
  One approval is enough. Optional **"prevent self-reviews"**: whoever triggered the run
  can't approve it.
- **Wait timer**: 1-43,200 minutes. It doesn't count as billable time.
- **Deployment branches and tags**: none, protected branches only, or selected name
  patterns.
  - Patterns are matched against `GITHUB_REF` with Ruby `File.fnmatch`, and `*` does not
    match `/`.
  - Branch rules and tag rules are configured **separately**.
  - Production: tag rule `v*.*.*`. Staging: branch rule `main`.
- **Admins bypass by default.** Turn that off for production where the plan allows.
- **Environment secrets and variables** go only to jobs that reference the environment,
  and secrets only after approval. On self-hosted runners such secrets should still be
  "treated with the same level of security as repository and organization secrets".
- `environment: {name, url, deployment: false|expr}`: `deployment: false` skips the
  deployment record, while reviewers and the wait timer still apply.

### 2.3 Tags are code: protect them

A tag-triggered run executes the workflow and `scripts/deploy.sh` **as of the tagged
commit**. Add these rulesets (Pro/Team and up for private repos):

- **Tag ruleset on `refs/tags/v*`**: restrict creation, update and deletion to maintainers.
  Released tags never move.
- **Branch ruleset on `main`**: require pull requests and status checks, plus CODEOWNERS
  for `.github/workflows/**`, `scripts/deploy.sh` and `deploy/**`.

### 2.4 Production gate by plan

This mirrors GitLab Free versus Premium.

- **Enterprise, or a public repo:** the tag push runs build, scan and then
  `deploy-production` with `environment: production`, which waits for a required
  reviewer. Turn on "prevent self-review" and "disallow bypass".
- **Pro/Team, private repo:** there are no reviewers.
  - The tag push builds, scans and publishes the release.
  - Production is deployed by a manual run, **"Run workflow" → Use workflow from: tag
    `vX.Y.Z`**. That makes `GITHUB_REF=refs/tags/vX.Y.Z`, so the environment's tag
    policy matches.
  - Only people with write access can dispatch (manually-run-a-workflow.md;
    `workflow_dispatch` must be on the default branch).
  - Switch with one repository variable, `SOUNDINGS_PRODUCTION_GATE=manual` (default
    `environment`). Combine it with the tag ruleset and Mode B for a real two-person rule.
- **Free, private repo:** there are no environments, so there is no gate and no
  environment secrets. Use `workflow_dispatch` only, and document it as unsupported for
  production.

### 2.5 Rollback

`rollback.yml` is a `workflow_dispatch` with inputs:

- `environment`: input `type: environment`;
- `revision`: string; empty means the previous revision.

It runs on that environment's runner with `environment: <input>` and the same concurrency
group, and calls `scripts/deploy.sh rollback`. Production rollbacks then go through the
same gate. The job's `runs-on` can come from the environment's variable
`SOUNDINGS_DEPLOY_RUNNER`.

### 2.6 Serialising deploys

From data/reusables/actions/actions-group-concurrency.md:

- A group has **at most one running and one pending** job. A newer pending job
  **cancels** the older pending one. That suits staging: the newest commit wins.
- Groups are per repository and case-insensitive, with FIFO order "not guaranteed".
- github.com (not GHES) also has `queue: max` (up to 100 pending). **actionlint 1.7.12
  rejects it** ("unexpected key "queue"", run here), so don't use it yet.
- **Never `cancel-in-progress: true` on a deploy job.** Killing `helm upgrade` mid-way can
  leave the release `pending-upgrade`, which blocks the next upgrade.
- `ci.yml` today has a workflow-level `concurrency: ci-${{ github.ref }}` with
  `cancel-in-progress: true`. If deploy jobs live in `ci.yml`, a second push to `main`
  cancels the first run, *including its running deploy*. Change it to:
  ```yaml
  concurrency:
    group: ci-${{ github.ref }}
    cancel-in-progress: ${{ github.event_name == 'pull_request' }}
  ```
- **Not verified:** whether a job that is waiting for approval already holds its
  concurrency slot.

## 3. Building and pushing

### 3.1 Actions and inputs

From the READMEs and `action.yml` files at the pinned tags.

- **`docker/setup-buildx-action`** (driver `docker-container` by default).
  - On GitHub-hosted runners nothing needs configuring.
  - Through a mirror: `driver-opts: image=<mirror>/moby/buildkit:v0.25.1`.
  - CA for a registry: `buildkitd-config-inline` with `[registry."harbor.internal"] ca=[…]`.
  - `version:` downloads buildx from GitHub releases; omit it to use the runner's own.
- **`docker/login-action`.**
  - ghcr: `registry: ghcr.io`, `username: ${{ github.actor }}`,
    `password: ${{ secrets.GITHUB_TOKEN }}`, and the job needs `packages: write`.
  - Another registry: `registry: ${{ vars.IMAGE_REGISTRY }}` with
    `secrets.REGISTRY_USERNAME` / `REGISTRY_PASSWORD`.
- **`docker/metadata-action`** lowercases image names (ghcr requires it).
  ```yaml
  images: ${{ vars.IMAGE_REPOSITORY || format('ghcr.io/{0}/soundings', github.repository_owner) }}
  flavor: latest=false
  tags: |
    type=sha,prefix=sha-,enable=${{ github.ref_type == 'branch' }}
    type=semver,pattern={{version}}
    type=semver,pattern={{major}}.{{minor}}
  env: { DOCKER_METADATA_SHORT_SHA_LENGTH: "8" }
  ```
  - `type=sha` defaults to 7 characters. 8 matches GitLab's `CI_COMMIT_SHORT_SHA`, so both
    CIs name an image the same way.
  - Pre-releases (`v1.2.0-rc.1`) produce only `{{version}}`.
  - `latest=auto` would add `latest` on tags; turn it off.
  - Output `version` is `1.2.3` on a tag.
- **`docker/build-push-action`** (node24; keep self-hosted runners current):
  ```yaml
  push: true
  tags: ${{ steps.meta.outputs.tags }}
  labels: ${{ steps.meta.outputs.labels }}
  build-args: |
    VERSION=${{ github.ref_type == 'tag' && steps.meta.outputs.version || github.sha }}
    VCS_REF=${{ github.sha }}
    SOURCE_URL=${{ github.server_url }}/${{ github.repository }}
    UBUNTU_MIRROR=${{ vars.UBUNTU_MIRROR }}
    PIP_INDEX_URL=${{ vars.PIP_INDEX_URL }}
    UV_DEFAULT_INDEX=${{ vars.UV_DEFAULT_INDEX }}
    NPM_CONFIG_REGISTRY=${{ vars.NPM_CONFIG_REGISTRY }}
  secret-files: ${{ env.CA_FILE != '' && format('build_ca={0}', env.CA_FILE) || '' }}
  cache-from: type=registry,ref=<repo>:buildcache
  cache-to: type=registry,ref=<repo>:buildcache,mode=max
  ```
  - Empty build args are harmless: the Dockerfile treats "" as unset.
  - `secret-files` maps to `--secret id=build_ca,src=…`, which the Dockerfile reads at
    `/run/secrets/build_ca`. Write the `CI_BUILD_CA` secret to `$RUNNER_TEMP/ca.pem` in an
    earlier step and set `CA_FILE`.
  - Output `digest` (and `metadata`) becomes a job output, so deploy pins
    `repo@sha256:…`.
  - GitHub's build-record artifact and job summary are on by default
    (`DOCKER_BUILD_RECORD_UPLOAD`, `DOCKER_BUILD_SUMMARY`). Turn them off on self-hosted
    runners without artifact storage access.
  - For VERSION on `main`, use `${GITHUB_SHA::8}` from a step output if the version must
    equal the tag `sha-xxxxxxxx`.
- **Cache:** `type=registry` works everywhere. `type=gha` uses GitHub's cache service:
  fine on GitHub-hosted runners, but it needs internet from a self-hosted one.

### 3.2 Attestations (Docker docs, build/ci/github-actions/attestations.md)

- **Defaults.** build-push-action adds a **provenance** attestation by default: `mode=max`
  for public repos, `mode=min` for private ones. Nothing is added with `load: true` or the
  docker exporter.
- **Max provenance records build-arg values.** So never put credentials in mirror URLs
  such as `PIP_INDEX_URL=https://user:pass@…`. Pass them as BuildKit secrets, or set
  `provenance: mode=min`.
- **SBOM attestations** need `sbom: true`. They are SPDX, generated by the
  `docker/buildkit-syft-scanner` image. Through a mirror:
  `attests: type=sbom,generator=<mirror>/docker/buildkit-syft-scanner:stable-1`.
- **Offline.** Both are produced by BuildKit itself, so neither needs the internet beyond
  pulling that scanner image.
- **Effect on the pushed image.** With attestations the tag becomes an image *index* with
  `unknown/unknown` attestation manifests. The deploy pins the index digest, which works.
  Very old registries or UIs may show the extra entries.
- **GitHub artifact attestations** (`actions/attest`, `attestations: write` +
  `id-token: write`) are a different thing:
  - they sign through Sigstore: the public-good Fulcio/Rekor for public repos, GitHub's own
    instance for private ones;
  - private repos need **Enterprise Cloud**;
  - the runner needs internet;
  - they can be verified offline later with `gh attestation verify` plus a downloaded
    bundle and trusted root (verify-attestations-offline.md).
  - Optional, only where the plan allows. The SBOM release asset (§4.5) covers the
    requirement.

### 3.3 Where to build

- **Default: GitHub-hosted `ubuntu-24.04`** (`vars.SOUNDINGS_BUILD_RUNNER` overrides it).
  Docker and buildx are present, no mirrors are needed, and the push goes to ghcr.
- **To pull from ghcr, the cluster needs:**
  - egress to ghcr, or an internal pull-through cache (Harbor proxy project);
  - for a private package, a pull secret (`image.pullSecrets` exists in the chart). ghcr
    accepts **classic PATs only** (`read:packages`, a bot account; packages-classic-pat-only.md).
- **Internal registry or internal mirrors:** build on a self-hosted build runner, never the
  deploy scale sets. Options:
  - buildx `driver: kubernetes` with `driver-opts: rootless=true` (BuildKit pods; needs
    RBAC in a build namespace);
  - `driver: remote` to a standing rootless `buildkitd` (mTLS);
  - a VM runner with Docker.

  The ARC runner image has the docker CLI and buildx but no daemon. **Not verified** here.
- **Multi-registry:** push to one registry and copy by digest (`crane copy` / `oras` /
  `skopeo`), so digests and signatures stay identical (publish-docker-images.md note).

## 4. Supply chain

### 4.1 Pin actions by full commit SHA, and enforce it

- secure-use.md: "Pinning an action to a full-length commit SHA is currently the only way
  to use an action as an immutable release." Check that the SHA comes from the action's
  repository, not a fork.
- github.com has repository- and organisation-level **policies requiring SHA-pinned
  actions** (GHES ≥ 3.19; feature `actions-blocklist-sha-pinning`). Turn the policy on
  once the workflows are pinned.
- **Why it matters (GHSA-69fq-xp46-6x23 / CVE-2026-33634, on CISA's KEV list):**
  - On 2026-03-19, from about 17:43 UTC, attackers holding a leaked token force-pushed
    **all `trivy-action` tags 0.0.1-0.34.2** and **`setup-trivy` v0.2.0-v0.2.6** to
    commits that stole CI secrets, for about 12 hours.
  - They also published Trivy **v0.69.4** (binary and images) and Docker Hub
    `aquasec/trivy:0.69.5/0.69.6` (03-22/23).
  - Only `trivy-action` 0.35.0 survived, thanks to an immutable release. Images
    referenced **by digest** were not affected.
  - "SHA pins to commits before 2025-04-09" of trivy-action were affected too, so a SHA
    pin is only as good as the commit it names. Keep pins current.
  - The repo's `aquasec/trivy:0.67.2` (by tag) was not among the hijacked tags. Pin it by
    digest anyway.

### 4.2 Keep pins current: Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    groups: { actions: { patterns: ["*"] } }
  - package-ecosystem: docker          # FROM lines in Dockerfile (digest pins)
    directory: /
    schedule: { interval: weekly }
```

- Dependabot updates `owner/action@<sha> # vX.Y.Z` and the trailing comment on the same
  line. It ignores local actions and `docker://` references.
- It applies a **default 3-day cooldown** to version updates (github.com; GHES > 3.21),
  configurable with `cooldown`. That gives time for a hijack like Trivy's to be noticed.
  Security updates have no cooldown.
- Ecosystems `helm`, `npm` and `pip`/uv also exist if wanted.
- Image references in CI variables (`TRIVY_IMAGE`) aren't seen. Keep them in one place
  and update them by hand.

### 4.3 Least privilege per job

- Workflow level: `permissions: {}` or `contents: read`, as `ci.yml` has now.
- Grant per job, using the permissions table in github-token-scope-descriptions.md:

| Job | Permissions |
|---|---|
| checks, scan, deploy-*, rollback | `contents: read` |
| image | `contents: read`, `packages: write` (ghcr); + `attestations: write`, `id-token: write` only with `actions/attest` |
| release (tags) | `contents: write` (create the GitHub Release, upload the SBOM) |
| deploy, Mode C only | + `id-token: write` |

- `actions/checkout` with `persist-credentials: false` everywhere. zizmor's `artipacked`
  flags 9 checkouts in today's `ci.yml`.
- Never interpolate `${{ github.event.* }}` into `run:`. Pass values through `env:`.
  actionlint and zizmor both catch this (run).
- Newer permission keys (`artifact-metadata`, `vulnerability-alerts`) exist. actionlint
  1.7.12 accepted `artifact-metadata`.

### 4.4 OIDC (`id-token: write`)

- The JWT's issuer is `https://token.actions.githubusercontent.com`; on GHES it is
  `https://HOST/_services/token`. Its claims include `repository`, `ref`, `environment`,
  `job_workflow_ref` and `sha`. Use it for registries or Vault that federate with it
  (e.g. JFrog, Vault).
- An on-prem Kubernetes cluster *can* trust it, as in Mode C (§1.5). Any OIDC-federated
  registry pull or push also needs the runner to reach the issuer endpoints, which
  github.com runners always can.
- Not needed for Mode A.

### 4.5 Trivy and syft: images, not actions

- **Prefer the images.**
  - `aquasecurity/trivy-action` → `setup-trivy` downloads the Trivy binary from GitHub
    releases at run time, which is a problem on self-hosted runners. It was also the
    vector in March.
  - `anchore/sbom-action` and `cosign-installer` download from GitHub releases too.
  - Running a **digest-pinned image** (`docker run`) is the same command on GitHub-hosted
    runners, self-hosted runners and GitLab, and it mirrors like any other image.
- **Trivy 0.75.0 defaults.**
  - DB: `--db-repository mirror.gcr.io/aquasec/trivy-db:2,ghcr.io/aquasecurity/trivy-db:2`.
    Java DB likewise. Override both with `TRIVY_DB_REPOSITORY` /
    `TRIVY_JAVA_DB_REPOSITORY` for air-gapped use.
  - Gate: `trivy image --exit-code 1 --severity ${TRIVY_SEVERITY:-CRITICAL} [--ignore-unfixed] repo@digest`.
  - SBOM: `trivy image --format cyclonedx --output soundings-X.Y.Z.cdx.json repo@digest`,
    or `--format spdx-json`.
  - `syft repo@digest -o cyclonedx-json` is an equivalent from `anchore/syft`.
- **Attach the SBOM to the release.** In the tag's `release` job (`contents: write`):
  `gh release create "$GITHUB_REF_NAME" soundings-*.cdx.json --verify-tag`. `gh` is on
  GitHub-hosted runners; elsewhere use the REST "upload release asset" call with curl.

### 4.6 cosign with a key (optional)

Keyless signing needs Fulcio/Rekor and the internet. With a key, cosign v3.1.3 signs
offline. Read in `cmd/cosign/cli/signcommon/common.go` and `options/sign.go`.

- The default `--use-signing-config=true` fetches a TUF signing config.
- `--tlog-upload=false` is **deprecated but works**, and only *without* a signing config.
  cosign errors on `--tlog-upload=false` combined with `--use-signing-config`.
- With `--key`, cosign fetches no trusted root.

```bash
# COSIGN_PRIVATE_KEY and COSIGN_PASSWORD come from the production environment's secrets
cosign sign --yes --key env://COSIGN_PRIVATE_KEY \
  --use-signing-config=false --tlog-upload=false "$IMAGE_REPOSITORY@$IMAGE_DIGEST"
cosign verify --key cosign.pub --insecure-ignore-tlog=true "$IMAGE_REPOSITORY@$IMAGE_DIGEST"
```

- Generate the key once with `cosign generate-key-pair` (or `k8s://ns/secret`). Publish
  `cosign.pub` in the repo or the release.
- The alternative in v3 is a `--signing-config` file without Rekor services
  (`cosign signing-config create …`).
- **Not verified** by running: the Go build was stopped to save disk. Run the commands
  once against the internal registry before relying on them.
- Enforcing signatures at admission (Kyverno, sigstore policy-controller) is out of scope.
- **Get cosign from an internally mirrored copy** of `ghcr.io/sigstore/cosign/cosign:v3.1.3`
  or a binary in the artifact store. `cosign-installer` downloads from GitHub releases.

## 5. Validating workflows offline (run here)

**actionlint 1.7.12.**

| Way to install | Result here |
|---|---|
| `go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12` | **Works** through proxy.golang.org. Go fetched its own go1.26.9 toolchain. 8.5 MB binary, about 1 minute |
| Docker Hub `rhysd/actionlint:1.7.12` | **Reachable** through mirror.gcr.io (digest above); not pulled |
| PyPI `actionlint-py` 1.7.12.25 | Sdist only. Its build downloads the binary **from GitHub releases**, so it fails here |
| npm `actionlint` 2.0.6 | A 2022 wasm build. Stale |
| GitHub release binaries | Blocked |

- **Today's `ci.yml`:** `actionlint .github/workflows/ci.yml` exits 0. With
  `-shellcheck=<shellcheck-py 0.11.0>` it reports 3 SC2086 notes, the intentional
  `$PDF_APT_PACKAGES` word-splitting at lines 35, 243 and 290. Add a
  `paths: … ignore: ['SC2086']` entry, or quote the variable.
- **A probe workflow using the planned syntax:**
  - `concurrency.queue` is rejected;
  - `runs-on: {group, labels}` with custom labels needs `.github/actionlint.yaml`
    `self-hosted-runner: labels: [soundings-staging, soundings-production]`.
    `config-variables: [...]` makes it check `vars.*` names strictly;
  - `${{ github.event.head_commit.message }}` in `run:` is flagged;
  - `environment.deployment: ${{ … }}` and `permissions: artifact-metadata: write` are
    accepted.

**zizmor 1.30.1** (`pip install zizmor`; plain wheels, no download at run time).

- `zizmor --offline .github/workflows/` reports 24 `unpinned-uses` (high) and 9
  `artipacked` (medium) on today's `ci.yml`.
- It caught the probe's template injection.
- It is the security linter: pinning, credential persistence, injection, dangerous
  triggers. `--offline` skips the checks that need the GitHub API.

**Checking beyond syntax without running on GitHub:**

- Keep logic in `scripts/deploy.sh`, which is shellchecked by `make check-scripts`, and
  run it by hand against the local k3s. Make it testable:
  - `DRY_RUN=1` → `helm upgrade --install --dry-run=server` and `helm template`;
  - `kubectl auth can-i --list --as=system:serviceaccount:arc-soundings-staging:soundings-deployer -n soundings-staging`
    proves the Role;
  - `-n soundings-production` proves the staging SA can't touch production.
- `nektos/act` (v0.2.89) can run jobs locally in containers. Its release binary is
  blocked here, but `go install` would work. It doesn't model environments, approvals,
  OIDC, runner groups or ARC, so it adds little for CD.
- A `check-workflows` target can run actionlint and zizmor (pinned, from the Go proxy or
  PyPI, or digest-pinned images). The lead could add it to `make check`. Both tools'
  config files go in `.github/`.

---

## 6. Recommended design for the GitHub side

This works with the shared `scripts/deploy.sh` that both CIs call. Its contract,
suggested so GitLab can use the same names:

```
scripts/deploy.sh deploy|rollback|smoke <staging|production>
  IMAGE_REPOSITORY, IMAGE_DIGEST (required for deploy), IMAGE_TAG (shown, and checked against the app's version)
  KUBE_NAMESPACE (default soundings-<env>), HELM_RELEASE (default soundings), KUBE_CONTEXT (optional; GitLab agent)
  DEPLOY_VALUES (default deploy/environments/<env>.yaml), DEPLOY_URL (the smoke's base URL)
  HELM_TIMEOUT, ROLLBACK_REVISION, DRY_RUN
```

Helm's `--atomic` is an alias of `--rollback-on-failure` in Helm 4.3 (deprecated but
accepted), so `--atomic --wait` works on 3.x and 4.x. Read in `pkg/cmd/upgrade.go`.
`--atomic` reverts Kubernetes objects, not the database: the pre-upgrade migration Job
must stay expand/contract-compatible with the previous release.

### 6.1 Workflows

**`ci.yml`** keeps today's checks and adds jobs gated on them, like GitLab's stage order.
Add `tags: ['v[0-9]+.[0-9]+.[0-9]+']` to `on.push` (filter syntax per workflow-syntax.md's
`v[12].[0-9]+.[0-9]+` example), and change the concurrency as in
§2.6.

```
backend frontend helm fake-agent audit contract e2e*  ──┐
image (GitHub-hosted; push; outputs repository+digest+tag) ─┴→ scan (Trivy gate + CycloneDX SBOM artifact)
   → deploy-staging     if: push to main      runs-on: ${{ vars.SOUNDINGS_STAGING_RUNNER || 'soundings-staging' }}
                        environment: staging   concurrency: soundings-deploy-staging (no cancel)
   → deploy-production  if: tag && vars.SOUNDINGS_PRODUCTION_GATE != 'manual'
                        runs-on: …production…  environment: production  concurrency: soundings-deploy-production
   → release            if: tag   (GitHub-hosted; contents: write; SBOM asset; optional cosign sign)
```

- **`deploy-production.yml`**: `workflow_dispatch`, for the manual gate on Pro/Team. It
  refuses unless `github.ref_type == 'tag'`, resolves the tag's digest from the registry
  (or the release's metadata), then runs the same production job.
- **`rollback.yml`**: `workflow_dispatch` (environment + revision). Same runners,
  environments and concurrency groups.
- Each deploy job: `actions/checkout` (pinned, `persist-credentials: false`) then
  `scripts/deploy.sh deploy <env>`. No other actions. On failure the script exits
  non-zero, `--atomic` has restored the previous release, and the job prints
  `helm history`.

### 6.2 Settings, secrets and variables (one table)

| Name | Where | Default | Purpose |
|---|---|---|---|
| `IMAGE_REPOSITORY` | repo variable | `ghcr.io/<owner>/soundings` | Where images go (any registry) |
| `REGISTRY_USERNAME` / `REGISTRY_PASSWORD` | repo secrets | `github.actor` / `GITHUB_TOKEN` | Only for non-ghcr registries |
| `SOUNDINGS_BUILD_RUNNER` | repo variable | `ubuntu-24.04` | Self-hosted build runner when registry or mirrors are internal |
| `UBUNTU_MIRROR`, `PIP_INDEX_URL`, `UV_DEFAULT_INDEX`, `NPM_CONFIG_REGISTRY` | repo variables | unset | Build args, same names as GitLab. Never embed credentials (provenance) |
| `CI_BUILD_CA` | repo secret (PEM text) | unset | Same name as GitLab's File variable. Written to a temp file → `secret-files: build_ca=…` |
| `TRIVY_IMAGE`, `TRIVY_SEVERITY`, `TRIVY_DB_REPOSITORY` | repo variables | `aquasec/trivy:0.75.0@sha256:af6a…`, `CRITICAL`, Trivy default | Scan gate |
| `SOUNDINGS_STAGING_RUNNER` / `SOUNDINGS_PRODUCTION_RUNNER` | repo variables | `soundings-staging` / `soundings-production` | ARC scale-set names (or labels) |
| `SOUNDINGS_PRODUCTION_GATE` | repo variable | `environment` | `manual` on Pro/Team private repos |
| `DEPLOY_URL` | environment variable (staging, production) | none | Smoke base URL; also the environment's `url` |
| `KUBE_NAMESPACE` | environment variable | `soundings-<env>` | Override only |
| `KUBECONFIG_DATA` | environment secret | unset | Mode B only |
| `COSIGN_PRIVATE_KEY`, `COSIGN_PASSWORD` | production environment secrets | unset | Signing on when set |

Environment settings:

- **`staging`:** branch policy `main`.
- **`production`:**
  - tag policy `v*.*.*`;
  - required reviewers + prevent self-review + no admin bypass (Enterprise or public);
  - on Pro/Team: the variable above + a tag ruleset.

Repo or org settings:

- require SHA-pinned actions;
- default `GITHUB_TOKEN` read-only;
- fork pull-request workflows off;
- runner group `soundings-deploy` → selected repository `soundings` (and on Enterprise,
  selected workflows `ci.yml`, `deploy-production.yml`, `rollback.yml` @ `refs/heads/main`).
  **Not verified:** whether tag refs can be listed there.

### 6.3 Runner setup (operator, once)

1. **Mirror** the ARC charts and images, the runner image, `alpine/helm` and the Trivy,
   syft and BuildKit images (digests above) into the internal registry. Build
   `soundings-deploy-runner` (runner + helm).
2. **Controller:** `helm install arc oci://<mirror>/gha-runner-scale-set-controller --version 0.15.0 -n arc-systems`
   with `image.repository` set to the mirror.
3. **GitHub App:** create it (org: Self-hosted runners RW, Metadata R), install it on the
   org, and create Secret `arc-github-app` in each runner namespace.
4. **Target namespaces and Roles:** `soundings-staging` and `soundings-production` with
   the Role from §1.4, plus a RoleBinding to `system:serviceaccount:arc-soundings-<env>:soundings-deployer`.
   Create the app's Secrets there (`existingSecret`); they are never in the repo.
5. **Scale sets.** One per environment:
   `helm install soundings-<env> oci://<mirror>/gha-runner-scale-set --version 0.15.0 -n arc-soundings-<env>`
   with:
   - `githubConfigUrl: https://github.com/<org>`, `githubConfigSecret: arc-github-app`;
   - `runnerGroup: soundings-deploy`, `minRunners: 0`, `maxRunners: 1`;
   - `template.spec.serviceAccountName: soundings-deployer`;
   - the runner container's image = `soundings-deploy-runner`;
   - `githubServerTLS` / `proxy` if needed.
6. **NetworkPolicy** for `arc-soundings-*`: egress to GitHub (443 via the proxy), the API
   server, DNS and the ingress only.
7. **Check it** with `kubectl auth can-i` as each SA in both namespaces, then run a
   staging deploy from `main`.

### 6.4 Open points for the lead

- **Deploy jobs in `ci.yml` or a separate `cd.yml`?** In `ci.yml` (recommended), staging
  waits for this commit's checks, as on GitLab, at the cost of e2e latency. In `cd.yml`
  it is faster but relies on branch protection.
- **Mode A default plus documented Mode B**, or Mode B by default for non-Enterprise orgs?
- **Who maintains `soundings-deploy-runner`** (a Dockerfile under `deploy/` or `dev/`)?
  Dependabot can track its `FROM`.
- **Bump `TRIVY_IMAGE` to 0.75.0 by digest** in both CIs, and the `alpine/helm` pin
  (3.16.2 → 3.22.0, or 4.x once tested).
