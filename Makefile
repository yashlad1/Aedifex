# Developer entry points. Every target works from a clean checkout.
#
# Targets above the line need no infrastructure; targets below it need docker compose.

PYTHON := .venv/bin/python
VENV := .venv

.DEFAULT_GOAL := help
.PHONY: help install lock check lint format typecheck test test-integration test-all \
        validate-registry audit migrate migration downgrade up down logs run-api clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

$(VENV):
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip uv

install: $(VENV) ## Install exactly the locked dependency set
	# --locked fails if uv.lock has drifted from pyproject.toml, so a developer cannot end up
	# with a dependency graph that CI will not reproduce.
	UV_PROJECT_ENVIRONMENT=$(VENV) $(VENV)/bin/uv sync --locked --extra dev

lock: $(VENV) ## Re-resolve uv.lock after changing dependencies in pyproject.toml
	$(VENV)/bin/uv lock

# --- No infrastructure required ---------------------------------------------

check: lint typecheck test ## Run every gate that does not need infrastructure

lint: ## Check formatting and lint rules
	$(VENV)/bin/ruff check src tests apps scripts migrations
	$(VENV)/bin/black --check src tests apps scripts migrations

format: ## Apply formatting and autofixable lint rules
	$(VENV)/bin/ruff check --fix src tests apps scripts migrations
	$(VENV)/bin/black src tests apps scripts migrations

typecheck: ## Run mypy in strict mode
	$(VENV)/bin/mypy

test: ## Run unit tests (no database needed)
	$(PYTHON) -m pytest tests/unit -q

test-integration: ## Run integration tests (requires PostgreSQL)
	# REQUIRE_INTEGRATION_TESTS turns an unexpected skip into a failure, so "it passed" cannot
	# mean "it never ran". Drop the variable to allow skipping when no database is available.
	REQUIRE_INTEGRATION_TESTS=1 $(PYTHON) -m pytest tests/integration -q -m integration

test-all: ## Run the whole suite
	$(PYTHON) -m pytest -q

validate-registry: ## Validate the source registry and show review status
	$(PYTHON) -m scripts.validate_registry

audit: ## Audit the locked dependency set for known vulnerabilities
	# Audits uv.lock rather than the installed environment: --strict otherwise fails on our
	# own editable, non-PyPI package, and the lock is what actually ships.
	$(VENV)/bin/uv export --frozen --no-emit-project --extra dev \
		--format requirements.txt -o .audit-requirements.txt
	$(VENV)/bin/pip-audit --strict --disable-pip -r .audit-requirements.txt
	@rm -f .audit-requirements.txt

# --- Requires docker compose -------------------------------------------------

up: ## Start PostgreSQL and MinIO
	docker compose up -d postgres minio minio_init

down: ## Stop the stack and remove volumes
	docker compose down -v

logs: ## Tail stack logs
	docker compose logs -f

migrate: ## Apply migrations to head
	$(VENV)/bin/alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add findings table"
	@test -n "$(m)" || (echo "usage: make migration m=\"description\"" && exit 1)
	$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

downgrade: ## Reverse the most recent migration
	$(VENV)/bin/alembic downgrade -1

run-api: ## Run the API with reload at http://localhost:8000/docs
	$(VENV)/bin/uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
