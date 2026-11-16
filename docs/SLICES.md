**Bastion Kit · SLICES.md**

# Bastion v0.1: Build Plan (vertical slices)

**Ship order (the cut line):** S0 → S1 → S2 → S3 → S4 → **S8 → S9a** (now publicly shippable) → S5 → S6 → S7 → S9b.
If Vishnu says usage is low, stop feature work and run `prompts/LOW_USAGE.md`.

**Every slice's definition of done:** `make check` green · new code has tests · docs touched where behaviour changed · `docs/PROGRESS.md` updated (done / decisions / next) · commit · `git push` · print a 3-line status.

---

## S0: Bootstrap and repo (~20 min)
- `git init`; uv project (Python 3.12); `src/` layout; ruff, pytest, pytest-cov; Makefile with all targets (unimplemented ones print "not yet: Sx"); `.gitignore` (incl. `.env`, `data/`, `.venv/`); `.env.example`; Apache-2.0 LICENSE; SECURITY.md; pre-commit (ruff, gitleaks); CI workflow (setup uv → `make check` → gitleaks action); dependabot.yml.
- Write ADR-001..006 (short). Create `docs/VERIFY.md`, `docs/PROGRESS.md`.
- `src/bastion/config.py` (pydantic-settings), `src/bastion/llm/` with replay/record/live plus unit tests using a fake transport.
- `gh repo create bastion-agent-governance --public --source=. --remote=origin --push` with description "Runtime governance control plane for AI agents: policy-enforcing MCP gateway, human approvals, kill switch, audit, evidence packs." Then `gh repo edit --add-topic` with ai-governance, mcp, agents, langgraph, eu-ai-act, claude, responsible-ai.
- **DoD:** repo public, CI green on GitHub (`gh run watch`).

## S1: Gateway core + audit (~60 min)
- `demo/data/generate.py` (50 customers, seed 42; notes for C-0013 and two others carry injection payloads).
- `demo/tools_server` (FastMCP; tools: lookup_customer, get_customer_notes, update_credit_limit, export_customer_data, send_email → writes to an outbox table).
- `gateway/conditions.py` (AST evaluator + exhaustive tests), `normalize.py`, `policy_engine.py`, `redaction.py` (Presidio, `en_core_web_sm`), `budgets.py`, `mcp_proxy.py`.
- `audit/log.py`, `audit/verify.py`, CLI `bastion verify-audit`.
- `policies/loan-ops-agent.yaml` from the seed in this kit.
- **DoD:** a scripted MCP client (no LLM) shows allow / deny / require_approval / redaction; audit verify passes; the tamper test fails as expected; RT-05..RT-12 and RT-24..RT-25 exist as pytest cases and pass.

## S2: Demo agent + replay fixtures (~45 min)
- `demo/loan_ops_agent/graph.py` (LangGraph; MCP client to the gateway with bearer token; SQLite checkpointer; handles `PENDING_APPROVAL` with `interrupt()`), `scenarios.py` for UC-02..UC-07.
- If a key is present (`make preflight` reports KEY_SET): `make record` to record fixtures for all scenarios. If not: ask Vishnu to add the key (START_HERE step 3) and meanwhile continue with S3 work that needs no LLM.
- **DoD:** `make demo` runs all six scenarios in replay with no key and prints a decision timeline per scenario.

## S3: Oversight (~45 min)
- `oversight/approvals.py` (args-bound single-use grants, TTL, revoke), resume-run flow, `killswitch.py`, `incidents/` rules + lifecycle, SDK budget enforcement for model calls.
- **DoD:** UC-04, UC-05, UC-06, UC-07 pass end-to-end in replay; RT-13..RT-23 pass.

## S4: API + Console (~60 min)
- FastAPI routers: agents, registry, policies (CRUD + versions + diff), approvals, killswitch, incidents, runs (start scenario, status), audit (events, verify), evidence (stub until S7). Passcode guard on mutating routes.
- Streamlit console pages per FR-81 with a mode banner and a disclaimer footer. Live Activity auto-refreshes.
- `make serve` runs both via honcho.
- Run the `reviewer` subagent on S0–S4; fix the high-priority findings.
- **DoD:** a click-through of UC-02..UC-07 works from the console in replay mode.

## S8: Package + deploy config (~30 min)
- Dockerfile (python:3.12-slim, uv sync, spaCy small model, Playwright Chromium with deps, non-root user), Procfile, docker-compose.yml, `railway.json` (Dockerfile builder; start = honcho), `/healthz`, seed on start.
- Verify `docker compose up` locally if Docker is available; otherwise verify `docker build` in CI (add a CI job).
- Tell Vishnu to do START_HERE step 7 (Railway clicks) and paste the URL using `prompts/DEPLOY_DONE.md`.
- **DoD:** image builds in CI; the container serves the console and `/healthz` returns 200.

## S9a: Ship-now polish (~20 min)
- README v1 (via `doc-writer`): one-line pitch, badges (CI, licence, Python), "Try it in 2 minutes", architecture Mermaid, features mapped to the problem, scenarios, results table markers, governance mapping summary, design decisions, limitations + disclaimer, roadmap, author (LinkedIn `cvishnuprasad`).
- `gh release create v0.1.0 --generate-notes`.
- **DoD:** a fresh clone in a temp dir runs `make demo` successfully; release published.

## S5: Registry + Assessor/Reviewer (~45 min)
- `knowledge/` paraphrased summaries (Art. 5, Art. 6, Annex III, Art. 50; `[VERIFY]`), `registry/assessor_graph.py`, sign-off flow, tier → template selection, token issuance; console Registry page; record fixtures for UC-01 and the 12 assessor cards.
- **DoD:** UC-01 passes in replay; the assessor suite runs.

## S6: Evals + CI gate (~45 min)
- `evals/run.py` running suites A/B/C from YAML; `thresholds.yaml`; `latest.json`; README table updater; CI job `make eval` that fails on thresholds; console Red-Team tab.
- **DoD:** CI shows the eval job green; the README table is populated.

## S7: Evidence pack (~30 min)
- Jinja2 template, generator from live DB, Playwright PDF with header (doc name) and footer `Page X of Y`; console Evidence page with preview and download; `make evidence`.
- Commit a sample at `docs/samples/evidence-pack-loan-ops-agent.pdf`.
- **DoD:** UC-09 passes; the sample PDF is in the repo and linked from the README.

## S9b: Showcase (~30 min)
- `make gif` → `docs/assets/demo.gif`, embedded at the top of the README.
- `docs/DEMO_SCRIPT.md`, `docs/THREAT_MODEL.md`, and `docs/SHOWCASE.md` (via `doc-writer`): LinkedIn launch post (≤ 1,300 chars), 5 interview talking points (design decision → trade-off → evidence), 60-second pitch, a pre-sales demo narrative for bank audiences (no employer or client names).
- Consolidate `docs/VERIFY.md`. Run the `reviewer` subagent on the whole repo and fix its findings.
- `gh release create v0.2.0 --generate-notes`.
- **DoD:** the SPEC §8 checklist is fully ticked in PROGRESS.

---
*SLICES.md · Page 1 of 1*
