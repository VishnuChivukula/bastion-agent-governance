**Bastion Kit · PROGRESS.md**

# Progress log (Claude updates this at the end of every slice)

## Status
| Slice | Status | Commit | Notes |
|---|---|---|---|
| S0 Bootstrap | ☑ | see `git log` (`chore: bootstrap`) | uv project, config, LLM replay/record/live client, CI, ADR-001..006, VERIFY register |
| S1 Gateway + audit | ☑ | see `git log` (`feat: gateway core`) | policy engine, AST conditions, arg hardening, Presidio redaction + DLP, tool budgets, MCP proxy over streamable HTTP, hash-chained audit + verify; pytest covers RT-04..RT-12, RT-17..RT-20, RT-23..RT-25 and the gateway half of RT-01..RT-03 (their incident half is S3); 266 tests, 98% coverage, overhead p95 ≈ 10 ms |
| S2 Demo agent + replay | ☑ | see `git log` (`feat: loan ops agent`) | LangGraph agent (model → tools → await_approval with `interrupt()`), MCP HTTP client with bearer token, 10 recorded fixtures, `make demo` runs UC-02..UC-07 in replay with a decision timeline; `make record` re-records |
| S3 Oversight | ☑ | see `git log` (`feat: oversight`) | args-bound single-use grants, TTL, revoke, kill switch (agent + global), incident rules + lifecycle, model token/cost budgets; UC-04..UC-07 pass end to end in replay; RT-13..RT-23 covered in pytest |
| S4 API + console | ☑ | see `git log` (`feat: control-plane API`) | FastAPI control plane with the gateway mounted at `/mcp`; routers for agents, kill switch, usage, policies (versions, diff, activate), approvals, incidents, runs, audit (events, verify), overview; evidence route answers 501 until S7; fail-closed passcode guard (ADR-008); Streamlit console with Overview, Run Scenario, Live Activity, Approvals, Incidents, Registry, Policies; `make serve` via honcho; 345 tests, 95% coverage |
| S8 Package + deploy | ☐ | | |
| S9a Ship-now polish | ☐ | | |
| S5 Registry + assessor | ☐ | | |
| S6 Evals + CI gate | ☐ | | |
| S7 Evidence pack | ☐ | | |
| S9b Showcase | ☐ | | |

## Next exact step
S4 reviewer findings (if any P0/P1 remain, fix first). Then S8: Dockerfile (python:3.12-slim, uv sync, non-root), `docker-compose.yml`, `railway.json`, CI `docker build` job that starts the container and checks `/healthz` and the console; `make up`. Then S9a (README v1, release v0.1.0), S5, S6, S7, S9b.

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
- 2026-11-16 — The demo agent ships its own tool manifest (all five tools, including the export) instead of using gateway discovery — otherwise the denied tool is invisible and UC-03 could not show a blocked attempt. Discovery filtering (FR-11) is covered by tests.
- 2026-11-16 — UC-03 uses a deliberately trusting system prompt and an injection written to look like routine back-office work — with the standard prompt and a blatant injection the model refused by itself, which would not exercise the gateway. Documented in `graph.py`.
- 2026-11-16 — UC-05 (swap) is scripted without a model, and UC-07's Kill is pressed by the scenario script after the first tool call — both are attacker/approver actions, not model behaviour.
- 2026-11-16 — After a kill the agent's next model call is blocked by the SDK hook, so the run ends with a halt message from the agent program rather than a model-written summary.
- 2026-11-16 — The model never sees approval ids; scenario runs reset the demo data first — keeps replay fixtures valid when a scenario is run repeatedly on one database.
- 2026-11-16 — CI failure on the S1 commit: `data/` in `.gitignore` also matched `demo/data/`, so the generator was never committed. Fixed by anchoring the rule to `/data/`.

- 2026-11-16 — CI failure on the S2 commit (two causes). (1) gitleaks flagged each fixture's own sha256 in a field named `key` (generic-api-key false positive): the field is now `fixture_sha256`, and `.gitleaks.toml` exempts only that one historical commit. (2) The 50 ms latency test measured 68 ms on the CI runner: the threshold was not loosened; spaCy's parser and NER stages (unused by the pattern-based recognisers) were switched off, which cut local p95 from ~23 ms to ~10 ms, and the test now samples 100 calls.
- 2026-11-16 — S4: the gateway is one route inside the API process; the passcode guard fails closed; `make serve` enables a fixed local passcode; one scenario run at a time, each starting with an audited demo reset; runs take `approver: scripted | human` (ADR-008).
- 2026-11-16 — Console pages for Evidence and Red-Team are added in S7 and S6 with their features, not as placeholders now — no page that pretends to work.
- 2026-11-16 — `runs.final_text` column added — the agent's closing summary must survive an API restart and be readable by the console.
- 2026-11-16 — `BASTION_API_URL` defaults to `http://127.0.0.1:8000` (not `localhost`) — the API binds IPv4 loopback; `localhost` can resolve to `::1` first.
- 2026-11-16 — Console pages are thin files in `console/pages/` that call `console/views/*.render()`; the first page can be chosen with `BASTION_CONSOLE_START_PAGE` — Streamlit's test harness can only open the start page reliably, and the GIF recorder needs deep links.
- 2026-11-16 — Honcho gives the first Procfile entry the platform's `$PORT`, so `console` is listed first and the API stays on 127.0.0.1:8000 (not exposed publicly).
- 2026-11-16 — Dependabot PRs #1–#3 were already closed (the action versions they proposed are in `ci.yml`).

## Human actions needed
- None now. Later: Railway deploy after S8 (`kit-local/START_HERE.md` step 7); review `docs/VERIFY.md`.

## Deferred / known gaps
- Makefile targets `eval`, `evidence`, `gif`, `serve`, `up` print "not yet: Sx" until their slice lands.
- "Active runs halted" marks run rows as `halted` and blocks the agent's next model or tool call; a run parked at an approval interrupt is not resumed.
- Fixtures cover the six scripted scenarios only. Any change to the agent's prompts, tool manifest, policy redaction rules or demo data needs `make record` (requires a key).
- Audit verification cannot detect deletion of the newest events (no external anchor for the chain head); noted in ADR-005.
- `config/settings.example.yaml` from ARCHITECTURE §3 is not created: `.env.example` already documents every setting.

---
*PROGRESS.md · Page 1 of 1*
