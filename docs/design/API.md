**Bastion Kit · design/API.md**

# Bastion: API and gateway contract

> Reference implementation; not production; not legal advice. All data is synthetic.

Two interfaces are served by one process (`uvicorn bastion.api.main:app --factory`, port 8000):

- the **control-plane REST API**, used by the console and by scripts. Interactive OpenAPI documentation is at `/docs`, the schema at `/openapi.json`;
- the **MCP gateway** at `/mcp`, used by agents.

In the container only the console port is public; the API and the gateway listen on loopback unless `BASTION_API_BIND` is set (see [`HLD.md`](HLD.md), deployment view).

## 1. Conventions

| Topic | Rule |
|---|---|
| Passcode | Mutating routes need the header `X-Bastion-Passcode`. No passcode configured on the server: `403`. Missing or wrong: `401`. Compared in constant time (`src/bastion/api/auth.py`). |
| Actor | Optional header `X-Bastion-Actor`: the name recorded in the audit log. Self-declared, not authenticated. Default `console-user`. |
| Errors | JSON `{"detail": "..."}`. `404` unknown resource, `409` wrong state, `422` validation, `403`/`401` passcode, `400` kill-switch request refused, `502` classification failed, `503` PDF unavailable. |
| Guard test | `tests/test_api.py::test_every_mutating_route_is_guarded` walks the OpenAPI schema and requires every `POST` except `/runs` to answer `403` on a server with no passcode. `tests/test_api.py::test_design_api_doc_lists_every_route` keeps this catalogue complete. |

## 2. Endpoint catalogue

Guard: **P** = passcode required; **P\*** = passcode required unless the server is in replay mode; blank = open (read-only).

