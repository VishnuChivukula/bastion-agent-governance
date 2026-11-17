**Bastion Kit · design/HLD.md**

# Bastion high-level design (arc42)

> Reference implementation; not production; not legal advice.

This document describes Bastion as built in version 0.2.0. It is derived from the code, the tests and the committed eval results, not from the original plan. Where the plan and the code differ, the code is described. Regulatory references are paraphrased starting points, each marked `[VERIFY]`; Bastion supports evidence for obligations and does not make any system compliant. All data in the demo is synthetic.

Contents: 1 Introduction and quality goals · 2 Constraints · 3 Context and scope · 4 Solution strategy · 5 Building-block view · 6 Runtime view · 7 Deployment view · 8 Cross-cutting concepts · 9 Architecture decisions · 10 Quality requirements · 11 Risks and technical debt · 12 Glossary.

## 1 Introduction and quality goals

### 1.1 What Bastion is

Bastion is a runtime governance control plane for AI agents. An agent reaches its tools only through a gateway that speaks MCP (Model Context Protocol) over streamable HTTP. For every call the gateway checks a kill switch, an agent policy and a budget, validates the arguments, applies the first matching rule (default deny), optionally masks personal data, forwards the call to a downstream tool server, and writes the decision to a hash-chained audit log. Around the gateway sit a registry with two-agent risk classification and human sign-off, argument-bound approvals, incidents, a FastAPI control-plane API, a Streamlit console, red-team evals that gate CI, and a generator for evidence packs (HTML and PDF).

The repository ships one governed demo agent (the Loan Ops Agent, a LangGraph tool-using agent) and a fictional bank's customer system as a downstream MCP tool server. Model responses are replayed from recorded fixtures by default, so the whole demo runs without an API key.

### 1.2 Stakeholders

| Stakeholder | Interest | Where they touch the system |
|---|---|---|
| Agent owner | Gets an agent registered, classified and given a policy and a token | `POST /registry/agents`, Registry page, `policies/<agent-id>.yaml` |
| Governance approver | Signs off the risk tier, decides approvals, presses the kill switch, changes policy | Console (Approvals, Registry, Policies, Incidents), routes guarded by the passcode |
| Auditor | Checks what an agent did, that the log is intact, and which controls were in force | `GET /audit/events`, `GET /audit/verify`, `make verify-audit`, evidence pack |
| Platform engineer | Runs, deploys and extends the system; keeps CI green | `make` targets, `Dockerfile`, `render.yaml`, `evals/`, `tests/` |

### 1.3 Top five quality goals

Ranked by how much of the design they drive.

| Rank | Goal | What it means here | Main mechanisms |
|---|---|---|---|
| 1 | Enforcement integrity | No tool call that reaches the gateway is executed unless policy allows it; any error resolves to deny | Default deny, whitelisted condition evaluator, fail-closed paths (section 8.7) |
| 2 | Tamper-evident traceability | Every decision, approval, kill and policy change is recorded in a chain whose modification, deletion or reordering is detectable | `AuditLog.append`, `verify_chain` |
| 3 | Human oversight bound to the exact action | An approval authorises one call with one set of arguments, once, for a limited time; a kill stops an agent at once | Args-hash grants, `KillSwitchService` |
| 4 | Reproducibility without a key | A reader can run the demo, the evals and CI with no API key and get the same decisions | `GovernedAnthropic` replay mode, content-addressed fixtures |
| 5 | Low overhead and small footprint | The gateway adds little latency and the stack fits a 512 MB host | p95 gateway overhead threshold, `BASTION_LOW_MEMORY` profile |

Regulatory framing, for orientation only: the audit log supports evidence for record-keeping expectations (EU AI Act Art. 12 [VERIFY]; GDPR Art. 5(1)(c) data minimisation for the masking of personal data [VERIFY]); approvals and the kill switch support evidence for human oversight (Art. 14 [VERIFY]); the red-team suite supports evidence for robustness testing (Art. 15 [VERIFY]). The evidence pack carries the full table with caveats.

## 2 Constraints

### 2.1 Technical

| Constraint | Source in the repository | Consequence |
|---|---|---|
| Python 3.12 only (`>=3.12,<3.13`), managed with uv | `pyproject.toml` | Type hints and PEP 695 syntax (`def _structured[T: BaseModel]`) are used |
| SQLite in WAL mode through SQLAlchemy | `src/bastion/db.py`, ADR-005 | Single writer; writers queue on a 15 s busy timeout (section 8.9) |
| One container, two processes under honcho | `Procfile`, `Dockerfile`, ADR-001 | Console and API share a failure domain with the gateway; no horizontal scaling |
| `make demo`, CI and `make eval` work with no API key | `Makefile` (`BASTION_MODE ?= replay`), `.github/workflows/ci.yml` (`BASTION_MODE: replay`) | Model answers come from `fixtures/llm/*.json`; unrecorded paths stop with `ReplayMissError` |
| Anthropic SDK only for model calls | `src/bastion/llm/client.py` (`AnthropicTransport`), `anthropic` in `pyproject.toml` | No other model provider is wired; the SDK is imported lazily so replay never needs it |
| No `eval()` or `exec()` on policy conditions | `src/bastion/gateway/conditions.py`, ruff rules S102 and S307 | Conditions are parsed with `ast`, checked against a whitelist and evaluated by a tree walk (ADR-003) |
| 512 MB hosts (Render free plan) | `render.yaml`, ADR-010 | A low-memory profile swaps the PII engine and disables the PDF |
| Model IDs and prices come from configuration | `config.py` (`model_fast`, `model_smart`), `config/prices.yaml` | An unknown model has no price and raises `UnknownModelPriceError` |

### 2.2 Organisational

| Constraint | Effect |
|---|---|
| Synthetic data only | Demo data is generated with Faker and a fixed seed (`demo/data/generate.py`, `SEED = 42`, 50 customers); e-mail addresses use `@bank.example` and `@example.com` |
| VERIFY rule | Every regulatory reference carries `[VERIFY]` and has a row in `docs/VERIFY.md`; the Assessor and Reviewer prompts instruct the model to mark each citation the same way, and a validator on `Assessment.cited_provisions` rejects any citation without the marker |
| Disclaimer | "Reference implementation; not production; not legal advice." appears in the README, the console footer (`console/common.py: footer`), the API description (`create_app`) and every evidence pack (`EvidencePack.disclaimer`, `LIMITATIONS`) |
| Reference implementation | Choices such as one shared passcode and SQLite are stated as limits, not defended as production design |
| Licence | Apache-2.0 (`pyproject.toml`) |

## 3 Context and scope

### 3.1 System context

The diagram is C4 level 1 (system context). At this level the demo agent is an external actor; in the container view (section 5) it runs inside the API process as an asyncio task.

```mermaid
flowchart LR
    owner(["Agent owner<br/>submits agent cards"])
    approver(["Governance approver<br/>signs off, approves, kills"])
    auditor(["Auditor<br/>reads the log and the evidence pack"])
    platform(["Platform engineer<br/>runs and extends Bastion"])

    bastion["Bastion<br/>Software system<br/>Governs every tool call an agent makes"]
    agent["Governed agent<br/>Loan Ops Agent, LangGraph<br/>Acts only through the gateway"]
    tools["Downstream tool server<br/>MCP over stdio, synthetic bank data<br/>Executes allowed tool calls"]
    model["Model API or replay fixtures<br/>Anthropic API, or fixtures/llm/*.json<br/>Answers model requests"]

    owner -->|"submits card, receives token"| bastion
    approver -->|"decides approvals, signs off, kills"| bastion
    auditor -->|"reads audit log, downloads evidence pack"| bastion
    platform -->|"deploys, runs evals"| bastion
    agent -->|"tool calls over MCP HTTP with bearer token"| bastion
    bastion -->|"allowed calls over MCP stdio"| tools
    agent -->|"model requests through GovernedAnthropic"| model
    bastion -->|"classification requests through GovernedAnthropic"| model
```

*Figure 1. C4 level 1, system context.*

### 3.2 Business context

| Partner | Inputs to Bastion | Outputs from Bastion |
|---|---|---|
| Agent owner | Agent card (`AgentCard`: purpose, context, affected users, data categories, tools requested, autonomy level) | Proposed tier, sign-off result, a gateway token shown once |
| Governance approver | Tier sign-off or override with a reason; approve or reject with a reason; kill and reactivate with a reason; policy YAML | Pending approvals with redacted arguments, incidents, run timelines |
| Auditor | Requests for the audit log, the chain check and the evidence pack | Events with hashes, a `VerifyResult`, the evidence pack as JSON, HTML or PDF |
| Governed agent | Tool calls and a run id header | Tool results with masked personal data, or a `DENIED`, `PENDING_APPROVAL` or `TOOL_ERROR` payload |

### 3.3 Technical context

