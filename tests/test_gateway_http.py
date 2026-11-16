"""End to end over real MCP streamable HTTP: client → bearer auth → gateway → stdio tools server."""

import json
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from bastion.audit.verify import verify_chain
from bastion.db import make_engine
from bastion.gateway.mcp_proxy import Gateway
from bastion.gateway.server import RUN_HEADER, build_mcp_app
from bastion.seed import DEMO_AGENT_ID, seed_demo

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def served(tmp_path_factory, demo_db, redactor):
    """The gateway on a real local port, with its own event loop (as in production)."""
    engine = make_engine(tmp_path_factory.mktemp("http") / "bastion.db")
    seed_demo(engine)
    gateway = Gateway(engine, redactor=redactor, demo_db=demo_db)
    token = gateway.registry.issue_token(DEMO_AGENT_ID)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(build_mcp_app(gateway), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    yield {"url": f"http://127.0.0.1:{port}/mcp", "token": token, "gateway": gateway}
    server.should_exit = True
    thread.join(timeout=10)
    engine.dispose()


def connect(served, token=None, run_id=None):
    headers = {"Authorization": f"Bearer {token or served['token']}"}
    if run_id:
        headers[RUN_HEADER] = run_id
    http = httpx2.AsyncClient(headers=headers, timeout=30)
    return Client(streamable_http_client(served["url"], http_client=http))


async def test_agent_discovers_only_permitted_tools(served):
    async with connect(served) as client:
        names = sorted(tool.name for tool in (await client.list_tools()).tools)
    assert names == ["get_customer_notes", "lookup_customer", "send_email", "update_credit_limit"]


async def test_allowed_call_returns_redacted_result(served):
    async with connect(served) as client:
        result = await client.call_tool("lookup_customer", {"customer_id": "C-0007"})
    assert not result.is_error
    assert result.structured_content["email"] == "<EMAIL_ADDRESS>"
    assert json.loads(result.content[0].text)["iban"] == "<IBAN_CODE>"


async def test_hidden_tool_called_directly_is_denied(served):
    async with connect(served) as client:
        result = await client.call_tool("export_customer_data", {"destination": "a@b.example"})
    assert result.is_error
    assert result.structured_content["status"] == "DENIED"
    assert result.structured_content["rule_id"] == "R-007"
    # IR-2 (exfiltration) opened an incident and tripped the kill switch for this agent
    gateway = served["gateway"]
    assert gateway.killswitch.active_scope(DEMO_AGENT_ID) == DEMO_AGENT_ID
    async with connect(served) as client:
        blocked = await client.call_tool("lookup_customer", {"customer_id": "C-0007"})
    assert blocked.structured_content["reason"] == "killswitch"
    gateway.killswitch.reactivate(DEMO_AGENT_ID, reason="test: reviewed", actor="approver")
    async with connect(served) as client:
        assert not (await client.call_tool("lookup_customer", {"customer_id": "C-0007"})).is_error


async def test_approval_gated_call_returns_pending(served):
    async with connect(served) as client:
        result = await client.call_tool(
            "send_email", {"to": "someone@elsewhere.example", "subject": "s", "body": "b"}
        )
    assert not result.is_error
    assert result.structured_content["status"] == "PENDING_APPROVAL"
    assert result.structured_content["approval_id"].startswith("APR-")


async def test_run_header_binds_calls_to_a_bastion_run(served):
    gateway = served["gateway"]
    run_id = gateway.registry.start_run(DEMO_AGENT_ID, "http-test")
    async with connect(served, run_id=run_id) as client:
        await client.call_tool("lookup_customer", {"customer_id": "C-0008"})
    assert gateway.budgets.tool_calls(DEMO_AGENT_ID, run_id) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-real-token"},
        {"Authorization": "Basic abc"},
        {"Authorization": "bearer"},
    ],
)
async def test_rt23_missing_or_invalid_token_is_401_and_audited(served, headers):
    gateway = served["gateway"]
    before = len(gateway.audit.events(event_type="auth_failed"))
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with httpx2.AsyncClient() as http:
        response = await http.post(served["url"], json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    events = gateway.audit.events(event_type="auth_failed")
    assert len(events) == before + 1
    assert "not-a-real-token" not in events[0].payload_json


async def test_rotated_token_stops_working(served):
    gateway = served["gateway"]
    old = served["token"]
    served["token"] = gateway.registry.issue_token(DEMO_AGENT_ID)
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            served["url"],
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": f"Bearer {old}"},
        )
    assert response.status_code == 401
    async with connect(served) as client:
        assert len((await client.list_tools()).tools) == 4


async def test_audit_chain_is_intact_after_http_traffic(served):
    assert verify_chain(served["gateway"].engine).ok
