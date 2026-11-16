# Bastion: the Makefile is the interface. Run `make help`.
.DEFAULT_GOAL := help
AGENT ?= loan-ops-agent
export BASTION_MODE ?= replay

.PHONY: help setup check preflight demo record eval evidence verify-audit gif serve up

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install dependencies and git hooks
	uv sync
	uv run pre-commit install

check: ## Lint, format check and tests (run before every commit)
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest --cov --cov-report=term-missing:skip-covered

preflight: ## Report whether an API key is configured (never prints the value)
	@uv run bastion preflight

demo: ## Run the scripted scenarios in replay mode (no API key needed)
	@BASTION_MODE=replay uv run python -m demo.loan_ops_agent.run

record: ## Re-record LLM fixtures (needs ANTHROPIC_API_KEY; calls the API)
	@BASTION_MODE=record uv run python -m demo.loan_ops_agent.run

eval: ## Run red-team, benign and assessor suites
	@echo "not yet: S6"

evidence: ## Generate the evidence pack: make evidence AGENT=loan-ops-agent
	@echo "not yet: S7"

verify-audit: ## Verify the audit hash chain
	@uv run bastion verify-audit

gif: ## Record the demo GIF
	@echo "not yet: S9b"

serve: ## Run API + console locally
	@echo "not yet: S4"

up: ## Run in Docker
	@echo "not yet: S8"