| Interface | Protocol and format | Authentication | Code |
|---|---|---|---|
| Agent to gateway | MCP streamable HTTP, stateless, JSON responses, at `/mcp`; `x-bastion-run` header carries the run id | `Authorization: Bearer <agent token>`; only the SHA-256 of the token is stored | `gateway/server.py` (`BearerAuth`, `build_mcp_route`) |
| Gateway to tool server | MCP over stdio to a subprocess started from `downstream.command` in the policy | None; the subprocess gets a minimal environment (`_PASS_THROUGH_ENV`) | `gateway/mcp_proxy.py` (`DownstreamPool`, `_Connection`) |
| Console to API | HTTP and JSON (`httpx`) | `X-Bastion-Passcode` for mutating routes; `X-Bastion-Actor` is a self-declared name | `console/client.py`, `api/auth.py`, `headers.py` |
| Operator to API | REST, OpenAPI at `/docs` | Same passcode guard | `api/main.py`, `api/routers/*` |
| Bastion to model API | Anthropic Messages API, only in `record` and `live` mode | `ANTHROPIC_API_KEY` from the environment | `llm/client.py` (`AnthropicTransport`) |
| Bastion to fixtures | JSON files named by the SHA-256 of the request | Filesystem | `llm/fixtures.py` (`FixtureStore`) |

## 4 Solution strategy

| Decision | What the code does | Why it shapes everything |
|---|---|---|
| Enforce at the tool boundary with an MCP gateway | `Gateway.call_tool` is the only path to a downstream tool; agents hold a bearer token for `/mcp` and no route to the tool server | Controls do not depend on what a model decides to do. The red-team suite tests the gateway with the calls a compromised agent would make |
| Policy as data, default deny | YAML parsed into Pydantic models with `extra="forbid"`; ordered rules, exact tool-name match, first match wins; no match is a deny (`Policy.evaluate`) | A policy is reviewable, versioned (`PolicyRow`) and hashed; every decision records the policy hash |
| Approvals bound to argument hashes | `args_hash` is the SHA-256 of canonical JSON of the normalised arguments; `ApprovalService.consume_grant` matches `(agent_id, tool, args_hash)` and marks the grant consumed | A changed argument is a different call and needs a new approval |
| Hash-chained audit | `hash = sha256(prev_hash || canonical_json(event))`, appended under the SQLite write lock; `verify_chain` walks it | Tamper evidence without extra infrastructure; the limit is truncation (section 11) |
| Replay fixtures | `GovernedAnthropic` hashes the whole request and answers from `fixtures/llm/<hash>.json` in replay mode | Deterministic demo and CI with no key; the cost is that only recorded paths run |
| One process for API and gateway | The gateway is one Starlette route inside the FastAPI app; the demo agent calls it over loopback HTTP with a real token | One port, one SQLite connection pool, simple deployment (ADR-001, ADR-008) |
| Governance of model calls through SDK hooks | `GovernanceHook` runs `before_call` (kill switch, token and cost budgets) and `after_call` (usage row, audit event) | Model spend and halts use the same kill switch and budget data as tool calls |

## 5 Building-block view

### 5.1 Containers

The diagram is C4 level 2 (containers). The three SQLite files live in the data directory, which is the parent of `BASTION_DB_PATH` (default `./data`).

```mermaid
flowchart TB
    visitor(["Approver, auditor, owner<br/>Browser"])

    subgraph host["Host or container (honcho runs two processes)"]
        console["Console<br/>Streamlit, port $PORT (8501)<br/>Pages call the API; holds no database handle"]

        subgraph apiproc["API and gateway process"]
            api["Control-plane API<br/>FastAPI and uvicorn, 127.0.0.1:8000<br/>REST routers, passcode guard, evidence rendering"]
            gw["Gateway at /mcp<br/>MCP low-level server, Starlette route<br/>Bearer auth, policy, redaction, audit"]
            agent["Demo agent task<br/>LangGraph, asyncio task via RunManager<br/>Loan Ops Agent, calls the gateway over HTTP"]
        end

        tools["Demo tools server<br/>MCP server over stdio, subprocess<br/>Five tools over synthetic bank data"]

        bastiondb[("bastion.db<br/>SQLite WAL<br/>Agents, policies, approvals, audit, usage")]
        demodb[("demo.db<br/>SQLite<br/>Synthetic customers, notes, outbox")]
        ckpt[("checkpoints.db<br/>SQLite<br/>LangGraph checkpoints for parked runs")]
        files[["Files on disk<br/>fixtures/llm, policies, knowledge, config/prices.yaml, evals/results/latest.json<br/>Read-only inputs"]]
    end

    model["Anthropic API<br/>Used only in record and live mode"]

    visitor -->|"HTTPS"| console
    console -->|"HTTP and JSON, BASTION_API_URL"| api
    api --> gw
    api -->|"starts and resumes runs"| agent
    agent -->|"tool calls, MCP HTTP, bearer token"| gw
    gw -->|"MCP stdio"| tools
    api --> bastiondb
    gw --> bastiondb
    agent --> ckpt
    tools --> demodb
    api --> files
    agent -->|"GovernedAnthropic"| files
    agent -.->|"record and live only"| model
```

*Figure 2. C4 level 2, containers.*

| Container | Code | Responsibility |
|---|---|---|
| Console | `src/bastion/console/app.py`, `pages/*.py`, `views/*.py`, `client.py` | Nine pages: Overview, Run Scenario, Live Activity, Approvals, Incidents, Registry, Policies, Evidence, Red-Team. Reads and writes only through the API |
| API and gateway process | `src/bastion/api/main.py` (`create_app`, lifespan), `api/state.py` (`build_state`) | Builds `AppState` (engine, `Gateway`, `RunManager`, `ClassificationService`), mounts `/mcp`, serves the routers |
| Demo agent | `demo/loan_ops_agent/graph.py`, `run.py` (`AgentRunner`), `api/runs.py` (`RunManager`) | A LangGraph graph run as an asyncio task; state checkpointed in `checkpoints.db` |
| Tools server | `demo/tools_server/__main__.py` | `lookup_customer`, `get_customer_notes`, `update_credit_limit`, `send_email`, `export_customer_data`; no governance of its own |
| `bastion.db` | `src/bastion/models.py` | Ten tables: `agents`, `agent_cards`, `assessments`, `policies`, `runs`, `approvals`, `incidents`, `usage`, `killswitch`, `audit_events` |
| `demo.db` | `demo/data/generate.py` (`build`, `restore`) | Customers, notes and an outbox; restored from a snapshot before each scenario |
| `checkpoints.db` | `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` in `AgentRunner._graph` | One thread per run id |

### 5.2 Gateway components

The diagram is C4 level 3 (components) for the gateway.

```mermaid
flowchart TB
    agentc["Governed agent<br/>MCP client"]

    subgraph gateway["Gateway"]
        auth["BearerAuth<br/>ASGI middleware<br/>Authenticates the token, audits failures"]
        server["build_mcp_server<br/>MCP low-level Server<br/>Per-agent tool list and call handler"]
        core["Gateway.call_tool<br/>Python class<br/>Orders the checks, audits, runs incident rules"]
        norm["normalize<br/>jsonschema, unicode NFC<br/>Strict arguments and args hash"]
        policy["Policy and Rule<br/>Pydantic, PyYAML<br/>Ordered rules, default deny"]
        cond["Condition evaluator<br/>ast whitelist<br/>Evaluates when clauses"]
        redact["Redactor / LightRedactor<br/>Presidio or patterns<br/>Masks and scans PII"]
        budget["BudgetTracker<br/>SQLAlchemy<br/>Counts tool calls per session"]
        pool["DownstreamPool<br/>MCP stdio client<br/>One connection per tool server"]
    end

    stores[("bastion.db")]
    tools["Tools server"]

    agentc --> auth --> server --> core
    core --> norm
    core --> policy --> cond
    core --> redact
    core --> budget --> stores
    core --> pool --> tools
    core -->|"AuditLog, ApprovalService, KillSwitchService, IncidentService"| stores
```

*Figure 3. C4 level 3, gateway components.*

| Component | File | Responsibility |
|---|---|---|
| `BearerAuth` | `gateway/server.py` | Looks up the SHA-256 of the token (`Registry.authenticate`); on failure appends `auth_failed` and answers 401 with `WWW-Authenticate: Bearer`; stores the agent id and the `x-bastion-run` value in the ASGI scope |
| `build_mcp_server`, `build_mcp_route` | `gateway/server.py` | `on_list_tools` returns `Gateway.list_tools(agent_id)`; `on_call_tool` returns the payload as text and structured content with `is_error` |
| `Gateway` | `gateway/mcp_proxy.py` | `call_tool`, `_decide_and_forward`, `_forward`, `_pending`, `_denied`, `_audit_decision`, `_run_incident_rules`, `list_tools` |
| `DownstreamPool`, `_Connection` | `gateway/mcp_proxy.py` | Starts each tool server once on first use; one owner task per connection because the MCP client context must be entered and exited in the same task |
| `normalize` | `gateway/normalize.py` | `is_valid_tool_name` (`[a-z][a-z0-9_]{0,63}`), `harden_schema` (closes every object), `validate_and_normalise`, `args_hash` |
| `Policy`, `Rule`, `IncidentRule`, `Decision` | `gateway/policy_engine.py` | Loading (`from_yaml`), `evaluate`, `visible_tools`, `unconditional_deny`, content hash |
| Condition evaluator | `gateway/conditions.py` | `compile_condition`; limits `MAX_LENGTH = 500`, `MAX_NODES = 100`; names `args`, `agent`, `tier`, `deny_count_10m`, `category`; functions `len`, `lower`, `startswith`, `endswith`, `contains`, `pct_change`, `now_hour` |
| `Redactor`, `LightRedactor`, `get_redactor` | `gateway/redaction.py` | Four entity types: `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`; `redact`, `scan` |
| `BudgetTracker` | `gateway/budgets.py` | `check_tool_call` and `record_tool_call` against `Usage` rows of kind `tool` |

