# Research: continuous delivery on self-managed GitLab (verified 2026-10-09)

> Phase 9 research (researcher subagent, read-only for the repo except this file). It
> feeds the build stage: one shared deploy script, GitLab and GitHub delivery jobs,
> the GitLab agent for Kubernetes, rootless image builds. Re-check versions before
> relying on a fact in a later phase.

**Versions this is for.** GitLab **19.4** (latest self-managed release: 19.4.1,
2026-09-22; tags `v19.4.1-ee`, branch `19-4-stable-ee` read on 2026-10-09), GitLab Runner
**19.4.1**, GitLab agent for Kubernetes (agentk/KAS) **19.4.1**, agent Helm chart
`gitlab-agent` **2.32.0** (appVersion `v19.4.0`), BuildKit **v0.34.0** (Docker Hub),
Trivy 0.75.0 latest (the repo pins 0.67.2), cosign CHANGELOG head v3.0.5.

**How it was verified.** `docs.gitlab.com`, `charts.gitlab.io` and `packages.gitlab.com`
are refused by this sandbox's proxy (403), so the documentation was read from its
source: the `doc/` Markdown of `gitlab-org/gitlab` at `19-4-stable-ee`, `docs/` of
`gitlab-org/gitlab-runner` at `v19.4.1`, `doc/` and code of
`gitlab-org/cluster-integration/gitlab-agent` at `v19.4.1`, and the chart repository
`gitlab-org/charts/gitlab-agent` at `v2.32.0` (all through the gitlab.com API, which
works here). The page URL on docs.gitlab.com is the doc path without `doc/` and
`_index.md`/`.md`, for example `doc/user/clusters/agent/ci_cd_workflow.md` is
<https://docs.gitlab.com/user/clusters/agent/ci_cd_workflow/>.

Marks used below: **[doc]** read in the 19.4 documentation source; **[src]** read in
the code; **[run]** executed in this sandbox; **[not verified]** reasoning or memory
only, check it in the build stage.

---

## 0. Answers in one table

| Need | GitLab 19.4 feature | Tier (self-managed) | Mark |
|---|---|---|---|
| Cluster access from CI without stored credentials | Agent for Kubernetes, CI/CD workflow (`ci_access`), `KUBECONFIG` injected per job | Free | [doc] |
| Restrict which jobs get the context | `ci_access.*.environments`, `protected_branches_only` (protected refs, tags too) | Free | [doc] [src] |
| CI job as its own Kubernetes identity | `access_as: ci_job` / `ci_user` / `impersonate` | **Premium** | [doc] |
| Least privilege on Free | the agent's own ServiceAccount, bound by namespace RoleBindings (chart `rbac.create=false`) | Free | [doc] [src] |
| Serialise deploys per environment | `resource_group` | Free | [doc] |
| Environments, tiers, URLs, auto-stop | `environment:name/url/deployment_tier/auto_stop_in` | Free | [doc] |
| Who may deploy production | protected environments ("Allowed to deploy") | **Premium** | [doc] |
| Approval before production | deployment approvals (approval rules, no self-approval by default) | **Premium** | [doc] |
| Free-tier production gate | `when: manual` + `allow_failure: false` on a **protected tag**: only people allowed to create that tag can run the job | Free | [doc] [src] |
| Secrets only on main and tags | protected variables (protected branches **and** protected tags) | Free | [doc] |
| Environment-scoped variables | project level: Free; group level: Premium | Free / Premium | [doc] |
| Immutable image tags in the registry | "immutable container tags" | **Ultimate** | [doc] |
| Who may push matching image tags | protected container tags (needs the registry metadata database) | Free | [doc] |
| Release with an SBOM attached | `release:` keyword (`glab`), generic package registry (`--use-package-registry`) | Free | [doc] |
| SBOM shown in the dependency list | `artifacts:reports:cyclonedx` | **Ultimate** | [doc] |
| Pull-through cache of Docker Hub | dependency proxy (group level, Docker Hub only) | Free | [doc] |
| Pull-through cache of other registries | container virtual registry (beta, flag off by default) | Premium | [doc] |

---

## 1. GitLab agent for Kubernetes on self-managed GitLab

### 1.1 What the instance needs: KAS ("GitLab Relay")

- In 19.x the docs call KAS **"GitLab Relay (KAS)"** (formerly "Kubernetes Agent
  Server"); it also relays runner traffic now (Job Router). [doc
  `administration/clusters/kas.md`]
- **Linux package (Omnibus):** enabled by default on a single node, served at
  `ws://gitlab.example.com/-/kubernetes-agent/` (`wss://` with TLS). Turn off with
  `gitlab_kas['enable'] = false`. The relevant settings, all optional on one node: [doc]
  - `gitlab_kas_external_url` / `gitlab_rails['gitlab_kas_external_url']`: the URL agentk
    dials (default: derived from `external_url`, i.e. `wss://<gitlab>/-/kubernetes-agent/`).
  - `gitlab_rails['gitlab_kas_external_k8s_proxy_url']`: the Kubernetes API proxy URL that
    goes into CI jobs' kubeconfig (default `https://<gitlab>/-/kubernetes-agent/k8s-proxy/`).
  - `gitlab_rails['gitlab_kas_internal_url']`: Rails → KAS gRPC (port 8153; never expose it).
  - `gitlab_kas['gitlab_address']`: set to `http://...` when the instance has no TLS and its
    hostname resolves to its own internal address (else KAS fails with
    `dial tcp <ip>:443: connect: connection refused`).
  - Ports: 8150 agent connections (WebSocket and gRPC), 8153 Rails API, 8154 Kubernetes API
    proxy, 8155 KAS-to-KAS private API.
- **GitLab Helm chart:** `global.kas.enabled` defaults to `true`; KAS gets its own host,
  `kas.<global.hosts.domain>` (`global.hosts.kas.name` to change it). The advertised
  agent address is `grpcs://kas.<domain>` with NGINX ingress or the chart's Envoy Gateway,
  `wss://kas.<domain>` with other ingress controllers, and `ws://` when both
  `global.hosts.https` and `global.hosts.kas.https` are false. [doc
  `charts/gitlab/kas/_index.md`, chart master]
- **TLS with an internal CA**, three places:
  1. KAS → GitLab API: put the internal CA in `/etc/gitlab/trusted-certs` (or point
     `gitlab_kas['env']['SSL_CERT_DIR']` at a directory), reconfigure and restart
     `gitlab-kas`. Symptom otherwise: `x509: certificate signed by unknown authority` in
     `/var/log/gitlab/gitlab-kas/`. [doc]
  2. agentk → KAS: chart value `config.kasCaCert` (`--set-file config.kasCaCert=ca.pem`),
     mounted into the pod; agentk flag `--kas-ca-cert-file`. [doc] [src chart]
  3. CI job (kubectl/helm) → KAS k8s-proxy: a File CI variable `SSL_CERT_FILE` with the
     CA (Go programs honour it), or `--certificate-authority`, or bake it into the job
     image. Our pipeline already exports `SSL_CERT_FILE=$CI_BUILD_CA` in its `.ca-bundle`
     anchor, so the deploy jobs only need to include it. [doc `ci_cd_workflow.md`]
