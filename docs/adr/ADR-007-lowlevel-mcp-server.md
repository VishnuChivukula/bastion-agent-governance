# ADR-007: Gateway on the low-level MCP server (mcp 2.x)

**Status:** accepted · 2026-11-16

## Context
ARCHITECTURE.md assumed a "FastMCP streamable-HTTP app" for the gateway. The installed SDK is `mcp` 2.3, where `FastMCP` was renamed `MCPServer` and several APIs changed. More importantly, the gateway is a proxy: its tool list differs per agent (least privilege in discovery, FR-11) and its tools are not Python functions it owns, which does not fit the decorator-based server.

## Decision
- The gateway uses `mcp.server.lowlevel.Server` with `on_list_tools` / `on_call_tool` handlers, served by `streamable_http_app(stateless_http=True, json_response=True)` at `/mcp`.
- Authentication is an ASGI middleware in front of the MCP app. It resolves the bearer token to an agent id, returns `401` (and writes an `auth_failed` audit event) otherwise, and passes the identity to the handlers through the ASGI scope.
- Enforcement lives in a transport-agnostic `Gateway` class (`gateway/mcp_proxy.py`); `gateway/server.py` is only the MCP adapter. Tests and evals can call the gateway directly or over HTTP.
- Each downstream stdio server is held open by one background task (the MCP client must be entered and exited in the same task); request tasks only call into it.
- The demo tools server uses `MCPServer` (the renamed FastMCP).
- Sessions for budgets are Bastion-issued run ids sent in the `X-Bastion-Run` header. Unknown ids fall into one shared bucket per agent, so inventing run ids cannot reset a budget.

## Consequences
- Stateless HTTP keeps the gateway simple and restart-safe; there is no MCP session state to lose.
- The gateway does not rely on the SDK for tool-argument validation: it validates against the downstream tool's schema itself, with unknown fields rejected (FR-13).
- Mounting inside FastAPI (S4) must run the MCP session manager's lifespan from the parent app.
