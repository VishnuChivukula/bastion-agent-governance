**Bastion Kit · PROGRESS.md**

# Progress log (Claude updates this at the end of every slice)

## Status
| Slice | Status | Commit | Notes |
|---|---|---|---|
| S0 Bootstrap | ☑ | see `git log` (`chore: bootstrap`) | uv project, config, LLM replay/record/live client, CI, ADR-001..006, VERIFY register |
| S1 Gateway + audit | ☑ | see `git log` (`feat: gateway core`) | policy engine, AST conditions, arg hardening, Presidio redaction + DLP, tool budgets, MCP proxy over streamable HTTP, hash-chained audit + verify; pytest covers RT-04..RT-12, RT-17..RT-20, RT-23..RT-25 and the gateway half of RT-01..RT-03 (their incident half is S3); 266 tests, 98% coverage, overhead p95 ≈ 23 ms |
| S2 Demo agent + replay | ☐ | | |
| S3 Oversight | ◐ | see `git log` (`feat: oversight`) | core done and unit-tested ahead of S2 (RT-13..RT-16, RT-20..RT-22, UC-04/05/07 at gateway level): args-bound single-use grants, TTL, revoke, kill switch (agent + global), incident rules + lifecycle, model token/cost budgets. Remaining: end-to-end UC-04..UC-07 through the agent in replay (lands with S2). |
| S4 API + console | ☐ | | |
| S8 Package + deploy | ☐ | | |
| S9a Ship-now polish | ☐ | | |
| S5 Registry + assessor | ☐ | | |
| S6 Evals + CI gate | ☐ | | |
| S7 Evidence pack | ☐ | | |
| S9b Showcase | ☐ | | |

## Next exact step
S2 (+ S3 end-to-end): build `demo/loan_ops_agent/` — `tools.py` (the agent's own tool manifest, all five tools), `graph.py` (LangGraph: `model` node → `tools` node → `await_approval` node using `interrupt()`; AsyncSqliteSaver; MCP streamable-HTTP client to the gateway with bearer token + `X-Bastion-Run`; `GovernedAnthropic` with `GovernanceHook`), `scenarios.py` (UC-02..UC-07; UC-05 swap and UC-07 kill are driven by the scenario script), `run.py` (starts the gateway on a local port, runs scenarios, prints a decision timeline from the audit log). Then `make record` (key is set) and `make demo` in replay. Claude API notes: no `temperature`, no forced `tool_choice`, pass assistant content (incl. thinking blocks) back unchanged, return all tool results in one user message.

## Decisions (date — decision — why)
- 2026-11-16 — The project has its own git repo (`git init` in the project folder) — the home folder is itself a git repo and must never be touched or pushed.
- 2026-11-16 — `START_HERE.*`, `setup.command`, `start-bastion.command` live in gitignored `kit-local/` — personal setup notes, not for publication (owner's decision). `CLAUDE.md`, `docs/`, `prompts/`, `policies/`, `.claude/` are published: the spec-driven process is part of the showcase.
- 2026-11-16 — The "no employer" rule in `CLAUDE.md` and the doc-writer agent is worded without naming anyone (owner's decision).
- 2026-11-16 — No `temperature` is sent on model calls (ADR-004) — the configured models reject non-default sampling parameters; replay provides determinism.
- 2026-11-16 — Fixture key hashes the whole request, not a fixed field list (ADR-004) — so `output_config` and future parameters distinguish fixtures.
- 2026-11-16 — Governance controls attach to the LLM client as call hooks (`before_call` / `after_call`) — budget, kill-switch and audit hooks land with their modules in S1/S3 rather than as stubs now.
- 2026-11-16 — Dependencies are added per slice, not all up front — keeps install and CI fast and avoids unused packages.
- 2026-11-16 — ruff rules S102/S307 are enabled — lint fails on any `exec()` / `eval()`.
- 2026-11-16 — Pre-commit runs ruff via `uv run` (local hooks) and gitleaks from its upstream hook repo.
- 2026-11-16 — Docker is not installed locally — S8 will verify the image with a CI `docker build` job.
- 2026-11-16 — Gateway uses the low-level `mcp` 2.x server, not FastMCP (ADR-007) — per-agent proxied tool lists; FastMCP no longer exists under that name in mcp 2.x.
- 2026-11-16 — Demo customer data lives in its own SQLite file (`data/demo.db`), separate from Bastion's database — the tools server stands in for the bank's system and must not share state with the control plane.
- 2026-11-16 — Budget sessions are Bastion-issued run ids; unknown ids share one bucket per agent — otherwise an agent could reset its budget by inventing ids.
- 2026-11-16 — Malformed calls to an always-denied tool are still reported under that tool's rule and category — an injected `export_customer_data` call with sloppy arguments must still count as exfiltration.
- 2026-11-16 — Approval ids are deterministic (`APR-` + hash of agent, tool, args hash, ordinal) — keeps replayed model fixtures stable (ADR-004).
- 2026-11-16 — Rejected arguments are audited by field name only; valid arguments are audited with PII masked — the audit log must not become a PII store.
- 2026-11-16 — Added an e-mail pattern recogniser alongside Presidio's — Presidio's own recogniser misses reserved test domains such as `@bank.example`.
- 2026-11-16 — `pending approval` rows are created in S1; decisions, grants, expiry and revocation follow in S3.
- 2026-11-16 — S3's oversight core was built before the S2 agent — model fixtures depend on tool results, and the kill switch and grants change those results, so recording once after oversight avoids re-recording.
- 2026-11-16 — Kill-switch denials are not counted by incident rules and a killed agent still authenticates — its calls are denied and audited rather than vanishing as 401s, without piling up duplicate incidents.
- 2026-11-16 — CI failure on the S1 commit: `data/` in `.gitignore` also matched `demo/data/`, so the generator was never committed. Fixed by anchoring the rule to `/data/`.

## Human actions needed
- None now. Later: Railway deploy after S8 (`kit-local/START_HERE.md` step 7); review `docs/VERIFY.md`.

## Deferred / known gaps
- Makefile targets `demo`, `record`, `eval`, `evidence`, `gif`, `serve`, `up` print "not yet: Sx" until their slice lands.
- The LLM client has the hook interface but no budget / kill-switch / audit hooks yet (S2, S3).
- "Active runs halted" marks run rows as `halted` and denies further calls; stopping a LangGraph run in flight is handled by the agent runner (S2).
- Audit verification cannot detect deletion of the newest events (no external anchor for the chain head); noted in ADR-005.
- `config/settings.example.yaml` from ARCHITECTURE §3 is not created: `.env.example` already documents every setting.

---
*PROGRESS.md · Page 1 of 1*
