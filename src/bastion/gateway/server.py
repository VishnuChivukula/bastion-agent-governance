"""MCP streamable-HTTP front door for the gateway (FR-10, ADR-007).

Agents connect to `/mcp` with `Authorization: Bearer <agent token>`. The low-level MCP server is
used (not the decorator-based `MCPServer`) because the tool list is per agent and proxied.
"""

import json
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from bastion import __version__
from bastion.gateway.mcp_proxy import Gateway
from bastion.headers import RUN_HEADER

AGENT_KEY = "bastion.agent_id"
RUN_KEY = "bastion.run_id"


class BearerAuth:
    """ASGI middleware: authenticate the agent token before anything reaches MCP (RT-23)."""

    def __init__(self, app: ASGIApp, gateway: Gateway) -> None:
        self.app = app
        self.gateway = gateway

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        agent_id = self.gateway.registry.authenticate(token) if scheme.lower() == "bearer" else None
        if agent_id is None:
            self.gateway.audit.append(
                "auth_failed",
                actor="anonymous",
                payload={
                    "path": scope.get("path", ""),
                    "reason": "missing_token" if not token else "invalid_token",
                },
            )
            response = JSONResponse(
                {"error": "unauthorized", "message": "A valid agent token is required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        scope[AGENT_KEY] = agent_id
        scope[RUN_KEY] = request.headers.get(RUN_HEADER)
        await self.app(scope, receive, send)


def _identity(ctx: Any) -> tuple[str, str | None]:
    scope = ctx.request.scope
    return scope[AGENT_KEY], scope.get(RUN_KEY)


def build_mcp_server(gateway: Gateway) -> Server:
    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        agent_id, _ = _identity(ctx)
        return types.ListToolsResult(
            tools=await gateway.list_tools(agent_id), cache_scope="private"
        )

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        agent_id, run_id = _identity(ctx)
        result = await gateway.call_tool(agent_id, params.name, params.arguments, run_id)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result.payload))],
            structured_content=result.payload,
            is_error=result.is_error,
        )

    return Server(
        "bastion-gateway",
        version=__version__,
        instructions="Tool calls are governed by Bastion policy and are audited.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def build_mcp_route(gateway: Gateway, *, path: str = "/mcp") -> tuple[Route, Any]:
    """The gateway as one route for a host ASGI app (the control-plane API mounts it at `/mcp`).

    Returns the route and the MCP session manager; the host must hold `manager.run()` open for
    its lifetime, because a mounted app's own lifespan is never started.
    """
    server = build_mcp_server(gateway)
    inner = server.streamable_http_app(
        streamable_http_path=path, stateless_http=True, json_response=True
    )
    return Route(path, endpoint=BearerAuth(inner, gateway)), server.session_manager


def build_mcp_app(gateway: Gateway, *, path: str = "/mcp") -> ASGIApp:
    """ASGI app serving the gateway at `path`, with bearer-token auth in front."""
    server = build_mcp_server(gateway)
    app = server.streamable_http_app(
        streamable_http_path=path, stateless_http=True, json_response=True
    )
    return BearerAuth(app, gateway)
