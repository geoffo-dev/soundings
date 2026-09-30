# Soundings backend. Run from the repo root with `make -C backend <target>`.
.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv
PORT ?= 8000
OPENAPI_OUT ?= openapi.json
SWAGGER_UI_VERSION ?= 5.33.0
SWAGGER_DIR := app/static/swagger

.PHONY: help install fmt lint typecheck test check dev worker migrate revision openapi vendor-swagger

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

install: ## Install dependencies from uv.lock
	$(UV) sync --locked

fmt: ## Format and auto-fix
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint: ## Lint (ruff) and check formatting
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: ## Type-check (mypy --strict)
	$(UV) run mypy

test: ## Run tests (needs Docker, or TEST_DATABASE_URL pointing at a throwaway DB)
	$(UV) run pytest

check: lint typecheck test ## Lint + typecheck + test

dev: ## Run the API with auto-reload on PORT (default 8000)
	$(UV) run soundings api --reload --port $(PORT)

worker: ## Run the background worker
	$(UV) run soundings worker

migrate: ## Apply database migrations (app + procrastinate schema)
	$(UV) run soundings migrate

revision: ## New Alembic revision from model changes: make revision m="add ideas"
	@test -n "$(m)" || { echo 'usage: make revision m="describe the change"'; exit 2; }
	$(UV) run alembic revision --autogenerate -m "$(m)"

openapi: ## Export the OpenAPI document to OPENAPI_OUT (default openapi.json)
	$(UV) run soundings openapi --output $(OPENAPI_OUT)

vendor-swagger: ## Refresh the vendored Swagger UI assets from npm (SWAGGER_UI_VERSION)
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	  (cd "$$tmp" && npm pack --silent swagger-ui-dist@$(SWAGGER_UI_VERSION) >/dev/null && tar xzf swagger-ui-dist-*.tgz) && \
	  for f in swagger-ui-bundle.js swagger-ui-bundle.js.LICENSE.txt swagger-ui.css favicon-32x32.png LICENSE NOTICE; do \
	    cp "$$tmp/package/$$f" $(SWAGGER_DIR)/; done && \
	  echo "$(SWAGGER_UI_VERSION)" > $(SWAGGER_DIR)/VERSION && \
	  echo "Swagger UI $(SWAGGER_UI_VERSION) vendored into $(SWAGGER_DIR)"
