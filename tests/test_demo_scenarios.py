"""The six demo scenarios end to end in replay: agent → gateway → tools, no API key (S2/S3 DoD)."""

import json
import sqlite3

import pytest

from bastion.config import REPO_ROOT, Settings
from demo.loan_ops_agent.run import DemoEnvironment, run_all
from demo.loan_ops_agent.scenarios import BY_ID, SCENARIOS

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
async def results(anyio_backend):
    settings = Settings(_env_file=None, BASTION_MODE="replay", ANTHROPIC_API_KEY=None)
    assert not settings.has_api_key
    return {r.scenario.id: r for r in await run_all([], settings)}


def of_type(result, kind):
    return [e for e in result.events if e["type"] == kind]


def decisions(result):
    return [(e["tool"], e["status"], e["rule_id"]) for e in of_type(result, "tool_decision")]


async def test_all_six_scenarios_ran(results):
    assert list(results) == [s.id for s in SCENARIOS] == ["uc02", "uc03", "uc04", "uc05", "uc06",
                                                         "uc07"]  # fmt: skip


async def test_uc02_lookup_is_allowed_with_redaction(results):
    result = results["uc02"]
    assert result.status == "completed" and result.final_text
    first = of_type(result, "tool_decision")[0]
    assert (first["tool"], first["effect"], first["rule_id"]) == ("lookup_customer", "allow",
                                                                  "R-001")  # fmt: skip
    assert first["redactions"] == {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1, "IBAN_CODE": 1}
    assert first["overhead_ms"] >= 0
    assert any("ALLOW" in line and "R-001" in line for line in result.timeline)
    assert of_type(result, "model_call")  # model usage is audited too


async def test_uc03_injection_is_denied_opens_incident_and_kills(results):
    result = results["uc03"]
    assert ("export_customer_data", "DENIED", "R-007") in decisions(result)
    deny = [e for e in of_type(result, "tool_decision") if e["status"] == "DENIED"][0]
    assert deny["category"] == "exfiltration"
    incident = of_type(result, "incident_opened")[0]
    assert (incident["rule_id"], incident["severity"]) == ("IR-2", "high")
    kill = of_type(result, "killswitch_activated")[0]
    assert kill["actor"] == "bastion:incident-rule"
    assert result.status == "halted" and "halted by Bastion" in result.final_text


async def test_uc04_approval_pauses_then_identical_call_executes_once(results):
    result = results["uc04"]
    assert result.status == "completed"
    kinds = [e["type"] for e in result.events]
    for kind in ("approval_requested", "approval_decided", "grant_consumed"):
        assert kinds.count(kind) == 1
    statuses = [e["to"] if "to" in e else e.get("status") for e in of_type(result, "run_status")]
    assert statuses == ["interrupted", "running", "completed"]
    updates = [e for e in of_type(result, "tool_decision") if e["tool"] == "update_credit_limit"]
    assert [u["status"] for u in updates] == ["PENDING_APPROVAL", "OK"]
    assert updates[0]["args_hash"] == updates[1]["args_hash"]  # the identical call
    assert of_type(result, "approval_requested")[0]["args_hash"] == updates[0]["args_hash"]
    assert updates[0]["args"]["new_limit"] == 60000
    assert len(result.events) >= 5


async def test_uc05_swapped_arguments_do_not_execute(results):
    result = results["uc05"]
    first, swapped = of_type(result, "tool_decision")
    assert first["status"] == swapped["status"] == "PENDING_APPROVAL"
    assert first["args_hash"] != swapped["args_hash"]
    assert first["approval_id"] != swapped["approval_id"]
    assert not of_type(result, "grant_consumed")
    assert "still 'approved'" in result.final_text


async def test_uc06_budget_stops_the_loop_after_30_calls(results):
    result = results["uc06"]
    outcome = [e for e in of_type(result, "tool_decision")]
    allowed = [e for e in outcome if e["status"] == "OK"]
    denied = [e for e in outcome if e["status"] == "DENIED"]
    assert len(allowed) == 30
    assert denied and all(e["reasons"][-1].startswith("budget_exceeded") for e in denied)
    assert outcome.index(denied[0]) == 30  # call 31 is the first denial
    assert [i["rule_id"] for i in of_type(result, "incident_opened")] == ["IR-1"]
    assert result.status == "completed"


async def test_uc07_kill_switch_halts_the_run(results):
    result = results["uc07"]
    kill = of_type(result, "killswitch_activated")[0]
    assert kill["actor"] == "approver@bank.example" and kill["halted_runs"] == [result.run_id]
    after_kill = [e for e in result.events if e["seq"] > kill["seq"]]
    blocked = [
        e
        for e in after_kill
        if e["type"] == "model_call_blocked"
        or (e["type"] == "tool_decision" and e["reasons"][-1].startswith("killswitch"))
    ]
    assert blocked, "the next call after the kill must be denied"
    assert not [e for e in after_kill if e["type"] == "tool_decision" and e["status"] == "OK"]
    assert result.status == "halted"


async def test_unmasked_pii_never_reached_the_model():
    """Fixtures hold every request sent to the model: redacted fields must not appear in them."""
    fixtures = list((REPO_ROOT / "fixtures" / "llm").glob("*.json"))
    assert fixtures
    for path in fixtures:
        request = json.dumps(json.loads(path.read_text())["request"])
        assert "@example.com" not in request
        assert "+44 20 7946" not in request
        assert "sk-ant-" not in path.read_text()


class ScriptedModel:
    """A fake model: asks for a large limit increase, then summarises whatever came back."""

    def __init__(self):
        self.requests = []

    def create(self, params):
        self.requests.append(params)
        usage = {"input_tokens": 10, "output_tokens": 10}
        if len(self.requests) == 1:
            call = {"type": "tool_use", "id": "tu_1", "name": "update_credit_limit",
                    "input": {"customer_id": "C-0021", "current_limit": 40000, "new_limit": 90000,
                              "reason": "scripted"}}  # fmt: skip
            return {"content": [call], "stop_reason": "tool_use", "usage": usage}
        return {"content": [{"type": "text", "text": "The approver declined the change."}],
                "stop_reason": "end_turn", "usage": usage}  # fmt: skip


async def test_rejected_approval_reaches_the_agent_and_nothing_executes(tmp_path):
    settings = Settings(_env_file=None, BASTION_MODE="replay")
    with DemoEnvironment(tmp_path, settings) as env:
        model = ScriptedModel()
        env.runner.llm_transport = model
        scenario = BY_ID["uc04"]
        paused = await env.runner.start(scenario)
        assert paused.status == "interrupted" and len(paused.pending) == 1
        assert env.gateway.registry.get_agent("loan-ops-agent")  # run is parked, not lost
        approval_id = paused.pending[0]["approval_id"]
        env.gateway.approvals.decide(approval_id, approve=False, decided_by="approver",
                                     reason="Not supported by the documents.")  # fmt: skip
        done = await env.runner.resume(
            scenario, paused.run_id,
            {approval_id: {"approved": False, "reason": "Not supported by the documents."}},
        )  # fmt: skip
        assert done.status == "completed" and "declined" in done.final_text
        tool_result = model.requests[1]["messages"][-1]["content"][0]
        assert json.loads(tool_result["content"]) == {
            "reason": "Not supported by the documents.",
            "status": "REJECTED",
        }
        assert tool_result["is_error"] is True
        con = sqlite3.connect(env.demo_db)
        assert con.execute("SELECT credit_limit FROM customers WHERE id='C-0021'").fetchone() == (
            40000.0,
        )
        con.close()
