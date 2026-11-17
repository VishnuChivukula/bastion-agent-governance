"""Governance for model calls (FR-23): kill switch and budgets before, usage and audit after."""

from datetime import UTC, datetime

from sqlalchemy import Engine, func, select

from bastion.audit.log import AuditLog
from bastion.db import session_scope
from bastion.llm.client import CallRecord
from bastion.models import Usage
from bastion.oversight.killswitch import KillSwitchService
from bastion.registry.service import PolicyStore, Registry


class ModelCallBlocked(Exception):
    """Raised before a model call that governance does not allow."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BudgetExceeded(ModelCallBlocked):
    pass


class KillSwitchActive(ModelCallBlocked):
    pass


class GovernanceHook:
    """A `CallHook` for `GovernedAnthropic`."""

    def __init__(self, engine: Engine, audit: AuditLog | None = None) -> None:
        self.engine = engine
        self.audit = audit or AuditLog(engine)
        self.policies = PolicyStore(engine, self.audit)
        self.killswitch = KillSwitchService(engine, self.audit)
        self.registry = Registry(engine, self.audit)

    def session_tokens(self, agent_id: str, run_id: str) -> int:
        with session_scope(self.engine) as session:
            return session.scalar(
                select(func.coalesce(func.sum(Usage.tokens_in + Usage.tokens_out), 0)).where(
                    Usage.agent_id == agent_id, Usage.run_id == run_id, Usage.kind == "model"
                )
            )

    def cost_today(self, agent_id: str) -> float:
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with session_scope(self.engine) as session:
            return session.scalar(
                select(func.coalesce(func.sum(Usage.cost_usd), 0.0)).where(
                    Usage.agent_id == agent_id, Usage.ts >= midnight.isoformat()
                )
            )

    def before_call(self, agent_id: str, run_id: str | None, model: str) -> None:
        blocked: ModelCallBlocked | None = None
        if self.killswitch.active_scope(agent_id):
            blocked = KillSwitchActive("killswitch")
        else:
            policy = self.policies.active(agent_id)
            budgets = policy.budgets if policy else None
            if budgets and budgets.max_tokens_per_session is not None:
                used = self.session_tokens(agent_id, self.registry.resolve_run(agent_id, run_id))
                if used >= budgets.max_tokens_per_session:
                    blocked = BudgetExceeded(
                        f"budget_exceeded: max_tokens_per_session={budgets.max_tokens_per_session}"
                    )
            if (
                blocked is None
                and budgets
                and budgets.max_cost_usd_per_day is not None
                and self.cost_today(agent_id) >= budgets.max_cost_usd_per_day
            ):
                blocked = BudgetExceeded(
                    f"budget_exceeded: max_cost_usd_per_day={budgets.max_cost_usd_per_day}"
                )
        if blocked is not None:
            self.audit.append(
                "model_call_blocked",
                actor=agent_id,
                agent_id=agent_id,
                payload={"run_id": run_id, "model": model, "reason": blocked.reason},
            )
            raise blocked

    def after_call(self, record: CallRecord) -> None:
        with session_scope(self.engine) as session:
            session.add(
                Usage(
                    agent_id=record.agent_id,
                    # Same rule as the gateway: only a run Bastion issued for this agent is a
                    # session of its own, so inventing run ids cannot reset the token budget.
                    run_id=self.registry.resolve_run(record.agent_id, record.run_id),
                    kind="model",
                    tokens_in=record.usage.input_tokens,
                    tokens_out=record.usage.output_tokens,
                    cost_usd=record.cost_usd,
                )
            )
        self.audit.append(
            "model_call",
            actor=record.agent_id,
            agent_id=record.agent_id,
            payload={
                "run_id": record.run_id,
                "model": record.model,
                "mode": record.mode,
                "replayed": record.replayed,
                "tokens_in": record.usage.input_tokens,
                "tokens_out": record.usage.output_tokens,
                "cost_usd": record.cost_usd,
                "stop_reason": record.stop_reason,
                "latency_ms": round(record.latency_ms, 1),
            },
        )