### 5.3 Oversight components

Covers approvals, the kill switch, incidents and budgets (C4 level 3).

```mermaid
flowchart TB
    gwc["Gateway"]
    apic["Control-plane API<br/>approvals, incidents and kill routes"]

    subgraph oversight["Oversight"]
        appr["ApprovalService<br/>SQLAlchemy<br/>Request, decide, consume single-use grant, expire, revoke"]
        kill["KillSwitchService<br/>SQLAlchemy<br/>Per-agent and global deny-all"]
        inc["IncidentService<br/>SQLAlchemy<br/>Rules after a denial, lifecycle, deny counter"]
        bud["BudgetTracker and GovernanceHook<br/>Tool calls at the gateway, tokens and cost before model calls"]
        runs["RunManager<br/>asyncio<br/>Resumes a parked run when its last approval is decided"]
    end

    audit["AuditLog"]
    store[("bastion.db")]

    gwc --> appr
    gwc --> kill
    gwc --> inc
    gwc --> bud
    apic --> appr
    apic --> kill
    apic --> inc
    apic --> runs
    inc -->|"on_incident kill"| kill
    kill -->|"revoke_open"| appr
    kill -->|"opens KILLSWITCH incident"| inc
    appr --> audit
    kill --> audit
    inc --> audit
    bud --> store
    appr --> store
    kill --> store
    inc --> store
```

*Figure 4. C4 level 3, oversight components.*

| Component | File | Responsibility |
|---|---|---|
| `ApprovalStore`, `ApprovalService` | `oversight/approvals.py` | `request` (reuses an unexpired pending approval for the same call; id `APR-` plus a hash of agent, tool, args hash and ordinal), `decide` (reason required, one conditional UPDATE), `consume_grant`, `expire_stale`, `revoke_open`. Default TTL 30 minutes |
| `KillSwitchService` | `oversight/killswitch.py` | `kill`, `reactivate`, `active_scope`, `is_active`, `status`; scopes are an agent id or `global` |
| `IncidentService` | `incidents/service.py` | `open` (one open incident per agent and rule), `advance` (open, acknowledged, contained, resolved; forward only; note required), `deny_count_10m`, `evaluate_rules` |
| `GovernanceHook` | `llm/governance.py` | `before_call` blocks on kill switch, `max_tokens_per_session`, `max_cost_usd_per_day`; `after_call` writes a `Usage` row and a `model_call` event |
| `BudgetTracker` | `gateway/budgets.py` | `max_tool_calls_per_session` |
| `RunManager` | `api/runs.py` | `start`, `on_decision`, `busy`; one run at a time |

### 5.4 Registry components

Covers agent cards, the assessor graph, classification and the policy store (C4 level 3).

```mermaid
flowchart TB
    apir["Registry API<br/>FastAPI router<br/>register, read record, sign off"]

    subgraph registry["Registry"]
        cls["ClassificationService<br/>Python class<br/>submit_card, run_assessment, sign_off, policy_for"]
        agraph["assessor_graph<br/>LangGraph<br/>retrieve, assess, review, revise once"]
        reg["Registry<br/>SQLAlchemy<br/>Agents, tokens, runs, run budget buckets"]
        pol["PolicyStore<br/>SQLAlchemy<br/>Versions, activation, hash check, cache"]
        models["registry.models<br/>Pydantic<br/>AgentCard, Assessment, Review, Classification"]
    end

    llmc["GovernedAnthropic"]
    know["knowledge/eu-ai-act-*.md<br/>Paraphrased notes"]
    tmpl["policies/templates/*.yaml and policies/agent-id.yaml"]
    st[("bastion.db")]

    apir --> cls
    cls --> agraph --> llmc
    agraph --> know
    cls --> reg --> st
    cls --> pol --> st
    cls --> tmpl
    cls --> models
```

*Figure 5. C4 level 3, registry components.*

| Component | File | Responsibility |
|---|---|---|
| `Registry` | `registry/service.py` | `create_agent` (rejects the reserved ids `global` and `unbound`), `issue_token` (only for `active` agents; stores the hash), `authenticate` (accepts `active` and `killed`), `start_run`, `set_run_status`, `resolve_run` |
| `PolicyStore` | `registry/service.py` | `activate` (validates, versions, deactivates the previous version, audits `policy_activated`), `active` (checks the stored hash, caches parsed policies by hash), `versions` |
| `ClassificationService` | `registry/classification.py` | Agent states `draft`, `assessing`, `awaiting_signoff`, `active` or `blocked`; `sign_off` claims the agent with one conditional UPDATE; `policy_for` picks `policies/<agent-id>.yaml` if it exists, else the tier template |
| Assessor graph | `registry/assessor_graph.py` | Nodes `retrieve`, `assess`, `review`, `revise`; structured output through `output_config.format` with a JSON schema; stops with a proposal (ADR-009) |
| Models | `registry/models.py` | `AgentCard`, `Assessment`, `Review`, `Classification` (`proposed`, `unresolved_disagreement`), tiers `prohibited`, `high`, `limited`, `minimal` |
| Seeding | `seed.py` | `seed_demo` (direct) and `seed_demo_classified` (through the real flow, used in replay) |

### 5.5 Audit components

```mermaid
flowchart LR
    writers["Gateway, oversight, registry,<br/>API, LLM hook<br/>Callers of append"]

    subgraph audit["Audit"]
        log["AuditLog<br/>SQLAlchemy<br/>append under BEGIN IMMEDIATE, events query"]
        ver["verify_chain<br/>Python<br/>Recomputes every link"]
    end

    tbl[("audit_events<br/>in bastion.db")]
    readers["API routes, evidence generator,<br/>CLI verify-audit, evals"]

    writers --> log --> tbl
    tbl --> ver --> readers
    log --> readers
```

*Figure 6. C4 level 3, audit components.*

| Component | File | Responsibility |
|---|---|---|
| `AuditLog.append` | `audit/log.py` | Reads the head, computes `event_hash(prev_hash, body)`, inserts, all in one immediate transaction. Genesis hash is 64 zeros |
| `AuditLog.events` | `audit/log.py` | Filtered, limited reads |
| `verify_chain` | `audit/verify.py` | Returns `VerifyResult` (`ok`, `events`, `first_broken_seq`, `reason`, `head_hash`); detects sequence gaps, wrong `prev_hash` and modified content |
| `AuditEvent` | `models.py` | `seq`, `ts`, `actor`, `event_type`, `agent_id`, `payload_json`, `prev_hash`, `hash` |
| Routes and CLI | `api/routers/audit.py`, `cli.py` | `GET /audit/events`, `GET /audit/verify`, `GET /overview` (verification cached for 5 s), `bastion verify-audit` (exit code 1 if broken) |

Event types written by the code include `tool_decision`, `approval_requested`, `approval_decided`, `grant_consumed`, `approval_revoked`, `killswitch_activated`, `killswitch_reactivated`, `incident_opened`, `incident_updated`, `policy_activated`, `agent_registered`, `agent_card_submitted`, `assessment_completed`, `signoff_recorded`, `token_issued`, `run_started`, `run_status`, `model_call`, `model_call_blocked`, `auth_failed`, `passcode_rejected` and `evidence_generated`.

### 5.6 Evidence components

```mermaid
flowchart LR
    route["Evidence routes<br/>FastAPI<br/>JSON, HTML, PDF, 30 s cache, one render at a time"]
    cli["bastion evidence<br/>Typer<br/>Writes files, optional scripted run first"]

    subgraph evidence["Evidence"]
        gen["generator.collect and render_html<br/>SQLAlchemy, Jinja2<br/>Builds EvidencePack from live records"]
        tpl["pack.html.j2<br/>Jinja2 template"]
        pdf["html_to_pdf<br/>Playwright, Chromium<br/>Header with name, footer Page X of Y"]
    end

    inputs[("bastion.db and<br/>evals/results/latest.json")]

    route --> gen
    cli --> gen
    gen --> inputs
    gen --> tpl
    route --> pdf
    cli --> pdf
```

*Figure 7. C4 level 3, evidence components.*

