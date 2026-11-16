"""Seed the demo agent and its policy into an empty database."""

from pathlib import Path

from sqlalchemy import Engine

from bastion.config import REPO_ROOT
from bastion.registry.service import PolicyStore, Registry

DEMO_AGENT_ID = "loan-ops-agent"
DEMO_POLICY = REPO_ROOT / "policies" / "loan-ops-agent.yaml"


def seed_demo(engine: Engine, policy_path: Path = DEMO_POLICY) -> bool:
    """Create the demo agent with its seed policy. Returns False if it already exists.

    Until slice S5 adds classification and sign-off, the demo agent is seeded directly as
    `active` at tier `high` (the tier UC-01 expects for a credit-related agent).
    """
    registry = Registry(engine)
    if registry.get_agent(DEMO_AGENT_ID) is not None:
        return False
    registry.create_agent(
        DEMO_AGENT_ID,
        name="Loan Ops Agent",
        owner="lending-operations@bank.example",
        tier="high",
        status="active",
        actor="seed",
    )
    PolicyStore(engine, registry.audit).activate(
        DEMO_AGENT_ID, policy_path.read_text(encoding="utf-8"), created_by="seed"
    )
    return True
