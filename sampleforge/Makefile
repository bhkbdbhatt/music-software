# SampleForge developer tasks.
#
#   make dev        bring up the whole stack
#   make test       pytest + coverage on the host
#   make migrate    alembic upgrade head
#   make lint       ruff check + ruff format --check
#   make generate   submit a sample job against the running API
#
# Run `make help` for the full list.
#
# Recipes assume a POSIX shell: Linux, macOS, WSL, or Git Bash on Windows.
# Native Windows cmd.exe is not supported — the Compose stack itself needs a
# Linux host or WSL2 anyway.

SHELL := /bin/sh

# Docker Compose v2. Override for the standalone v1 binary:
#   make dev COMPOSE=docker-compose
COMPOSE ?= docker compose

# The venv uv creates. Overridable: `make test PYTHON=/usr/bin/python3`.
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif [ -x .venv/Scripts/python.exe ]; then echo .venv/Scripts/python.exe; else echo python3; fi)

# .env is required by compose (env_file) and by alembic (settings).
ENV_FILE := .env

# The dev API key, read out of .env so `make generate` cannot drift from the key
# the API actually accepts. Falls back to the example value.
API_KEY := $(shell grep -oE 'SAMPLEFORGE_API_KEYS=.*' $(ENV_FILE) 2>/dev/null | head -n1 | grep -oE '"[^"]+"' | head -n1 | tr -d '"')

.DEFAULT_GOAL := help
.PHONY: help env dev dev-cpu up down logs ps rebuild shell dbshell \
        test test-fast coverage migrate migrate-down migration \
        lint format fmt check clean generate recipe curl-health

## ---------------------------------------------------------------------------
## Help
## ---------------------------------------------------------------------------
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## ---------------------------------------------------------------------------
## Local environment
## ---------------------------------------------------------------------------
env: $(ENV_FILE) ## Create .env from the template if it does not exist

$(ENV_FILE): .env.example
	@echo "Creating .env from .env.example"
	@cp .env.example $@
	@echo "Edit $ENV_FILE and change SAMPLEFORGE_API_KEYS before sharing anything."

install: ## Create the local venv with dev dependencies (uv)
	uv sync --group dev

## ---------------------------------------------------------------------------
## Stack
## ---------------------------------------------------------------------------
dev: env ## Build and start the whole stack (Postgres, Redis, MinIO, api, worker)
	$(COMPOSE) up --build

dev-cpu: env ## Start the stack on CPU only, skipping the API and worker
	$(COMPOSE) up postgres redis minio

up: env ## Start already-built services
	$(COMPOSE) up

down: ## Stop the stack, keeping volumes
	$(COMPOSE) down

clean-stack: ## Stop the stack and DELETE all volumes (jobs, recipes, samples)
	$(COMPOSE) down -v

rebuild: env ## Force a rebuild with no cache (needed after pyproject changes)
	$(COMPOSE) build --no-cache

logs: ## Tail logs from every service
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

shell: ## Shell into the running API container
	$(COMPOSE) exec api /bin/bash

dbshell: ## Open psql against the dev database
	$(COMPOSE) exec postgres psql -U sampleforge -d sampleforge

## ---------------------------------------------------------------------------
## Tests
## ---------------------------------------------------------------------------
test: ## Run the test suite with a coverage report
	$(PYTHON) -m pytest --cov=app --cov-report=term-missing

test-fast: ## Run the test suite without coverage
	$(PYTHON) -m pytest -q

coverage: test ## Alias for test, kept for muscle memory

## ---------------------------------------------------------------------------
## Database
## ---------------------------------------------------------------------------
migrate: ## Apply all migrations (host interpreter, needs a reachable database)
	$(PYTHON) -m alembic upgrade head

migrate-down: ## Roll back one migration
	$(PYTHON) -m alembic downgrade -1

migration: ## Autogenerate a revision: make migration m="add x"
	$(PYTHON) -m alembic revision --autogenerate -m "$(m)"

check-migrations: ## Fail if the models have drifted from the migrations
	$(PYTHON) -m alembic check

## ---------------------------------------------------------------------------
## Lint and format
## ---------------------------------------------------------------------------
lint: ## ruff check, then verify formatting
	$(PYTHON) -m ruff check app tests alembic
	$(PYTHON) -m ruff format --check app tests alembic

format: ## Apply ruff's autofixes and reformat in place
	$(PYTHON) -m ruff check --fix app tests alembic
	$(PYTHON) -m ruff format app tests alembic

fmt: format ## Alias for format

check: lint test ## Everything CI would run

## ---------------------------------------------------------------------------
## Smoke test against a running stack
## ---------------------------------------------------------------------------
# The spec below is validated against app.models.schemas.GenerationSpec: type,
# category, fundamental_hz, spectral_ceiling_hz, spectral_floor_hz, peak_db,
# attack_ms, decay_ms, sustain_level, release_ms, bpm, key and genre are all
# required. Note the field is `format` (not file_format), and there is no `seed`
# in the spec — seeding is derived per job by the worker.
SPEC := {"type":"one_shot","category":"kick","duration_ms":300,"fundamental_hz":[40.0,90.0],"spectral_ceiling_hz":12000.0,"spectral_floor_hz":20.0,"peak_db":-12.0,"attack_ms":1.0,"decay_ms":100.0,"sustain_level":0.0,"release_ms":50.0,"bpm":120.0,"key":"F#m","genre":"techno","format":"wav","batch_size":1}

curl-health: ## GET /v1/health
	@curl -sS http://localhost:8000/v1/health | $(PYTHON) -m json.tool

generate: env ## Submit a generation job and poll it to completion
	@echo "==> POST /v1/generate"
	@response=$$(curl -sS -X POST http://localhost:8000/v1/generate \
		-H "Content-Type: application/json" \
		-H "X-API-Key: $(API_KEY)" \
		-d '$(SPEC)'); \
	echo "$$response" | $(PYTHON) -m json.tool; \
	job_id=$$(echo "$$response" | $(PYTHON) -c "import json,sys; print(json.load(sys.stdin)['job_id'])"); \
	echo "==> polling $$job_id"; \
	for i in $$(seq 1 30); do \
		body=$$(curl -sS "http://localhost:8000/v1/jobs/$$job_id" -H "X-API-Key: $(API_KEY)"); \
		status=$$(echo "$$body" | $(PYTHON) -c "import json,sys; print(json.load(sys.stdin)['status'])"); \
		echo "    [$$i] $$status"; \
		case "$$status" in \
			complete|complete_with_warnings) echo "$$body" | $(PYTHON) -m json.tool; break ;; \
			failed) echo "$$body" | $(PYTHON) -m json.tool; exit 1 ;; \
		esac; \
		sleep 2; \
	done

recipe: env ## Save the same spec as a named recipe
	@curl -sS -X POST http://localhost:8000/v1/recipes \
		-H "Content-Type: application/json" \
		-H "X-API-Key: $(API_KEY)" \
		-d '{"name":"dev-kick","description":"40-90 Hz kick, fast attack","spec":$(SPEC)}' \
		| $(PYTHON) -m json.tool

## ---------------------------------------------------------------------------
## Housekeeping
## ---------------------------------------------------------------------------
clean: ## Remove caches, coverage output, and local renders
	@rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov var
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Cleaned."
