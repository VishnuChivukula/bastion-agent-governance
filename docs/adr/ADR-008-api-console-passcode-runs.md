# ADR-008: API hosts the gateway; fail-closed passcode; one scenario run at a time

**Status:** accepted · 2026-11-16

## Context
Slice S4 adds the control-plane API and the console. Three things were left open by ARCHITECTURE.md: how the MCP gateway lives inside the API process, what "mutating actions need `BASTION_PASSCODE`" means when no passcode is set, and how scenario runs started by anonymous visitors of a public demo behave.

## Decision
- **One process, one port for API and gateway.** The gateway is added to the FastAPI app as a single route at `/mcp` (bearer-token middleware in front), and the API's lifespan holds the MCP session manager open. No third process was needed (the fallback in ARCHITECTURE §2 is unused). The demo agent reaches the gateway over real HTTP at `BASTION_API_URL + /mcp`, with a real agent token.
- **The passcode guard fails closed.** With no `BASTION_PASSCODE`, every mutating route answers `403`: approvals, kill and reactivate, incident updates, policy activation. A wrong passcode answers `401` and is audited (`passcode_rejected`). Comparison is constant-time.
- **Local development.** `make serve` sets `BASTION_LOCAL_DEV=1`. Only then, and only if no passcode is configured, the fixed passcode `bastion-local` is accepted and the console fills it in. A deployment never sets this flag.
- **Scenario runs are open in replay mode** (FR-82): they cost nothing and use recorded model responses. In `record` and `live` mode, starting a run needs the passcode.
- **One run at a time; each run starts with a demo reset.** Starting a scenario rebuilds the synthetic bank data, releases the kill switch, resolves open incidents and revokes open approvals (all audited, attributed to `demo-reset`). A second start while a run is in progress answers `409`.
- **Who decides approvals.** A run is started with `approver: scripted` (the scenario script plays the approver, so a visitor without the passcode can still watch UC-04 and UC-05 end to end) or `approver: human` (the run parks at the approval until someone with the passcode decides in the console; the API then resumes it from the LangGraph checkpoint).
- **The actor name is self-declared.** The console sends the name the user typed (`X-Bastion-Actor`). It is recorded in the audit log but not authenticated; v0.1 has no user model (SPEC §7).

## Consequences
- A public demo with no passcode is read-only apart from replayed scenarios, whose side effects are confined to the demo agent and are undone by the next run.
- Anyone who can reach a deployment in replay mode can trigger the demo reset. That is acceptable for a demo and is called out as a limitation; a real deployment would put scenario runs behind authentication too.
- In replay mode, paths that were never recorded (an approver rejecting, or a policy edit that changes what the agent sees) end the run with an explanatory message rather than a model reply.
- Shared-passcode auth and self-declared actors are not accountability controls. SSO and RBAC are out of scope for v0.1.