- **TLS is mandatory for kubectl and Helm through KAS.** The docs warn that without TLS
  `kubectl` from CI fails with `error: You must be logged in to the server (the server
  has asked for the client to provide credentials)` ("Enable TLS", `ci_cd_workflow.md`
  troubleshooting). Reproduced here on an `http://` GitLab: the job's kubeconfig token
  works with `curl` (200), agentk connects over `ws://`, but `kubectl get configmaps`
  fails with exactly that error, because client-go only reads a kubeconfig's credentials
  when the transport is TLS ("only try to read the auth information if we are secure").
  Every deploy path (production and the local verification) needs `https` for the
  k8s-proxy URL. [doc] [run] [src client-go v0.31.4 `tools/clientcmd/client_config.go:232`]
- Receptive agents (GitLab dials the agent; for clusters that can't reach GitLab) are
  **Ultimate** and need a URL configuration per agent; not needed here (our clusters can
  reach GitLab). [doc]

### 1.2 Installing agentk from an internal mirror (air-gapped)

- **Chart:** `gitlab-agent` from <https://charts.gitlab.io> (source
  `gitlab-org/charts/gitlab-agent`; 2.32.0 = appVersion v19.4.0, released 2026-09-19).
  Air-gapped: copy the `.tgz` into the internal Helm/OCI repository (Harbor, Nexus,
  Artifactory) once per upgrade. Its only dependency (`ingress-nginx`) is conditional and
  off by default. [src chart]
- **Image:** `registry.gitlab.com/gitlab-org/cluster-integration/gitlab-agent/agentk:<tag>`
  (chart value `image.repository`, `image.tag` defaults to the chart's appVersion).
  Mirror it and set `image.repository=<mirror>/gitlab-org/cluster-integration/gitlab-agent/agentk`
  and `image.tag=v19.4.1`. agentk is **not** published on Docker Hub (only `gitlab-ce`,
  `gitlab-ee`, `gitlab-runner`, `gitlab-runner-helper`, `glab`, ... are). A FIPS variant
  is `agentk-fips`. [src chart] [run: Docker Hub API listing]
- **Version skew:** agentk should match GitLab's major.minor; the previous and next minor
  are supported (GitLab 19.4 → agentk 19.3–19.5). The chart can lag the agent; set
  `image.tag` explicitly. [doc `install/_index.md`]
- **Values that matter for us** (chart 2.32.0 `values.yaml`, templates read): [src chart]

  | Value | Default | Recommendation |
  |---|---|---|
  | `config.kasAddress` | `grpcs://kas.gitlab.com` | `wss://<gitlab>/-/kubernetes-agent/` (Omnibus) or `grpcs://kas.<domain>` (chart) |
  | `config.token` / `config.secretName` | – | `config.secretName`: the operator creates the Secret with the agent token (key `token`); no token in values or Git |
  | `config.kasCaCert` | – | the internal CA (PEM) |
  | `rbac.create` | `true` → a **ClusterRoleBinding to `cluster-admin`** (or to `rbac.useExistingRole`, still cluster-wide) | **`false`**, and bind the ServiceAccount per namespace yourself (1.6) |
  | `serviceAccount.create` / `.name` | `true` | keep; name it (e.g. `soundings-staging-agent`) |
  | `config.operational_container_scanning.enabled` | `true` (creates its own ServiceAccount, ClusterRole/Binding) | **`false`** (OCS is Ultimate and needs cluster-wide reads) |
  | `replicas` | 2 (leader election through a Lease in its namespace) | keep 2 |
  | `extraEnv` | – | `HTTPS_PROXY`/`NO_PROXY` only if KAS is behind a proxy |

  The Deployment sets `automountServiceAccountToken: false` and mounts a projected token
  itself. The chart README warns the default `cluster-admin` binding is not for
  production. [src chart] [doc]
- What agentk itself needs from RBAC in **its own namespace**: `leases`
  (coordination.k8s.io: get/create/update, leader election `module-runner`) and `events`
  (create/patch) [src `internal/cmd/agentk/leader_elector.go`, `command.go`]. Run here: agentk
  with exactly that Role in its namespace plus `edit` bound by a RoleBinding in
  `soundings-staging` (no cluster-wide rights) connected, took its Lease (`agent-<id>-lock`),
  skipped the Flux module ("missing RBAC", harmless), and proxied 200 in
  `soundings-staging` and 403 in `default`. [run] Discovery
  (`/api`, `/apis`) is allowed to every authenticated identity by the built-in
  `system:discovery` ClusterRole [not verified here; Kubernetes default].

### 1.3 Registering the agent

- Agent name: RFC 1123 DNS label, ≤ 63 characters, unique in the project. Optional config
  file on the **default branch** of the agent's configuration project:
  `.gitlab/agents/<agent-name>/config.yaml`. [doc]
- Register in the UI (**Operate > Kubernetes clusters > Connect a cluster**) or with the
  API: `POST /projects/:id/cluster_agents` (`name`), then
  `POST /projects/:id/cluster_agents/:agent_id/tokens` (returns the token once). The token
  can read the config project's code: store it only as a Kubernetes Secret. [doc
  `api/cluster_agents.md`, `install/_index.md`]
- Configuration changes take "one or two minutes" to propagate. [doc]

### 1.4 `ci_access`: who may use the agent from CI

```yaml
# .gitlab/agents/soundings-production/config.yaml (in the agent configuration project)
ci_access:
  projects:
    - id: platform/soundings            # full path of the project whose jobs may use it
      default_namespace: soundings-production
      environments: [production]        # only jobs with environment:name production
      protected_branches_only: true     # only pipelines on protected refs
```

- `projects` (≤ 500), `groups` (≤ 500, subgroups included), or `instance: {}` (all
  projects; an administrator must first enable "instance level authorization",
  application setting `organization_cluster_agent_authorization_enabled`, since 17.11).
  Authorized projects/groups must share the agent project's **top-level group** unless
  instance-level authorization is on. [doc] [src `ci_access/finder.rb`]
- **Implicit access:** jobs of the agent's own configuration project can use every agent
  configured there; an explicit `projects` entry for that project replaces the implicit
  default ("closest, most-specific authorization wins": project, then implicit, then
  groups from the innermost). [src `finder.rb`] [doc agent repo
  `doc/kubernetes_ci_access.md`]
- `environments`: only jobs whose `environment:name` matches (wildcards like `review/*`)
  get the context; other jobs simply have no context for this agent. Free. [doc]
- `protected_branches_only: true`: GA since 17.10 (the doc page still carries a stale
  "feature flag" box). The API that builds the kubeconfig passes
  `protected_ref: pipeline.protected_ref?`, which is true for protected branches **and
  protected tags**, so tag pipelines on protected `v*` tags qualify. Run here: a job with
  `environment: staging` got the context on `main` and on the protected tag `v0.0.1`, and
  none on the unprotected branch `feature-x`; a job without an environment got none.
  [doc] [src `lib/api/ci/jobs.rb` `allowed_agents`] [run]
