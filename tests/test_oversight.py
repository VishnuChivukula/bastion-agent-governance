"""Approvals, grants, kill switch, incidents and model budgets (S3). RT ids: docs/EVALS.md."""

import json
import sqlite3

import pytest

from bastion.audit.verify import verify_chain
from bastion.config import Settings
from bastion.incidents.service import IncidentError
from bastion.llm import FixtureStore, GovernedAnthropic
from bastion.llm.client import Prices
from bastion.llm.governance import BudgetExceeded, GovernanceHook, KillSwitchActive
from bastion.oversight.approvals import ApprovalError
from bastion.oversight.killswitch import GLOBAL, KillSwitchError

pytestmark = pytest.mark.anyio


def limit_of(harness, customer_id):
    con = sqlite3.connect(harness.gateway.pool.env["BASTION_DEMO_DB"])
    try:
        return con.execute(
            "SELECT credit_limit FROM customers WHERE id=?", (customer_id,)
        ).fetchone()[0]
    finally:
        con.close()


def raise_args(harness, customer_id, new_limit):
    return {
        "customer_id": customer_id,
        "current_limit": limit_of(harness, customer_id),
        "new_limit": new_limit,
        "reason": "customer request ref 8812",
    }


def events(harness, event_type):
    return harness.gateway.audit.events(event_type=event_type, newest_first=False)


# --- UC-04: approval → grant → identical call executes ------------------------------------------
async def test_uc04_approved_call_executes_once_with_the_identical_arguments(harness):
    approvals = harness.gateway.approvals
    args = raise_args(harness, "C-0042", 70000)
    pending = await harness.call("update_credit_limit", args)
    assert pending.status == "PENDING_APPROVAL"
    approval_id = pending.payload["approval_id"]

    approvals.decide(approval_id, approve=True, decided_by="approver@bank.example",
                     reason="Income verified")  # fmt: skip
    assert limit_of(harness, "C-0042") != 70000  # approving does not execute anything

    done = await harness.call("update_credit_limit", args)
    assert done.status == "OK" and done.payload["new_limit"] == 70000
    assert limit_of(harness, "C-0042") == 70000
    assert approvals.get(approval_id).status == "consumed"
    assert any(f"grant {approval_id} consumed" in r for r in done.decision.reasons)

    types = [e.event_type for e in harness.gateway.audit.events(newest_first=False)]
    for expected in ("approval_requested", "approval_decided", "grant_consumed"):
        assert types.count(expected) == 1
    assert types.count("tool_decision") == 2  # 5+ audit events for the flow
    assert json.loads(events(harness, "approval_decided")[0].payload_json)["args_hash"] == (
        pending.args_hash
    )
    assert verify_chain(harness.gateway.engine).ok


async def test_rt14_consumed_grant_cannot_be_reused(harness):
    args = raise_args(harness, "C-0043", 70000)
    first = await harness.call("update_credit_limit", args)
    harness.gateway.approvals.decide(
        first.payload["approval_id"], approve=True, decided_by="approver", reason="ok"
    )
    assert (await harness.call("update_credit_limit", args)).status == "OK"
    again = await harness.call("update_credit_limit", {**args, "current_limit": 70000})
    assert again.status == "PENDING_APPROVAL"
    replay = await harness.call("update_credit_limit", args)  # the very same call again
    assert replay.status == "PENDING_APPROVAL"
    assert replay.payload["approval_id"] != first.payload["approval_id"]


async def test_rt13_uc05_approve_then_swap_does_not_execute(harness):
    args = raise_args(harness, "C-0044", 60000)
    first = await harness.call("update_credit_limit", args)
    approval_id = first.payload["approval_id"]
    harness.gateway.approvals.decide(approval_id, approve=True, decided_by="approver", reason="ok")

    swapped = await harness.call("update_credit_limit", {**args, "new_limit": 600000})
    assert swapped.status == "PENDING_APPROVAL"
    assert swapped.payload["approval_id"] != approval_id
    assert limit_of(harness, "C-0044") == args["current_limit"]
    assert harness.gateway.approvals.get(approval_id).status == "approved"  # still unconsumed

    for variant in ({"reason": "different reason"}, {"customer_id": "C-0045"}):
        other = await harness.call("update_credit_limit", {**args, **variant})
        assert other.status in ("PENDING_APPROVAL", "TOOL_ERROR", "DENIED")
        assert other.status != "OK"
    assert harness.gateway.approvals.get(approval_id).status == "approved"


