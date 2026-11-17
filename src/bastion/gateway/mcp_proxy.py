"""The enforcement point: every tool call an agent makes goes through `Gateway.call_tool`.

Order of checks (docs/design/LLD.md §2.1):
  kill switch → tool-name check → policy load → budget → tool lookup → argument validation
  → policy rules → DLP scan of inputs → grant check → forward to the downstream tool
  → redact the output → audit → incident rules (after a denial).

`Gateway` is transport-agnostic; `bastion.gateway.server` exposes it over MCP streamable HTTP.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

from mcp import Client, StdioServerParameters, types
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from bastion.audit.log import AuditLog
from bastion.config import REPO_ROOT
from bastion.gateway.budgets import BudgetTracker
from bastion.gateway.normalize import (
    ArgumentError,
    args_hash,
    is_valid_tool_name,
    validate_and_normalise,
)
from bastion.gateway.policy_engine import Decision, Downstream, Policy, PolicyLoadError
from bastion.gateway.redaction import SUPPORTED_ENTITIES, BaseRedactor, get_redactor
from bastion.incidents.service import IncidentService
from bastion.oversight.approvals import ApprovalService
from bastion.oversight.killswitch import KillSwitchService
from bastion.registry.service import PolicyStore, Registry

Status = Literal["OK", "DENIED", "PENDING_APPROVAL", "TOOL_ERROR"]


class GatewayResult(BaseModel):
    status: Status
    decision: Decision
    payload: dict[str, Any]  # exactly what the agent receives
    is_error: bool = False
    args_hash: str | None = None
    redactions: dict[str, int] = Field(default_factory=dict)
    overhead_ms: float = 0.0  # gateway time, excluding the downstream tool
    downstream_ms: float = 0.0


class _Connection:
    """One downstream MCP server over stdio, owned by a single background task.

    The MCP client's context manager must be entered and exited in the same task, while tool
    calls arrive on arbitrary request tasks. The owner task holds the connection open; callers
    just use `client`.
    """

    def __init__(self, spec: Downstream, env: dict[str, str]) -> None:
        self.spec = spec
        self.env = env
        self.client: Client | None = None
        self.tools: dict[str, types.Tool] = {}
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: BaseException | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._serve(), name=f"downstream:{self.spec.name}")
        await self._ready.wait()
        if self._error is not None:
            raise RuntimeError(f"downstream '{self.spec.name}' failed to start") from self._error

    async def _serve(self) -> None:
        command = self.spec.command
        params = StdioServerParameters(
            # "python" means "this interpreter", so the server runs in the same environment.
            command=sys.executable if command[0] in ("python", "python3") else command[0],
            args=command[1:],
            env=self.env,
            cwd=str(REPO_ROOT),
        )
        try:
            async with Client(params) as client:
                listed = await client.list_tools()
                self.tools = {tool.name: tool for tool in listed.tools}
                self.client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the waiting caller
            self._error = exc
        finally:
            self.client = None
            self._ready.set()

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)


class DownstreamPool:
    """Connections to downstream tool servers, started on first use and shared."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        # Tool servers get a minimal environment: never the API key, passcode or other secrets.
        inherited = {k: v for k, v in os.environ.items() if k in _PASS_THROUGH_ENV}
        self.env = {**inherited, **(env or {})}
        self._connections: dict[tuple[str, ...], _Connection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, specs: list[Downstream]) -> list[_Connection]:
        connections = []
        async with self._lock:
            for spec in specs:
                key = tuple(spec.command)
                if key not in self._connections:
                    connection = _Connection(spec, self.env)
                    await connection.start()
                    self._connections[key] = connection
                connections.append(self._connections[key])
        return connections

    async def aclose(self) -> None:
        for connection in self._connections.values():
            await connection.stop()
        self._connections.clear()


_PASS_THROUGH_ENV = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TZ", "PYTHONPATH", "VIRTUAL_ENV", "SYSTEMROOT"}
)


def _text(result: types.CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, types.TextContent))


