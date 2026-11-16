"""Run the scripted scenarios against a real gateway and print what Bastion decided.

    python -m demo.loan_ops_agent.run            # all scenarios, mode from BASTION_MODE (replay)
    python -m demo.loan_ops_agent.run uc03 uc04  # selected scenarios

`make demo` runs this in replay mode: model responses come from fixtures, so no API key is
needed. Everything else is real: the gateway, the policy engine, the tools server, the audit log.
"""

import asyncio
import json
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import uvicorn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine

from bastion import DISCLAIMER
from bastion.audit.verify import verify_chain
from bastion.config import Settings, get_settings
from bastion.db import make_engine
from bastion.gateway.mcp_proxy import Gateway
from bastion.gateway.server import RUN_HEADER, build_mcp_app
from bastion.llm import GovernedAnthropic
from bastion.llm.governance import GovernanceHook
from bastion.models import AuditEvent
from bastion.seed import DEMO_AGENT_ID, seed_demo
from demo.data.generate import build as build_demo_data
from demo.loan_ops_agent.graph import SYSTEM_STANDARD, SYSTEM_TRUSTING, AgentDeps, build_graph
from demo.loan_ops_agent.scenarios import BY_ID, SCENARIOS, Scenario

APPROVER = "approver@bank.example"


@dataclass
class RunResult:
    scenario: Scenario
    run_id: str
    status: str  # completed / interrupted / halted / failed
    since: int = 1  # first audit seq of this run
    final_text: str = ""
    pending: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class AgentRunner:
    """Runs the Loan Ops Agent against a gateway URL. Used by `make demo` and by the API."""

    def __init__(
        self,
        gateway: Gateway,
        gateway_url: str,
        *,
        checkpoint_path: Path,
        settings: Settings | None = None,
        agent_id: str = DEMO_AGENT_ID,
        llm_transport: Any = None,
    ) -> None:
        self.llm_transport = llm_transport  # tests inject a scripted model here
        self.gateway = gateway
        self.gateway_url = gateway_url
        self.checkpoint_path = checkpoint_path
        self.settings = settings or get_settings()
        self.agent_id = agent_id
        self.token = gateway.registry.issue_token(agent_id, actor="demo-runner")

    # --- plumbing ------------------------------------------------------------------------------
    async def call_tool(
        self, run_id: str, name: str, args: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """One governed tool call, over MCP streamable HTTP with the agent's bearer token."""
        headers = {"Authorization": f"Bearer {self.token}", RUN_HEADER: run_id}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=60) as http,
            Client(streamable_http_client(self.gateway_url, http_client=http)) as client,
        ):
            result = await client.call_tool(name, args)
        payload = result.structured_content
        if not isinstance(payload, dict):
            payload = {"result": payload}
        return payload, bool(result.is_error)

    async def warm_up(self) -> None:
        """Start the tools server and load the PII analyser before the first timed call."""
        _ = self.gateway.redactor
        headers = {"Authorization": f"Bearer {self.token}"}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=120) as http,
            Client(streamable_http_client(self.gateway_url, http_client=http)) as client,
        ):
            await client.list_tools()

    def _deps(self, scenario: Scenario, run_id: str, on_tool: Callable | None) -> AgentDeps:
        llm = GovernedAnthropic(
            self.agent_id,
            settings=self.settings,
            transport=self.llm_transport,
            mode="live" if self.llm_transport is not None else None,
            hooks=[GovernanceHook(self.gateway.engine, self.gateway.audit)],
        )

        async def call(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            return await self.call_tool(run_id, name, args)

        return AgentDeps(
            llm=llm,
            call_tool=call,
            model=self.settings.model_fast,
            run_id=run_id,
            system=SYSTEM_TRUSTING if scenario.system == "trusting" else SYSTEM_STANDARD,
            after_tool_call=on_tool,
        )

    @asynccontextmanager
    async def _graph(self, deps: AgentDeps):
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            yield build_graph(deps, saver)

    def _first_seq(self) -> int:
        head = self.gateway.audit.events(limit=1)
        return head[0].seq + 1 if head else 1

    def _finish(self, scenario: Scenario, run_id: str, state: dict, since: int) -> RunResult:
        registry = self.gateway.registry
        interrupts = state.get("__interrupt__") or []
        if interrupts:
            status = "interrupted"
            pending = interrupts[0].value["approvals"]
        else:
            pending = []
            status = state.get("outcome", "completed")
            status = "completed" if status == "max_steps" else status
        with_kill = self.gateway.killswitch.active_scope(self.agent_id) is not None
        if with_kill and status != "interrupted":
            status = "halted"  # the kill switch already marked the run row
        else:
            registry.set_run_status(run_id, status)
        events = audit_since(self.gateway.engine, since)
        return RunResult(
            scenario=scenario,
            run_id=run_id,
            status=status,
            since=since,
            final_text=state.get("final_text", ""),
            pending=pending,
            timeline=[line for event in events if (line := timeline_line(event))],
            events=events,
        )

    # --- public API ----------------------------------------------------------------------------
    async def start(self, scenario: Scenario, on_tool: Callable | None = None) -> RunResult:
        since = self._first_seq()
        run_id = self.gateway.registry.start_run(self.agent_id, scenario.id)
        if scenario.kill_after_tool_calls is not None and on_tool is None:
            on_tool = self._killer(scenario.kill_after_tool_calls)
        deps = self._deps(scenario, run_id, on_tool)
        config = {"configurable": {"thread_id": run_id}}
        async with self._graph(deps) as graph:
            state = await graph.ainvoke(
                {"messages": [{"role": "user", "content": scenario.prompt}], "steps": 0}, config
            )
        return self._finish(scenario, run_id, state, since)

    async def resume(
        self, scenario: Scenario, run_id: str, decisions: dict[str, dict[str, Any]]
    ) -> RunResult:
        """Continue an interrupted run once its approvals have been decided."""
        since = self._first_seq()
        self.gateway.registry.set_run_status(run_id, "running")
        deps = self._deps(scenario, run_id, None)
        config = {"configurable": {"thread_id": run_id}}
        async with self._graph(deps) as graph:
            state = await graph.ainvoke(Command(resume=decisions), config)
        return self._finish(scenario, run_id, state, since)

    def _killer(self, after: int) -> Callable:
        calls = {"n": 0}

        def on_tool(_index: int, _name: str, _payload: dict[str, Any]) -> None:
            calls["n"] += 1
            if calls["n"] == after:
                self.gateway.killswitch.kill(
                    self.agent_id, reason="Demo: approver pressed Kill during the run",
                    actor=APPROVER,
                )  # fmt: skip

        return on_tool

    async def run_scripted(self, scenario: Scenario) -> RunResult:
        """Run a scenario end to end, with the script standing in for the human approver."""
        if scenario.scripted:
            return await self._approve_then_swap(scenario)
        result = await self.start(scenario)
        if result.status == "interrupted" and scenario.approver:
            approve = scenario.approver == "approve"
            decisions = {}
            for item in result.pending:
                self.gateway.approvals.decide(
                    item["approval_id"], approve=approve, decided_by=APPROVER,
                    reason=scenario.approver_reason,
                )  # fmt: skip
                decisions[item["approval_id"]] = {
                    "approved": approve,
                    "reason": scenario.approver_reason,
                }
            resumed = await self.resume(scenario, result.run_id, decisions)
            resumed.since = result.since
            resumed.events = audit_since(self.gateway.engine, result.since)
            resumed.timeline = [line for e in resumed.events if (line := timeline_line(e))]
            return resumed
        return result

    async def _approve_then_swap(self, scenario: Scenario) -> RunResult:
        """UC-05, no model involved: get 60,000 approved, then call with 600,000."""
        since = self._first_seq()
        run_id = self.gateway.registry.start_run(self.agent_id, scenario.id)
        args = {
            "customer_id": "C-0021",
            "current_limit": 40000,
            "new_limit": 60000,
            "reason": "customer request ref 8812",
        }
        first, _ = await self.call_tool(run_id, "update_credit_limit", args)
        self.gateway.approvals.decide(
            first["approval_id"], approve=True, decided_by=APPROVER,
            reason="Approved for 60,000 as requested.",
        )  # fmt: skip
        swapped, _ = await self.call_tool(
            run_id, "update_credit_limit", {**args, "new_limit": 600000}
        )
        grant = self.gateway.approvals.get(first["approval_id"])
        text = (
            f"Approved {first['approval_id']} for 60,000. The call with 600,000 came back "
            f"{swapped['status']} ({swapped.get('approval_id')}); nothing executed and the "
            f"original grant is still '{grant.status}'."
        )
        return self._finish(scenario, run_id, {"outcome": "completed", "final_text": text}, since)


# --- presentation --------------------------------------------------------------------------------
def audit_since(engine: Engine, since_seq: int) -> list[dict[str, Any]]:
    from sqlalchemy import select

    with engine.connect() as conn:
        rows = conn.execute(
            select(AuditEvent).where(AuditEvent.seq >= since_seq).order_by(AuditEvent.seq)
        ).all()
    return [
        {"seq": r.seq, "type": r.event_type, "actor": r.actor, **json.loads(r.payload_json)}
        for r in rows
    ]


def timeline_line(event: dict[str, Any]) -> str | None:
    kind = event["type"]
    if kind == "tool_decision":
        label = {"allow": "ALLOW", "deny": "DENY ", "require_approval": "APPROVAL"}[event["effect"]]
        if event["status"] == "OK" and event["effect"] == "require_approval":
            label = "ALLOW (grant)"
        rule = event["rule_id"] or event["reasons"][-1].split(":")[0]
        extra = ""
        if event["redactions"]:
            extra = f"  redactions: {sum(event['redactions'].values())}"
        if event["category"]:
            extra += f"  category: {event['category']}"
        if event.get("approval_id"):
            extra += f"  → {event['approval_id']}"
        return f"{label:<13} {rule:<17} {event['tool']:<22} {event['overhead_ms']:>6.1f} ms{extra}"
    if kind == "approval_decided":
        return f"  ↳ approver {event['decision']} {event['approval_id']}: {event['reason']}"
    if kind == "grant_consumed":
        return f"  ↳ grant {event['approval_id']} consumed (single use)"
    if kind == "incident_opened":
        return (
            f"  ↳ INCIDENT #{event['incident_id']} {event['rule_id']} severity={event['severity']}"
        )
    if kind == "killswitch_activated":
        return f"  ↳ KILL SWITCH on {event['scope']} by {event['actor']}: {event['reason']}"
    if kind == "model_call_blocked":
        return f"MODEL BLOCKED {event['reason']}"
    return None


class DemoEnvironment:
    """A throwaway Bastion (database, gateway on a local port) plus fresh synthetic bank data."""

    def __init__(self, workdir: Path, settings: Settings | None = None) -> None:
        self.workdir = workdir
        self.settings = settings or get_settings()
        self.demo_db = workdir / "demo.db"
        build_demo_data(self.demo_db)
        self.engine = make_engine(workdir / "bastion.db")
        seed_demo(self.engine)
        self.gateway = Gateway(self.engine, demo_db=self.demo_db)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        config = uvicorn.Config(
            build_mcp_app(self.gateway), host="127.0.0.1", port=self.port, log_level="error"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.runner: AgentRunner | None = None

    def __enter__(self) -> "DemoEnvironment":
        self._thread.start()
        deadline = time.time() + 20
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("gateway did not start")
        self.runner = AgentRunner(
            self.gateway,
            f"http://127.0.0.1:{self.port}/mcp",
            checkpoint_path=self.workdir / "checkpoints.db",
            settings=self.settings,
        )
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
        self.engine.dispose()

    def reset_between_scenarios(self) -> None:
        """Each scenario starts from the same bank data and an agent that is allowed to act."""
        build_demo_data(self.demo_db)
        if self.gateway.killswitch.active_scope(DEMO_AGENT_ID):
            self.gateway.killswitch.reactivate(
                DEMO_AGENT_ID, reason="Demo: reset before the next scenario", actor=APPROVER
            )
        for incident in self.gateway.incidents.all(agent_id=DEMO_AGENT_ID):
            if incident.status != "resolved":
                self.gateway.incidents.advance(
                    incident.id, "resolved", actor=APPROVER, note="Demo: reset between scenarios"
                )
        self.gateway.approvals.revoke_open(DEMO_AGENT_ID, reason="demo reset", actor=APPROVER)


def print_result(result: RunResult) -> None:
    scenario = result.scenario
    print(f"\n━━ {scenario.use_case} · {scenario.title} " + "━" * 20)
    print(f"   task:  {scenario.prompt}")
    print(f"   watch: {scenario.what_to_watch}")
    for line in result.timeline:
        print(f"   {line}")
    print(f"   run {result.status.upper()}")
    if result.final_text:
        text = " ".join(result.final_text.split())
        print(f"   agent: {text[:400]}{'…' if len(text) > 400 else ''}")


async def run_all(ids: list[str], settings: Settings | None = None) -> list[RunResult]:
    settings = settings or get_settings()
    scenarios = [BY_ID[i] for i in ids] if ids else SCENARIOS
    results = []
    with (
        tempfile.TemporaryDirectory(prefix="bastion-demo-") as tmp,
        DemoEnvironment(Path(tmp), settings) as env,
    ):
        print(f"Bastion demo · mode={settings.mode} · gateway on 127.0.0.1:{env.port}")
        if settings.mode == "record" and not ids:
            for stale in settings.fixtures_dir.glob("*.json"):  # full re-record: drop old ones
                stale.unlink()
        await env.runner.warm_up()
        for scenario in scenarios:
            env.reset_between_scenarios()
            result = await env.runner.run_scripted(scenario)
            print_result(result)
            results.append(result)
        check = verify_chain(env.engine)
        print(
            f"\nAudit log: {check.events} events, hash chain "
            f"{'intact' if check.ok else 'BROKEN at seq ' + str(check.first_broken_seq)}."
        )
    print(DISCLAIMER)
    return results


def main() -> None:
    asyncio.run(run_all(sys.argv[1:]))


if __name__ == "__main__":
    main()