async def test_rt15_grant_expires_after_ttl(harness):
    approvals = harness.gateway.approvals
    approvals.ttl_seconds = 0  # expires immediately
    args = raise_args(harness, "C-0046", 70000)
    first = await harness.call("update_credit_limit", args)
    with pytest.raises(ApprovalError, match="expired"):
        approvals.decide(first.payload["approval_id"], approve=True, decided_by="a", reason="ok")
    assert approvals.get(first.payload["approval_id"]).status == "expired"

    approvals.ttl_seconds = 1800
    second = await harness.call("update_credit_limit", args)
    approvals.decide(second.payload["approval_id"], approve=True, decided_by="a", reason="ok")
    from bastion.db import session_scope
    from bastion.models import Approval

    with session_scope(harness.gateway.engine) as session:  # time passes: the grant goes stale
        session.get(Approval, second.payload["approval_id"]).expires_at = "2000-01-01T00:00:00"
    third = await harness.call("update_credit_limit", args)
    assert third.status == "PENDING_APPROVAL"
    assert approvals.get(second.payload["approval_id"]).status == "expired"
    assert limit_of(harness, "C-0046") == args["current_limit"]


async def test_rt16_grant_for_one_agent_is_useless_to_another(harness):
    gateway = harness.gateway
    seed_policy = gateway.policies.active_row(harness.agent_id).content_yaml
    gateway.registry.create_agent("agent-b", name="B", owner="o", status="active")
    gateway.policies.activate(
        "agent-b", seed_policy.replace("agent: loan-ops-agent", "agent: agent-b"), created_by="t"
    )
    args = raise_args(harness, "C-0047", 70000)
    first = await harness.call("update_credit_limit", args)
    gateway.approvals.decide(first.payload["approval_id"], approve=True, decided_by="a",
                             reason="ok")  # fmt: skip
    as_b = await gateway.call_tool("agent-b", "update_credit_limit", args)
    assert as_b.status == "PENDING_APPROVAL"
    assert limit_of(harness, "C-0047") == args["current_limit"]
    assert gateway.approvals.get(first.payload["approval_id"]).status == "approved"


async def test_rejected_approval_grants_nothing(harness):
    args = raise_args(harness, "C-0048", 70000)
    first = await harness.call("update_credit_limit", args)
    harness.gateway.approvals.decide(
        first.payload["approval_id"], approve=False, decided_by="approver", reason="No evidence"
    )
    again = await harness.call("update_credit_limit", args)
    assert again.status == "PENDING_APPROVAL"
    assert again.payload["approval_id"] != first.payload["approval_id"]
    assert limit_of(harness, "C-0048") == args["current_limit"]


async def test_decisions_need_a_reason_and_a_pending_approval(harness):
    approvals = harness.gateway.approvals
    first = await harness.call("update_credit_limit", raise_args(harness, "C-0049", 70000))
    approval_id = first.payload["approval_id"]
    with pytest.raises(ApprovalError, match="reason"):
        approvals.decide(approval_id, approve=True, decided_by="a", reason="  ")
    with pytest.raises(ApprovalError, match="unknown"):
        approvals.decide("APR-missing", approve=True, decided_by="a", reason="ok")
    approvals.decide(approval_id, approve=True, decided_by="a", reason="ok")
    with pytest.raises(ApprovalError, match="not pending"):
        approvals.decide(approval_id, approve=False, decided_by="a", reason="changed my mind")
    assert [a.id for a in approvals.all(status="approved", agent_id=harness.agent_id)] == [
        approval_id
    ]