### Meta

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/healthz` | | Liveness of the API process |
| GET | `/meta` | | Version, mode, whether mutations are enabled, low-memory profile, PII engine, whether the PDF is available, whether the seed policy is in force |

### Agents, kill switch, usage (`routers/agents.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/agents` | | All agents with status, tier, active policy version and hash, kill state |
| GET | `/agents/{agent_id}` | | One agent |
| GET | `/agents/{agent_id}/usage` | | Today's tool calls, model calls, tokens and cost; the policy's caps; per-run figures |
| GET | `/killswitch` | | Every kill-switch row (scope, active, reason, actor, time) |
| POST | `/agents/{agent_id}/kill` | P | Stop one agent. Body `{reason}` |
| POST | `/agents/{agent_id}/reactivate` | P | Release one agent. Body `{reason}` |
| POST | `/killswitch/global/kill` | P | Stop every agent. Body `{reason}` |
| POST | `/killswitch/global/reactivate` | P | Release the global switch. Body `{reason}` |

### Registry (`routers/registry.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/registry/samples` | | The twelve synthetic agent cards |
| GET | `/registry/agents/{agent_id}` | | Card, Assessor and Reviewer output, proposed tier, sign-off |
| POST | `/registry/agents` | P | Submit an agent card and run the classification. The agent then waits for sign-off |
| POST | `/registry/agents/{agent_id}/signoff` | P | Body `{tier, override_reason?}`. Returns the outcome and, once, the gateway token |

### Policies (`routers/policies.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/agents/{agent_id}/policies` | | Version history with hashes |
| GET | `/agents/{agent_id}/policies/{version}` | | One version, including the YAML |
| GET | `/agents/{agent_id}/policies/diff` | | Unified diff between `from_version` and `to_version` |
| POST | `/agents/{agent_id}/policies` | P | Validate and activate YAML as a new version. Rejects invalid policies, an unchanged policy (`409`) and any change to `downstream` (`422`) |

### Oversight (`routers/oversight.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/approvals` | | Approvals, filterable by `status` and `agent_id` |
| GET | `/approvals/{approval_id}` | | One approval with masked arguments and the arguments hash |
| POST | `/approvals/{approval_id}/decision` | P | Body `{approve, reason}`. Creates a single-use grant or rejects; resumes the parked run if this was its last open decision |
| GET | `/incidents` | | Incidents, filterable by `agent_id` |
| POST | `/incidents/{incident_id}/advance` | P | Body `{status, note}`. Moves the incident forward one or more steps |

### Scenario runs (`routers/runs.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/scenarios` | | The six scripted scenarios |
| POST | `/runs` | P\* | Body `{scenario, approver: scripted \| human}`. Starts a run in the background (`202`). `409` while another run is in progress or the global kill switch is active; `403` for `approver=human` when no passcode is configured |
| GET | `/runs` | | Recent runs |
| GET | `/runs/{run_id}` | | Status, pending approvals, the decision timeline, the audit events of the run, the agent's final text |

### Audit and overview (`routers/audit.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/audit/events` | | Events, newest first; filters `agent_id`, `event_type`, `after_seq`, `limit` |
| GET | `/audit/verify` | | Recomputes the hash chain; reports the first broken sequence number |
| GET | `/overview` | | Counts for the console's first page, including chain integrity (cached for 5 s unless `fresh=true`) |

### Evals and evidence (`routers/evals.py`, `routers/evidence.py`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| GET | `/evals/latest` | | The scoreboard written by `make eval` |
| GET | `/agents/{agent_id}/evidence` | | The evidence pack as data |
| GET | `/agents/{agent_id}/evidence.html` | | The pack as a self-contained HTML document |
| GET | `/agents/{agent_id}/evidence.pdf` | | The pack as PDF. `503` in the low-memory profile or without Chromium |

The evidence routes are open because they are read-only. Rendering is serialised and cached for 30 s per agent, and each generation writes an `evidence_generated` audit event.

## 3. MCP gateway contract

| Item | Value |
|---|---|
| Endpoint | `POST /mcp` (MCP streamable HTTP, stateless, JSON responses) |
| Authentication | `Authorization: Bearer <agent token>`. The token is issued once at sign-off and stored as a sha256 hash. Missing or invalid: `401` with `WWW-Authenticate: Bearer`, audited as `auth_failed` |
| Session header | `x-bastion-run: <run id>` (optional). Only run ids Bastion issued for this agent are separate budget sessions; anything else shares the bucket `unbound` |
| `tools/list` | Returns only tools for which the agent's policy has an `allow` or `require_approval` rule. Denied tools are hidden |
| `tools/call` | Always answers with a result (never a transport error for a policy outcome). The result carries the payload as `structuredContent` and as JSON text; `isError` is true for `DENIED` and `TOOL_ERROR` |

### Result payloads

| Status | Payload | Meaning for the agent |
|---|---|---|
| allowed | The tool's own structured result, with PII masked as `<ENTITY_TYPE>` where the rule says so | Use it |
| `DENIED` | `{status, rule_id, reason, detail, message}`. `reason` is the rule's category, `policy_rule`, or one of `killswitch`, `invalid_tool_name`, `no_active_policy`, `condition_error`, `budget_exceeded`, `unknown_tool`, `invalid_arguments`, `scan_input`, `default_deny` | The action did not run. Do not retry or work around it |
| `PENDING_APPROVAL` | `{status, approval_id, rule_id, message}` | Nothing ran. Once a human approves, repeat the identical call: same tool, same arguments |
| `TOOL_ERROR` | `{status, message}` | The downstream tool failed; the message is masked |

### What an agent integration has to do

1. Connect to `/mcp` with its bearer token and, if it wants per-run budgets, the run header.
2. Treat `PENDING_APPROVAL` as "pause", not as an error, and re-issue the identical call after approval. The demo agent does this with a LangGraph `interrupt()` (`demo/loan_ops_agent/graph.py`).
3. Route model calls through `GovernedAnthropic` (`src/bastion/llm/client.py`) if model budgets, the kill switch on model calls and model-call audit events are wanted. The gateway alone governs tool calls for any MCP client.

---
*design/API.md · Page 1 of 1*