- `default_namespace`: sets the namespace of the generated context. Documented only in
  the agent repository's design doc, not on docs.gitlab.com; works (the injected context
  had `namespace: soundings-staging`). [doc agent repo] [run]

### 1.5 How a job gets the cluster (no stored credentials)

- Every job of an authorized project gets a kubeconfig as a File variable and
  **`KUBECONFIG` points to it**; one context per agent the job may use. kubectl, Helm and
  any client-go tool use it with no setup. [doc `ci_cd_workflow.md`,
  `predefined_variables.md`]
- **Context name:** `<agent configuration project full path>:<agent name>`, for example
  `platform/k8s-agents:soundings-production`. With the agent configured in the same
  project, `$CI_PROJECT_PATH:<agent-name>` (run here: `platform/soundings:soundings-staging`,
  cluster `gitlab`, user `agent:<id>`, `KUBECONFIG` under the build directory's `.tmp/`).
  Run `kubectl config get-contexts` in a job if unsure. `KUBE_CONTEXT` is only Auto
  DevOps' variable name; for our jobs it is just a convenient variable. [doc] [run]
- Server: the KAS k8s-proxy URL (cluster entry named `gitlab`); token
  `ci:<agent_id>:<CI_JOB_TOKEN>`, so the credential dies with the job. [doc agent repo]
- Runners do **not** need network access to the cluster: they reach the API server
  through GitLab (KAS) and the agent's outbound tunnel. Any runner that reaches GitLab can
  deploy. (Contrast with GitHub Actions, where the deploy job must run inside the
  network.) [doc]
- Make `~/.kube/cache` writable in the job image (else every call re-discovers the API).
  Avoid kubectl 1.27.0/1.27.1 (validation 426 bug). [doc]

### 1.6 Impersonation vs plain RBAC (least privilege)

- **Default (`access_as: agent`):** the job acts as agentk's ServiceAccount. All tiers. [doc]
- **Impersonation (Premium, Ultimate):** `access_as: ci_job: {}` (user
  `gitlab:ci_job:<job id>`, groups `gitlab:ci_job`, `gitlab:group:<id>`,
  `gitlab:project:<id>`, `gitlab:project_env:<project id>:<env slug>`,
  `gitlab:project_env_tier:<project id>:<tier>`, ...), `ci_user: {}` (the user running the
  job, groups from project roles), or `impersonate: {username, uid, groups, extra}` (a
  static identity, e.g. a ServiceAccount). The agent's ServiceAccount then needs the
  `impersonate` verb. [doc] [doc agent repo]
- **Decision for Soundings: namespace-scoped RBAC on the agent's own ServiceAccount, one
  agent per environment.** Reasons:
  - It works on GitLab **Free** (impersonation is Premium) and is the same on Premium.
  - `ci_job` impersonation needs `impersonate` on arbitrary user names (job IDs change),
    which cannot be narrowed with `resourceNames`; an agentk compromise could then
    impersonate any user that has a cluster binding. Namespace RoleBindings give agentk
    nothing outside the Soundings namespaces at all. [not verified: Kubernetes
    impersonation semantics from memory]
  - One agent per environment (`soundings-staging` bound only in `soundings-staging`,
    `soundings-production` bound only in `soundings-production`, each with
    `ci_access.environments` set to its environment) keeps a staging job from touching
    production even on Free. Two agents in one cluster are supported: distinct Helm release
    names or namespaces; the docs prefer one agent plus impersonation where Premium is
    available. [doc `install/_index.md` "Install multiple agents"]
  - Optional on Premium: keep the two agents and add `access_as: ci_job` with RoleBindings
    to the group `gitlab:project_env_tier:<project id>:production` (defence in depth).
- **What the deploy identity needs** in each Soundings namespace (chart templates read:
  no cluster-scoped objects, no Roles): core `configmaps, secrets, services,
  serviceaccounts, persistentvolumeclaims, pods, pods/log, events (read)`, apps
  `deployments, statefulsets` (+ `replicasets` read for `--wait`), batch `jobs` (the
  migration hook), networking `ingresses, networkpolicies`, policy
  `poddisruptionbudgets`, autoscaling `horizontalpodautoscalers`, and only when used:
  `gateway.networking.k8s.io httproutes`, `monitoring.coreos.com servicemonitors`,
  `kagent.dev agents, remotemcpservers` (all in the release namespace). The built-in
  `edit` ClusterRole bound with a **RoleBinding** covers the core and workload kinds but
  not the CRDs unless they aggregate to `edit`; a small `soundings-deployer` ClusterRole
  (namespaced rules only) bound by RoleBindings is clearer. Namespaces are created by
  operators (no `--create-namespace`). [src `deploy/helm/templates`]

---

## 2. GitLab CI for deploys

### 2.1 Environments [doc `ci/yaml/_index.md`, `ci/environments/_index.md`]

```yaml
deploy:staging:
  environment:
    name: staging
    url: $STAGING_URL              # shown in the UI; CI_ENVIRONMENT_URL in the job
    deployment_tier: staging       # production|staging|testing|development|other; variables allowed since 18.5
    kubernetes:
      agent: platform/k8s-agents:soundings-staging   # optional: dashboard; needs user_access for viewers
```

- `deployment_tier` is set when the environment is first created; later changes need the
  Environments API. `auto_stop_in` (e.g. `1 week`, `never`) is for review apps; staging and
  production should not auto-stop.
- `environment:kubernetes:agent` (17.6+) only wires the Kubernetes dashboard (and
  Premium "managed resources", opt-in); the old `namespace`/`flux_resource_path` keys are
  deprecated since 18.4 in favour of `dashboard:namespace`. Not required for deploying.
- Re-deploy and **Rollback environment** in **Operate > Environments** re-run an older
  deployment job; with "Prevent outdated deployment jobs" on (project setting, **General
  pipelines**), keep "Allow job retries for rollback deployments" checked or the rollback
  buttons are disabled. A re-run old job needs its inputs (the image digest) still
  available: carry the digest in a tiny dotenv artifact that does not expire, or resolve
  it from the immutable tag. [doc `deployments.md`, `deployment_safety.md`]

### 2.2 Production gate: Free and Premium with the same YAML

```yaml
deploy:production:
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
      when: manual
      allow_failure: false                         # blocking: the pipeline waits
  manual_confirmation: "Deploy $CI_COMMIT_TAG to production?"   # 17.1+
  environment: { name: production, deployment_tier: production }
  resource_group: production
```

- `when: manual` jobs default to `allow_failure: true` outside `rules` and to `false`
  inside `rules`; say it explicitly. [doc `jobs/job_control.md`]
- **Free:** who can run the manual job is decided by the job's ref. For a **tag** the
  rule is "can create this tag" (`Ci::BuildPolicy#protected_ref`: `can_create_tag?` for
  tags, `can_update_branch?` for branches), so protecting `v*` with "Allowed to create:
  Maintainers" (or a release group) means only those people can start, retry or cancel the
  production job. Protected tags are Free. There is no four-eyes rule on Free: the person
  who pushed the tag may also run the job. [src `app/policies/ci/build_policy.rb`] [doc
  `protected_tags.md`]
- **Premium:** protect the environment `production` (**Settings > CI/CD > Protected
  environments**: "Allowed to deploy" plus approval rules, or the API
  `POST /projects/:id/protected_environments`). Jobs for it then wait as *blocked*; by
  default the pipeline triggerer can't approve their own deployment; after approval
  someone still runs the job. A protected environment also lets its deployers run the
  job without tag-creation rights. Group-level protected environments exist too. [doc
  `protected_environments.md`, `deployment_approvals.md`]
- Optional: deploy freezes (`CI_DEPLOY_FREEZE`), Free. [doc]

### 2.3 Serialising deploys

- `resource_group: staging` / `production`: one job at a time per group across all
  pipelines of the project. Process modes (`unordered` default, `oldest_first`,
  `newest_first`, `newest_ready_first`) are changed only through the API
  (`PUT /projects/:id/resource_groups/:key`). Free. [doc `ci/resource_groups/_index.md`]
- Pair it with **Prevent outdated deployment jobs** so an older pipeline's deploy can't
  overwrite a newer one. [doc]
- Helm adds its own last-resort lock (a release with a pending operation refuses another
  upgrade). Neither lock spans GitLab **and** GitHub: deploy each environment from one CI
  only (2.7). [not verified: Helm behaviour from memory]

### 2.4 Rules, protected refs and variables

```yaml
rules:
  - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH        # main: build, push, deploy staging
  - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/            # release: build, push, gated production
```

- Our `workflow:rules` already create pipelines for branches, tags and merge requests.
- Protect `main` (merge only through MRs) and the tag pattern `v*`. Mark deploy-time
  variables **Protected** (only pipelines on protected branches/tags get them) and
  **Masked** (default since 18.3) or **Masked and hidden**. Project variables can be
  scoped to an environment on Free (group-level scoping is Premium); don't use
  environment-scoped variables in `rules` (they are not known at pipeline creation).
  [doc `ci/variables/_index.md`, `environments/_index.md`]
- `CI_COMMIT_REF_PROTECTED` is `true` for protected refs. `CI_COMMIT_SHORT_SHA` is the
  **first 8 characters** (GitHub has no equivalent; use `${GITHUB_SHA::8}` so both CIs
  name `sha-<8 hex>` identically). [doc `predefined_variables.md`]
- Merge request pipelines don't get protected variables unless the project allows it.

### 2.5 Registry, credentials and the cluster's pulls

- `CI_REGISTRY` (`host[:port]`), `CI_REGISTRY_IMAGE` (`host[:port]/<project path>`),
  `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD` (= the job token, valid only while the job
  runs). Our `IMAGE_REPOSITORY` already defaults to `CI_REGISTRY_IMAGE`. [doc]
- The **cluster** can't use the job token to pull later. Use a project **deploy token**
  with `read_registry` (named `gitlab-deploy-token` it also appears as
  `CI_DEPLOY_USER`/`CI_DEPLOY_PASSWORD`), stored by operators as a `docker-registry`
  Secret in each namespace and referenced by the chart's existing `image.pullSecrets`, or
  let nodes pull from an internal mirror that already holds the image. [doc
  `predefined_variables.md`] [src `deploy/helm/values.yaml`]
- Image tags `sha-*`/`X.Y.Z` can't be made immutable on Free (immutable container
  tags are Ultimate, GA 18.10); protected container tags (Free, needs the registry
  metadata database on self-managed) restrict who may push matching tags. The build job
  should refuse to overwrite an existing `sha-*`/`X.Y.Z` tag. [doc]
