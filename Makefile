# Nursing Documentation AI. Run `make help` for the targets.
# .env may hold secrets: it is only read for the values below, and only
# COMPOSE_PROJECT_NAME and the three ports are exported to child processes.
# Precedence: command line > environment > .env > default (the order pydantic-settings uses).
# A makefile assignment beats an environment variable, so keep the environment's
# value of these three across the include and put it back afterwards.
ENV_SETTINGS := PORT_OFFSET AI_MODE AI_MONTHLY_CAP_USD
$(foreach v,$(ENV_SETTINGS),$(if $(filter environment,$(origin $v)),$(eval saved_$v := $($v))))
-include .env
$(foreach v,$(ENV_SETTINGS),$(if $(filter-out undefined,$(origin saved_$v)),$(eval $v := $(saved_$v))))

PORT_OFFSET ?= 0
ifneq ($(filter-out 0 1 2 3 4 5 6 7 8 9,$(PORT_OFFSET))$(words $(PORT_OFFSET)),1)
$(error PORT_OFFSET must be a whole number from 0 to 9)
endif

COMPOSE_PROJECT_NAME := nursing-ai-$(PORT_OFFSET)
WEB_PORT := $(shell echo $$((5173 + 10 * $(PORT_OFFSET))))
API_PORT := $(shell echo $$((8000 + 10 * $(PORT_OFFSET))))
DB_PORT := $(shell echo $$((55432 + 10 * $(PORT_OFFSET))))
export COMPOSE_PROJECT_NAME WEB_PORT API_PORT DB_PORT
export PATH := $(CURDIR)/.tools/bin:$(PATH)

.DEFAULT_GOAL := help
.PHONY: help ports up down dev e2e check-py check-web check actionlint gen-api openapi spend private-words accept-binary tools public-check public-check-ci hooks setup

help: ## List the targets
	@grep -E '^[a-z0-9-]+:.*## ' Makefile | awk -F ':.*## ' '{printf "%-16s %s\n", $$1, $$2}'

ports: ## Print the project name and ports for PORT_OFFSET
	@echo COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME)
	@echo WEB_PORT=$(WEB_PORT)
	@echo API_PORT=$(API_PORT)
	@echo DB_PORT=$(DB_PORT)

up: ## Start Postgres and the API in Docker Compose
	docker compose up -d --build --wait

down: ## Stop Postgres and the API (keeps the data volume)
	docker compose down

dev: up ## Start Postgres and the API, then the web app (Ctrl+C stops the web app)
	pnpm -C web dev

# The stack stays up afterwards: the caller runs `make down`.
e2e: up ## Start the stack, then run the Playwright tests
	pnpm -C web e2e

check-py: ## Python checks: ruff, pyright, pytest with coverage
	uv run ruff check
	uv run ruff format --check
	uv run pyright
	uv run pytest --cov --cov-report=term-missing

check-web: ## Web checks: eslint, tsc, vitest, build, prettier
	pnpm -C web lint
	pnpm -C web typecheck
	pnpm -C web test
	pnpm -C web build
	pnpm -C web format:check

check: check-py check-web actionlint ## Every check

gen-api: ## Rewrite web/src/api/schema.d.ts from api/openapi.json
	pnpm -C web gen:api

openapi: ## Rewrite api/openapi.json from the app
	uv run python -m nursing_api.openapi_export

spend: ## Show the AI mode and monthly cap
	@echo "AI_MODE=$(or $(AI_MODE),mock)"
	@echo "AI_MONTHLY_CAP_USD=$(or $(AI_MONTHLY_CAP_USD),not set)"
	@echo "no AI usage recorded yet (no provider before P1)"

# Interactive: the words are typed at a hidden prompt, so don't pipe it.
private-words: ## Add private words to the hashed word list (hidden prompt)
	@uv run python scripts/privacy_words.py

# Look at the file first: an image must show synthetic data only, and a font must come from its
# published source. FILE is a path from the repo root.
accept-binary: ## Record a reviewed binary file by its git blob id (FILE=path)
	@test -n '$(subst ','\'',$(FILE))' || { echo 'usage: make accept-binary FILE=path/to/file'; exit 2; }
	@uv run python scripts/reviewed_binaries.py '$(subst ','\'',$(FILE))'

tools: ## Install the pinned gitleaks into .tools/bin
	@scripts/install-tools.sh

public-check: ## Scan the whole git history for secrets, stray paths and private words
	@uv run python scripts/public_check.py

# CI has no private word list, so it checks secrets and paths only. Never use it as the local gate.
public-check-ci: ## The CI part of public-check: secrets and paths only
	@uv run python scripts/public_check.py --ci

hooks: ## Install the git pre-commit and pre-push hooks
	@uv run pre-commit install

setup: ## Install everything, including the test browser (some PCs need their own pnpm store flag)
	uv sync --all-packages
	pnpm -C web install --frozen-lockfile
	pnpm -C web exec playwright install chromium
	$(MAKE) tools
	$(MAKE) hooks

actionlint: ## Lint the GitHub Actions workflows
	uv run actionlint