| Component | File | Responsibility |
|---|---|---|
| `collect` | `evidence/generator.py` | Reads the agent, registration record, active policy, approvals, incidents, usage, audit events and the last eval results; verifies the chain; filters the framework `MAPPING` to rows for which evidence is present and names the omitted ones |
| `render_html`, `generate` | `evidence/generator.py` | Jinja2 with autoescape; `generate` appends an `evidence_generated` event |
| `html_to_pdf` | `evidence/pdf.py` | A4, header with the document name, footer with the disclaimer and `Page X of Y`; raises `PdfUnavailable` if Chromium is missing |
| Routes | `api/routers/evidence.py` | `/agents/{id}/evidence`, `.html`, `.pdf`; the PDF route answers 503 in low-memory mode |
| CLI | `evidence/cli.py`, `cli.py` | `make evidence`; `--demo` first runs the scripted scenarios in a throwaway environment |

### 5.7 Evals components

```mermaid
flowchart LR
    runner["evals/run.py<br/>Python<br/>Runs suites, evaluates thresholds, writes latest.json"]

    subgraph suites["Suites"]
        interp["evals/scenario.py<br/>YAML step interpreter<br/>Real gateway, no model"]
        asr["evals/assessor_suite.py<br/>Replayed classification<br/>12 cards, 3 seeded errors"]
    end

    data["evals/redteam/*.yaml, evals/benign/*.yaml,<br/>evals/assessor/*"]
    thr["evals/thresholds.yaml"]
    res["evals/results/latest.json"]
    ci["CI eval job<br/>make eval, README table check"]

    runner --> interp
    runner --> asr
    interp --> data
    asr --> data
    runner --> thr
    runner --> res
    ci --> runner
```

*Figure 8. C4 level 3, evals components.*

| Component | File | Responsibility |
|---|---|---|
| Runner | `evals/run.py` | `run`, `evaluate` (seven thresholds), `p95`, `clean_run_verifies`; exits 1 on breach; writes `latest.json` only when all three suites ran |
| Interpreter | `evals/scenario.py` | `Context.step` handles `call`, `decide`, `expire`, `kill`, `second_agent`, `http_auth`, `model_budget`, `tamper_audit`, `activate_policy`, `tamper_policy_row` and `expect_*` steps; scenarios with a `scenario:` key replay a recorded demo run (layer `agent`) |
| Assessor suite | `evals/assessor_suite.py` | Gold tiers in `evals/assessor/gold.yaml`, seeded wrong assessments in `seeded_errors.yaml` |
| Thresholds | `evals/thresholds.yaml` | See section 10 |
| Report | `scripts/update_readme_results.py`, `api/routers/evals.py`, console Red-Team page | README table and `/evals/latest` |

## 6 Runtime view

Check order in `Gateway._decide_and_forward` (the order in the code, as listed in the module docstring):

1. `killswitch.active_scope(agent_id)`: deny with `killswitch: <scope>`.
2. `is_valid_tool_name(name)`: deny `invalid_tool_name`.
3. `policies.active(agent_id)`: `PolicyLoadError` denies with `condition_error: ...`; no policy denies `no_active_policy`.
4. `budgets.check_tool_call`: deny `budget_exceeded: max_tool_calls_per_session=N`. Then `record_tool_call` (every call that gets this far counts, including ones denied later).
5. `_catalogue(policy)`: starts the tool servers on first use; a name not in the catalogue is denied (`unknown_tool` or the rule that matches).
6. `validate_and_normalise(arguments, tool.input_schema)`: deny `invalid_arguments`; then `args_hash`.
7. `policy.evaluate(name, args, {"agent": agent_id})`.
8. If allowed and the rule has `scan_input`: scan the arguments; action `redact` masks them, otherwise the effect becomes the action.
9. `deny` returns denied; `require_approval` calls `ApprovalService.consume_grant` and, with no grant, `_pending`.
10. `_forward`: call the tool, redact the output with the rule's `redact_output` entities.

Back in `call_tool`: `_audit_decision` appends `tool_decision`, then for a `DENIED` result that is not a kill-switch denial, `_run_incident_rules` evaluates the policy's incident rules and may kill the agent.

### 6.1 Allowed call with redaction

```mermaid
sequenceDiagram
    participant A as Agent
    participant B as BearerAuth
    participant G as Gateway
    participant P as Policy
    participant R as Redactor
    participant T as Tools server
    participant L as AuditLog

    A->>B: POST /mcp tools/call lookup_customer, bearer token, x-bastion-run
    B->>B: Registry.authenticate(token)
    B->>G: call_tool(agent_id, name, arguments, run_id)
    G->>G: killswitch, tool name, policy load, budget check and count
    G->>G: validate_and_normalise, args_hash
    G->>P: evaluate(lookup_customer, args)
    P-->>G: allow R-001, redact EMAIL, PHONE, IBAN
    G->>T: call_tool over stdio
    T-->>G: structured content
    G->>R: redact(content, entities)
    R-->>G: masked content, counts
    G->>L: append tool_decision (masked args, args_hash, policy_hash, overhead_ms)
    G-->>A: status OK, masked payload
```

`BearerAuth.__call__` authenticates before MCP sees the request; `Gateway.call_tool` maps the header to a budget bucket with `Registry.resolve_run` (only runs Bastion started for that agent count; anything else falls into the shared `unbound` bucket). The rule `R-001` in `policies/loan-ops-agent.yaml` masks e-mail, phone and IBAN in the output (`BaseRedactor.redact`). The audit event stores arguments with all four supported entity types masked, or only field names when the arguments were rejected. `test_unmasked_pii_never_reached_the_model` checks the model-facing side; `test_decision_is_audited_with_policy_hash_rule_and_latency` checks the record.

### 6.2 Injection, deny, incident and kill

```mermaid
sequenceDiagram
    participant A as Agent
    participant G as Gateway
    participant P as Policy
    participant I as IncidentService
    participant K as KillSwitchService
    participant H as GovernanceHook
    participant L as AuditLog

    A->>G: get_customer_notes C-0013
    G-->>A: OK, note text with an injected instruction
    A->>G: export_customer_data, all customers, external destination
    G->>P: evaluate(export_customer_data)
    P-->>G: deny R-007, category exfiltration
    G->>L: append tool_decision DENIED
    G->>I: evaluate_rules(category exfiltration)
    I->>I: IR-2 matches, open incident (high)
    I->>L: append incident_opened
    G->>K: kill(agent, reason incident IR-2, actor bastion:incident-rule)
    K->>L: append killswitch_activated
    G-->>A: DENIED, nothing executed
    A->>H: before_call for next model request
    H->>L: append model_call_blocked
    H-->>A: raises KillSwitchActive, run halts
```

The injected text is planted in the synthetic note for customer `C-0013` (`demo/data/generate.py`, `INJECTED_NOTES`). The deny comes from rule `R-007`, which carries `category: exfiltration`. `Gateway._run_incident_rules` passes that category and the count of recent denials to `IncidentService.evaluate_rules`; `IncidentRule` `IR-2` (`category == 'exfiltration'`, `on_incident: kill`) opens a high-severity incident and `KillSwitchService.kill` follows. In the graph, `model` catches `ModelCallBlocked` and ends with outcome `halted`. This scenario uses the trusting system prompt (`SYSTEM_TRUSTING`) so that the model follows the injection; the gateway holds regardless (tests: `test_uc03_injection_is_denied_opens_incident_and_kills`, `test_rt01_exfiltration_deny_opens_a_high_incident_and_kills_the_agent`).

### 6.3 Approval with an argument-bound grant and LangGraph resume

```mermaid
sequenceDiagram
    participant A as Agent graph
    participant G as Gateway
    participant S as ApprovalService
    participant C as Checkpoints
    participant U as Approver via API
    participant M as RunManager

    A->>G: update_credit_limit C-0021 to 60000
    G->>G: R-003 requires approval
    G->>S: consume_grant(agent, tool, args_hash)
    S-->>G: none
    G->>S: request(agent, run, tool, args_hash, redacted args)
    G-->>A: PENDING_APPROVAL, approval_id
    A->>A: await_approval calls interrupt()
    A->>C: checkpoint saved, run status interrupted
    U->>S: POST /approvals/id/decision, passcode, approve, reason
    S->>S: decide runs one conditional UPDATE, pending to approved
    U->>M: on_decision(approval)
    M->>A: runner.resume(decisions) with Command(resume=decisions)
    A->>G: identical call, same tool and arguments
    G->>S: consume_grant(agent, tool, args_hash)
    S-->>G: grant, status consumed
    G->>G: forward, redact output
    G-->>A: OK
```

The `tools` node in `demo/loan_ops_agent/graph.py` collects `PENDING_APPROVAL` payloads and routes to `await_approval`, whose first statement is `interrupt({"approvals": ...})`. `AgentRunner._finish` sets the run to `interrupted`. `approvals.py: decide` requires a reason and uses one conditional UPDATE, so a kill switch that revokes at the same moment cannot be overwritten. `RunManager.on_decision` resumes only when no approval of the run is still pending and the run is `interrupted`; it builds the `decisions` map and calls `AgentRunner.resume`, which re-invokes the graph with the same thread id (the run id). On resume `await_approval` re-runs from the top and re-issues the identical call; `consume_grant` marks the grant `consumed` and appends `grant_consumed`. A rejected approval yields a `REJECTED` tool result and nothing executes (`test_rejected_approval_reaches_the_agent_and_nothing_executes`). Tests: `test_uc04_human_approval_resumes_the_run`, `test_rt14_consumed_grant_cannot_be_reused`.