- **Dependency proxy** (Free, group level, `CI_DEPENDENCY_PROXY_GROUP_IMAGE_PREFIX`):
  a pull-through cache of **Docker Hub only**, fetched by GitLab itself, so it helps only
  where GitLab has egress; in a strict air gap keep `REGISTRY_MIRROR` pointing at the
  internal mirror. It fits our convention (`${REGISTRY_MIRROR}/library/python:3.12-slim`
  works with `REGISTRY_MIRROR=$CI_DEPENDENCY_PROXY_GROUP_IMAGE_PREFIX`). [doc]

### 2.6 Releases and SBOM

- `release:` uses `glab release create` with the job token (image
  `registry.gitlab.com/gitlab-org/cli`, on Docker Hub as `gitlab/glab:v1.122.0`); a
  release that already exists makes the job fail. Assets: `glab release create "$TAG"
  sbom.cdx.json --use-package-registry` uploads them to the generic package registry
  (Free; `PUT /projects/:id/packages/generic/<name>/<version>/<file>` with `JOB-TOKEN`).
  [doc `releases/_index.md`, `generic_packages/_index.md`]
- `artifacts:reports:cyclonedx` is Ultimate (dependency list); on other tiers keep the SBOM
  as a plain artifact plus the release asset. [doc `artifacts_reports.md`]