class Gateway:
    def __init__(
        self,
        engine: Engine,
        *,
        pool: DownstreamPool | None = None,
        redactor: BaseRedactor | None = None,
        demo_db: Path | str | None = None,
        low_memory: bool | None = None,
    ) -> None:
        self.engine = engine
        self._low_memory = low_memory
        self.audit = AuditLog(engine)
        self.registry = Registry(engine, self.audit)
        self.policies = PolicyStore(engine, self.audit)
        self.budgets = BudgetTracker(engine)
        self.approvals = ApprovalService(engine, self.audit)
        self.incidents = IncidentService(engine, self.audit)
        self.killswitch = KillSwitchService(engine, self.audit, self.approvals, self.incidents)
        self._redactor = redactor
        self._owns_pool = pool is None
        self.pool = pool or DownstreamPool({"BASTION_DEMO_DB": str(demo_db)} if demo_db else None)

    @property
    def redactor(self) -> BaseRedactor:
        if self._redactor is None:
            self._redactor = get_redactor(self._low_memory)
        return self._redactor

    async def aclose(self) -> None:
        if self._owns_pool:
            await self.pool.aclose()

    # --- discovery -----------------------------------------------------------------------------
    async def _catalogue(self, policy: Policy) -> dict[str, tuple[_Connection, types.Tool]]:
        catalogue: dict[str, tuple[_Connection, types.Tool]] = {}
        for connection in await self.pool.connect(policy.downstream):
            for name, tool in connection.tools.items():
                catalogue.setdefault(name, (connection, tool))
        return catalogue

    async def list_tools(self, agent_id: str) -> list[types.Tool]:
        """Least privilege in discovery (FR-11): only tools the policy can allow are listed."""
        try:
            policy = self.policies.active(agent_id)
        except PolicyLoadError:
            policy = None
        if policy is None:
            return []
        visible = policy.visible_tools()
        catalogue = await self._catalogue(policy)
        return [tool for name, (_, tool) in sorted(catalogue.items()) if name in visible]

    # --- enforcement ---------------------------------------------------------------------------
    async def call_tool(
        self,
        agent_id: str,
        name: Any,
        arguments: Any,
        run_id: str | None = None,
    ) -> GatewayResult:
        started = time.perf_counter()
        bucket = self.registry.resolve_run(agent_id, run_id)
        result = await self._decide_and_forward(agent_id, name, arguments, bucket)
        total_ms = (time.perf_counter() - started) * 1000
        result.overhead_ms = round(max(total_ms - result.downstream_ms, 0.0), 3)
        self._audit_decision(agent_id, bucket, name, arguments, result)
        if result.status == "DENIED" and not result.decision.reasons[-1].startswith("killswitch"):
            self._run_incident_rules(agent_id, name, result)
        return result

    def _run_incident_rules(self, agent_id: str, name: Any, result: GatewayResult) -> None:
        try:
            policy = self.policies.active(agent_id)
        except PolicyLoadError:
            policy = None
        if policy is None:
            return
        trigger = f"DENY {result.decision.rule_id or result.payload['reason']} on {str(name)[:60]}"
        for incident, action in self.incidents.evaluate_rules(
            agent_id, policy, category=result.decision.category, trigger=trigger
        ):
            if action == "kill":
                self.killswitch.kill(
                    agent_id,
                    reason=f"incident #{incident.id} ({incident.rule_id})",
                    actor="bastion:incident-rule",
                )

    async def _decide_and_forward(
        self, agent_id: str, name: Any, arguments: Any, bucket: str
    ) -> GatewayResult:
        scope = self.killswitch.active_scope(agent_id)  # checked before anything else
        if scope is not None:
            return self._denied(Decision(effect="deny", reasons=[f"killswitch: {scope}"]))

        if not is_valid_tool_name(name):
            return self._denied(Decision(effect="deny", reasons=["invalid_tool_name"]))

        try:
            policy = self.policies.active(agent_id)
        except PolicyLoadError as exc:
            return self._denied(Decision(effect="deny", reasons=[f"condition_error: {exc}"[:300]]))
        if policy is None:
            return self._denied(Decision(effect="deny", reasons=["no_active_policy"]))
        policy_hash = policy.content_hash

        over_budget = self.budgets.check_tool_call(agent_id, bucket, policy.budgets)
        if over_budget:
            return self._denied(
                Decision(effect="deny", policy_hash=policy_hash, reasons=[over_budget])
            )
        self.budgets.record_tool_call(agent_id, bucket)

        catalogue = await self._catalogue(policy)
        entry = catalogue.get(name)
        if entry is None:
            # Unknown downstream: the policy still decides (normally default deny).
            decision = policy.evaluate(name, {}, {"agent": agent_id})
            if decision.effect != "deny":
                decision = Decision(
                    effect="deny",
                    rule_id=decision.rule_id,
                    policy_hash=policy_hash,
                    reasons=["unknown_tool"],
                )
            return self._denied(decision)
        connection, tool = entry

        try:
            args = validate_and_normalise(arguments, tool.input_schema)
        except ArgumentError as exc:
            decision = policy.unconditional_deny(name) or Decision(
                effect="deny", policy_hash=policy_hash
            )
            decision.reasons.append(f"invalid_arguments: {exc}")
            return self._denied(decision)
        digest = args_hash(args)

        decision = policy.evaluate(name, args, {"agent": agent_id})

        if decision.effect == "allow" and decision.scan_input is not None:
            found = self.redactor.scan(args, decision.scan_input.entities)
            if found:
                summary = ", ".join(f"{entity} x{n}" for entity, n in sorted(found.items()))
                decision.reasons.append(f"scan_input: {summary}")
                action = decision.scan_input.action
                if action == "redact":
                    args, _ = self.redactor.redact(args, decision.scan_input.entities)
                else:
                    decision.effect = action
                    decision.redactions = []

        if decision.effect == "deny":
            return self._denied(decision, digest)
        if decision.effect == "require_approval":
            grant = self.approvals.consume_grant(agent_id, name, digest)
            if grant is None:
                return self._pending(agent_id, bucket, name, args, digest, decision)
            decision.reasons.append(f"grant {grant.id} consumed (approved by {grant.decided_by})")
        return await self._forward(connection, name, args, digest, decision)

    async def _forward(
        self,
        connection: _Connection,
        name: str,
        args: dict[str, Any],
        digest: str,
        decision: Decision,
    ) -> GatewayResult:
        if connection.client is None:
            return GatewayResult(
                status="TOOL_ERROR",
                decision=decision,
                payload={"status": "TOOL_ERROR", "message": "downstream tool server unavailable"},
                is_error=True,
                args_hash=digest,
            )
        called = time.perf_counter()
        raw = await connection.client.call_tool(name, args)
        downstream_ms = (time.perf_counter() - called) * 1000

        if raw.is_error:
            message, counts = self.redactor.redact(_text(raw), decision.redactions)
            return GatewayResult(
                status="TOOL_ERROR",
                decision=decision,
                payload={"status": "TOOL_ERROR", "message": message},
                is_error=True,
                args_hash=digest,
                redactions=counts,
                downstream_ms=downstream_ms,
            )
        content = raw.structured_content
        if not isinstance(content, dict):
            content = {"result": content if content is not None else _text(raw)}
        payload, counts = self.redactor.redact(content, decision.redactions)
        return GatewayResult(
            status="OK",
            decision=decision,
            payload=payload,
            args_hash=digest,
            redactions=counts,
            downstream_ms=downstream_ms,
        )

    def _pending(
        self,
        agent_id: str,
        bucket: str,
        name: str,
        args: dict[str, Any],
        digest: str,
        decision: Decision,
    ) -> GatewayResult:
        redacted, _ = self.redactor.redact(args, list(SUPPORTED_ENTITIES))
        approval, created = self.approvals.request(
            agent_id=agent_id,
            run_id=None if bucket == "unbound" else bucket,
            tool=name,
            args_hash=digest,
            args_redacted=redacted,
            rule_id=decision.rule_id,
        )
        if created:
            self.audit.append(
                "approval_requested",
                actor=agent_id,
                agent_id=agent_id,
                payload={
                    "approval_id": approval.id,
                    "tool": name,
                    "args_hash": digest,
                    "rule_id": decision.rule_id,
                    "expires_at": approval.expires_at,
                },
            )
        return GatewayResult(
            status="PENDING_APPROVAL",
            decision=decision,
            payload={
                "status": "PENDING_APPROVAL",
                "approval_id": approval.id,
                "rule_id": decision.rule_id,
                "message": (
                    "This action needs human approval before it can run. Nothing was executed. "
                    "Once approved, repeat the identical call."
                ),
            },
            args_hash=digest,
        )

    @staticmethod
    def _denied(decision: Decision, digest: str | None = None) -> GatewayResult:
        detail = decision.reasons[-1] if decision.reasons else "denied"
        if detail.startswith("matched "):
            reason = decision.category or "policy_rule"
        else:
            reason = detail.split(":")[0]
        return GatewayResult(
            status="DENIED",
            decision=decision,
            payload={
                "status": "DENIED",
                "rule_id": decision.rule_id,
                "reason": reason,
                "detail": detail,
                "message": "Blocked by Bastion policy. The action was not executed.",
            },
            is_error=True,
            args_hash=digest,
        )

    def _audit_decision(
        self, agent_id: str, bucket: str, name: Any, arguments: Any, result: GatewayResult
    ) -> None:
        if result.args_hash is not None and isinstance(arguments, dict):
            shown, _ = self.redactor.redact(arguments, list(SUPPORTED_ENTITIES))
        elif isinstance(arguments, dict):
            shown = {"_fields": sorted(str(key)[:60] for key in arguments)}  # values withheld
        else:
            shown = {}
        decision = result.decision
        self.audit.append(
            "tool_decision",
            actor=agent_id,
            agent_id=agent_id,
            payload={
                "run_id": bucket,
                "tool": str(name)[:100],
                "status": result.status,
                "effect": decision.effect,
                "rule_id": decision.rule_id,
                "policy_hash": decision.policy_hash,
                "reasons": decision.reasons,
                "category": decision.category,
                "args_hash": result.args_hash,
                "args": shown,
                "redactions": result.redactions,
                "approval_id": result.payload.get("approval_id"),
                "overhead_ms": result.overhead_ms,
                "downstream_ms": round(result.downstream_ms, 3),
            },
        )
