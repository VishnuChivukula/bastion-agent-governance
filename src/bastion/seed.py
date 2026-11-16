"""Seed the demo agent and its policy into an empty database."""

from pathlib import Path

from sqlalchemy import Engine

from bastion.config import REPO_ROOT, Settings
from bastion.registry.service import PolicyStore, Registry

DEMO_AGENT_ID = "loan-ops-agent"
DEMO_POLICY = REPO_ROOT / "policies" / "loan-ops-agent.yaml"
DEMO_CARD = REPO_ROOT / "evals" / "assessor" / "cards" / "01-loan-ops-agent.yaml"
SEED_APPROVER = "governance-approver@bank.example"


def seed_demo(engine: Engine, policy_path: Path = DEMO_POLICY) -> bool:
    """Create the demo agent directly as `active` at tier `high`, with its seed policy.

    The shortcut for tests and for modes where the classification cannot be replayed. It skips
    the Assessor / Reviewer / sign-off flow; `seed_demo_classified` is the real thing.
    Returns False if the agent already exists.
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


def seed_demo_classified(engine: Engine, settings: Settings):
    """UC-01 for the demo agent: submit its card, let the Assessor and Reviewer classify it,
    and sign off the proposed tier as the seed approver. Returns the classification and the
    sign-off result, or None if the agent already exists.

    In replay mode the two agents answer from recorded fixtures, so this costs nothing.
    """
    from bastion.registry.classification import ClassificationService, load_card

    service = ClassificationService(engine, settings=settings)
    if service.registry.get_agent(DEMO_AGENT_ID) is not None:
        return None
    classification = service.register(load_card(DEMO_CARD), actor="lending-operations@bank.example")
    signoff = service.sign_off(
        DEMO_AGENT_ID, tier=classification.proposed.tier, approver=SEED_APPROVER
    )
    return classification, signoff
