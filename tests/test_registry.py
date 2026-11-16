import pytest

from bastion.models import Agent
from bastion.registry.service import Registry, RegistryError, hash_token
from bastion.seed import DEMO_AGENT_ID, seed_demo


def test_seed_is_idempotent_and_audited(engine):
    assert seed_demo(engine) is True
    assert seed_demo(engine) is False
    registry = Registry(engine)
    assert [a.id for a in registry.list_agents()] == [DEMO_AGENT_ID]
    types = [e.event_type for e in registry.audit.events(newest_first=False)]
    assert types == ["agent_registered", "policy_activated"]


def test_token_is_shown_once_and_only_its_hash_is_stored(engine):
    seed_demo(engine)
    registry = Registry(engine)
    token = registry.issue_token(DEMO_AGENT_ID)
    assert len(token) >= 43  # 32 random bytes, url-safe
    stored = registry.get_agent(DEMO_AGENT_ID).token_hash
    assert stored == hash_token(token) and token not in stored
    assert registry.authenticate(token) == DEMO_AGENT_ID
    assert registry.authenticate(token + "x") is None
    assert registry.authenticate("") is None and registry.authenticate(None) is None
    assert token not in "".join(e.payload_json for e in registry.audit.events())


def test_no_token_before_sign_off(engine):
    registry = Registry(engine)
    registry.create_agent("draft-agent", name="Draft", owner="owner@bank.example")
    with pytest.raises(RegistryError, match="no token before sign-off"):
        registry.issue_token("draft-agent")
    with pytest.raises(RegistryError, match="unknown agent"):
        registry.issue_token("ghost")
    with pytest.raises(RegistryError, match="already exists"):
        registry.create_agent("draft-agent", name="Again", owner="o")


def test_blocked_agent_cannot_authenticate(engine):
    from bastion.db import session_scope

    seed_demo(engine)
    registry = Registry(engine)
    token = registry.issue_token(DEMO_AGENT_ID)
    with session_scope(engine) as session:
        session.get(Agent, DEMO_AGENT_ID).status = "blocked"
    assert registry.authenticate(token) is None


def test_runs_and_budget_buckets(engine):
    seed_demo(engine)
    registry = Registry(engine)
    run_id = registry.start_run(DEMO_AGENT_ID, "uc-02")
    assert registry.resolve_run(DEMO_AGENT_ID, run_id) == run_id
    assert registry.resolve_run(DEMO_AGENT_ID, "invented") == "unbound"
    assert registry.resolve_run(DEMO_AGENT_ID, None) == "unbound"
    assert registry.resolve_run("another-agent", run_id) == "unbound"  # not that agent's run
    registry.set_run_status(run_id, "completed")
    with pytest.raises(RegistryError):
        registry.set_run_status("run-missing", "completed")
