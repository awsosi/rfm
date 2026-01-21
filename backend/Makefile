# Makefile for Modular File Manager - Database Layer
# =============================================================================
# Common commands for database setup, migrations, and testing
# =============================================================================

.PHONY: help install setup migrate verify clean test format lint

# Default target
.DEFAULT_GOAL := help

# Python interpreter
PYTHON := python3
PIP := pip3

# Alembic commands
ALEMBIC := alembic

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(GREEN)Modular File Manager - Database Layer$(NC)"
	@echo "$(YELLOW)Available commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'

install: ## Install Python dependencies
	@echo "$(GREEN)Installing dependencies...$(NC)"
	$(PIP) install -r requirements.txt

install-dev: ## Install dependencies including dev tools
	@echo "$(GREEN)Installing dependencies with dev tools...$(NC)"
	$(PIP) install -r requirements.txt
	$(PIP) install -e ".[dev]"

setup: ## Initial setup (copy .env.example, install deps)
	@echo "$(GREEN)Setting up database layer...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(YELLOW)Creating .env from .env.example$(NC)"; \
		cp .env.example .env; \
		echo "$(RED)⚠️  Edit .env with your database credentials!$(NC)"; \
	else \
		echo "$(YELLOW).env already exists, skipping$(NC)"; \
	fi
	@$(MAKE) install
	@echo "$(GREEN)✓ Setup complete$(NC)"

migrate: ## Run database migrations (alembic upgrade head)
	@echo "$(GREEN)Running database migrations...$(NC)"
	$(ALEMBIC) upgrade head
	@echo "$(GREEN)✓ Migrations complete$(NC)"

migrate-down: ## Rollback one migration
	@echo "$(YELLOW)Rolling back one migration...$(NC)"
	$(ALEMBIC) downgrade -1
	@echo "$(GREEN)✓ Rollback complete$(NC)"

migrate-create: ## Create new migration (usage: make migrate-create MSG="description")
	@if [ -z "$(MSG)" ]; then \
		echo "$(RED)Error: MSG parameter required$(NC)"; \
		echo "Usage: make migrate-create MSG=\"your migration description\""; \
		exit 1; \
	fi
	@echo "$(GREEN)Creating new migration: $(MSG)$(NC)"
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

migrate-history: ## Show migration history
	@echo "$(GREEN)Migration history:$(NC)"
	$(ALEMBIC) history --verbose

migrate-current: ## Show current migration version
	@echo "$(GREEN)Current migration version:$(NC)"
	$(ALEMBIC) current

verify: ## Verify database schema
	@echo "$(GREEN)Verifying database schema...$(NC)"
	$(PYTHON) verify_schema.py

createdb: ## Create PostgreSQL database (requires DATABASE_URL in .env)
	@echo "$(GREEN)Creating database...$(NC)"
	@if [ -f .env ]; then \
		export $$(cat .env | grep -v '^#' | xargs) && \
		createdb $$(echo $$DATABASE_URL | sed 's/.*\/\([^\/]*\)$$/\1/'); \
		echo "$(GREEN)✓ Database created$(NC)"; \
	else \
		echo "$(RED)Error: .env file not found$(NC)"; \
		exit 1; \
	fi

dropdb: ## Drop PostgreSQL database (DESTRUCTIVE!)
	@echo "$(RED)⚠️  WARNING: This will delete all data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		if [ -f .env ]; then \
			export $$(cat .env | grep -v '^#' | xargs) && \
			dropdb $$(echo $$DATABASE_URL | sed 's/.*\/\([^\/]*\)$$/\1/') && \
			echo "$(GREEN)✓ Database dropped$(NC)"; \
		else \
			echo "$(RED)Error: .env file not found$(NC)"; \
			exit 1; \
		fi \
	else \
		echo "$(YELLOW)Cancelled$(NC)"; \
	fi

reset: ## Reset database (drop, create, migrate)
	@echo "$(YELLOW)Resetting database...$(NC)"
	@$(MAKE) dropdb
	@$(MAKE) createdb
	@$(MAKE) migrate
	@$(MAKE) verify
	@echo "$(GREEN)✓ Database reset complete$(NC)"

psql: ## Open psql shell to database
	@if [ -f .env ]; then \
		export $$(cat .env | grep -v '^#' | xargs) && \
		psql $$DATABASE_URL; \
	else \
		echo "$(RED)Error: .env file not found$(NC)"; \
		exit 1; \
	fi

test: ## Run tests
	@echo "$(GREEN)Running tests...$(NC)"
	pytest -v

test-cov: ## Run tests with coverage report
	@echo "$(GREEN)Running tests with coverage...$(NC)"
	pytest --cov=. --cov-report=html --cov-report=term

format: ## Format code with black and isort
	@echo "$(GREEN)Formatting code...$(NC)"
	black .
	isort .
	@echo "$(GREEN)✓ Formatting complete$(NC)"

lint: ## Run linters (ruff, mypy)
	@echo "$(GREEN)Running linters...$(NC)"
	ruff check .
	mypy .
	@echo "$(GREEN)✓ Linting complete$(NC)"

clean: ## Clean up generated files
	@echo "$(GREEN)Cleaning up...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

.PHONY: all
all: setup migrate verify ## Complete setup (install, migrate, verify)
	@echo "$(GREEN)✓ All tasks complete!$(NC)"
	@echo "$(YELLOW)Default admin credentials: admin / admin123$(NC)"
	@echo "$(RED)⚠️  Change password immediately!$(NC)"