### 6.4 Approve-then-swap

```mermaid
sequenceDiagram
    participant X as Scripted attacker
    participant G as Gateway
    participant S as ApprovalService
    participant U as Approver
    participant L as AuditLog

    X->>G: update_credit_limit new_limit 60000
    G->>S: request, hash H1
    G-->>X: PENDING_APPROVAL, approval A1
    U->>S: decide(A1, approve)
    S->>L: append approval_decided
    X->>G: update_credit_limit new_limit 600000
    G->>G: R-003 requires approval, hash H2 differs from H1
    G->>S: consume_grant(agent, tool, H2)
    S-->>G: none
    G->>S: request, hash H2
    G-->>X: PENDING_APPROVAL, approval A2
    G->>L: append tool_decision PENDING_APPROVAL
```

`AgentRunner.swap_begin` and `swap_finish` (`demo/loan_ops_agent/run.py`) drive this without a model, because the swap is an attacker action. `args_hash` covers the normalised arguments, so `consume_grant` matches nothing for 600000. `ApprovalStore.request` creates a second approval with a deterministic id. The tool never runs and the original grant stays `approved` until its TTL (30 minutes), a kill, or a demo reset revokes it. Tests: `test_rt13_uc05_approve_then_swap_does_not_execute`, `test_uc05_swapped_arguments_do_not_execute`.

### 6.5 Budget stop

```mermaid
sequenceDiagram
    participant A as Agent
    participant G as Gateway
    participant B as BudgetTracker
    participant I as IncidentService
    participant L as AuditLog

    A->>G: tool call number 31 in the session
    G->>B: check_tool_call(agent, run, budgets)
    B-->>G: budget_exceeded, max_tool_calls_per_session=30
    G->>L: append tool_decision DENIED
    G->>I: evaluate_rules
    I->>I: IR-1 deny_count_10m >= 3 after three denials
    I->>L: append incident_opened (medium)
    G-->>A: DENIED, budget_exceeded
```

`BudgetTracker.tool_calls` counts `Usage` rows of kind `tool` for the agent and run bucket; `record_tool_call` adds a row on every call that passes the budget step. The cap comes from the policy (`budgets.max_tool_calls_per_session: 30` in the seed policy). Token and cost caps are enforced elsewhere: `GovernanceHook.before_call` raises `BudgetExceeded` before a model call and appends `model_call_blocked`. `IncidentService.deny_count_10m` counts `tool_decision` events with status `DENIED` in the last ten minutes, excluding kill-switch denials. Tests: `test_rt20_call_31_in_a_session_is_denied`, `test_ir1_opens_once_after_three_denials`, `test_rt21_token_cap_blocks_the_next_model_call_and_is_audited`.

### 6.6 Kill switch

```mermaid
sequenceDiagram
    participant U as Approver
    participant API as API route
    participant K as KillSwitchService
    participant S as ApprovalService
    participant I as IncidentService
    participant G as Gateway
    participant L as AuditLog

    U->>API: POST /agents/id/kill, passcode, reason
    API->>K: kill(scope, reason, actor)
    K->>K: one transaction: killswitch row, agents active to killed, runs to halted
    K->>S: revoke_open(agent)
    S->>L: append approval_revoked per approval
    K->>L: append killswitch_activated
    K->>I: open KILLSWITCH incident if none is open
    Note over G: next call from the agent
    G->>K: active_scope(agent)
    K-->>G: scope
    G->>L: append tool_decision DENIED killswitch
    G-->>A: DENIED, no incident rules run
```

`KillSwitchService.kill` requires a reason, accepts an agent id or `global`, marks active agents `killed`, marks `running` and `interrupted` runs `halted`, and then revokes pending approvals and unused grants. `active_scope` is the first check in `_decide_and_forward` and is a read-only lookup. A killed agent still authenticates (`Registry.authenticate` accepts `killed`) so that its calls are denied and recorded instead of disappearing as 401s. A parked run is not resumed; its row is `halted`. `reactivate` needs a reason and does not return an agent to `active` while the global switch is active. Tests: `test_rt22_uc07_kill_switch_denies_revokes_and_halts`, `test_global_kill_switch_stops_every_agent`, `test_kill_switch_blocks_model_calls_too`.

### 6.7 Registration and classification

```mermaid
sequenceDiagram
    participant O as Owner
    participant API as Registry route
    participant C as ClassificationService
    participant GR as Assessor graph
    participant M as GovernedAnthropic
    participant H as Approver
    participant PS as PolicyStore
    participant R as Registry

    O->>API: POST /registry/agents (card), passcode
    API->>C: submit_card(card)
    C->>R: create_agent, status draft
    C->>C: run_assessment(agent_id), status assessing
    C->>GR: classify(deps, card)
    GR->>M: Assessor request (JSON schema output)
    GR->>M: Reviewer request
    GR->>M: Assessor revision, only if the Reviewer disagreed
    GR-->>C: Classification
    C->>C: status awaiting_signoff, audit assessment_completed
    H->>API: POST /registry/agents/id/signoff (tier, override reason)
    API->>C: sign_off(agent_id, tier, approver)
    C->>C: conditional UPDATE awaiting_signoff to active or blocked
    C->>PS: activate(policy_for(agent, tier))
    C->>R: issue_token(agent_id)
    C-->>H: SignOffResult with the token, once
```

`ClassificationService.submit_card` creates a draft with no credential. `build_graph` in `registry/assessor_graph.py` runs `retrieve` (all four knowledge notes), `assess`, `review` and, only on `disagree`, `revise`; each call goes through `GovernedAnthropic` with a `GovernanceHook`, so replay, usage and audit apply. The graph ends with a proposal; the sign-off is a separate durable state (ADR-009). `sign_off` requires a reason to override the proposed tier; a `prohibited` tier sets status `blocked` and returns before any policy or token exists. Otherwise `policy_for` returns `policies/<agent-id>.yaml` if present, else `policies/templates/<tier>.yaml` with `__AGENT_ID__` replaced; the templates contain no tool rules, so every call is denied until rules are added as a new version. `Registry.issue_token` refuses agents that are not `active`. The tier is decision support for a human, and every cited provision is unverified `[VERIFY]`. Tests: `test_uc01_demo_agent_is_classified_high_and_signed_off_in_replay`, `test_no_credential_before_sign_off`, `test_override_needs_a_reason`, `test_sign_off_is_claimed_once`.

### 6.8 Evidence generation

```mermaid
sequenceDiagram
    participant U as Auditor
    participant R as Evidence route
    participant G as generator
    participant D as bastion.db
    participant V as verify_chain
    participant P as html_to_pdf

    U->>R: GET /agents/id/evidence.pdf
    R->>R: lock, check 30 s cache
    R->>G: generate(engine, agent_id, actor)
    G->>D: read agent, record, policy, approvals, incidents, usage, events
    G->>V: verify_chain(engine)
    V-->>G: VerifyResult
    G->>G: read evals/results/latest.json, compare policy hash
    G->>G: filter MAPPING to rows with evidence, render_html
    G->>D: append evidence_generated
    R->>P: html_to_pdf(html, document name, disclaimer)
    P-->>R: PDF bytes
    R-->>U: attachment evidence-pack-id.pdf
```

`collect` assembles an `EvidencePack`: registration and sign-off, the policy in force with its hash, oversight counts and median decision time, robustness from the last eval run, incidents, usage, and record-keeping with the chain check. The robustness section and the red-team mapping row are shown as evidence only when the eval run's `policy_hash` equals the hash of the policy in force (`robustness["matches_policy"]`; `test_eval_results_for_another_policy_are_not_presented_as_evidence`). `generate` appends `evidence_generated` with the policy hash, event count and chain status. `html_to_pdf` prints with a header carrying the document name and a footer carrying the disclaimer and `Page X of Y`. In low-memory mode the PDF route answers 503 and the HTML pack remains. Tests: `test_pdf_has_the_document_name_header_and_page_x_of_y_footer`, `test_mapping_lists_only_capabilities_with_evidence`, `test_generation_is_audited_and_cached`.

## 7 Deployment view

