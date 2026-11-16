"""Per-agent budgets (FR-23). Tool calls are enforced here at the gateway."""

from sqlalchemy import Engine, func, select

from bastion.db import session_scope
from bastion.gateway.policy_engine import Budgets
from bastion.models import Usage


class BudgetTracker:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def tool_calls(self, agent_id: str, run_id: str) -> int:
        with session_scope(self.engine) as session:
            return session.scalar(
                select(func.count())
                .select_from(Usage)
                .where(Usage.agent_id == agent_id, Usage.run_id == run_id, Usage.kind == "tool")
            )

    def check_tool_call(self, agent_id: str, run_id: str, budgets: Budgets) -> str | None:
        """Return a denial reason if one more tool call would exceed the session cap."""
        cap = budgets.max_tool_calls_per_session
        if cap is not None and self.tool_calls(agent_id, run_id) >= cap:
            return f"budget_exceeded: max_tool_calls_per_session={cap}"
        return None

    def record_tool_call(self, agent_id: str, run_id: str) -> None:
        with session_scope(self.engine) as session:
            session.add(Usage(agent_id=agent_id, run_id=run_id, kind="tool"))
