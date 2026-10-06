# Soundings' fake kagent agent (README.md). `make -C dev/fake-agent <target>`.
.DEFAULT_GOAL := help
IMAGE ?= soundings-fake-agent:dev
BUILD_CA ?= $(SSL_CERT_FILE)
comma := ,
build_ca_flag = $(if $(wildcard $(BUILD_CA)),--secret id=build_ca$(comma)src=$(BUILD_CA))

.PHONY: help install check lint typecheck test fmt run image

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

install: ## uv sync --locked (with the dev tools)
	uv sync --locked

check: lint typecheck test ## ruff, mypy --strict, pytest

lint: ## ruff check + format --check
	uv run ruff check . && uv run ruff format --check .

typecheck: ## mypy --strict
	uv run mypy

test: ## pytest (FAKE_AGENT_COMPAT=0 skips the a2a-sdk 0.3.23 client check)
	uv run pytest

fmt: ## ruff format + fix
	uv run ruff format . && uv run ruff check --fix .

# `make run` defaults for `make dev` (dev/README.md "AI: the fake kagent"); the
# environment's FAKE_AGENT_* win.
FAKE_AGENT_PORT ?= 8083
FAKE_AGENT_MCP_URL ?= http://localhost:8000/mcp
FAKE_AGENT_KEYS_DIR ?= $(abspath $(CURDIR)/../.fake-agent-keys)
export FAKE_AGENT_PORT FAKE_AGENT_MCP_URL FAKE_AGENT_KEYS_DIR

run: ## Serve on FAKE_AGENT_PORT (8083) for the dev API (FAKE_AGENT_MCP_URL), keys in dev/.fake-agent-keys
	mkdir -p "$(FAKE_AGENT_KEYS_DIR)" && uv run fake-agent

image: ## Build the image (IMAGE, default soundings-fake-agent:dev)
	docker build $(build_ca_flag) -t $(IMAGE) .
