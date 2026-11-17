**Bastion Kit · CLAUDE.md**

# Bastion: project memory for Claude Code

## Who and why
- Owner: Vishnu Chivukula. GitHub: `VishnuChivukula`. LinkedIn: `cvishnuprasad`.
- Background: risk & compliance professional in BFSI (European banks), IAPP AIGP and Claude Certified Architect candidate, moving into senior AI engineering / AI governance roles.
- This repo is his **public portfolio flagship**. Audiences: (1) hiring managers for Forward Deployed Engineer, AI Platform Lead and Head of AI Governance roles; (2) bank clients in pre-sales demos.
- **Division of labour:** Vishnu clicks approvals, does the few human-only steps (see `kit-local/START_HERE.md`, local only, not published) and reviews `[VERIFY]` items. **You do everything else**: specs, architecture, code, tests, evals, docs, git, GitHub, deploy config, launch copy.

## What Bastion is
A **runtime governance control plane for AI agents**. Every tool call an agent makes passes through a policy-enforcing MCP gateway, with risk classification at registration, human approvals bound to exact arguments, kill switch, budgets, PII redaction, a tamper-evident audit log, incidents, red-team evals in CI and auto-generated regulatory evidence packs.

Product name: **Bastion**. Repo name: **`bastion-agent-governance`**, which avoids confusion with Azure Bastion.

## Sources of truth (read in this order before any work)
1. `docs/SPEC.md`: what to build (requirement IDs FR-xx / NFR-xx)
2. `docs/ARCHITECTURE.md`: how to build it. Decisions are fixed unless you write an ADR in `docs/adr/`
3. `docs/USE_CASES.md`: scenarios, acceptance criteria, demo script
4. `docs/EVALS.md`: eval suites, scenario catalogue, CI thresholds
5. `docs/GOVERNANCE_MAPPING.md`: regulatory mapping and the VERIFY rule
6. `docs/SLICES.md`: build order, definition of done per slice, cut line
7. `docs/PROGRESS.md`: current state. **Update it at the end of every slice.**

## Non-negotiables
- **Synthetic data only.** No real people, banks, employers or clients. Never mention the owner's employer, its clients or any real bank. Use emails `@example.com` / `@bank.example`, test-format IBANs, Faker names with a fixed seed.
- **Secrets:** never read, print or commit `.env` or key values. Keys come from env vars / `.env` loaded at runtime. `.env` is gitignored. gitleaks runs in pre-commit and CI.
- **Default-deny:** a tool with no matching rule is denied. **No `eval()` / `exec()`** on policy conditions. Use the custom AST evaluator in ARCHITECTURE.md.
- **VERIFY rule:** every regulatory reference (article, annex, clause, control ID) carries a `[VERIFY]` marker and an entry in `docs/VERIFY.md`. Paraphrase in your own words and never paste passages of legal or standards text. Never invent ISO/IEC 42001 Annex A control numbers; cite clause level or write `[VERIFY: control id]`.
- **Disclaimer** in the README, console footer and every evidence pack: *reference implementation; not production; not legal advice.*
- **`make demo` must work with NO API key** (replay mode). Never break it.
- **`main` stays green.** Run `make check` before every commit.

## Working rules
- Build in vertical slices per `docs/SLICES.md`. A slice is done only when tests are green, docs are touched, PROGRESS is updated, and the slice is committed and pushed.
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`), small and frequent.
- A smaller working slice beats broad scaffolding. No stubs that pretend to work; if something is deferred, say so in PROGRESS.
- If a library API differs from what ARCHITECTURE.md assumes, check the installed version (source or docs), adapt, and record an ADR.
- **Save usage by delegating:** use the `doc-writer` subagent for prose docs, README sections, synthetic data text and launch copy. Use the `reviewer` subagent for an independent review at the end of S4 and S9. Keep architecture and core code yourself.
- If context gets long: write the exact next step into PROGRESS, commit, push, and tell Vishnu to run `/clear` and paste `prompts/RESUME.md`.
- **Ask Vishnu only for:** API key presence, GitHub auth, the Railway URL, licence or name changes, and VERIFY review. Decide everything else yourself and log it under PROGRESS → Decisions.
- After each slice, print a 3-line status: what's done, what's next, and any human action needed.
- **Design docs stay current.** Every slice that changes behaviour updates the affected sections of `docs/design/` (HLD, LLD, AGENT_ARCHITECTURE, DATA_MODEL, API, SECURITY) and the rows it touches in `docs/design/TRACEABILITY.md`, adds or removes rows in `docs/design/DIVERGENCES.md`, and rebuilds the pack with `make design-pdf`. Design docs describe the code as built, not the plan.

## Commands (the Makefile is the interface)
`make setup` · `make check` (ruff + pytest) · `make demo` (replay, no key) · `make record` (needs key) · `make eval` · `make evidence AGENT=loan-ops-agent` · `make verify-audit` · `make gif` · `make serve` (API + console locally) · `make up` (docker compose) · `make design-pdf`

## Conventions
- Python 3.12, uv, type hints, ruff (format + lint), pytest, Pydantic v2 at every boundary, pydantic-settings for config.
- Mermaid for diagrams in markdown.
- **PDF/DOCX outputs produced by the system** (e.g. evidence packs) carry a header with the document name and a footer reading `Page X of Y`.
- Model IDs come from config: fast = `claude-haiku-5-5`, smart = `claude-sonnet-5-5`. Prices live in `config/prices.yaml`, marked `[VERIFY]`; check them against docs.claude.com when web access is available.
- Licence: Apache-2.0.

---
*CLAUDE.md · Page 1 of 1*
