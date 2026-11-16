"""Interpreter for the red-team and benign scenario files (docs/EVALS.md, suites A and B).

Each YAML file is one scenario: a list of steps run against a real, freshly seeded gateway
(policy engine, approvals, kill switch, incidents, audit log, the demo tools server). There is
no model in this layer: steps are the calls a compromised or mistaken agent would make, so
the result does not depend on what a model happens to do. Scenarios with `scenario:` steps
run the recorded agent-in-the-loop demo scenarios instead.

A scenario passes only if every expectation in every step holds.
"""

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import update

from bastion.audit.verify import verify_chain
from bastion.config import Settings
from bastion.db import make_engine, session_scope
from bastion.gateway.mcp_proxy import DownstreamPool, Gateway
from bastion.gateway.policy_engine import PolicyLoadError
from bastion.gateway.redaction import BaseRedactor
from bastion.gateway.server import build_mcp_app
from bastion.llm.governance import BudgetExceeded, GovernanceHook
from bastion.models import Approval, AuditEvent, PolicyRow, Usage, iso, utcnow
from bastion.seed import DEMO_AGENT_ID, DEMO_POLICY, seed_demo
from demo.data.generate import build as build_demo_data

APPROVER = "approver@bank.example"


class Failed(Exception):
    """An expectation did not hold."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


class Context:
    def __init__(
        self, workdir: Path, pool: DownstreamPool, redactor: BaseRedactor, demo_db: Path,
        settings: Settings,
    ) -> None:  # fmt: skip
        self.workdir = workdir
        self.demo_db = demo_db
        self.settings = settings
        build_demo_data(demo_db)
        self.engine = make_engine(workdir / "bastion.db")
        seed_demo(self.engine)
        self.gateway = Gateway(self.engine, pool=pool, redactor=redactor)
        self.run_id = self.gateway.registry.start_run(DEMO_AGENT_ID, "eval")
        self.runs = {DEMO_AGENT_ID: self.run_id}
        self.last = None  # last GatewayResult
        self.latencies: list[float] = []
        self.actual: list[str] = []
        self.rule_id: str | None = None

    # --- helpers -------------------------------------------------------------------------------
    def approvals(self) -> list[Approval]:
        return sorted(self.gateway.approvals.all(), key=lambda a: a.created_at)

    def pick(self, which: str) -> Approval:
        rows = self.approvals()
        check(bool(rows), "no approval exists")
        return rows[0] if which == "first" else rows[-1]

    def db_value(self, sql: str, *params: Any) -> Any:
        with sqlite3.connect(self.demo_db) as con:
            return con.execute(sql, params).fetchone()[0]

    # --- steps ---------------------------------------------------------------------------------
    async def call(self, spec: dict[str, Any], expect: dict[str, Any] | None) -> None:
        agent = spec.get("agent", DEMO_AGENT_ID)
        result = await self.gateway.call_tool(
            agent, spec["tool"], spec.get("args", {}), self.runs.get(agent)
        )
        self.last = result
        self.latencies.append(result.overhead_ms)
        self.rule_id = result.decision.rule_id
        reason = result.payload.get("reason", "")
        self.actual.append(
            f"{result.status}"
            + (f" {result.decision.rule_id}" if result.decision.rule_id else "")
            + (f" ({reason})" if reason else "")
        )
        for key, wanted in (expect or {}).items():
            got = {
                "status": result.status,
                "rule_id": result.decision.rule_id,
                "reason": reason,
                "effect": result.decision.effect,
                "category": result.decision.category,
                "detail_contains": result.payload.get("detail", ""),
                "redactions": sum(result.redactions.values()),
                "result_contains": json.dumps(result.payload),
            }[key]
            if key.endswith("_contains"):
                check(str(wanted) in got, f"{spec['tool']}: {key} {wanted!r} not in {got!r}")
            else:
                check(got == wanted, f"{spec['tool']}: {key} is {got!r}, expected {wanted!r}")

    async def step(self, step: dict[str, Any]) -> None:
        gateway = self.gateway
        if "call" in step:
            for _ in range(step.get("repeat", 1)):
                await self.call(step["call"], step.get("expect"))
        elif "decide" in step:
            approval = self.pick(step.get("which", "last"))
            gateway.approvals.decide(
                approval.id, approve=step["decide"] == "approve", decided_by=APPROVER,
                reason=step.get("reason", "Eval: scripted approver."),
            )  # fmt: skip
        elif "expire" in step:
            approval = self.pick(step["expire"])
            with session_scope(self.engine) as session:
                session.execute(
                    update(Approval)
                    .where(Approval.id == approval.id)
                    .values(expires_at=iso(utcnow() - timedelta(minutes=1)))
                )
        elif "kill" in step:
            gateway.killswitch.kill(DEMO_AGENT_ID, reason=step["kill"], actor=APPROVER)
        elif "second_agent" in step:
            agent = step["second_agent"]
            gateway.registry.create_agent(
                agent, name="Second agent", owner="eval@bank.example", tier="high",
                status="active", actor="eval",
            )  # fmt: skip
            text = DEMO_POLICY.read_text(encoding="utf-8").replace(
                f"agent: {DEMO_AGENT_ID}", f"agent: {agent}"
            )
            gateway.policies.activate(agent, text, created_by="eval")
            self.runs[agent] = gateway.registry.start_run(agent, "eval")
        elif "http_auth" in step:
            headers = {"missing": {}, "invalid": {"Authorization": "Bearer not-a-real-token"}}[
                step["http_auth"]
            ]
            transport = httpx.ASGITransport(app=build_mcp_app(gateway))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
                response = await http.post(
                    "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers=headers,
                )  # fmt: skip
            self.actual.append(f"HTTP {response.status_code}")
            check(response.status_code == 401, f"expected 401, got {response.status_code}")
        elif "model_budget" in step:
            with session_scope(self.engine) as session:
                session.add(
                    Usage(agent_id=DEMO_AGENT_ID, run_id=self.run_id, kind="model",
                          tokens_in=step["model_budget"], tokens_out=0)
                )  # fmt: skip
            hook = GovernanceHook(self.engine, gateway.audit)
            try:
                hook.before_call(DEMO_AGENT_ID, self.run_id, self.settings.model_fast)
            except BudgetExceeded as blocked:
                self.actual.append(f"BudgetExceeded ({blocked.reason.split(':')[0]})")
            else:
                raise Failed("the model call was not blocked")
        elif "tamper_audit" in step:
            seq = step["tamper_audit"]
            with session_scope(self.engine) as session:
                session.execute(
                    update(AuditEvent).where(AuditEvent.seq == seq).values(actor="someone-else")
                )
            result = verify_chain(self.engine)
            self.actual.append(f"verify broken at seq {result.first_broken_seq}")
            check(not result.ok and result.first_broken_seq == seq, f"verify said {result}")
        elif "activate_policy" in step:
            spec = step["activate_policy"]
            text = DEMO_POLICY.read_text(encoding="utf-8")
            for old, new in spec.get("replace", {}).items():
                check(old in text, f"policy text does not contain {old!r}")
                text = text.replace(old, new)
            text += spec.get("append", "")
            try:
                gateway.policies.activate(DEMO_AGENT_ID, text, created_by=APPROVER)
                outcome = "activated"
            except PolicyLoadError:
                outcome = "rejected"
            self.actual.append(f"policy {outcome}")
            check(outcome == step["expect"], f"policy was {outcome}, expected {step['expect']}")
        elif "tamper_policy_row" in step:
            with session_scope(self.engine) as session:
                session.execute(
                    update(PolicyRow)
                    .where(PolicyRow.active.is_(True))
                    .values(content_yaml=PolicyRow.content_yaml + step["tamper_policy_row"])
                )
        elif "expect_incident" in step:
            wanted = step["expect_incident"]
            found = [(i.rule_id, i.severity) for i in gateway.incidents.all()]
            self.actual.append(f"incidents {found}")
            check((wanted["rule_id"], wanted["severity"]) in found, f"incidents: {found}")
        elif "expect_agent_status" in step:
            status = gateway.registry.get_agent(DEMO_AGENT_ID).status
            check(status == step["expect_agent_status"], f"agent is {status}")
        elif "expect_approval" in step:
            wanted = step["expect_approval"]
            approval = self.pick(wanted.get("which", "last"))
            check(approval.status == wanted["status"], f"approval is {approval.status}")
        elif "expect_approvals" in step:
            check(len(self.approvals()) == step["expect_approvals"], f"{len(self.approvals())}")
        elif "expect_limit" in step:
            customer, wanted = next(iter(step["expect_limit"].items()))
            got = self.db_value("select credit_limit from customers where id = ?", customer)
            self.actual.append(f"{customer} limit {got:g}")
            check(got == wanted, f"{customer} limit is {got:g}, expected {wanted:g}")
        elif "expect_outbox" in step:
            got = self.db_value("select count(*) from outbox")
            self.actual.append(f"outbox {got}")
            check(got == step["expect_outbox"], f"outbox has {got} rows")
        elif "expect_audit" in step:
            kinds = {e.event_type for e in gateway.audit.events(limit=500)}
            check(step["expect_audit"] in kinds, f"no '{step['expect_audit']}' audit event")
        elif "expect_verify_ok" in step:
            check(verify_chain(self.engine).ok, "audit chain is broken")
        else:
            raise Failed(f"unknown step: {step}")


async def run_agent_scenario(spec: dict[str, Any], settings: Settings, workdir: Path) -> list[str]:
    """Agent-in-the-loop layer: a recorded demo scenario, replayed through a real gateway."""
    from demo.loan_ops_agent.run import DemoEnvironment
    from demo.loan_ops_agent.scenarios import BY_ID

    with DemoEnvironment(workdir, settings) as env:
        await env.runner.warm_up()
        result = await env.runner.run_scripted(BY_ID[spec["scenario"]])
        decisions = [
            f"{e['tool']} {e['status']} {e['rule_id'] or ''}".strip()
            for e in result.events
            if e["type"] == "tool_decision"
        ]
        kinds = [e["type"] for e in result.events]
        check(result.status == spec["status"], f"run ended {result.status}")
        for wanted in spec.get("decisions", []):
            check(wanted in decisions, f"decision {wanted!r} not in {decisions}")
        for wanted in spec.get("events", []):
            check(wanted in kinds, f"event {wanted!r} not in the audit trail")
        for unwanted in spec.get("no_events", []):
            check(unwanted not in kinds, f"event {unwanted!r} should not be in the audit trail")
        check(verify_chain(env.engine).ok, "audit chain is broken")
    return [f"run {result.status}", *decisions[-2:]]


async def run_scenario(
    path: Path, *, pool: DownstreamPool, redactor: BaseRedactor, demo_db: Path, workdir: Path,
    settings: Settings,
) -> dict[str, Any]:  # fmt: skip
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    record: dict[str, Any] = {
        "suite": spec["suite"],
        "id": spec["id"],
        "category": spec["category"],
        "layer": "agent" if "scenario" in spec else "gateway",
        "title": spec["title"],
        "expected": spec["expected"],
        "actual": "",
        "pass": False,
        "latency_ms": None,
        "rule_id": None,
        "error": None,
    }
    try:
        if "scenario" in spec:
            actual = await run_agent_scenario(spec, settings, workdir)
        else:
            context = Context(workdir, pool, redactor, demo_db, settings)
            try:
                for step in spec["steps"]:
                    await context.step(step)
            finally:
                actual = context.actual
                if context.latencies:
                    record["latency_ms"] = round(max(context.latencies), 3)
                record["rule_id"] = context.rule_id
                record["latencies"] = context.latencies
                context.engine.dispose()
        record["pass"] = True
    except Failed as failed:
        record["error"] = str(failed)
        actual = locals().get("actual") or []
    record["actual"] = "; ".join(actual[-3:])
    return record
