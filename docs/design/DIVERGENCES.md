**Bastion Kit · design/DIVERGENCES.md**

# Where the code differs from the specification

> Reference implementation; not production; not legal advice. All data is synthetic.

`docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/USE_CASES.md` and `docs/EVALS.md` were written before the code and are kept as the original plan. The design documents in this folder describe the code as built. This file lists every difference found, so a reader of the plan is not misled. "Recorded in" names the ADR or the entry in `docs/PROGRESS.md` (Decisions) where the change was decided; "not recorded" means it was found during the documentation review.

Status values: **intended** (a deliberate change), **narrower** (the code does less than the plan says), **wider** (the code does more), **wording** (the plan's text is simply out of date).

## 1. Architecture and libraries

| # | Plan says | Code does | Status | Recorded in |
|---|---|---|---|---|
| A1 | The gateway is a FastMCP streamable-HTTP app mounted in FastAPI (ARCHITECTURE §2, §11) | The low-level `mcp.server.lowlevel.Server` with bearer-auth ASGI middleware, added to the API as one route at `/mcp` (`gateway/server.py`). The demo tools server uses `MCPServer`, the renamed FastMCP | intended | ADR-007, ADR-008 |
| A2 | Fallback: a third process on port 8100 if mounting is awkward | Not needed; two processes (console, API + gateway) plus the tools server as a stdio subprocess | wording | ADR-008 |
| A3 | Fixture key = hash of `{model, system, messages, tools, tool_choice, temperature, max_tokens}`; `temperature=0` on all agent calls (ARCHITECTURE §7) | The key hashes the whole request; no `temperature` is sent at all, because the configured models reject non-default sampling parameters | intended | ADR-004, PROGRESS |
| A4 | Registration graph ends in `interrupt(await_signoff)` (ARCHITECTURE §6.4) | The graph ends with a proposal; sign-off is a database state (`awaiting_signoff`) and a service call | intended | ADR-009 |
| A5 | "retrieve(knowledge/)" suggests ranked retrieval | All four notes are passed to the model in a fixed order | intended | ADR-009 |
| A6 | Structured output for the Assessor and Reviewer (mechanism unspecified; forced tool use was assumed) | `output_config.format` with a JSON schema, re-validated by Pydantic; forced tool choice is rejected by the configured model | intended | ADR-009 |
| A7 | `BASTION_API_URL` default `http://localhost:8000` | `http://127.0.0.1:8000` | intended | PROGRESS |
| A8 | Configuration table lists eight variables (ARCHITECTURE §10) | Also `BASTION_LOCAL_DEV`, `BASTION_LOW_MEMORY`, `BASTION_FIXTURES`, `BASTION_PRICES_PATH`, and for processes `BASTION_BIND`, `BASTION_API_BIND`, `BASTION_CONSOLE_START_PAGE`, `BASTION_DEMO_DB` | wider | ADR-008, ADR-010 |
| A9 | `config/settings.example.yaml` in the repository layout | Does not exist; settings are environment variables documented in `.env.example` | narrower | PROGRESS (known gaps) |
| A10 | Layout lists `registry/models.py`, `incidents/rules.py`, `console/pages/*.py`, `api/auth.py`, `scripts/make_gif.py`, `scripts/update_readme_results.py` | `incidents/rules.py` does not exist: incident rules are part of the policy (`gateway/policy_engine.py`) and evaluated in `incidents/service.py`. Console page bodies live in `console/views/`, with thin files in `console/pages/`. Additional modules: `api/state.py`, `api/runs.py`, `api/schemas.py`, `registry/classification.py`, `evidence/cli.py`, `headers.py`, `seed.py`, and scripts `smoke.py`, `memory_report.py`, `console_walk.py`, `make_doc_pdf.py` | wording | PROGRESS |
| A11 | Libraries: Presidio and spaCy for PII (ARCHITECTURE §11) | Presidio by default; a second, built-in pattern engine in the low-memory profile | wider | ADR-010 |
| A12 | Deployment on Railway (SPEC §4, SLICES S8) | `render.yaml` for Render's free tier is the primary path; `railway.json` remains | intended | PROGRESS (S8b) |
| A14 | ADR-001: one SQLite file shared by both processes | The console never opens a database; it only calls the API over HTTP. Only the API process (and the tools subprocess, for `demo.db`) open SQLite files | wording | not recorded |
| A15 | Registration graph starts with a `load_card` node (ARCHITECTURE §6.4) | No such node: the card is the graph's initial state (`registry/assessor_graph.py`) | wording | not recorded |
| A16 | ADR-009: outside replay mode the demo agent is seeded directly | True for the API (`api/state.py::_seed`). `make demo` and `make record` always run the real classification (`DemoEnvironment`), which is how the UC-01 fixtures are recorded | wording | not recorded |
| A13 | Docker image: "Playwright Chromium with deps" | Present; in the low-memory profile it is installed but never started | wording | ADR-010 |

## 2. Data model (ARCHITECTURE §4)

| # | Plan says | Code does | Status | Recorded in |
|---|---|---|---|---|
| D1 | `runs`: id, agent_id, scenario, status, thread_id, started_at, ended_at | Adds `final_text` | wider | PROGRESS |
| D2 | `approvals`: no rule or timestamps beyond `expires_at` | Adds `rule_id`, `created_at`, `decided_at` | wider | not recorded |
| D3 | `usage`: no primary key listed | Adds an autoincrement `id` | wording | not recorded |
| D4 | `agent_cards`, `assessments`, `policies`, `incidents`: keys as listed | Each has an autoincrement `id`; `incidents` also has `opened_at`, `closed_at`, `notes_json` as planned | wording | not recorded |
| D5 | One SQLite database | Three files: Bastion's database, the demo bank's database (`demo.db`, with a `.pristine` snapshot), and the LangGraph checkpoint database | intended | PROGRESS |
| D7 | `policies.agent_id` nullable "for templates" | Nothing writes a null agent id: templates are files in `policies/templates/` | wording | not recorded |
| D8 | One assessment per agent implied | A re-assessment adds a row; the newest is read | wording | not recorded |
| D9 | `agent_cards.version` | Always 1: no code writes a later card version | narrower | not recorded |
| D10 | A grant "is stored" (ARCHITECTURE §6.2) | There is no grants table: a grant is an `approvals` row in status `approved`, and `consumed` marks its use | wording | ADR-002 |
| D11 | Foreign keys not specified | Only `agent_cards.agent_id` and `assessments.agent_id` are real foreign keys; every other reference is logical | wording | not recorded |
| D6 | Run statuses not enumerated | `running`, `interrupted`, `completed`, `halted`, `failed` | wording | not recorded |

## 3. Functional requirements (SPEC §5)

| # | Requirement | Code does | Status | Recorded in |
|---|---|---|---|---|
| F1 | FR-03: on disagreement the Assessor revises once; remaining disagreement is shown to the human | As specified; "remaining disagreement" is computed as the Reviewer's recommended tier differing from the revised tier | wording | ADR-009 |
| F2 | FR-05: the tier selects a default policy template | Templates exist for `high`, `limited`, `minimal` and contain no tool rules (default deny). An agent-specific file `policies/<agent-id>.yaml` takes precedence, which is what the demo agent uses | intended | ADR-009 |
| F3 | FR-12: evaluation order kill switch → budget → rules | Kill switch → tool-name check → policy load → budget → catalogue lookup → argument validation → rules → input scan → grant check | wider | not recorded (see LLD §2.1) |
| F4 | FR-13: normalise tool names "exact match only" | Names must also match `[a-z][a-z0-9_]{0,63}`; anything else is denied as `invalid_tool_name` before the policy is consulted | wider | not recorded |
| F5 | FR-14: `scan_input` actions `deny`, `require_approval`, `redact` | All three exist; only `require_approval` is used by the seed policy and covered by eval scenarios | wording | not recorded |
| F6 | FR-22: kill switch halts active runs | Run rows are marked `halted` and the agent's next model or tool call is blocked. A run parked at an approval is not resumed or cancelled as a task | narrower | PROGRESS (known gaps) |
| F7 | FR-23: budgets per session and per day for tokens, cost and tool calls | Three caps exist: tool calls per session, tokens per session, cost per day. There is no per-day cap on tokens or tool calls and no per-session cost cap | narrower | not recorded |
| F18 | FR-23: model budgets enforced through the SDK wrapper | The check runs before each model call, so the call that crosses a cap completes and the next one is blocked | wording | not recorded |
| F19 | §8: tokens "shown once and stored as an sha256 hash" | As specified. Tokens never expire, and no API route rotates one (the demo runner re-issues its own at start) | narrower | not recorded |
| F20 | FR-31: verify covers the audit log | Only `audit_events` is hash-chained. Direct edits to approvals, incidents or usage rows are not detected; the stored policy text is checked against its own stored hash | narrower | not recorded |
| F8 | FR-30: every registry event is audited | Yes; additional event types exist beyond the plan (`auth_failed`, `passcode_rejected`, `model_call_blocked`, `evidence_generated`, `run_started`, `run_status`) | wider | not recorded |
| F9 | FR-31: verify detects modification, deletion or reordering | Yes, except deletion of the newest events, which leaves a shorter valid chain | narrower | ADR-005, PROGRESS |
| F10 | FR-40: an example rule "any exfiltration-category deny" | Incident rules are policy data; a kill-switch activation also opens a `KILLSWITCH` incident if none is open; kill-switch denials are not counted towards the deny threshold | wider | PROGRESS |
| F11 | FR-50: evidence pack sections as listed | All present. The framework mapping lists only capabilities with evidence in the pack, and the red-team row only when the eval results were produced against the policy in force | wider | PROGRESS |
| F12 | FR-60: README results table regenerated automatically | `make eval` rewrites it; CI checks that the committed table is current rather than committing it | intended | PROGRESS |
| F13 | FR-70: six scripted scenarios | UC-02 to UC-07. UC-05 (approve-then-swap) and the kill in UC-07 are driven by the scenario script, not by the model; UC-03 uses a deliberately trusting system prompt | intended | PROGRESS |
| F14 | FR-80: routers include "policies (CRUD + versions + diff)" (SLICES S4) | List, read, diff and activate a new version. There is no update-in-place and no delete: versions are immutable | narrower | ADR-008 |
| F15 | FR-81: console pages Overview, Registry, Live Activity, Approvals, Incidents, Policies, Evidence, Red-Team, Run Scenario | All nine exist | — | — |
| F16 | FR-82: mutating actions and live mode require the passcode | Mutating routes fail closed (`403`) when no passcode is configured. Starting a scenario is open in replay mode and needs the passcode in record and live mode. `make serve` enables a fixed local passcode | intended | ADR-008 |
| F17 | Not in the plan | Policy changes through the API cannot alter `downstream`; `global` and `unbound` are reserved agent ids; one scenario run at a time; each run starts with a demo reset that never releases the global kill switch | wider | ADR-008, PROGRESS |

## 4. Use cases and evals

| # | Plan says | Code does | Status | Recorded in |
|---|---|---|---|---|
| U1 | Every ★ use case has a Run Scenario button (USE_CASES) | UC-02 to UC-07 do. UC-01 runs from the Registry page (register and sign off) and at start-up in replay mode, not from Run Scenario | intended | ADR-009 |
| U2 | UC-01: the `high` template is applied | Tier `high` is recorded as the template tier, but the agent-specific policy overrides the template for the demo agent | intended | ADR-009 |
| U3 | UC-10: CLI exit code ≠ 0 on tamper; red banner in the console | Both exist | — | — |
| U4 | UC-11: README table regenerated on `main` | Checked in CI, not regenerated by CI (see F12) | intended | PROGRESS |
| U5 | EVALS: "agent-in-the-loop scenarios" as a second layer for the suites | Three scenarios replay recorded agent runs (RT-01, B-01, B-14). All others, including injection cases RT-02 to RT-04, are gateway-layer: they issue the call an injected agent would make | intended | PROGRESS (S6) |
| U6 | EVALS RT-02: `require_approval` (R-006) or deny via scan | `require_approval` under R-006 | wording | — |
| U7 | EVALS RT-05: case variant of the export tool | Uses `Lookup_Customer` (an allowed tool) so the case fails if the gateway ever case-folds; the export variant is checked as a second step | intended | PROGRESS |
| U8 | Demo data: notes for C-0013 and two others carry injection payloads (SLICES S1) | Four customers carry payloads (`INJECTED_NOTES` in `demo/data/generate.py`) | wider | not recorded |
| U9 | NFR-03: ≥ 80% line coverage on gateway, policy and audit | Coverage of `src/bastion` (lines and branches, about 94%) is reported per file by `make check`; the gateway, policy and audit files are above 95%, but no threshold is enforced in CI | narrower | not recorded |
| U10 | SPEC §8: live URL | Not deployed yet; the blueprint is ready and CI proves the image runs within 512 MB | narrower | PROGRESS (human action) |

## 5. How to use this file

When a later change closes a difference, remove the row. When a change introduces one, add a row and name the ADR or PROGRESS entry. The plan documents themselves are left as written.

---
*design/DIVERGENCES.md · Page 1 of 1*