```mermaid
flowchart TB
    subgraph local["Local: make serve"]
        lh["honcho start<br/>console 8501 and API 127.0.0.1:8000<br/>BASTION_LOCAL_DEV=1"]
        ld[("data/ directory<br/>bastion.db, demo.db, checkpoints.db, evidence/<br/>Persisted on the host")]
        lh --> ld
    end

    subgraph docker["Docker: make up"]
        dc["bastion container, python:3.12-slim<br/>non-root uid 10001<br/>honcho: console and API"]
        dv[("volume bastion-data at /app/data<br/>Persisted across restarts")]
        dp["Published ports 8501 and 8000"]
        dc --> dv
        dp --> dc
    end

    subgraph render["Render free plan: render.yaml"]
        rc["bastion container, same image<br/>BASTION_MODE=replay, BASTION_LOW_MEMORY=true<br/>512 MB, sleeps after 15 idle minutes"]
        re[("container filesystem<br/>Ephemeral")]
        rp["Public port: console only<br/>health check /_stcore/health"]
        rc --> re
        rp --> rc
    end

    subgraph railway["Railway: railway.json"]
        rwc["Dockerfile build, honcho start<br/>health check /_stcore/health<br/>restart on failure, max 3 retries"]
    end
```

*Figure 9. Deployment view.*

| Target | Start | Ports | Notes |
|---|---|---|---|
| Local | `make serve` runs `BASTION_LOCAL_DEV=1 PORT=8501 uv run honcho start` | Console 8501; API on 127.0.0.1:8000 (`/docs`) | Procfile entries `console` and `api`; the console is first because honcho gives the first entry `$PORT`. State in `./data` (the default `BASTION_DB_PATH` is `./data/bastion.db`) |
| Docker | `make up` runs `docker compose up --build` | Compose publishes 8501 and 8000 and sets `BASTION_API_BIND=0.0.0.0` | Volume `bastion-data` at `/app/data`; `restart: unless-stopped`; mode defaults to `replay`; `BASTION_PASSCODE` and `ANTHROPIC_API_KEY` come from the host environment and default to empty |
| Render | Blueprint `render.yaml`, runtime `docker`, plan `free`, `autoDeploy: true` | Public port serves the console only; the API stays on loopback | `BASTION_MODE=replay`, `BASTION_LOW_MEMORY=true`, `BASTION_PASSCODE` is a dashboard secret (`sync: false`); health check on the console |
| Railway | `railway.json`: builder `DOCKERFILE`, start `honcho start` | Health check `/_stcore/health`, timeout 180 s | The file defines no volume and no environment variables |

Image contents (`Dockerfile`): `python:3.12-slim`; uv 0.9.28 copied from `ghcr.io/astral-sh/uv`; locked, no-dev dependencies; directories `src`, `demo`, `policies`, `config`, `fixtures`, `knowledge`, `evals`, `scripts`; `Procfile`, `LICENSE`, `render.yaml`; `libatomic1`; headless Chromium with system libraries at `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright`. The image creates the system user `bastion` (uid 10001, shell `/usr/sbin/nologin`), makes only `/app/data` and `/app/.streamlit` writable and switches to that user. Environment defaults: `BASTION_MODE=replay`, `BASTION_DB_PATH=/app/data/bastion.db`, `BASTION_BIND=0.0.0.0`, `MALLOC_ARENA_MAX=2`, `PORT=8501`. `EXPOSE 8501`. The `HEALTHCHECK` runs `python scripts/smoke.py --health-only`. CI starts the image and asserts that `id -u` is not 0.

| What | Persisted | Ephemeral |
|---|---|---|
| `bastion.db`, `demo.db`, `checkpoints.db` | Local `./data`; Docker volume `bastion-data` | Render free plan filesystem; Railway unless a volume is attached outside `railway.json` |
| Evidence output | `data/evidence` for `make evidence`; `docs/samples/` for committed samples | The API renders packs on demand and keeps a 30 s in-memory cache |
| Fixtures, policies, knowledge notes | In the image or repository | Never written at runtime, except by `make record` |
| In-flight run tasks, policy cache, rate-limit state of passcode audit | None | Lost on process restart |

On start with `BASTION_SEED_ON_START=true` (default), `build_state` seeds the demo agent: in replay mode through the real classification and sign-off flow using fixtures (`seed_demo_classified`), otherwise directly (`seed_demo`), and restores `demo.db` if it is missing. An empty or reset ephemeral disk therefore returns to a working demo.

## 8 Cross-cutting concepts

### 8.1 Identity and tokens

