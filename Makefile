# Soundings: top-level tasks. `make` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE ?= docker compose -f dev/docker-compose.yml
IMAGE ?= soundings:dev
# CA bundle trusted by the image build's npm/pip/uv (TLS-intercepting proxies). Passed
# as a BuildKit secret, never stored in the image. Empty: none.
BUILD_CA ?= $(SSL_CERT_FILE)
# Extra `docker build` flags, e.g. --build-arg RUNTIME_APT_PACKAGES= when no Debian
# mirror is reachable, or --build-arg NPM_CONFIG_REGISTRY=https://npm.internal/.
IMAGE_BUILD_ARGS ?=
VCS_REF := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
OPENAPI_JSON := frontend/src/api/generated/openapi.json
# `make demo`: the image with demo data on http://localhost:$(DEMO_PORT) (scripts/demo.sh).
DEMO_PORT ?= 8000
# `make e2e` runs against this URL (by default the one `make demo` serves).
E2E_BASE_URL ?= http://localhost:$(DEMO_PORT)

comma := ,
build_ca_flag = $(if $(wildcard $(BUILD_CA)),--secret id=build_ca$(comma)src=$(BUILD_CA))

.PHONY: help dev-up dev-down dev-logs dev check check-backend check-frontend check-helm \
        check-scripts e2e image demo demo-down k3s-up k3s-load k3s-install k3s-smoke k3s-down \
        openapi gen-api seed

help: ## List targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

# --- Local dev services (Postgres, Keycloak, Mailpit) -----------------------------------
dev-up: ## Start dev services (docker compose) and wait until healthy
	$(COMPOSE) up -d --wait

dev-down: ## Stop dev services (keeps data; add -v by hand to wipe it)
	$(COMPOSE) down

dev-logs: ## Follow dev service logs
	$(COMPOSE) logs -f --tail=100

dev: ## How to run the backend and frontend dev servers
	@echo "1. make dev-up                                   # Postgres, Keycloak, Mailpit (dev/README.md)"
	@echo "2. export SOUNDINGS_DATABASE_URL=postgresql+psycopg://soundings:soundings@localhost:5432/soundings"
	@echo "   export SOUNDINGS_DEV_LOGIN_ENABLED=true"
	@echo "   make -C backend install migrate               # once, and after pulling migrations"
	@echo "   make seed                                     # demo data (alice is the platform admin)"
	@echo "3. make -C backend dev                           # API on http://localhost:8000"
	@echo "   make -C backend worker                        # background jobs (other terminal)"
	@echo "4. npm --prefix frontend ci && npm --prefix frontend run dev   # SPA on http://localhost:5173"
	@echo "   (npm --prefix frontend run dev:mock runs the SPA against MSW mocks, no backend needed)"

# --- Checks ------------------------------------------------------------------------------
check: check-backend check-frontend check-helm check-scripts ## Run every check

check-backend: ## Backend lint + mypy + tests (needs Docker for testcontainers)
	$(MAKE) -C backend check

check-frontend: ## Frontend typecheck + lint + tests + build
	npm --prefix frontend run check

check-helm: ## helm lint + template for defaults and deploy/helm/ci/*-values.yaml
	scripts/check-task.sh helm

check-scripts: ## bash -n (+ shellcheck when available) for scripts/
	scripts/check-task.sh scripts

e2e: ## Playwright end-to-end tests (e2e/) against E2E_BASE_URL (default: make demo)
	@if [ ! -f e2e/package.json ]; then echo "e2e/ does not exist yet (Phase 1, owned by qa)"; \
	else [ -d e2e/node_modules ] || npm --prefix e2e ci; \
	  E2E_BASE_URL=$(E2E_BASE_URL) npm --prefix e2e run test; fi

# --- Image and local Kubernetes ----------------------------------------------------------
image: ## Build the container image (IMAGE, default soundings:dev)
	docker build $(build_ca_flag) --build-arg VCS_REF=$(VCS_REF) \
	  --build-arg BUILD_DATE=$$(date -u +%Y-%m-%dT%H:%M:%SZ) $(IMAGE_BUILD_ARGS) -t $(IMAGE) .

demo: image ## Build the image, run it with Postgres + demo data on localhost:DEMO_PORT
	IMAGE=$(IMAGE) DEMO_PORT=$(DEMO_PORT) scripts/demo.sh up

demo-down: ## Remove the demo containers and their data
	scripts/demo.sh down

k3s-up: ## Start a local k3s cluster in Docker (K3S_NAME, ports 16443/18081)
	scripts/k3s-up.sh

k3s-load: ## Import the image (IMAGE) into the k3s node
	scripts/k3s-load-image.sh $(IMAGE)

k3s-install: k3s-load ## Load the image (IMAGE) and helm upgrade --install it with dev/k3s-values.yaml
	image='$(IMAGE)'; scripts/k3s-install.sh \
	  --set image.repository="$${image%:*}" --set image.tag="$${image##*:}"

k3s-smoke: ## Curl /healthz, /readyz and / through the ingress, then helm test
	scripts/k3s-smoke.sh

k3s-down: ## Delete the local k3s cluster
	scripts/k3s-down.sh

# --- API contract ------------------------------------------------------------------------
openapi: ## Export the backend's OpenAPI document to $(OPENAPI_JSON)
	$(MAKE) -C backend openapi OPENAPI_OUT=$(CURDIR)/$(OPENAPI_JSON)

gen-api: openapi ## Export OpenAPI and regenerate the TypeScript client types
	npm --prefix frontend run gen:api

seed: ## Migrate + load demo data into SOUNDINGS_DATABASE_URL (RESET=1 replaces all data)
	cd backend && uv run soundings migrate && uv run soundings seed $(if $(RESET),--reset)
