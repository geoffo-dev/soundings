# Soundings: one image for the REST API (which also serves the built SPA) and the
# background worker. Ubuntu 24.04 with Ubuntu's Python 3.12 and the Pango stack for
# WeasyPrint's PDF export (ADR 0011).
#
#   docker build -t soundings:dev .
#   docker run --rm -p 8000:8000 --env-file soundings.env soundings:dev   # API + SPA
#   docker run --rm --env-file soundings.env soundings:dev worker         # worker
#   docker run --rm --env-file soundings.env soundings:dev migrate        # migrations
#
# The image runs in **production** mode (SOUNDINGS_ENVIRONMENT=production): it needs
# SOUNDINGS_DATABASE_URL, SOUNDINGS_SECRET_KEY (32+ random characters) and
# SOUNDINGS_BASE_URLS at least (docs/operator-guide.md, "Running the image without
# Helm"). Development (dev login, the demo seed without --force) must be asked for
# with SOUNDINGS_ENVIRONMENT=development, as make demo and the chart's devLogin do.
#
# Build-time HTTPS behind a TLS-intercepting proxy: pass the CA bundle as a BuildKit
# secret (never stored in a layer):  docker build --secret id=build_ca,src=/path/ca.pem .
# Air-gapped mirrors: --build-arg NPM_CONFIG_REGISTRY=... / PIP_INDEX_URL=... /
# UV_DEFAULT_INDEX=... / UBUNTU_MIRROR=http://mirror.internal/ubuntu, and override the
# base images with NODE_IMAGE / UBUNTU_IMAGE.

ARG NODE_IMAGE=node:22-alpine
ARG UBUNTU_IMAGE=ubuntu:24.04

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
COPY scripts/precompress-assets.mjs /tmp/precompress-assets.mjs
# Brotli and gzip twins of every compressible file (served by backend/app/spa.py).
RUN npm run build && node /tmp/precompress-assets.mjs dist

# ---------------------------------------------------------------------------------
# 2. Base: Ubuntu, its Python 3.12 and the runtime libraries (shared by the backend
#    build and the runtime, so the venv's interpreter, /usr/bin/python3.12, and the
#    libraries WeasyPrint loads are the same in both)
# ---------------------------------------------------------------------------------
FROM ${UBUNTU_IMAGE} AS base
# python3.12: the interpreter (no pip, no venv module). libpango-1.0-0, libpangoft2-1.0-0
# and libharfbuzz-subset0 (pulling GLib, HarfBuzz, FreeType and fontconfig's library):
# what WeasyPrint dlopen()s. fontconfig: its config and fc-cache, so the system font
# cache is built here and not at runtime. fonts-dejavu-core: the fallback for glyphs the
# bundled fonts lack (Greek, Cyrillic, symbols). ca-certificates: TLS to the IdP, SMTP
# and the database. tzdata: SOUNDINGS_TIMEZONE (zoneinfo reads the system database).
# RUNTIME_APT_PACKAGES adds packages (an internal mirror's keyring, debugging tools).
ARG RUNTIME_APT_PACKAGES=""
# e.g. http://mirror.internal/ubuntu (replaces archive.ubuntu.com, security.ubuntu.com
# and ports.ubuntu.com). An https mirror behind a TLS-intercepting proxy uses the
# build_ca secret.
ARG UBUNTU_MIRROR=""
# Not version-pinned on purpose: rebuilds pick up Ubuntu security fixes (Trivy gate).
# hadolint ignore=DL3008,DL3009,SC2086
RUN --mount=type=secret,id=build_ca,required=false \
    set -eu; export DEBIAN_FRONTEND=noninteractive; \
    if [ -n "${UBUNTU_MIRROR}" ]; then \
      sed -i -E "s#https?://(archive|security|ports)\.ubuntu\.com/ubuntu(-ports)?/?#${UBUNTU_MIRROR%/}/#g" \
        /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    apt_ca=""; \
    if [ -s /run/secrets/build_ca ]; then apt_ca="-o Acquire::https::CaInfo=/run/secrets/build_ca"; fi; \
    apt-get ${apt_ca} update; \
    apt-get ${apt_ca} upgrade -y; \
    apt-get ${apt_ca} install -y --no-install-recommends \
      python3.12 libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fontconfig \
      fonts-dejavu-core ca-certificates tzdata ${RUNTIME_APT_PACKAGES}; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* /var/log/apt/* /var/log/dpkg.log; \
    # The image's default user (uid 1000) is not used; the app runs as 10001.
    userdel --remove ubuntu 2>/dev/null || true; \
    groupadd --gid 10001 soundings; \
    useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin soundings; \
    # No setuid or setgid programs (su, passwd, mount, ...): nothing here needs them, and
    # a plain `docker run` doesn't set no-new-privileges as the chart and demo.sh do.
    find / -xdev -perm /6000 -type f -exec chmod a-s {} +

# ---------------------------------------------------------------------------------
# 3. Backend: a self-contained virtualenv at /app/venv (non-editable, no dev deps),
#    built with uv on the base's /usr/bin/python3.12 (uv never downloads a Python)
# ---------------------------------------------------------------------------------
FROM base AS backend
ARG UV_VERSION=0.8.17
ARG PIP_INDEX_URL
ARG UV_DEFAULT_INDEX
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/venv
# python3.12-venv (build stage only) brings ensurepip, used once to install uv into
# its own venv; uv itself creates /app/venv without it.
# hadolint ignore=DL3008,DL3009,SC2086
RUN --mount=type=secret,id=build_ca,required=false \
    set -eu; export DEBIAN_FRONTEND=noninteractive; \
    apt_ca=""; \
    if [ -s /run/secrets/build_ca ]; then \
      apt_ca="-o Acquire::https::CaInfo=/run/secrets/build_ca"; \
      export PIP_CERT=/run/secrets/build_ca; \
    fi; \
    apt-get ${apt_ca} update; \
    apt-get ${apt_ca} install -y --no-install-recommends python3.12-venv; \
    rm -rf /var/lib/apt/lists/*; \
    python3.12 -m venv /opt/uv; \
    /opt/uv/bin/pip install "uv==${UV_VERSION}"; \
    ln -s /opt/uv/bin/uv /usr/local/bin/uv
WORKDIR /src/backend

# Dependencies first (cached until pyproject.toml/uv.lock change). The "otel" extra
# makes the chart's otel.endpoint value work without a rebuild.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-install-project --extra otel

# Then the project itself, installed as a wheel (not editable). The wheel includes the
# Alembic migrations (app/migrations), the demo data (app/seed), the email and PDF
# templates and the bundled fonts (app/assets/fonts). The last line checks that
# WeasyPrint finds Pango, HarfBuzz and fontconfig here, i.e. in the runtime's libraries.
COPY backend/README.md ./
COPY backend/app ./app
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-editable --extra otel \
    && /app/venv/bin/soundings --help >/dev/null \
    && /app/venv/bin/python -c "import weasyprint; weasyprint.HTML(string='<p>ok</p>').write_pdf()"

# ---------------------------------------------------------------------------------
# 4. Runtime
# ---------------------------------------------------------------------------------
FROM base AS runtime
ARG UBUNTU_IMAGE

COPY --from=backend /app/venv /app/venv
COPY --from=frontend /src/frontend/dist /app/static

# Read-only root filesystem: only /tmp (an emptyDir in Kubernetes, a tmpfs with
# `docker run --read-only --tmpfs /tmp`) is writable, so HOME and caches point there
# (fontconfig caches the fonts WeasyPrint adds under $XDG_CACHE_HOME/fontconfig) and no
# bytecode is written.
ENV PATH="/app/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/cache \
    SOUNDINGS_STATIC_DIR=/app/static \
    SOUNDINGS_HOST=0.0.0.0 \
    SOUNDINGS_PORT=8000 \
    SOUNDINGS_ENVIRONMENT=production

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
      org.opencontainers.image.base.name="${UBUNTU_IMAGE}"

WORKDIR /app
USER 10001:10001
# 8000: API + SPA. 9090: Prometheus /metrics (SOUNDINGS_METRICS_PORT; not on 8000 in
# production).
EXPOSE 8000 9090
# No HEALTHCHECK: Kubernetes probes /healthz (liveness) and /readyz (readiness).
ENTRYPOINT ["soundings"]
CMD ["api"]