- Signing: GitLab's cosign tutorial is keyless (`id_tokens: aud: sigstore`), which needs
  Fulcio/Rekor on the internet. Key-based offline signing: `cosign sign --key
  env://COSIGN_PRIVATE_KEY <repo>@sha256:...` with no transparency log
  (`--tlog-upload=false` in cosign 2.x; **deprecated in 3.x** (#4458) in favour of
  `--signing-config`), verify with `cosign verify --key cosign.pub
  --insecure-ignore-tlog=true`. [doc `cosign_tutorial.md`] [src cosign CHANGELOG,
  `doc/cosign_sign.md`; exact 3.x offline flags **not verified**]

### 2.7 Both CIs on one repository

The PO wants GitHub **and** GitLab. If both mirrors of the repository deploy, both will
push `sha-<8>` and both will `helm upgrade` the same staging release, and their locks
(`resource_group`, GitHub `concurrency`) don't see each other. Make delivery opt-in per CI:
GitLab deploy jobs only when a project variable names the agent (e.g. `rules: - if:
$KUBE_AGENT_PROJECT`, a plain project variable, not environment-scoped), GitHub's only when
a repository variable says so. Checks, scans and the k3s e2e stay in both. [not verified:
design]

---

## 3. Building images on runners

### 3.1 kaniko: archived

GitLab 19.4's "Use kaniko" page is now **"(removed)"**: kaniko "is no longer a maintained
project" (GoogleContainerTools/kaniko#3348); the docs point to Docker, BuildKit, Buildah and
Podman instead and have a "Migrate from Kaniko to BuildKit" section. Our `image:build` job
still uses kaniko v1.23.2. [doc `ci/docker/using_kaniko.md`, `using_buildkit.md`]

### 3.2 Rootless BuildKit (no privileged containers) [doc `ci/docker/using_buildkit.md`]

```yaml
image:build:
  image: { name: "${REGISTRY_MIRROR}/moby/buildkit:v0.34.0-rootless", entrypoint: [""] }
  variables:
    BUILDKITD_FLAGS: --oci-worker-no-process-sandbox
  script:
    - buildctl-daemonless.sh build --frontend dockerfile.v0 --local context=. --local dockerfile=.
        --secret id=build_ca,src="$CI_BUILD_CA"
        --opt build-arg:UBUNTU_IMAGE="$UBUNTU_IMAGE" ...
        --import-cache type=registry,ref="$IMAGE_REPOSITORY/cache:buildkit"
        --export-cache type=registry,ref="$IMAGE_REPOSITORY/cache:buildkit",mode=max
        --output type=image,\"name=$IMAGE_REPOSITORY:sha-$CI_COMMIT_SHORT_SHA\",push=true
        --metadata-file build-meta.json        # .["containerimage.digest"]
```

- `entrypoint: [""]` is required (the image's entrypoint is the daemon); registry auth is
  a hand-written `~/.docker/config.json`. [doc]
- `--oci-worker-no-process-sandbox` avoids a new PID namespace and `/proc` mount, which
  Kubernetes can't allow without `procMount: Unmasked`; upstream calls it "discouraged"
  (build steps can signal BuildKit's own processes, and leftover processes aren't killed)
  but uses it in its own Kubernetes examples. [src BuildKit `docs/rootless.md`,
  `examples/kubernetes/job.rootless.yaml`]
- **It still needs the runner's cooperation:**
  - **Kubernetes executor:** the build container needs seccomp and AppArmor relaxed:
    `[runners.kubernetes.build_container_security_context.seccomp_profile] type =
    "Unconfined"` and `...app_armor_profile] type = "Unconfined"` (or `Localhost`
    profiles that allow `unshare`/`mount`; `app_armor_profile` needs Kubernetes ≥ 1.30;
    Runner 18.11+ replaced the old annotations). AppArmor symptom: `[rootlesskit:child]
    error: failed to share mount point: /: permission denied`. BuildKit's image runs as
    UID 1000 (mapped to root inside builds). Nodes must allow unprivileged user
    namespaces: on **Ubuntu 24.04** set `kernel.apparmor_restrict_unprivileged_userns=0`;
    elsewhere `user.max_user_namespaces` > 0. [doc runner
    `executors/kubernetes/_index.md`, `troubleshooting.md`] [src BuildKit `rootless.md`]
  - **Docker executor without privileged:** the default seccomp profile blocks it
    (`fork/exec /proc/self/exe: operation not permitted`); the GitLab BuildKit page says
    use a custom seccomp profile in `security_opt` and **not** `seccomp:unconfined`,
    while the Buildah page tells you to set `security_opt = ["seccomp:unconfined",
    "apparmor:unconfined"]`. Upstream's `docker run` recipe is `seccomp=unconfined`,
    `apparmor=unconfined`, `systempaths=unconfined` (the last is unnecessary with
    `--oci-worker-no-process-sandbox`). [doc] [src]
  - **Docker executor, privileged:** works as is (GitLab.com's hosted runners are privileged).
- **Custom CA:** the docs say `moby/buildkit:rootless` has **no system CA store**; write a
  `buildkitd.toml` (`[registry."<host>"] ca = [...]`, auto-discovered in
  `~/.config/buildkit/`) **and** set `SSL_CERT_FILE` before the daemon starts. The
  Dockerfile's own `build_ca` secret is separate and works unchanged with `--secret
  id=build_ca,src=$CI_BUILD_CA`. [doc]
- Registry mirror for `FROM` lines: not needed here (we pass `UBUNTU_IMAGE`/`NODE_IMAGE`
  build args with the mirror prefix); otherwise `[registry."docker.io"] mirrors = [...]`
  in `buildkitd.toml`. [doc]
- Cache: `type=registry`, `mode=max`; since BuildKit v0.21 the cache is an OCI image
  manifest by default (`image-manifest=true`, `oci-mediatypes=true`), which registries
  without manifest-list support for cache (older Harbor/ECR) accept. [src BuildKit README]
- Several names in one push: `--output type=image,\"name=repo:a,repo:b\",push=true` (CSV
  quoting). Digest: `--metadata-file`, key `containerimage.digest`. [src BuildKit README]

### 3.3 Buildah (alternative)

`quay.io/buildah/stable` with `STORAGE_DRIVER=vfs` (overlay on overlay fails) and
`BUILDAH_FORMAT=docker`; rootless needs the same `security_opt` relaxations
(`Error during unshare(CLONE_NEWUSER): Operation not permitted` otherwise). quay.io is a
separate mirror to set up; vfs builds are slower and use more disk. Not recommended over
BuildKit for us; mention it as the fallback the docs give when runner security settings
can't change. [doc `using_docker_build.md`, `buildah_rootless_multi_arch.md`]

### 3.4 Docker executor with dind (keep the existing path)

- Needs `privileged = true`. TLS (recommended): `DOCKER_TLS_CERTDIR: "/certs"` and the
  runner shares `/certs/client`; the client talks to `tcp://docker:2376`. Without TLS (what
  our `.dind` template does): service `command: ["--tls=false"]`, `DOCKER_HOST:
  tcp://docker:2375`, `DOCKER_TLS_CERTDIR: ""`. The service **alias** `docker` is the
  hostname. [doc `ci/docker/docker_in_docker.md`]
- Registry mirror for the dind daemon: service `command: ["--registry-mirror", "https://..."]`
  or runner config. [doc `using_docker_build.md`]
- `docker buildx build --secret id=build_ca,src=$CI_BUILD_CA --push --metadata-file ...`
  works with the default `docker` driver. Registry **cache export** (`--cache-to
  type=registry,mode=max`) needs the `docker-container` driver, whose builder image
  defaults to `moby/buildkit:buildx-stable-1` from Docker Hub: pass `--driver-opt
  image=$REGISTRY_MIRROR/moby/buildkit:v0.34.0` in an air gap. [doc `using_buildkit.md`]
  [src docker docs `drivers/docker-container.md`]

### 3.5 Runner images in an air gap

- The runner's **helper image** defaults to
  `registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-v${CI_RUNNER_VERSION}`
  even for self-managed GitLab. Mirror it (Docker Hub has the same image as
  `gitlab/gitlab-runner-helper:x86_64-v19.4.1`) and set `helper_image` in `config.toml`.
  [doc runner `configuration/advanced-configuration.md`] [run: Docker Hub API]
- Runners register with **runner authentication tokens** (`glrt-...`) created with
  `POST /user/runners` (`runner_type=instance_type|group_type|project_type`, a token with
  the `create_runner` scope); registration tokens are deprecated. [doc
  `tutorials/automate_runner_creation`, runner `register/_index.md`]

---

## 4. Running a real self-managed GitLab here (verification stage)

### 4.1 What was run (2026-10-09, prefix `p9-rg-`, everything removed afterwards)

| Step | Result |
|---|---|
| `gitlab/gitlab-ce:19.4.1-ce.0` through `mirror.gcr.io` | **Works.** amd64: 1.515 GB compressed, 3.866 GB uncompressed (all blobs streamed and measured), `docker pull` 82 s. This Docker uses the **containerd snapshotter**, which keeps the compressed blobs next to the unpacked layers: the pull took **5.4 GB** of disk. |
| `gitlab/gitlab-runner:v19.4.1` | Works (114 MB compressed, about 0.4 GB on disk). `gitlab/gitlab-runner-helper:x86_64-v19.4.1` exists on Docker Hub (checked, not pulled). |
| agentk image `registry.gitlab.com/.../agentk:v19.4.1` | **Not pullable here**: the registry answers manifests, but blobs redirect to `cdn.registry.gitlab-static.net`, which the proxy refuses (403). `charts.gitlab.io` is refused too. |
| agentk from source | **Works**: tag archive from the gitlab.com API, `CGO_ENABLED=0 go build ./cmd/agentk` (go.mod needs Go 1.26.0; the host's Go 1.24 fetched it through `proxy.golang.org`), 238 s, 73 MB static binary. Kept at `/tmp/claude-0/-home-user-soundings/026c21a0-f442-59fc-91ce-6ca1d81cca90/scratchpad/agentk-out/agentk` (sha256 `4c7d2532…`). It reports version `v0.0.0` (no ldflags), which only makes GitLab show an "update" hint. |
| GitLab boot (reduced memory, data on tmpfs) | First try **failed**: GitLab 19.4 rejects a guessable `initial_root_password` ("Password must not contain commonly used combinations of words and letters") and the reconfigure aborts. With a random password: `/-/readiness` 200 after **264 s** (machine load about 11 from other agents), **3.55 GiB** memory including 0.57 GB of data in tmpfs. KAS is on by default (`/-/kubernetes-agent/` 426, `k8s-proxy/` 401 anonymously). |
| Admin token | `gitlab-rails runner` creating a PAT (`api`, `k8s_proxy`, `create_runner`): 75 s. |
| Setup through the REST API | group, project, commit of `.gitlab/agents/soundings-staging/config.yaml`, `cluster_agents` + token, `POST /user/runners` (`glrt-` token) + `gitlab-runner register`, protected tag `v*`: all scriptable, no UI. |
| agentk ↔ KAS over `ws://` | agentk (host process; ServiceAccount with only namespace Role/RoleBindings in k3s) connected; GraphQL `clusterAgents.connections` shows it. |
| k8s-proxy with a PAT (`pat:<agent>:<token>`, `user_access`) over HTTP | 200 in `soundings-staging`, 403 in `default` and for namespaces. |
| CI job, `environment: staging`, shell runner | `KUBECONFIG` injected, context `platform/soundings:soundings-staging`, namespace from `default_namespace`; `curl` with its token over HTTP 200/403 as above; **`kubectl` fails** "You must be logged in" (client-go sends no kubeconfig credentials over plain HTTP, see 1.1), so Helm would too. |
| `protected_branches_only` | protected tag `v0.0.1`: context present; unprotected branch: none; job without environment: none. |

Not run: TLS on GitLab, the image build and push in CI, `helm upgrade` through KAS (blocked
by the TLS finding), Premium features (protected environments, approvals, impersonation).

### 4.2 Disk and memory budget

Free disk moved between **2.4 and 9.3 GB** during this session (the product team is
building at the same time); RAM had about 10 GB available. A full verification needs:

| Piece | Disk | RAM |
|---|---|---|
| `gitlab-ce` image | 5.4 GB | – |
| GitLab data (tmpfs works, as here) | 0.6 GB + registry storage (about 0.6 GB per pushed Soundings image, plus build cache) | 3.5 GiB + tmpfs |
| runner + helper images | 0.5 GB | small |
| image build: dind (+ base images + BuildKit cache inside) or rootless BuildKit image + cache | 2–3 GB | 1–2 GiB while building |
| k3s (image present) + Soundings image + Postgres in the cluster (state on tmpfs works) | about 1.5 GB | 0.5–1 GiB |
| agentk image built from the kept binary | 0.2 GB | small |

About **10–12 GB of disk**: it does **not** fit next to the product team's work today.
To make it fit: tmpfs for GitLab and k3s state (done here), registry storage on tmpfs,
build with the rootless BuildKit job instead of dind, and run the stage while the product
team is idle or after its owner frees space (the shared build cache had 5.2 GB
reclaimable this morning; not ours to prune). Keep a disk guard: the one used here
removed the containers when free space fell under 1.5 GB.

### 4.3 Plan for the verification stage

Use your own prefix, ports and network; every name below is an example.

1. **TLS first** (1.1): a throwaway CA and a certificate with SANs `p9-gitlab`,
   `localhost`, `127.0.0.1`. Mount it at `/etc/gitlab/ssl/p9-gitlab.{crt,key}` and the CA
   at `/etc/gitlab/trusted-certs/` (KAS calls GitLab's API over https).
2. `docker network create p9-net`; GitLab CE 19.4.1 with
   `--tmpfs /var/opt/gitlab:rw,exec,size=3g --tmpfs /var/log/gitlab --shm-size 256m
   --memory 7g` and `GITLAB_OMNIBUS_CONFIG`:
   `external_url 'https://p9-gitlab'; registry_external_url 'https://p9-gitlab:5050';
   letsencrypt['enable']=false; gitlab_rails['initial_root_password']='<random>';
   gitlab_rails['usage_ping_enabled']=false; puma['worker_processes']=0;
   sidekiq['concurrency']=10; prometheus_monitoring['enable']=false;` plus the
   `MALLOC_CONF`/`GITALY_COMMAND_SPAWN_MAX_PARALLEL` lines of the memory-constrained guide
   (omnibus `doc/settings/memory_constrained_envs.md`). KAS needs nothing (on by default;
   agents use `wss://p9-gitlab/-/kubernetes-agent/`). Wait for `/-/readiness` (about
   4.5 min); `gitlab_rails['monitoring_whitelist']` must admit the caller.
3. PAT with `gitlab-rails runner` (75 s). Then REST: `POST /groups`, `POST /projects`
   (`namespace_id`), push the repository (`git -c http.sslCAInfo=ca.pem push
   https://oauth2:<PAT>@127.0.0.1:<port>/<group>/soundings.git HEAD:main`; push a
   history-less copy if the history is big), `POST /projects/:id/protected_tags`
   (`name=v*`, `create_access_level=40`), `POST /projects/:id/variables` (`key`, `value`,
   `protected`, `masked`, `variable_type=file`, `environment_scope`). `main` is protected
   by default.
4. Agents: commit `.gitlab/agents/soundings-{staging,production}/config.yaml` (1.4), then
   `POST /projects/:id/cluster_agents` and `/tokens` for each.
5. k3s: `K3S_NAME=p9-k3s` with its own `K3S_API_PORT`/`K3S_HTTP_PORT`
   (`scripts/k3s-up.sh`), `docker network connect p9-net p9-k3s`. The node pulls from
   `p9-gitlab:5050` with the CA (`registries.yaml` `configs."p9-gitlab:5050".tls.ca_file`,
   or `insecure_skip_verify` for a throwaway run) and a deploy-token pull Secret. Pods
   can't use Docker's embedded DNS (127.0.0.11 is not reachable from pod network
   namespaces), so give agentk `hostAliases` (the chart has the value) with GitLab's
   container IP.
6. agentk image: `FROM ubuntu:24.04` (present locally) + the kept binary, `USER 1000`,
   `ENTRYPOINT ["/usr/bin/agentk"]`; `scripts/k3s-load-image.sh`; install the chart from the
   tag archive of `gitlab-org/charts/gitlab-agent` v2.32.0 with `image.repository/tag`,
   `image.pullPolicy=Never`, `rbac.create=false`, `config.kasAddress=wss://p9-gitlab/-/kubernetes-agent/`,
   `--set-file config.kasCaCert=ca.pem`, `config.secretName`,
   `config.operational_container_scanning.enabled=false`, `hostAliases`; the RBAC of 1.6
   applied first.
7. Runner: `gitlab/gitlab-runner:v19.4.1`, Docker executor, `privileged = true` (allowed
   locally), `network_mode = "p9-net"`, `helper_image =
   "gitlab/gitlab-runner-helper:x86_64-v19.4.1"`, `tls-ca-file` = the CA (jobs then get
   `CI_SERVER_TLS_CA_FILE`), `volumes = ["/certs/client", "/cache"]`. Sandbox-specific: job
   and service containers that pull from `mirror.gcr.io` go through the TLS-intercepting
   proxy, so dind and BuildKit must trust `/root/.ccr/ca-bundle.crt` (pass it as
   `CI_BUILD_CA`, as the design does for an internal CA); dind also needs
   `--insecure-registry=p9-gitlab:5050` or the CA in `/etc/docker/certs.d/p9-gitlab:5050/`.
8. Pipeline variables: `REGISTRY_MIRROR=mirror.gcr.io`, `CI_BUILD_CA` (File: the sandbox
   bundle + the throwaway CA), `K3S_REGISTRY_MIRROR`, `KUBE_AGENT_PROJECT`, the
   environment URLs. Expect a cold image build of 10+ minutes on this machine under load.
9. Prove: main → build, scan, staging deploy, smoke; a protected tag such as `v0.0.1`
   → manual production job runnable only by a Maintainer; a failing upgrade rolls back;
   the rollback job; a second pipeline waits on the `resource_group`.
10. Clean up by name: containers, network, the anonymous volumes `rancher/k3s` creates
    for its `VOLUME`s (three here; `docker rm -v` or remove them by ID), the images
    (`gitlab-ce` re-pulls in about 80 s, so don't keep 5.4 GB on a shared disk).

---

## 5. Recommended design for the build stage

The PO's flow, GitLab side, built from the facts above. Everything that exists stays
(lint → test → build → scan → deploy-test); delivery adds jobs and two stages.

### 5.1 Files

| File | Content |
|---|---|
| `scripts/deploy.sh` | The one deploy script for GitLab, GitHub and people: `deploy.sh <staging\|production> <image-ref@sha256:…>` and `deploy.sh rollback <env> [revision]`. `helm upgrade --install --atomic --wait --timeout …` (Helm 4 keeps `--atomic` as a deprecated alias of `--rollback-on-failure`), values from `deploy/environments/<env>.yaml` plus `--set image.repository/tag/digest`, `helm test`, then the production-safe smoke; exits non-zero with the previous release still running. Uses `--kube-context "$KUBE_CONTEXT"` when set, else the current context (works with the injected `KUBECONFIG` and with a person's own). |
| `deploy/environments/{staging,production}.yaml` | Non-secret values only (`baseUrls`, replicas, `existingSecret` names, `image.pullSecrets`, ingress hosts). |
| `deploy/gitlab-agent/` | `config.staging.yaml` / `config.production.yaml` (contents of `.gitlab/agents/soundings-<env>/config.yaml` for the agent configuration project), `rbac.yaml` (per-namespace Role/RoleBindings of 1.6: agentk's own Lease/Events, deploy rights in the Soundings namespace), `values.yaml` for the `gitlab-agent` chart (mirror image, `rbac.create=false`, OCS off, `config.secretName`, `config.kasCaCert`), README with the install order. |
| `.gitlab-ci.yml` | New stages `release` and `deploy` after `deploy-test`; jobs in 5.3. |
| `.gitlab/agents/` in this repo | Not by default: the agent configuration project should be one the platform team owns (`ci_access` is edited there); the README says how to use this project instead (implicit access, explicit entry recommended). |

### 5.2 Variables (one table, sensible defaults)

| Variable | Default | Purpose |
|---|---|---|
| `REGISTRY_MIRROR` | `docker.io` (exists) | Docker Hub mirror prefix for every tool image (BuildKit, Trivy, glab, deploy tools). |
| `IMAGE_REPOSITORY` | `$CI_REGISTRY_IMAGE` (exists) | Where the image goes. |
| `IMAGE_REGISTRY_USER` / `IMAGE_REGISTRY_PASSWORD` | `$CI_REGISTRY_USER` / `$CI_REGISTRY_PASSWORD` | Credentials for another registry (protected, masked). |
| `IMAGE_BUILDER` | `buildkit` | `buildkit` = rootless BuildKit job; `dind` = the Docker-in-Docker job. |
| `BUILDKIT_IMAGE` | `${REGISTRY_MIRROR}/moby/buildkit:v0.34.0-rootless` | Rootless builder (the dind path uses the same tag without `-rootless` as the buildx builder image). |
| `CI_BUILD_CA` | unset (exists, File) | Internal CA bundle: Dockerfile `build_ca` secret, `buildkitd.toml` + `SSL_CERT_FILE` for BuildKit, and `SSL_CERT_FILE` for kubectl/Helm talking to KAS over TLS. |
| `SCAN_SEVERITY` | `CRITICAL` | Trivy gate (`--exit-code 1 --severity $SCAN_SEVERITY`, keep `--ignore-unfixed` configurable). |
| `KUBE_AGENT_PROJECT` | unset | Path of the agent configuration project. **Unset = no deploy jobs** (2.7). Context = `$KUBE_AGENT_PROJECT:soundings-$CI_ENVIRONMENT_NAME`. |
| `STAGING_URL` / `PRODUCTION_URL` | unset | `environment:url` and the smoke target. |
| `DEPLOY_IMAGE` | `${REGISTRY_MIRROR}/alpine/k8s:<pinned>` | kubectl + Helm + curl + jq + bash in one image (Docker Hub `alpine/k8s`, tags per Kubernetes minor such as `1.31.13`; it ships whatever Helm was current at build time, so pin and check `helm version`). [not verified: image contents beyond its README] |
| `COSIGN_PRIVATE_KEY` (File) / `COSIGN_PASSWORD` | unset | Signing runs only when set (protected, hidden). |

### 5.3 Jobs

| Job | Stage | Rules | What it does |
|---|---|---|---|
| `image:build` | build | `IMAGE_BUILDER == buildkit` (default) | Rootless BuildKit (3.2): build args and `build_ca` secret as today, registry cache `"$IMAGE_REPOSITORY/cache:buildkit"`, pushes `sha-$CI_COMMIT_SHORT_SHA` on branches and `X.Y.Z` + `X.Y` on `vX.Y.Z` tags (`VERSION` build arg = the tag without `v`, else `sha-<8>`), refuses to overwrite an existing tag, writes `image.env` (`IMAGE_DIGEST`, `IMAGE_REF=$IMAGE_REPOSITORY@sha256:…`) as a dotenv artifact that never expires (GitLab's "Rollback environment" re-runs old deploy jobs that need it). |
| `image:build:dind` | build | `IMAGE_BUILDER == dind` | The same with `docker buildx` on the `.dind` service (3.4): `docker-container` driver with `--driver-opt image=$BUILDKIT_IMAGE` (non-rootless tag) so the cache flags are identical. Replaces kaniko. |
| `image:trivy` | scan | as today | Exists; the gate becomes `SCAN_SEVERITY` and it scans `$IMAGE_REF` (digest). Adds `trivy image --format cyclonedx --output sbom.cdx.json` (artifact). Deploy jobs `needs:` it, so nothing deploys an image that failed the scan. |
| `image:sign` | scan | `COSIGN_PRIVATE_KEY` set, main/tags | `cosign sign --key …` by digest, no transparency log (2.6). |
| `release` | release | `vX.Y.Z` tags | `glab release create "$CI_COMMIT_TAG" sbom.cdx.json --use-package-registry` (image `${REGISTRY_MIRROR}/gitlab/glab:<pinned>`); chart packaged with `--version X.Y.Z --app-version X.Y.Z` as an asset if wanted. |
| `deploy:staging` | deploy | main (and, recommended, release tags before production), `KUBE_AGENT_PROJECT` set | `environment: {name: staging, url: $STAGING_URL, deployment_tier: staging}`, `resource_group: staging`, `needs: [image:build*, image:trivy]`, `scripts/deploy.sh staging "$IMAGE_REF"`. Any runner works (the agent tunnels through GitLab). |
| `deploy:production` | deploy | `vX.Y.Z` tags, `when: manual`, `allow_failure: false`, `manual_confirmation` | `environment: {name: production, deployment_tier: production}`, `resource_group: production`. Free: protected tag `v*` (create: Maintainers or a release group) decides who can run it. Premium: protected environment `production` + approval rules; same YAML. |
| `rollback:staging` / `rollback:production` | deploy | manual, same rules and `resource_group` as the deploy | `scripts/deploy.sh rollback <env>` (`helm rollback` to the previous revision, or `ROLLBACK_REVISION`), then the smoke. |

`ci_access` for the two agents: `soundings-staging` → `environments: [staging]`;
`soundings-production` → `environments: [production]`, `protected_branches_only: true`
(both with `default_namespace`). A job only ever sees the context of its own
environment, and the production context only on protected refs.

### 5.4 Settings the operator guide must list (GitLab side)

1. GitLab on **https** (KAS k8s-proxy included); KAS enabled (default).
2. Two namespaces and the RBAC from `deploy/gitlab-agent/rbac.yaml`; the Secrets the chart
   references (`existingSecret`s, the registry pull Secret from a `read_registry` deploy
   token).
3. Agent configuration project with the two `config.yaml`s; register both agents; install
   the `gitlab-agent` chart twice (release names `soundings-staging-agent`,
   `soundings-production-agent`) from the internal mirror with the token Secrets.
4. Project: protect `main` and `v*`; **Prevent outdated deployment jobs** on; CI/CD
   variables of 5.2 (protected where secret); Premium: protected environment
   `production` with approvers.
5. Runners: a runner that allows the rootless BuildKit job (Kubernetes executor with
   seccomp/AppArmor `Unconfined` or `Localhost` profiles for the build container, nodes
   with unprivileged user namespaces) **or** a privileged Docker runner for
   `IMAGE_BUILDER=dind`; `helper_image` from the mirror.
6. Air gap: mirror `gitlab-ce`/`gitlab-runner`/`gitlab-runner-helper`, agentk, the
   `gitlab-agent` chart, `moby/buildkit`, `aquasec/trivy` and the Trivy DB repositories,
   `gitlab/glab`, the deploy-tools image.

### 5.5 Open points for the lead

- Build once or rebuild on tags: the app reports the version baked in at build time, so a
  tag pipeline rebuilds with `VERSION=X.Y.Z` (registry cache makes it quick); the digest
  that reaches production then differs from the one staging ran on `main`. Recommended:
  tag pipelines deploy staging automatically, then wait at the production gate, so the
  exact production digest has passed the staging smoke.
- Which CI delivers (2.7): both can, one should per environment.
- Premium-only extras (impersonation as defence in depth, deployment approvals) are
  documented, not required.

---

## Sources

All read on 2026-10-09 through the gitlab.com API (`/api/v4/projects/<path>/repository/files/<file>/raw?ref=<ref>`):

- gitlab-org/gitlab `19-4-stable-ee`: `doc/user/clusters/agent/{ci_cd_workflow,install/_index,_index,user_access,managed_kubernetes_resources,troubleshooting}.md`,
  `doc/administration/clusters/kas.md`, `doc/api/cluster_agents.md`,
  `doc/ci/environments/{_index,protected_environments,deployment_approvals,deployments,deployment_safety}.md`,
  `doc/ci/resource_groups/_index.md`, `doc/ci/yaml/{_index,artifacts_reports}.md`,
  `doc/ci/jobs/job_control.md`, `doc/ci/variables/{_index,predefined_variables}.md`,
  `doc/ci/pipelines/settings.md`, `doc/user/project/protected_tags.md`,
  `doc/ci/docker/{using_buildkit,using_docker_build,docker_in_docker,using_kaniko,buildah_rootless_multi_arch}.md`,
  `doc/user/packages/{dependency_proxy/_index,container_registry/immutable_container_tags,container_registry/protected_container_tags,container_registry/cosign_tutorial,generic_packages/_index,virtual_registry/container/_index}.md`,
  `doc/user/project/releases/_index.md`, `doc/install/docker/{installation,configuration}.md`,
  `doc/administration/packages/container_registry.md`, `doc/tutorials/automate_runner_creation/_index.md`;
  code: `app/finders/clusters/agents/authorizations/ci_access/finder.rb`,
  `lib/api/ci/jobs.rb`, `app/policies/ci/build_policy.rb`.
- gitlab-org/gitlab-runner `v19.4.1`: `docs/executors/kubernetes/{_index,troubleshooting}.md`,
  `docs/configuration/advanced-configuration.md`, `docs/register/_index.md`.
- gitlab-org/cluster-integration/gitlab-agent `v19.4.1`: `doc/kubernetes_ci_access.md`,
  `Makefile`, `go.mod`, `build/agentk.fips.Dockerfile`, `internal/cmd/agentk/*`.
- gitlab-org/charts/gitlab-agent `v2.32.0`: `Chart.yaml`, `values.yaml`, `templates/*`.
- gitlab-org/charts/gitlab `master`: `doc/charts/gitlab/kas/_index.md`.
- gitlab-org/omnibus-gitlab `19-4-stable`: `doc/settings/memory_constrained_envs.md`.
- moby/buildkit `master`: `README.md`, `docs/rootless.md`, `examples/kubernetes/job.rootless.yaml`.
- docker/docs `main`: `content/manuals/build/builders/drivers/docker-container.md`.
- sigstore/cosign `main`: `CHANGELOG.md`, `doc/cosign_sign.md`, `README.md`.
- Docker Hub API (tags and sizes) and `mirror.gcr.io` (manifests and blobs).
