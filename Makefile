# Bastion: the Makefile is the interface. Run `make help`.
.DEFAULT_GOAL := help
AGENT ?= loan-ops-agent
export BASTION_MODE ?= replay

.PHONY: help setup check preflight demo record eval evidence verify-audit gif serve up smoke evidence-sample design-pdf

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install dependencies, git hooks and the headless browser used for PDFs
	uv sync
	uv run pre-commit install
	uv run playwright install chromium

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
	@BASTION_MODE=record uv run python -m evals.assessor_suite

eval: ## Run red-team, benign and assessor suites; fail on thresholds; refresh the README table
	@BASTION_MODE=replay uv run python -m evals.run
	@uv run python scripts/update_readme_results.py

evidence: ## Evidence pack (HTML + PDF) from the local database: make evidence AGENT=loan-ops-agent
	@uv run bastion evidence --agent $(AGENT) --out data/evidence

evidence-sample: ## Regenerate docs/samples/ after running the scripted scenarios (replay)
	@uv run bastion evidence --agent $(AGENT) --out docs/samples --demo

verify-audit: ## Verify the audit hash chain
	@uv run bastion verify-audit

gif: ## Record the demo GIF (docs/assets/demo.gif) from a throwaway replay-mode instance
	@uv run python scripts/make_gif.py

serve: ## Run API + console locally (console on http://localhost:8501, API docs on :8000/docs)
	@echo "Console: http://localhost:8501   API: http://127.0.0.1:8000/docs   (Ctrl-C stops both)"
	@BASTION_LOCAL_DEV=1 PORT=8501 uv run honcho start

up: ## Run in Docker (console on http://localhost:8501, API docs on http://localhost:8000/docs)
	docker compose up --build

DESIGN_DOCS = HLD LLD AGENT_ARCHITECTURE DATA_MODEL API SECURITY TRACEABILITY DIVERGENCES

design-pdf: ## Build docs/design/Bastion-Design-Pack.pdf from the design documents (needs network for Mermaid)
	@uv run python scripts/make_doc_pdf.py --title "Bastion Design Pack" \
		--subtitle "Architecture and design of a runtime governance control plane for AI agents" \
		--out docs/design/Bastion-Design-Pack.pdf $(addprefix docs/design/,$(addsuffix .md,$(DESIGN_DOCS)))

smoke: ## Smoke-test a running instance (make serve or the container): health + UC-03 + audit
	@uv run python scripts/smoke.py
