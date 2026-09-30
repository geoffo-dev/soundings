# Soundings: one image for the REST API (which also serves the built SPA) and the
# background worker.
#
#   docker build -t soundings:dev .
#   docker run --rm -p 8000:8000 -e SOUNDINGS_DATABASE_URL=... soundings:dev            # API + SPA
#   docker run --rm -e SOUNDINGS_DATABASE_URL=... soundings:dev worker                  # worker
#   docker run --rm -e SOUNDINGS_DATABASE_URL=... soundings:dev migrate                 # migrations
#
# Build-time HTTPS behind a TLS-intercepting proxy: pass the CA bundle as a BuildKit
# secret (never stored in a layer):  docker build --secret id=build_ca,src=/path/ca.pem .
# Air-gapped mirrors: --build-arg NPM_CONFIG_REGISTRY=... / PIP_INDEX_URL=... /
# UV_DEFAULT_INDEX=... and override the base images with NODE_IMAGE / PYTHON_IMAGE.

ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

# ---------------------------------------------------------------------------------
# 1. Frontend: Vite build -> /src/frontend/dist
# ---------------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS frontend
ARG NPM_CONFIG_REGISTRY
ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------------
# 2. Backend: a self-contained virtualenv at /app/venv (non-editable, no dev deps)
# ---------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS backend
ARG UV_VERSION=0.8.17
ARG PIP_INDEX_URL
ARG UV_DEFAULT_INDEX
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/venv
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install "uv==${UV_VERSION}"
WORKDIR /src/backend

# Dependencies first (cached until pyproject.toml/uv.lock change). The "otel" extra
# makes the chart's otel.endpoint value work without a rebuild.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-install-project --extra otel

# Then the project itself, installed as a wheel (not editable).
COPY backend/README.md ./
COPY backend/app ./app
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-editable --extra otel

# app.migrate looks for Alembic scripts in <dir containing the app package>/migrations,
# i.e. next to the installed package in site-packages.
COPY backend/migrations /app/venv/lib/python3.12/site-packages/migrations
RUN rm -rf /app/venv/lib/python3.12/site-packages/migrations/__pycache__ \
    && /app/venv/bin/python -m compileall -q /app/venv/lib/python3.12/site-packages/migrations \
    && /app/venv/bin/soundings --help >/dev/null

# ---------------------------------------------------------------------------------
# 3. Runtime
# ---------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# Debian packages needed at runtime: Pango, HarfBuzz (incl. subsetting) and fontconfig
# for WeasyPrint's PDF export. Set to "" to skip apt (e.g. no Debian mirror reachable;
# PDF export will then fail at runtime). Point at an internal mirror with DEBIAN_MIRROR.
# The same RUN drops pip (the app has its own venv) and creates the non-root user.
ARG PYTHON_IMAGE
ARG RUNTIME_APT_PACKAGES="libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libfontconfig1"
ARG DEBIAN_MIRROR
# Not version-pinned on purpose: rebuilds pick up Debian security fixes (Trivy gate).
# hadolint ignore=DL3008
RUN set -eu; export DEBIAN_FRONTEND=noninteractive; \
    if [ -n "${RUNTIME_APT_PACKAGES}" ]; then \
      if [ -n "${DEBIAN_MIRROR:-}" ]; then \
        sed -i "s#http://deb.debian.org#${DEBIAN_MIRROR}#g" /etc/apt/sources.list.d/debian.sources; \
      fi; \
      apt-get update; \
      apt-get upgrade -y; \
      apt-get install -y --no-install-recommends ${RUNTIME_APT_PACKAGES}; \
      rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb; \
    fi; \
    rm -rf /usr/local/lib/python3.12/site-packages/pip /usr/local/lib/python3.12/site-packages/pip-* \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12; \
    groupadd --gid 10001 soundings; \
    useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin soundings

COPY --from=backend /app/venv /app/venv
COPY --from=frontend /src/frontend/dist /app/static

# Read-only root filesystem: only /tmp (an emptyDir in Kubernetes) is writable, so
# HOME and caches (e.g. fontconfig) point there and no bytecode is written.
ENV PATH="/app/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    SOUNDINGS_STATIC_DIR=/app/static \
    SOUNDINGS_HOST=0.0.0.0 \
    SOUNDINGS_PORT=8000

ARG VERSION=0.1.0
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG SOURCE_URL=""
LABEL org.opencontainers.image.title="Soundings" \
      org.opencontainers.image.description="Submit ideas, give each an owner, evaluate them blind. API + SPA + worker." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.base.name="${PYTHON_IMAGE}"

WORKDIR /app
USER 10001:10001
EXPOSE 8000
# No HEALTHCHECK: Kubernetes probes /healthz (liveness) and /readyz (readiness).
ENTRYPOINT ["soundings"]
CMD ["api"]
