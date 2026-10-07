# Soundings: top-level tasks. `make` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE ?= docker compose -f dev/docker-compose.yml
IMAGE ?= soundings:dev
# CA bundle trusted by the image build's npm/pip/uv (TLS-intercepting proxies). Passed
# as a BuildKit secret, never stored in the image. Empty: none.
BUILD_CA ?= $(SSL_CERT_FILE)
# Extra `docker build` flags, e.g. --build-arg UBUNTU_MIRROR=http://mirror.internal/ubuntu
# or --build-arg NPM_CONFIG_REGISTRY=https://npm.internal/.
IMAGE_BUILD_ARGS ?=
VCS_REF := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
OPENAPI_JSON := frontend/src/api/generated/openapi.json
# `make demo`: the image with demo data on http://localhost:$(DEMO_PORT) and its email in
# Mailpit on http://localhost:$(DEMO_MAILPIT_PORT) (scripts/demo.sh).
DEMO_PORT ?= 8000
DEMO_MAILPIT_PORT ?= 8026
# `make demo DEMO_AI=1`: AI assistance against the fake kagent agent too.
DEMO_AI ?=
# `make e2e` runs against this URL (by default the one `make demo` serves).
E2E_BASE_URL ?= http://localhost:$(DEMO_PORT)
# `make k3s-install SSO=1` / `make k3s-smoke SSO=1`: single sign-on with Keycloak in k3s.
SSO ?=
# `make k3s-install SMTP=1` / `make k3s-smoke SMTP=1`: email to Mailpit in k3s.
SMTP ?=
# `make k3s-install MCP=1` / `make k3s-smoke MCP=1`: the MCP server for in-cluster agents.
MCP ?=
# `make k3s-install AI=1` / `make k3s-smoke AI=1`: AI runs against the fake kagent in k3s.
# `make k3s-install PROD=1` / `make k3s-smoke PROD=1`: production mode (no dev login).
AI ?=
# The fake kagent agent's image (dev/fake-agent; dev, CI and k3s only).
FAKE_AGENT_IMAGE ?= soundings-fake-agent:dev
# `make sso-smoke` runs against this app (configured for the dev Keycloak realm).
SSO_BASE_URL ?= http://localhost:8000
# `make email-smoke` runs against this app (dev login, worker, Mailpit: MAILPIT_URL,
# MAILPIT_CONTAINER; defaults: the dev compose Mailpit).
EMAIL_BASE_URL ?= http://localhost:8000
# `make public-smoke` runs against this app (demo data and dev login: `make dev` or
# `make demo`).
PUBLIC_BASE_URL ?= http://localhost:8000
# `make mcp-smoke` runs against this app (demo data and dev login: `make dev` or `make demo`).
MCP_BASE_URL ?= http://localhost:8000
# `make ai-smoke` runs against this app (demo data, dev login, features.ai and the fake agent
# with FAKE_AGENT_KEYS_DIR=AI_FAKE_KEYS_DIR: dev/README.md "AI: the fake kagent").
AI_BASE_URL ?= http://localhost:8000
AI_FAKE_KEYS_DIR ?= $(CURDIR)/dev/.fake-agent-keys
AI_FAKE_URL ?= http://localhost:$(SOUNDINGS_DEV_FAKE_AGENT_PORT)
SOUNDINGS_DEV_FAKE_AGENT_PORT ?= 8083

comma := ,
build_ca_flag = $(if $(wildcard $(BUILD_CA)),--secret id=build_ca$(comma)src=$(BUILD_CA))

.PHONY: help dev-up dev-down dev-logs dev check check-backend check-frontend check-helm \
        check-scripts check-fake-agent e2e image fake-agent-image demo demo-down k3s-up k3s-load \
        k3s-keycloak k3s-mailpit k3s-fake-agent k3s-kagent-crds k3s-install k3s-smoke k3s-down \
        openapi gen-api seed sso-smoke email-smoke public-smoke mcp-smoke ai-smoke

help: ## List targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

# --- Local dev services (Postgres, Keycloak, Mailpit) -----------------------------------
dev-up: ## Start dev services (docker compose) and wait until healthy
	$(COMPOSE) up -d --wait

