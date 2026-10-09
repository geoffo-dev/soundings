# ci-local: the GitLab pipeline on a throwaway self-managed GitLab

`ci-local.sh` stands up, on one Docker host, what a site runs for Soundings' continuous
delivery (docs/operator-guide.md "Continuous delivery"), so `.gitlab-ci.yml`,
`scripts/deploy.sh` and the agent setup can be run for real before a change reaches the
site:

- **GitLab CE 19.4** with its container registry and agent server (KAS), on https with a
  throwaway CA (kubectl and Helm send the agent proxy's credentials over TLS only);
- the project **platform/soundings** (the path `.gitlab/agents/*/config.yaml` names), `main`
  and `v*` protected, the CI/CD variables the pipeline documents, a `read_registry` deploy
  token, and the agents `soundings-staging` and `soundings-production` registered;
- a **runner** (Docker executor): `rootless` mode runs no privileged container (the rootless
  BuildKit job gets seccomp and AppArmor unconfined, as the operator guide asks of a
  site's runner); `privileged` mode for `IMAGE_BUILDER=dind`;
- **k3s** on the same Docker network, set up as `deploy/gitlab-agent/README.md` tells
  operators: `deploy/environments/cluster-setup.yaml`, `deploy/gitlab-agent/rbac.yaml`, the
  Secrets, and GitLab's `gitlab-agent` chart twice with `deploy/gitlab-agent/values.yaml`
  (agentk connects out to KAS; nothing in GitLab holds a cluster credential). The
  environments answer at `http://staging.soundings.test` and
  `http://production.soundings.test` inside the network (aliases of the k3s node).

```bash
scripts/ci-local/ci-local.sh up                  # about 10 minutes the first time
CD_ONLY=1 scripts/ci-local/ci-local.sh push      # snapshot of this working tree -> main
scripts/ci-local/ci-local.sh wait <pipeline>     # job table as it goes
scripts/ci-local/ci-local.sh bump 0.2.0 && CD_ONLY=1 scripts/ci-local/ci-local.sh tag v0.2.0
scripts/ci-local/ci-local.sh play <pipeline> deploy:production   # the gate
scripts/ci-local/ci-local.sh play <pipeline> rollback:staging ROLLBACK_REVISION=2
scripts/ci-local/ci-local.sh probe               # what CI jobs reach through each agent
scripts/ci-local/ci-local.sh github staging deploy IMAGE_REPOSITORY=… IMAGE_DIGEST=… IMAGE_TAG=…
                                                 # GitHub's deploy step in a pod, as an ARC runner
scripts/ci-local/ci-local.sh down --images       # everything, images included
```

`push` copies the working tree (tracked and untracked files git doesn't ignore, so
uncommitted changes too) into `.ci-local/<name>/repo`, a copy with its own history, commits
and pushes it. `CD_ONLY=1` adds `-o ci.variable=CD_ONLY=1`: the pipeline then skips its
lint, test, e2e and k3s jobs (release check, chart lint, image build, scan gate and
delivery still run). GitLab's web UI is at `https://<prefix>gitlab:8910` (resolve the name to
127.0.0.1 and trust `.ci-local/<name>/tls/ca.crt`), user `root`, password in
`.ci-local/<name>/root-password`.

## What it needs

| | |
|---|---|
| Memory | about 4.5 GB for GitLab (its data and registry in tmpfs), 2-3 GB for k3s (state in tmpfs, two environments), 1 GB for Trivy's database while a scan runs, 2-3 GB for the dind service's storage while the dind build runs |
| Disk | the images: `gitlab/gitlab-ce` 5.4 GB with Docker's containerd image store, the runner and helper 0.5 GB, the job images 1-2 GB (`CI_LOCAL_DEPLOY_TOOLS=1` saves 1.1 GB); 2-3 GB for BuildKit's state while the rootless build runs (see below) |
| Network | the images through `CI_LOCAL_MIRROR` (a Docker Hub mirror); the image build reaches the Ubuntu archive, PyPI and npm (or set the pipeline's mirror variables with `CI_LOCAL_VARIABLES`); agentk: `AGENTK_IMAGE` from a mirror of registry.gitlab.com, or `AGENTK_BINARY` (a binary built from the agent's source); the `gitlab-agent` chart: `GITLAB_AGENT_CHART`, else its source archive from gitlab.com |
| Ports | five from `CI_LOCAL_PORT` (8910) on 127.0.0.1: GitLab, registry, (ssh), k3s API, k3s ingress |

Behind a TLS-intercepting proxy, `CI_LOCAL_EXTRA_CA` (default `$SSL_CERT_FILE`) is added to
everything's trust: the runner, `CI_BUILD_CA` (the build, BuildKit, Trivy, kubectl, glab) and
k3s's registry configuration.

The rootless BuildKit job keeps its state in a Docker volume per job (2-3 GB of disk while
it builds). Short of disk, give it RAM with `CI_LOCAL_BUILDKIT_DIR`: an ext4 file system on
a RAM-backed loop device (`truncate -s 6G /dev/shm/bk.ext4 && mkfs.ext4 -q /dev/shm/bk.ext4
&& mount -o loop,discard /dev/shm/bk.ext4 <dir> && chmod 1777 <dir>`), never a plain tmpfs:
unprivileged overlayfs on tmpfs refuses directory renames (EXDEV) and dpkg fails in the
image's apt step. One build at a time then (they share the directory).

`CI_LOCAL_PATHS` pushes the committed `HEAD` plus only those paths from the working tree,
for when other people's unfinished work elsewhere in the tree doesn't build yet.

`ci-local.sh guard` (run it in the background) stops the runner and its jobs when free
disk or memory runs low. `down` removes the containers, the job containers and volumes,
the network and the state; `--images` also the images it pulled.

## Limits

GitLab CE is the Free tier: the production gate is the protected manual job;
deployment approvals and protected environments (Premium) can't be shown here. GitHub
Actions itself can't run here: `github` runs `deploy-env.yml`'s step script (read from the
workflow) in a pod with the ARC staging ServiceAccount, or for production in a pod without
rights and with `KUBECONFIG_DATA`, using the deploy tools image in the runner image's place.
`docs/test-plans/phase-9.md` records a run.