# --- UC-07 / RT-22: kill switch ------------------------------------------------------------------
async def test_rt22_uc07_kill_switch_denies_revokes_and_halts(harness):
    gateway = harness.gateway
    pending = await harness.call("update_credit_limit", raise_args(harness, "C-0050", 70000))
    granted = await harness.call(
        "send_email", {"to": "x@else.example", "subject": "s", "body": "b"}
    )
    gateway.approvals.decide(granted.payload["approval_id"], approve=True, decided_by="a",
                             reason="ok")  # fmt: skip

    outcome = gateway.killswitch.kill(harness.agent_id, reason="Suspicious activity",
                                      actor="approver@bank.example")  # fmt: skip
    assert set(outcome["revoked_approvals"]) == {
        pending.payload["approval_id"],
        granted.payload["approval_id"],
    }
    assert outcome["halted_runs"] == [harness.run_id]

    denied = await harness.call("lookup_customer", {"customer_id": "C-0007"})
    assert denied.status == "DENIED" and denied.payload["reason"] == "killswitch"
    blocked = await harness.call(
        "send_email", {"to": "x@else.example", "subject": "s", "body": "b"}
    )
    assert blocked.payload["reason"] == "killswitch"  # the revoked grant is useless
    assert gateway.approvals.get(pending.payload["approval_id"]).status == "revoked"
    assert gateway.registry.get_agent(harness.agent_id).status == "killed"
    assert [i.rule_id for i in gateway.incidents.all(agent_id=harness.agent_id)] == ["KILLSWITCH"]
    # kill-switch denials do not pile up as new incidents
    for _ in range(4):
        await harness.call("lookup_customer", {"customer_id": "C-0007"})
    assert len(gateway.incidents.all()) == 1

    with pytest.raises(KillSwitchError, match="reason"):
        gateway.killswitch.reactivate(harness.agent_id, reason="", actor="approver")
    gateway.killswitch.reactivate(
        harness.agent_id, reason="Reviewed, false alarm", actor="approver"
    )
    assert gateway.registry.get_agent(harness.agent_id).status == "active"
    assert (await harness.call("lookup_customer", {"customer_id": "C-0007"})).status == "OK"
    types = [e.event_type for e in gateway.audit.events(newest_first=False)]
    assert "killswitch_activated" in types and "killswitch_reactivated" in types
    assert types.count("approval_revoked") == 2
    assert verify_chain(gateway.engine).ok


async def test_global_kill_switch_stops_every_agent(harness):
    gateway = harness.gateway
    gateway.killswitch.kill(GLOBAL, reason="Platform incident", actor="approver")
    assert gateway.killswitch.active_scope(harness.agent_id) == GLOBAL
    denied = await harness.call("lookup_customer", {"customer_id": "C-0007"})
    assert denied.decision.reasons == ["killswitch: global"]
    with pytest.raises(KillSwitchError, match="not active"):
        gateway.killswitch.reactivate(harness.agent_id, reason="x", actor="a")
    gateway.killswitch.reactivate(GLOBAL, reason="Resolved", actor="approver")
    assert (await harness.call("lookup_customer", {"customer_id": "C-0007"})).status == "OK"
    assert [k.scope for k in gateway.killswitch.status()] == [GLOBAL]


async def test_kill_needs_a_reason_and_a_known_agent(harness):
    with pytest.raises(KillSwitchError, match="reason"):
        harness.gateway.killswitch.kill(harness.agent_id, reason=" ", actor="a")
    with pytest.raises(KillSwitchError, match="unknown agent"):
        harness.gateway.killswitch.kill("ghost", reason="x", actor="a")


# --- incidents -----------------------------------------------------------------------------------
async def test_ir1_opens_once_after_three_denials(harness):
    gateway = harness.gateway
    for _ in range(2):
        await harness.call("delete_customer", {})
    assert gateway.incidents.all() == []
    for _ in range(3):
        await harness.call("delete_customer", {})
    incidents = gateway.incidents.all(agent_id=harness.agent_id)
    assert [(i.rule_id, i.severity) for i in incidents] == [("IR-1", "medium")]
    assert gateway.killswitch.active_scope(harness.agent_id) is None  # IR-1 does not kill