dev-down: ## Stop dev services (keeps data; add -v by hand to wipe it)
	$(COMPOSE) down

dev-logs: ## Follow dev service logs
	$(COMPOSE) logs -f --tail=100

dev: ## How to run the backend and frontend dev servers (with Keycloak SSO)
	@echo "1. make dev-up                                   # Postgres, Keycloak, Mailpit (dev/README.md)"
	@echo "2. cp dev/.env.example dev/.env                  # once: database, dev login and Keycloak SSO settings"
	@echo "   set -a; . dev/.env; set +a                    # in every shell that runs the backend"
	@echo "   make -C backend install migrate               # once, and after pulling migrations"
	@echo "   make seed                                     # demo data (alice is the platform admin)"
	@echo "3. make -C backend dev                           # API on http://localhost:8000"
	@echo "   make -C backend worker                        # sends email, reminders, digests (other terminal)"
	@echo "4. npm --prefix frontend ci && npm --prefix frontend run dev   # SPA on http://localhost:5173"
	@echo "   (npm --prefix frontend run dev:mock runs the SPA against MSW mocks, no backend needed)"
	@echo "5. http://localhost:5173 -> Sign in with SSO -> alice / password (Keycloak users: dev/README.md)"
	@echo "   make sso-smoke                                # the same flow scripted with curl, plus groups -> access"
	@echo "6. http://localhost:8025                         # Mailpit: every email the worker sends"
	@echo "   make email-smoke                              # invite -> email with the evaluate link; SMTP outage -> delivered later"

# --- Checks ------------------------------------------------------------------------------
check: check-backend check-frontend check-helm check-scripts check-fake-agent ## Run every check

check-backend: ## Backend lint + mypy + tests (needs Docker for testcontainers)
	$(MAKE) -C backend check

check-frontend: ## Frontend typecheck + lint + tests + build
	npm --prefix frontend run check

check-helm: ## helm lint + template for defaults and deploy/helm/ci/*-values.yaml
	scripts/check-task.sh helm

check-scripts: ## bash -n (+ shellcheck when available) for scripts/
	scripts/check-task.sh scripts

check-fake-agent: ## The fake kagent agent (dev/fake-agent): ruff, mypy --strict, pytest
	$(MAKE) -C dev/fake-agent check

e2e: ## Playwright end-to-end tests (e2e/) against E2E_BASE_URL (default: make demo)
	@if [ ! -f e2e/package.json ]; then echo "e2e/ does not exist yet (Phase 1, owned by qa)"; \
	else [ -d e2e/node_modules ] || npm --prefix e2e ci; \
	  E2E_BASE_URL=$(E2E_BASE_URL) npm --prefix e2e run test; fi

# --- Image and local Kubernetes ----------------------------------------------------------
image: ## Build the container image (IMAGE, default soundings:dev)
	docker build $(build_ca_flag) --build-arg VCS_REF=$(VCS_REF) \
	  --build-arg BUILD_DATE=$$(date -u +%Y-%m-%dT%H:%M:%SZ) $(IMAGE_BUILD_ARGS) -t $(IMAGE) .

fake-agent-image: ## Build the fake kagent agent's image (FAKE_AGENT_IMAGE, default soundings-fake-agent:dev)
	$(MAKE) -C dev/fake-agent image IMAGE=$(FAKE_AGENT_IMAGE)

demo: image $(if $(filter 1,$(DEMO_AI)),fake-agent-image) ## Build the image, run it with Postgres, the worker, Mailpit (localhost:DEMO_MAILPIT_PORT) + demo data on localhost:DEMO_PORT (DEMO_AI=1: + the fake kagent agent)
	IMAGE=$(IMAGE) DEMO_PORT=$(DEMO_PORT) DEMO_MAILPIT_PORT=$(DEMO_MAILPIT_PORT) DEMO_AI='$(DEMO_AI)' \
	  FAKE_AGENT_IMAGE=$(FAKE_AGENT_IMAGE) scripts/demo.sh up

demo-down: ## Remove the demo containers and their data
	scripts/demo.sh down

