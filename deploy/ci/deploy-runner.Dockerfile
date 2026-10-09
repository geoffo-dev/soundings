# syntax=docker/dockerfile:1
# Images that run scripts/deploy.sh: helm and kubectl, both static binaries copied from
# their images, every base pinned by digest (Dependabot's docker ecosystem bumps them).
#
#   runner (default)  the GitHub Actions runner for Actions Runner Controller (ARC) scale
#                     sets in the cluster (deploy/ci/arc-values.yaml): the official runner
#                     image plus helm and kubectl. It already has bash, curl, git and jq.
#   tools             a small deploy image for GitLab's DEPLOY_IMAGE or a person's laptop:
#                     alpine/helm (bash, curl, git, helm) plus kubectl.
#
#   docker build -f deploy/ci/deploy-runner.Dockerfile -t <registry>/soundings-deploy-runner:2.338.0-1 deploy/ci
#   docker build -f deploy/ci/deploy-runner.Dockerfile --target tools -t <registry>/soundings-deploy-tools:1 deploy/ci
#   (make deploy-runner-image / make deploy-tools-image)
#
# Air-gapped: point BuildKit at your mirrors instead of editing the FROM lines, e.g. in
# buildkitd.toml: [registry."docker.io"] mirrors = ["harbor.internal/dockerhub"] and
# [registry."ghcr.io"] mirrors = ["harbor.internal/ghcr"] (or the Docker daemon's
# registry-mirrors for docker.io). Nothing is downloaded from the internet otherwise.

FROM docker.io/alpine/helm:3.16.2@sha256:a19a2968fd672336d39771f6c899781424d725229148656dbc2a1e305003cdec AS helm
FROM docker.io/rancher/kubectl:v1.31.14@sha256:c01afebbff02d9e67108604f48a8cc780ff7dd1af0ea12d108f0fc019e532301 AS kubectl

# --- tools: GitLab's deploy jobs, people ------------------------------------------------
FROM docker.io/alpine/helm:3.16.2@sha256:a19a2968fd672336d39771f6c899781424d725229148656dbc2a1e305003cdec AS tools
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl
# A shell as the default command: CI jobs run their script in it.
ENTRYPOINT []
CMD ["bash"]

# --- runner: GitHub Actions on ARC --------------------------------------------------------
# The runner image's user (runner, uid 1001) and entrypoint stay as they are; ARC runs
# /home/runner/run.sh. The container must be named "runner" in the scale set's template.
FROM ghcr.io/actions/actions-runner:2.338.0@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807 AS runner
COPY --from=helm /usr/bin/helm /usr/local/bin/helm
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl
