# Soundings' fake kagent (dev, e2e, CI and k3s only; never production): the A2A surface of
# kagent v0.10.2's controller for any agent with a key, serving on 8083 like
# kagent-controller. README.md says what it is and what it isn't.
#
#   docker build -t soundings-fake-agent:dev dev/fake-agent      # or: make fake-agent-image
#   docker run --rm -p 8064:8083 -e FAKE_AGENT_MCP_URL=http://host:8000/mcp \
#     -e FAKE_AGENT_KEYS=soundings/idea-evaluator=sdg_... soundings-fake-agent:dev
#
# Behind a TLS-intercepting proxy pass the CA bundle as a BuildKit secret (never stored in
# a layer): --secret id=build_ca,src=/path/ca.pem. Mirrors: --build-arg PIP_INDEX_URL=...
# / UV_DEFAULT_INDEX=...; the base image with PYTHON_IMAGE.
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
ARG UV_VERSION=0.8.17
ARG PIP_INDEX_URL
ARG UV_DEFAULT_INDEX
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/venv
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install "uv==${UV_VERSION}"
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY fake_agent ./fake_agent
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-editable \
    && /app/venv/bin/python -c "import fake_agent.app; fake_agent.app.create_app()"

FROM ${PYTHON_IMAGE}
COPY --from=build /app/venv /app/venv
ENV PATH="/app/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FAKE_AGENT_PORT=8083
LABEL org.opencontainers.image.title="Soundings fake kagent agent" \
      org.opencontainers.image.description="A deterministic A2A agent shaped like kagent v0.10.2's controller, for Soundings' tests."
USER 10001:10001
EXPOSE 8083
ENTRYPOINT ["fake-agent"]
