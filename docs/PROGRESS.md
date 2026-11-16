**Bastion Kit · PROGRESS.md**

# Progress log (Claude updates this at the end of every slice)

## Status
| Slice | Status | Commit | Notes |
|---|---|---|---|
| S0 Bootstrap | ☑ | see `git log` (`chore: bootstrap`) | uv project, config, LLM replay/record/live client, CI, ADR-001..006, VERIFY register |
| S1 Gateway + audit | ☐ | | |
| S2 Demo agent + replay | ☐ | | |
| S3 Oversight | ☐ | | |
| S4 API + console | ☐ | | |
| S8 Package + deploy | ☐ | | |
| S9a Ship-now polish | ☐ | | |
| S5 Registry + assessor | ☐ | | |
| S6 Evals + CI gate | ☐ | | |
| S7 Evidence pack | ☐ | | |
| S9b Showcase | ☐ | | |

## Next exact step
S1: add deps (`mcp`, `sqlalchemy`, `presidio-analyzer`, `presidio-anonymizer`, `faker`, spaCy `en_core_web_sm`); build `demo/data/generate.py`, `demo/tools_server`, `gateway/conditions.py` first (AST evaluator + exhaustive tests), then `normalize.py`, `policy_engine.py`, `redaction.py`, `budgets.py`, `mcp_proxy.py`, `audit/log.py`, `audit/verify.py`, CLI `bastion verify-audit`. Check the installed `mcp` version for mounting a low-level server in FastAPI and write ADR-007.

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

## Human actions needed
- None now. Later: Railway deploy after S8 (`kit-local/START_HERE.md` step 7); review `docs/VERIFY.md`.

## Deferred / known gaps
- Makefile targets `demo`, `record`, `eval`, `evidence`, `verify-audit`, `gif`, `serve`, `up` print "not yet: Sx" until their slice lands.
- The LLM client has the hook interface but no budget / kill-switch / audit hooks yet (S1, S3).
- `config/settings.example.yaml` from ARCHITECTURE §3 is not created: `.env.example` already documents every setting.

---
*PROGRESS.md · Page 1 of 1*