async def test_incident_lifecycle_moves_forward_only_with_notes(harness):
    incidents = harness.gateway.incidents
    incident, created = incidents.open(
        harness.agent_id, rule_id="IR-9", severity="low", summary="s"
    )
    again, created_again = incidents.open(
        harness.agent_id, rule_id="IR-9", severity="low", summary="s"
    )
    assert created and not created_again and again.id == incident.id
    incidents.advance(incident.id, "acknowledged", actor="approver", note="Looking into it")
    incidents.advance(incident.id, "contained", actor="approver", note="Agent stopped")
    with pytest.raises(IncidentError, match="cannot move"):
        incidents.advance(incident.id, "acknowledged", actor="approver", note="back")
    with pytest.raises(IncidentError, match="note"):
        incidents.advance(incident.id, "resolved", actor="approver", note="")
    with pytest.raises(IncidentError, match="unknown status"):
        incidents.advance(incident.id, "closed", actor="approver", note="x")
    with pytest.raises(IncidentError, match="unknown incident"):
        incidents.advance(9999, "resolved", actor="approver", note="x")
    resolved = incidents.advance(incident.id, "resolved", actor="approver", note="Root cause fixed")
    assert resolved.closed_at is not None
    assert [n["status"] for n in json.loads(resolved.notes_json)] == [
        "acknowledged",
        "contained",
        "resolved",
    ]
    assert not incidents.has_open(harness.agent_id)
    _, reopened = incidents.open(harness.agent_id, rule_id="IR-9", severity="low", summary="s")
    assert reopened  # a resolved incident does not suppress a new one


# --- RT-21: model budgets through the SDK wrapper -----------------------------------------------
class FakeTransport:
    def __init__(self):
        self.calls = 0

    def create(self, params):
        self.calls += 1
        return {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 120_000, "output_tokens": 30_000}}  # fmt: skip


def governed_client(harness, tmp_path, transport):
    return GovernedAnthropic(
        harness.agent_id,
        mode="live",
        settings=Settings(_env_file=None),
        transport=transport,
        store=FixtureStore(tmp_path / "fx"),
        prices=Prices({"claude-haiku-5-5": {"input_per_mtok": 0.1, "output_per_mtok": 0.5}}),
        hooks=[GovernanceHook(harness.gateway.engine, harness.gateway.audit)],
    )


async def test_rt21_token_cap_blocks_the_next_model_call_and_is_audited(harness, tmp_path):
    transport = FakeTransport()
    client = governed_client(harness, tmp_path, transport)
    message = [{"role": "user", "content": "hi"}]
    client.create(model="claude-haiku-5-5", messages=message, run_id=harness.run_id)
    client.create(model="claude-haiku-5-5", messages=message, run_id=harness.run_id)  # 300k used
    with pytest.raises(BudgetExceeded, match="max_tokens_per_session=200000"):
        client.create(model="claude-haiku-5-5", messages=message, run_id=harness.run_id)
    assert transport.calls == 2  # the third call never reached the model
    blocked = json.loads(events(harness, "model_call_blocked")[0].payload_json)
    assert blocked["reason"].startswith("budget_exceeded")
    assert len(events(harness, "model_call")) == 2
    other_run = harness.gateway.registry.start_run(harness.agent_id)
    client.create(model="claude-haiku-5-5", messages=message, run_id=other_run)  # per session


async def test_daily_cost_cap_blocks_model_calls(harness, tmp_path):
    store = harness.gateway.policies
    text = store.active_row(harness.agent_id).content_yaml
    store.activate(
        harness.agent_id,
        text.replace("max_cost_usd_per_day: 5.0", "max_cost_usd_per_day: 0.01"),
        created_by="approver",
    )
    transport = FakeTransport()
    client = governed_client(harness, tmp_path, transport)
    message = [{"role": "user", "content": "hi"}]
    client.create(model="claude-haiku-5-5", messages=message, run_id=harness.run_id)  # $0.027
    with pytest.raises(BudgetExceeded, match="max_cost_usd_per_day"):
        client.create(model="claude-haiku-5-5", messages=message, run_id=harness.run_id)


async def test_kill_switch_blocks_model_calls_too(harness, tmp_path):
    transport = FakeTransport()
    client = governed_client(harness, tmp_path, transport)
    harness.gateway.killswitch.kill(harness.agent_id, reason="stop", actor="approver")
    with pytest.raises(KillSwitchActive):
        client.create(model="claude-haiku-5-5", messages=[{"role": "user", "content": "hi"}])
    assert transport.calls == 0