- Agents authenticate to the gateway with a bearer token issued by `Registry.issue_token` (`secrets.token_urlsafe(32)`). Only `sha256(token)` is stored (`Agent.token_hash`); the token is shown once in `SignOffResult`. Issuing again rotates it (`test_rotated_token_stops_working`).
- No token exists before sign-off, and `issue_token` refuses any status other than `active` (`test_no_token_before_sign_off`, `test_blocked_agent_cannot_authenticate`).
- `authenticate` accepts `active` and `killed` agents. Failures append `auth_failed` with `missing_token` or `invalid_token`; there is no throttling of these events (listed in PROGRESS known gaps).
- A run id from the client is trusted only if Bastion started that run for that agent (`Registry.resolve_run`); otherwise the call lands in the agent's shared `unbound` bucket.
- `AgentRunner.__init__` issues a fresh token for the demo agent each time it is created (`actor="demo-runner"`).
- The tool-server subprocess receives only `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `TZ`, `PYTHONPATH`, `VIRTUAL_ENV`, `SYSTEMROOT` and any variables the gateway adds (`BASTION_DEMO_DB`); the API key and passcode are not passed (`test_tool_servers_do_not_inherit_secrets`).

### 8.2 Passcode guard

`api/auth.py`: one shared passcode, compared with `hmac.compare_digest`. `Settings.effective_passcode` is the configured passcode (whitespace-only counts as unset) or, only when `BASTION_LOCAL_DEV` is set, the fixed local value. With no effective passcode every guarded route answers 403; a wrong passcode answers 401 and appends `passcode_rejected`, at most once per 10 s window with a suppressed counter. The actor name comes from `X-Bastion-Actor`, is cut to 80 characters and is not authenticated. Starting a scenario run is open in replay mode and needs the passcode in `record` and `live` modes. Read routes, including the evidence routes, are open. `test_every_mutating_route_is_guarded` walks the OpenAPI document to check that mutating routes are guarded (PROGRESS describes it as proving every POST route is guarded; the run start applies the passcode check itself, in code, outside replay mode).

### 8.3 Policy as code and default deny

- Format: YAML with `agent`, `version_note`, `downstream`, `budgets`, `incident_rules`, `rules`. Unknown keys are rejected (`extra="forbid"`); rule and incident rule ids must be unique.
- Matching: `Policy.evaluate` walks the rules in order, compares the tool name exactly (no trimming or case folding), evaluates the optional `when`, and returns the first match. No match returns `deny` with reason `default_deny`.
- Rule fields: `effect` (`allow`, `deny`, `require_approval`), `redact_output` (entity list), `scan_input` (`entities`, `action` of `deny`, `require_approval` or `redact`, default `require_approval`), `category`.
- Versioning: `PolicyStore.activate` stores `content_yaml` and `content_hash`, increments the version, and deactivates earlier versions; every `tool_decision` carries `policy_hash`.
- The policy API refuses changes to `downstream` because `downstream.command` is a process the gateway starts (`api/routers/policies.py`; `test_policy_api_cannot_change_the_downstream_command`).
- Discovery shows least privilege: `Policy.visible_tools` lists tools with an `allow` or `require_approval` rule; calling a hidden tool is still evaluated and denied (`test_hidden_tool_called_directly_is_denied`).
- Tier templates (`policies/templates/*.yaml`) carry budgets and incident rules and no tool rules.

### 8.4 Hash-chained audit

`event_hash = sha256(prev_hash + canonical_json(body))` with body `{seq, ts, actor, event_type, agent_id, payload}` and `canonical_json` using sorted keys and compact separators. `AuditLog.append` opens its own connection with `immediate=True`, so two writers cannot read the same head. The chain gives tamper evidence for modification, deletion in the middle and reordering (`test_rt24_tampering_is_detected_at_the_first_broken_event`, `test_reordering_is_detected`, `test_recomputing_one_hash_still_breaks_the_next_link`). It does not detect removal of the newest events: there is no external anchor for the head. Audit payloads never carry rejected argument values (field names only) and carry valid arguments with PII masked. This supports evidence for record-keeping expectations (EU AI Act Art. 12 [VERIFY]); DORA ICT logging expectations [VERIFY] are an optional further reference. Neither is a compliance claim.

### 8.5 PII handling: two engines

| | `Redactor` (default) | `LightRedactor` (`BASTION_LOW_MEMORY=true`) |
|---|---|---|
| Technology | Presidio analyzer with spaCy `en_core_web_sm`; parser and NER pipes disabled; extra e-mail recogniser for any TLD | Regular expressions, Luhn and IBAN mod-97 checks, per-country IBAN lengths, `phonenumbers` over eight regions |
| Entities | `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD` | Same four |
| Shared logic | `BaseRedactor.redact`, `scan`, `resolve_overlaps`; mask format `<ENTITY>`; minimum score 0.35 | Same |
| Selected by | `get_redactor(low_memory)`, cached per process | Same |

Uses: output redaction per rule (`redact_output`), input scanning per rule (`scan_input`), masking of arguments in the audit log and in approval records (all four entities). `test_light_engine_agrees_with_presidio_on_all_demo_and_eval_text` is what keeps the two in agreement on the synthetic corpus; outside that corpus equality is not proven. Names and addresses are not masked by either engine.

### 8.6 Replay determinism

`GovernedAnthropic.create` builds the request, computes `fixture_key` (SHA-256 over the canonical JSON of the whole request with `None` values dropped) and, in replay mode, loads `fixtures/llm/<key>.json` or raises `ReplayMissError`. `record` calls the API and saves the fixture; `live` calls the API and saves nothing. No `temperature` is sent (ADR-004). Determinism of the surrounding system is arranged deliberately: approval ids are deterministic (`APR-` plus a hash), demo data is restored from a snapshot before each scenario, and the model never sees approval ids. A change to a prompt, the tool manifest, a redaction rule or the demo data changes request content and needs `make record`.

### 8.7 Error handling: fail closed

| Failure | Behaviour | Code |
|---|---|---|
| Condition cannot be evaluated | Rule result is `deny` with `condition_error: <message>` | `Policy.evaluate` |
| Condition not in the whitelist, too long (500 characters) or too large (100 nodes) | Policy fails to load and is never activated | `compile_condition`, `Rule._compile` |
| Policy text invalid, or stored text does not match its recorded hash | Every call is denied (`condition_error: ...`); nothing is forwarded | `PolicyStore.active`, `_decide_and_forward` |
| Agent has no active policy | Deny `no_active_policy`; discovery returns no tools | `_decide_and_forward`, `list_tools` |
| Tool not in the policy | Deny `default_deny` | `Policy.evaluate` |
| Tool not exposed by the downstream server | Deny `unknown_tool` | `_decide_and_forward` |
| Name or arguments malformed | Deny `invalid_tool_name` or `invalid_arguments`, reported under the tool's unconditional deny rule if one exists | `is_valid_tool_name`, `validate_and_normalise`, `Policy.unconditional_deny` |
| Downstream tool reports an error | Status `TOOL_ERROR`, message redacted, passed to the agent; not a deny | `_forward` |
| Downstream connection missing | `TOOL_ERROR`, "downstream tool server unavailable" | `_forward` |
| No or invalid agent token | HTTP 401, `auth_failed` event | `BearerAuth` |
| No passcode configured | Guarded routes answer 403 | `check_passcode` |
| Model call not allowed (kill, token cap, cost cap) | `ModelCallBlocked` raised before the call; run ends `halted` | `GovernanceHook.before_call`, graph `model` node |
| Replay fixture missing | Run completes with an explanatory text; registration answers 409 | `RunManager._spawn`, `routers/registry.py` |
| Any other exception in a run task | Run marked `failed`; the API shows only the exception type | `RunManager._spawn` |

### 8.8 Configuration

`Settings` (`config.py`, `pydantic-settings`) reads environment variables and a local `.env` file; empty values mean unset. `get_settings` is cached for the life of the process.

| Variable | Default | Purpose |
|---|---|---|
| `BASTION_MODE` | `replay` | `replay`, `record` or `live` |
| `ANTHROPIC_API_KEY` | unset | Needed only for `record` and `live`; held as `SecretStr` |
| `BASTION_PASSCODE` | unset | Shared passcode for mutating routes |
| `BASTION_DB_PATH` | `./data/bastion.db` | Main database; `demo.db` and `checkpoints.db` sit in its directory |
| `BASTION_MODEL_FAST` | `claude-haiku-5-5` | Model for the demo agent |
| `BASTION_MODEL_SMART` | `claude-sonnet-5-5` | Model for the Assessor and Reviewer |
| `BASTION_LOCAL_DEV` | `false` | Accept the local passcode when none is configured; `make serve` only |
| `BASTION_API_URL` | `http://127.0.0.1:8000` | Used by the console and by the demo agent to reach `/mcp` |
| `BASTION_SEED_ON_START` | `true` | Seed the demo agent and data at start |
| `BASTION_LOW_MEMORY` | `false` | Light PII engine, no PDF, lean console |
| `BASTION_FIXTURES` | `<repo>/fixtures/llm` | Fixture directory |
| `BASTION_PRICES_PATH` | `<repo>/config/prices.yaml` | Price table for cost accounting |

Read outside `Settings`: `BASTION_DEMO_DB` (tools server, default `data/demo.db`, set by the gateway), `BASTION_CONSOLE_START_PAGE` (default `overview`), `BASTION_BIND` and `BASTION_API_BIND` (Procfile bind addresses, default `127.0.0.1`), `PORT` (Procfile console port, default 8501).

### 8.9 Concurrency and SQLite locking

`make_engine` sets WAL, `synchronous=NORMAL`, `foreign_keys=ON`, a 15 s connect timeout and `check_same_thread=False`, disables the driver's implicit BEGIN and issues `BEGIN` or `BEGIN IMMEDIATE` from a `begin` event.

| Helper | Transaction | Use |
|---|---|---|
| `session_scope` | `BEGIN IMMEDIATE`; commit on success, rollback on error | Any unit of work that writes, or reads then writes |
| `read_scope` | Deferred; closed without commit; never write through it | Hot-path lookups: kill switch, policy row, agent lookup, budget count |
| `AuditLog.append` | Own connection with `immediate=True` | Serialises appends to the chain |

A deferred transaction that reads and then writes fails with "database is locked" if another connection commits in between, and the busy timeout does not cover that upgrade; taking the lock first makes writers queue instead (PROGRESS, 2026-11-17). Conditional UPDATEs decide races: `ApprovalService.decide`, `consume_grant`, `ClassificationService.sign_off`. Tests: `test_concurrent_appends_keep_one_unbroken_chain`, `test_concurrent_read_then_write_units_of_work_do_not_fail_with_database_is_locked`. The API evidence route serialises renders with a lock; `RunManager` allows one run task at a time.

## 9 Architecture decisions

| ADR | Title | One-line rationale | Link |
|---|---|---|---|
| ADR-001 | Single container, two processes | One command locally and one free hosted service | [ADR-001](../adr/ADR-001-single-container.md) |
| ADR-002 | Approvals are bound to exact arguments and are single-use | A grant authorises one call with one argument set, once | [ADR-002](../adr/ADR-002-args-bound-approval-grants.md) |
| ADR-003 | Custom AST evaluator for policy conditions | Conditions are data; no `eval()` or `exec()` on policy text | [ADR-003](../adr/ADR-003-custom-condition-evaluator.md) |
| ADR-004 | Record/replay fixtures for model calls | Deterministic runs and CI with no key | [ADR-004](../adr/ADR-004-llm-replay-fixtures.md) |
| ADR-005 | SQLite (WAL) with SQLAlchemy 2.0 | Shared state with no extra infrastructure; tamper evidence rather than prevention | [ADR-005](../adr/ADR-005-sqlite-wal-sqlalchemy.md) |
| ADR-006 | Playwright for the evidence PDF and the demo GIF | Header and `Page X of Y` footer from a headless browser | [ADR-006](../adr/ADR-006-playwright-pdf-gif.md) |
| ADR-007 | Gateway on the low-level MCP server (mcp 2.x) | Per-agent proxied tool lists need the low-level server | [ADR-007](../adr/ADR-007-lowlevel-mcp-server.md) |
| ADR-008 | API hosts the gateway; fail-closed passcode; one scenario run at a time | One port, no passcode means no mutations, serial runs because each starts with a reset | [ADR-008](../adr/ADR-008-api-console-passcode-runs.md) |
| ADR-009 | Classification graph ends with a proposal; sign-off is a durable database state | Sign-off survives restarts and does not depend on a held-open graph | [ADR-009](../adr/ADR-009-classification-signoff.md) |
| ADR-010 | Low-memory mode for small hosts (Render free tier) | Swap the PII engine and drop the browser to fit 512 MB | [ADR-010](../adr/ADR-010-low-memory-mode.md) |

## 10 Quality requirements

Measured values come from `evals/results/latest.json` (generated 2026-11-16T19:45:49+00:00, Bastion 0.2.0, mode `replay`, 81 gateway calls timed) or from the named test. The tests named below exist in `tests/`; this document records that they exist and what they assert, not a fresh run.

| # | Stimulus | Response | Measure and result | Source |
|---|---|---|---|---|
| Q1 | Each of 25 red-team scenarios in `evals/redteam/*.yaml` | Every attack is stopped | Must-block rate 1.0 (25 of 25); threshold 1.0 | `latest.json` (`redteam_must_block_rate`, `counts.redteam`) |
| Q2 | 15 legitimate scenarios | Allowed calls are not blocked | Benign pass rate 1.0 (15 of 15); threshold 0.95 | `latest.json` (`benign_pass_rate`) |
| Q3 | Any gateway call, excluding the downstream tool | Low added latency | Overhead p95 8.21 ms over 81 timed calls; threshold below 50 ms | `latest.json` (`gateway_overhead_p95_ms`); `test_gateway_overhead_p95_is_under_50_ms` asserts the same bound over 100 calls |
| Q4 | Twelve synthetic agent cards, replayed | Tier matches the gold set | Assessor tier accuracy 1.0 (12 of 12); threshold 0.80 | `latest.json` (`assessor_tier_accuracy`) |
| Q5 | Three deliberately wrong assessments | Reviewer disagrees | 3 of 3 caught; threshold 2 | `latest.json` (`reviewer_seeded_catches`, `reviewer_seeded_total`) |
| Q6 | Assessor and Reviewer outputs | Valid against the schema | Structured output validity 1.0; threshold 1.0 | `latest.json` (`structured_output_validity`) |
| Q7 | Ordinary calls, including a denied one | Chain verifies | `audit_verify_clean_run` true | `latest.json`, `clean_run_verifies` |
| Q8 | An audit row is modified, an event is removed or two are reordered | `verify_chain` names the first broken sequence number | Detected at the first broken event | `test_rt24_tampering_is_detected_at_the_first_broken_event`, `test_reordering_is_detected` |
| Q9 | Approved for 60000, called with 600000 | New approval, nothing executes | Original grant stays unused | `test_rt13_uc05_approve_then_swap_does_not_execute` |
| Q10 | Grant reused; grant after TTL; grant used by another agent | Call is not executed | Denied or pending again | `test_rt14_consumed_grant_cannot_be_reused`, `test_rt15_grant_expires_after_ttl`, `test_rt16_grant_for_one_agent_is_useless_to_another` |
| Q11 | Stored policy row edited, or code placed in a condition | All calls denied; policy not activated | Fails closed | `test_rt25_tampered_policy_row_denies_everything`, `test_policy_text_not_matching_its_hash_denies_everything`, `test_rt25_policy_with_code_in_a_condition_cannot_be_activated` |
| Q12 | Missing or invalid agent token | HTTP 401 and an audit event | 401, `auth_failed` recorded | `test_rt23_missing_or_invalid_token_is_401_and_audited` |
| Q13 | Kill pressed during a run | Next call denied, approvals revoked, runs halted | Halted | `test_rt22_uc07_kill_switch_denies_revokes_and_halts`, `test_uc07_kill_switch_halts_the_run` |
| Q14 | Concurrent appends and read-then-write units of work | One unbroken chain; no "database is locked" | Chain verifies | `test_concurrent_appends_keep_one_unbroken_chain`, `test_concurrent_read_then_write_units_of_work_do_not_fail_with_database_is_locked` |
| Q15 | Run with no API key | Defaults to replay; no SDK client needed | Works keyless | `test_defaults_are_replay_and_keyless`, `test_replay_needs_no_api_key_or_sdk_client` |
| Q16 | Low-memory profile on a 512 MB limit | Container is not OOM-killed, all processes alive, resident memory under 450 MB | CI step "Not OOM-killed, every process alive, under 450 MB resident" runs `scripts/memory_report.py --max 450 --min-processes 4` and checks `OOMKilled` is false. A measured peak of about 276 MB is stated in `README.md` and `docs/SHOWCASE.md`; `docs/PROGRESS.md` and ADR-010 record about 260 MB resident (macOS) | `.github/workflows/ci.yml`; `README.md`; `docs/PROGRESS.md` (S8b) |
| Q17 | Two PII engines, same demo and eval strings | Same spans | Equal on the synthetic corpus | `test_light_engine_agrees_with_presidio_on_all_demo_and_eval_text` |
| Q18 | Unmasked personal data in tool output | Model never sees it | Asserted | `test_unmasked_pii_never_reached_the_model` |

Test volume: `make check` runs 424 tests and reports about 94% coverage of `src/bastion` (lines and branches) for the state documented here. No minimum is enforced in CI.

## 11 Risks and technical debt

| # | Risk or debt | Impact | What would fix it |
|---|---|---|---|
| 1 | No external anchor for the audit chain head | Deleting the newest events leaves a shorter, valid chain; truncation is not detected (ADR-005, README) | Periodically sign and store the head hash and sequence outside the database (for example in the evidence pack or an external store) |
| 2 | One shared passcode, self-declared actor names | Approvals and kills are not attributable to a person; the passcode holder can do everything guarded | SSO, roles, four-eyes approval for the largest actions |
| 3 | SQLite single writer on one node | Throughput ceiling; no high availability; the gateway shares a failure domain with the API | A server database, and the gateway as a separate process (ADR-001 already names the split) |
| 4 | One scenario run at a time; each start resets the demo agent | In replay mode anyone who can reach the deployment can start a run, which resets the demo agent's data, kill switch, incidents and approvals (the global kill switch is not released; the start answers 409 while it is active) | Authentication on run start; per-run isolated state |
| 5 | Run tasks live in the API process | A restart loses the in-flight task; the run row can stay `running` or `interrupted` until the next run supersedes it. A parked run whose approval expires stays `interrupted` | Durable job queue or startup recovery that reconciles run rows with checkpoints |
| 6 | Kill switch halts rows and blocks the next call | A run parked at an approval interrupt is not resumed and is marked `halted`; an agent with a direct route to a tool is not governed at all | Network-level egress control so the gateway is the only route |
| 7 | Two PII engines | They must stay in agreement; equality is proven on the synthetic corpus only; neither masks names or addresses | One engine, or a broader equivalence corpus; add an NER stage where needed |
| 8 | Replay covers recorded paths only | A rejected approval, a changed policy, a changed prompt or tool manifest, or an unrecorded card ends in `ReplayMissError` (an explanatory message). Registration in replay covers the twelve sample cards | `make record` with a key after any change to requests |
| 9 | Regulatory content is unverified | Every reference and every paraphrase in `knowledge/*.md` and the mapping is `[VERIFY]`; the tier is decision support, not a legal classification | Human review of `docs/VERIFY.md` against primary sources |
| 10 | `_forward` handles a missing connection and tool-reported errors; I found no handler for an exception raised by the MCP client call itself | A transport failure could surface as an unhandled error to the MCP layer rather than a `TOOL_ERROR` result | Wrap the call, return `TOOL_ERROR`, and add a test |
| 11 | `auth_failed` events are not throttled | A flood of bad tokens grows the audit log (passcode failures are throttled) | Apply the same windowed throttling |
| 12 | Evidence routes are open and each generation writes an event | At most one per agent per 30 s, with a self-declared actor name | Guard the routes or aggregate the events |
| 13 | Low-memory profile has no PDF | The PDF header and footer are shown only by the sample in `docs/samples/` and by CI on the default profile | Render PDFs outside the small host |
| 14 | Ephemeral storage on Render's free plan | Database and checkpoints are lost on restart; the seed restores the demo state | A persistent volume on a paid plan |
| 15 | `evals/results/latest.json` is tracked | `make eval` leaves a timestamp-only diff (PROGRESS known gaps) | Keep results out of version control or pin the timestamp |
| 16 | Budget counting includes calls later denied | A session cap counts attempts, not executions | Document or count executions separately |
| 17 | Policy cache is per process, keyed by hash | Safe (the hash is checked on every read) but each process parses its own copy | None needed |

## 12 Glossary

| Term | Meaning in this document |
|---|---|
| Agent card | The owner's declaration about an agent (`AgentCard`) submitted at registration |
| Args hash | SHA-256 of the canonical JSON of normalised tool arguments; the key for grants and approvals |
| Assessor, Reviewer | The two model roles that propose and challenge a risk tier (`bastion-assessor`, `bastion-reviewer`) |
| Audit chain | The sequence of `audit_events` rows linked by `prev_hash` and `hash` |
| Bucket | The budget scope for tool calls: a Bastion run id, or the shared `unbound` bucket |
| Category | Optional label on a rule (for example `exfiltration`) used by incident rules |
| Condition | The `when` expression of a rule, evaluated by the AST whitelist evaluator |
| Default deny | A tool with no matching rule is refused |
| Decision | The gateway's verdict on one call: effect, rule id, policy hash, reasons |
| Downstream | A tool server the gateway proxies to over stdio |
| DLP | Scanning tool inputs for personal data (`scan_input`) |
| Fixture | A recorded model response stored under the SHA-256 of its request |
| Grant | An approved approval that can be consumed once by the identical call |
| Gateway | The MCP server at `/mcp` implemented by `Gateway` |
| Kill switch | Per-agent or global deny-all, checked first |
| Low-memory mode | The `BASTION_LOW_MEMORY` profile for 512 MB hosts |
| MCP | Model Context Protocol, the tool protocol between agent, gateway and tool server |
| Policy hash | SHA-256 of the policy YAML text in force |
| Replay, record, live | Modes of `GovernedAnthropic` |
| Run | One execution of a scenario, identified by `run-<12 hex>` |
| Sign-off | The human decision that accepts or overrides the proposed tier and activates a policy |
| Tier | `prohibited`, `high`, `limited` or `minimal`; decision support only |
| VERIFY | The marker on every regulatory reference, tracked in `docs/VERIFY.md` |

---
*design/HLD.md · Page 1 of 1*