k3s-up: ## Start a local k3s cluster in Docker (K3S_NAME, ports 16443/18081)
	scripts/k3s-up.sh

k3s-load: ## Import the image (IMAGE) into the k3s node
	scripts/k3s-load-image.sh $(IMAGE)

k3s-keycloak: ## Keycloak with the dev realm in the k3s cluster (for SSO=1 below)
	scripts/k3s-keycloak.sh up

k3s-mailpit: ## Mailpit in the k3s cluster (for SMTP=1 below; inbox http://mailpit.localhost:18081)
	scripts/k3s-mailpit.sh up

k3s-fake-agent: ## The fake kagent in k3s as kagent/kagent-controller:8083 (for AI=1 below; builds FAKE_AGENT_IMAGE if missing)
	FAKE_AGENT_IMAGE=$(FAKE_AGENT_IMAGE) scripts/k3s-fake-agent.sh up

k3s-kagent-crds: ## kagent v0.10.2's CRDs in k3s (KAGENT_VERSION), then a server-side dry run of every kagent manifest
	scripts/k3s-kagent-crds.sh install && scripts/k3s-kagent-crds.sh check

k3s-install: k3s-load ## Load the image (IMAGE) and helm upgrade --install it (dev/k3s-values.yaml; SSO=1: + Keycloak; SMTP=1: + Mailpit; MCP=1: + agents' NetworkPolicy; AI=1: + AI runs; PROD=1: production mode)
	image='$(IMAGE)'; SSO='$(SSO)' SMTP='$(SMTP)' MCP='$(MCP)' AI='$(AI)' PROD='$(PROD)' scripts/k3s-install.sh \
	  --set image.repository="$${image%:*}" --set image.tag="$${image##*:}"

k3s-smoke: ## Curl /healthz, /readyz and / through the ingress, public form + PDF export, then helm test (SSO=1: + SSO flow; SMTP=1: + email; MCP=1: + MCP, in-cluster client; AI=1: + AI runs; PROD=1: production checks)
	SSO='$(SSO)' SMTP='$(SMTP)' MCP='$(MCP)' AI='$(AI)' PROD='$(PROD)' scripts/k3s-smoke.sh

k3s-down: ## Delete the local k3s cluster
	scripts/k3s-down.sh

sso-smoke: ## Scripted SSO sign-in + groups -> access against SSO_BASE_URL (default the make dev API)
	scripts/sso-smoke.sh $(SSO_BASE_URL)

email-smoke: ## Invite -> branded email in Mailpit, then an SMTP outage -> delivered once (EMAIL_BASE_URL, MAILPIT_URL)
	scripts/email-smoke.sh $(EMAIL_BASE_URL)

public-smoke: ## Public form + branding, then anonymous idea -> approved -> proposal -> PDF/Markdown export (PUBLIC_BASE_URL)
	scripts/public-smoke.sh $(PUBLIC_BASE_URL)

mcp-smoke: ## API key -> /mcp: tools, blind search, submit an evaluation, project restriction, audit, revoke -> 401 (MCP_BASE_URL)
	scripts/mcp-smoke.sh $(MCP_BASE_URL)

ai-smoke: ## Register an agent, "Ask AI to evaluate" -> cited AI evaluation left out of the aggregate, research, draft, cancel (AI_BASE_URL, fake agent)
	AI_FAKE_KEYS_DIR='$(AI_FAKE_KEYS_DIR)' AI_FAKE_URL='$(AI_FAKE_URL)' scripts/ai-smoke.sh $(AI_BASE_URL)

# --- API contract ------------------------------------------------------------------------
openapi: ## Export the backend's OpenAPI document to $(OPENAPI_JSON)
	$(MAKE) -C backend openapi OPENAPI_OUT=$(CURDIR)/$(OPENAPI_JSON)

gen-api: openapi ## Export OpenAPI and regenerate the TypeScript client types
	npm --prefix frontend run gen:api

seed: ## Migrate + load demo data into SOUNDINGS_DATABASE_URL (RESET=1 replaces all data)
	cd backend && uv run soundings migrate && uv run soundings seed $(if $(RESET),--reset)
