**Bastion Kit · SPEC.md**

# Bastion v0.1: Product Specification

## 1. Problem
Banks and other regulated firms are moving from chatbots to **agents that take actions**: updating records, sending emails, exporting data. Most AI governance tooling stops at questionnaires, inventories and policy PDFs. Almost nothing **enforces** governance when an agent actually acts, or produces evidence an auditor can trust. The EU AI Act, NIST AI RMF and ISO/IEC 42001 all expect risk management, record-keeping, human oversight, robustness and incident handling to work in practice, not just on paper.

## 2. Product
Bastion is a **runtime governance control plane for AI agents**:
- **Classify before deploy:** an Assessor agent and a Reviewer agent propose an EU AI Act risk tier for each agent, and a human signs off.
- **Enforce at the tool boundary:** an MCP gateway applies policy-as-code to every tool call (allow / deny / require approval), plus PII redaction, budgets and a kill switch.
- **Prove it:** a hash-chained audit log, incidents, red-team evals in CI and an auto-generated evidence pack mapped to regulatory expectations.

## 3. Personas
| Persona | Needs |
|---|---|
| **Agent Owner** (business/engineering) | Register an agent, get it approved quickly, know what it may do |
| **Governance Approver** (2nd line: risk/compliance) | Classify risk, approve risky actions, stop an agent instantly |
| **Auditor / Model Risk** (3rd line, regulator) | Tamper-evident records, evidence mapped to obligations |
| **Platform Engineer** | Drop-in gateway, clear policy language, low latency, CI gates |

## 4. Goals for v0.1 (showcase)
1. A stranger can `git clone` and run `make demo` with no API key in under 5 minutes.
2. A live public demo URL runs in replay mode at zero cost.
3. CI is green with an eval gate, and the README shows the badge, GIF and results table.
4. A 3-minute demo covers classification → enforcement → approval → kill switch → evidence.
5. Release `v0.1.0` is tagged with notes.

## 5. Functional requirements

### Registry and classification
- **FR-01** Register an agent with an **agent card**: id, name, owner, business purpose, deployment context, affected users, data categories (incl. personal/special-category flags), tools requested, autonomy level (`suggest` | `act_with_approval` | `autonomous`), models used.
- **FR-02** The **Assessor agent** proposes a tier ∈ {`prohibited`, `high`, `limited`, `minimal`} with rationale, cited provisions `[VERIFY]`, likely obligations, confidence (0–1) and open questions. The output is structured (Pydantic).
- **FR-03** The **Reviewer agent** critiques the assessment independently (agree / disagree plus specific challenges). On disagreement, the Assessor revises **once**; any remaining disagreement is shown to the human.
- **FR-04** **Human sign-off:** accept the tier or override it with a mandatory reason. `prohibited` blocks registration. No gateway credential is issued before sign-off.
- **FR-05** The signed-off tier selects a **default policy template**; an agent-specific policy may override it. On activation, Bastion issues an **agent token** (shown once, stored hashed).

### Gateway (enforcement)
- **FR-10** An MCP server endpoint (streamable HTTP, `/mcp`) authenticates the agent token and proxies to the downstream MCP tool servers named in the agent's policy.
- **FR-11** **Least privilege in discovery:** `tools/list` returns only tools whose policy is `allow` or `require_approval`. Denied tools are hidden, but direct calls to them are still evaluated and denied.
- **FR-12** **Policy engine:** YAML, ordered rules, first match wins, **default deny**. Effects: `allow`, `deny`, `require_approval`. Conditions use a safe expression language over normalised arguments. Evaluation order: kill switch → budget → rules.
- **FR-13** **Argument hardening:** before policy evaluation, validate arguments against the tool's JSON schema; reject unknown fields; apply strict typing (no unicode digits or numeric strings for numbers); normalise tool names (exact match only, no case or whitespace tricks).
- **FR-14** **PII controls:** `redact_output: [entities]` masks PII in tool results before the agent sees them; `scan_input: [entities]` runs DLP on outbound tools (e.g. `send_email`) with a configurable action (`deny` | `require_approval` | `redact`).
- **FR-15** **Policy versioning:** each policy version is content-hashed; activation and changes are audited; every decision records the policy hash and rule id that fired.

