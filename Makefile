# AlgoLens developer entrypoints.
#
# This repo is a hybrid: a Vite/React frontend at the root and a Flask API
# service under algolens-api/. `make install` sets up both.
#
# Fresh clone, first time:
#     make install        # frontend deps + backend venv + .env scaffold
#     make dev            # run the frontend dev server
SHELL := /bin/bash

VENV   := algolens-api/.venv
VPY    := $(VENV)/bin/python
VPIP   := $(VENV)/bin/pip
PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help install install-frontend install-backend test build dev clean

help: ## Show available targets
	@echo "AlgoLens -- portfolio dashboard (React frontend + Flask backend)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: install-frontend install-backend ## Install everything (main entrypoint)
	@echo ""
	@echo "Ready. Run 'make dev' for the frontend, or 'make test' to run the suites."

install-frontend: ## Install frontend (npm) dependencies
	@command -v npm >/dev/null 2>&1 || { echo "npm not found. Install Node.js 20+."; exit 1; }
	@npm ci

install-backend: ## Create the backend venv and install Python dependencies
	@command -v $(PYTHON) >/dev/null 2>&1 || { echo "$(PYTHON) not found. Install Python 3.11+."; exit 1; }
	@if [ ! -d $(VENV) ]; then \
		echo "Creating API virtualenv at $(VENV)"; \
		$(PYTHON) -m venv $(VENV); \
	fi
	@$(VPIP) install --quiet --upgrade pip
	@$(VPIP) install --quiet -r algolens-api/requirements.txt
	@if [ ! -f algolens-api/.env ] && [ -f algolens-api/.env.example ]; then \
		cp algolens-api/.env.example algolens-api/.env; \
		echo ""; \
		echo "Created algolens-api/.env from algolens-api/.env.example -- fill in DB creds and JWT_SECRET_KEY."; \
	fi

test: ## Run frontend and backend test suites
	@echo "==> Frontend"
	@npm test --if-present
	@echo "==> Backend"
	@if [ -d algolens-api/tests ]; then \
		cd algolens-api && .venv/bin/python -m pytest tests -q; \
	else \
		echo "algolens-api/tests not present on this branch yet -- skipping."; \
	fi

build: ## Build the production frontend bundle
	@npm run build

dev: ## Start the frontend dev server
	@npm run dev

clean: ## Remove installed dependencies and build output
	@rm -rf node_modules build $(VENV)
	@find algolens-api -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned node_modules, build/, and the backend venv."