### Oversight
- **FR-20** `require_approval` creates a **pending approval** bound to `(agent_id, tool, args_hash)` with a TTL (default 30 min). The agent receives a structured `PENDING_APPROVAL` result containing the approval id.
- **FR-21** An approver approves or rejects with a reason. Approval creates a **single-use grant**; the identical call (same args hash) consumes it. Different arguments require a new approval, which defeats approve-then-swap.
- **FR-22** **Kill switch** per agent and globally: immediate deny-all, pending approvals revoked, active runs halted. Reactivation requires a reason. All of it is audited.
- **FR-23** **Budgets** per agent (per session and per day): tokens, cost in USD, tool calls. Model calls are enforced through the Bastion SDK wrapper; tool calls at the gateway.

### Audit
- **FR-30** An append-only **hash-chained** event log covering every model call, tool decision, approval action, policy change, kill-switch action, incident and registry event. `hash = sha256(prev_hash || canonical_json(event_without_hash))`.
- **FR-31** `verify` (CLI + API) detects modification, deletion or reordering and reports the first broken link.

### Incidents
- **FR-40** Rules open incidents (e.g. ≥3 denies in 10 min; any exfiltration-category deny). Lifecycle: `open → acknowledged → contained → resolved` with notes. An optional `on_incident: kill` trips the kill switch.

### Evidence
- **FR-50** An **evidence pack** per agent in HTML + PDF. The PDF header carries the document name and the footer reads `Page X of Y`. Sections: system description (card), classification and sign-off, policy in force (hash), oversight statistics, budget usage, incidents, red-team results, audit integrity result, control mapping table, limitations, disclaimer, generation timestamp.

### Evals
- **FR-60** Red-team, benign and assessor suites (see EVALS.md). The scoreboard is written to JSON, the README results table is regenerated automatically, and CI fails when thresholds are breached.

### Demo workload
- **FR-70** **Loan Ops Agent** (LangGraph) plus a demo tools MCP server with 50 synthetic customers, and six scripted scenarios (USE_CASES.md).
- **FR-71** LLM modes: `replay` (default; fixtures, no key), `record` (live + save fixtures), `live`.

### API and console
- **FR-80** A FastAPI control-plane API with OpenAPI at `/docs`.
- **FR-81** A Streamlit console: Overview, Registry, Live Activity, Approvals, Incidents, Policies (with version history), Evidence, Red-Team, Run Scenario.
- **FR-82** The public deploy defaults to replay mode; live mode and all mutating actions require `BASTION_PASSCODE`. A visible banner shows the current mode.

## 6. Non-functional requirements
- **NFR-01** Gateway overhead p95 < 50 ms locally (excluding the downstream tool).
- **NFR-02** One-command run (`make demo`), one-command container (`make up`).
- **NFR-03** ≥ 80% line coverage on `gateway/`, `policy`, `audit/`.
- **NFR-04** CI makes no network calls to model APIs (replay only); everything is deterministic (seeded).
- **NFR-05** No secrets in the repo; gitleaks runs in pre-commit and CI; Dependabot is enabled.
- **NFR-06** Every regulatory reference carries `[VERIFY]` and is tracked in `docs/VERIFY.md`.
- **NFR-07** Clear README, architecture diagrams, ADRs, threat model and limitations.

## 7. Out of scope (v0.1)
Kubernetes, multi-tenancy, SSO/RBAC beyond the passcode, OPA/Rego, a real regulatory database, fine-tuning, multiple LLM providers (Anthropic only, behind an interface), production hardening, real email or data export.

## 8. Success criteria checklist
- [ ] `make demo` works on a clean machine without a key
- [ ] Live URL (Railway) in replay mode
- [ ] CI green: tests, red-team gate, gitleaks
- [ ] README: GIF, badge, live link, architecture, results table, quickstart, disclaimer
- [ ] Evidence pack PDF generated for `loan-ops-agent`
- [ ] Release `v0.1.0`
- [ ] `docs/VERIFY.md` complete for Vishnu's review

---
*SPEC.md · Page 1 of 1*
