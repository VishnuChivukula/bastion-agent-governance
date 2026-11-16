"""Control-plane API end to end: a real server, the gateway mounted at /mcp, replay mode (S4)."""

import sqlite3

import pytest
import yaml

from bastion.config import REPO_ROOT
from tests.apiserver import ApiServer

AGENT = "loan-ops-agent"
SEED_POLICY = (REPO_ROOT / "policies" / "loan-ops-agent.yaml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    with ApiServer(tmp_path_factory.mktemp("api")) as server:
        yield server


@pytest.fixture(scope="module")
def locked(tmp_path_factory):
    """A public deployment with no passcode configured."""
    with ApiServer(tmp_path_factory.mktemp("locked"), passcode=None) as server:
        yield server


# --- meta, read-only routes ----------------------------------------------------------------------
def test_healthz_meta_and_openapi(api):
    assert api.anon.get("/healthz").json() == {"status": "ok"}
    meta = api.anon.get("/meta").json()
    assert meta["mode"] == "replay" and meta["mutations_enabled"] is True
    assert "not legal advice" in meta["disclaimer"]
    paths = api.anon.get("/openapi.json").json()["paths"]
    assert "/approvals/{approval_id}/decision" in paths and "/runs" in paths


def test_agent_is_seeded_with_policy(api):
    agents = api.anon.get("/agents").json()
    assert [a["id"] for a in agents] == [AGENT]
    agent = api.anon.get(f"/agents/{AGENT}").json()
    assert agent["tier"] == "high" and agent["policy_version"] >= 1 and agent["policy_hash"]
    assert "token_hash" not in agent
    assert api.anon.get("/agents/nope").status_code == 404


def test_scenarios_listed(api):
    listed = api.anon.get("/scenarios").json()
    assert [s["id"] for s in listed] == ["uc02", "uc03", "uc04", "uc05", "uc06", "uc07"]
    assert {s["id"] for s in listed if s["needs_approval"]} == {"uc04", "uc05"}


def test_evidence_route_is_honest_about_not_existing_yet(api):
    assert api.anon.get(f"/agents/{AGENT}/evidence").status_code in (200, 501)


# --- passcode guard ------------------------------------------------------------------------------
MUTATIONS = [
    ("/agents/loan-ops-agent/kill", {"reason": "x"}),
    ("/agents/loan-ops-agent/reactivate", {"reason": "x"}),
    ("/killswitch/global/kill", {"reason": "x"}),
    ("/killswitch/global/reactivate", {"reason": "x"}),
    ("/approvals/APR-0000000000/decision", {"approve": True, "reason": "x"}),
    ("/incidents/1/advance", {"status": "acknowledged", "note": "x"}),
    ("/agents/loan-ops-agent/policies", {"content_yaml": "agent: loan-ops-agent"}),
]


@pytest.mark.parametrize(("path", "body"), MUTATIONS)
def test_mutations_need_the_passcode(api, path, body):
    assert api.anon.post(path, json=body).status_code == 401
    wrong = api.anon.post(path, json=body, headers={"X-Bastion-Passcode": "test-passcodf"})
    assert wrong.status_code == 401


@pytest.mark.parametrize(("path", "body"), MUTATIONS)
def test_mutations_are_disabled_without_a_configured_passcode(locked, path, body):
    for headers in ({}, {"X-Bastion-Passcode": ""}, {"X-Bastion-Passcode": "bastion-local"}):
        assert locked.anon.post(path, json=body, headers=headers).status_code == 403
    assert locked.anon.get("/meta").json()["mutations_enabled"] is False


def test_rejected_passcodes_are_audited(api):
    api.anon.post("/killswitch/global/kill", json={"reason": "x"})
    events = api.anon.get("/audit/events", params={"event_type": "passcode_rejected"}).json()
    assert events and events[0]["actor"] == "anonymous"


def test_local_dev_passcode_only_with_the_flag(tmp_path):
    from bastion.config import LOCAL_DEV_PASSCODE, Settings

    assert Settings(_env_file=None, BASTION_PASSCODE=None).effective_passcode is None
    dev = Settings(_env_file=None, BASTION_PASSCODE=None, BASTION_LOCAL_DEV=True)
    assert dev.effective_passcode == LOCAL_DEV_PASSCODE
    own = Settings(_env_file=None, BASTION_PASSCODE="mine", BASTION_LOCAL_DEV=True)
    assert own.effective_passcode == "mine"


def test_gateway_is_mounted_and_needs_an_agent_token(api):
    response = api.anon.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    assert api.anon.get("/not-a-route").status_code == 404


# --- scenarios through the API -------------------------------------------------------------------
def test_uc02_runs_without_a_passcode_in_replay(locked):
    detail = locked.run("uc02")
    assert detail["status"] == "completed" and detail["final_text"]
    assert any("ALLOW" in line and "R-001" in line for line in detail["timeline"])
    assert detail["title"] and detail["error"] is None


def test_uc03_denied_incident_and_kill(api):
    detail = api.run("uc03")
    assert detail["status"] == "halted"
    assert any("DENY" in line and "R-007" in line for line in detail["timeline"])
    agent = api.anon.get(f"/agents/{AGENT}").json()
    assert agent["status"] == "killed" and agent["killed_by"] == AGENT
    incidents = api.anon.get("/incidents", params={"agent_id": AGENT}).json()
    assert incidents[0]["rule_id"] == "IR-2" and incidents[0]["status"] == "open"
    assert api.anon.get("/overview").json()["agents_killed"] == 1

    # incident lifecycle through the API, then reactivation with a reason
    number = incidents[0]["id"]
    step = api.admin.post(
        f"/incidents/{number}/advance", json={"status": "acknowledged", "note": "Seen."}
    )
    assert step.status_code == 200 and step.json()["notes"][0]["actor"] == "approver@bank.example"
    back = api.admin.post(f"/incidents/{number}/advance", json={"status": "acknowledged",
                                                                 "note": "again"})  # fmt: skip
    assert back.status_code == 409
    gone = api.admin.post("/incidents/9999/advance", json={"status": "resolved", "note": "x"})
    assert gone.status_code == 404
    assert api.admin.post(f"/agents/{AGENT}/reactivate", json={"reason": ""}).status_code == 422
    done = api.admin.post(f"/agents/{AGENT}/reactivate", json={"reason": "Note reviewed."})
    assert done.status_code == 200
    assert api.anon.get(f"/agents/{AGENT}").json()["status"] == "active"
    assert api.admin.post(f"/agents/{AGENT}/reactivate", json={"reason": "x"}).status_code == 409


def test_uc04_human_approval_resumes_the_run(api):
    paused = api.run("uc04", approver="human", until=("interrupted", "failed"))
    assert paused["status"] == "interrupted" and len(paused["pending"]) == 1
    approval = paused["pending"][0]
    assert approval["tool"] == "update_credit_limit" and approval["args"]["new_limit"] == 60000
    assert (
        api.anon.get("/approvals", params={"status": "pending"}).json()[0]["id"] == approval["id"]
    )
    assert api.anon.get("/overview").json()["pending_approvals"] == 1

    no_reason = api.admin.post(
        f"/approvals/{approval['id']}/decision", json={"approve": True, "reason": ""}
    )
    assert no_reason.status_code == 422
    decided = api.admin.post(
        f"/approvals/{approval['id']}/decision",
        json={"approve": True, "reason": "Ref 8812 checked."},
    )
    assert decided.status_code == 200 and decided.json()["run_resumed"] == paused["id"]
    assert decided.json()["approval"]["decided_by"] == "approver@bank.example"

    detail = api.wait(paused["id"])
    assert detail["status"] == "completed" and detail["pending"] == []
    kinds = [e["type"] for e in detail["events"]]
    assert kinds.count("grant_consumed") == 1
    final = api.anon.get(f"/approvals/{approval['id']}").json()
    assert final["status"] == "consumed" and final["args_hash"]
    again = api.admin.post(
        f"/approvals/{approval['id']}/decision", json={"approve": True, "reason": "twice"}
    )
    assert again.status_code == 409
    limit = sqlite3.connect(api.state.demo_db).execute(
        "select credit_limit from customers where id = 'C-0021'"
    ).fetchone()[0]  # fmt: skip
    assert limit == 60000


def test_uc04_rejection_ends_the_run_without_executing(api):
    paused = api.run("uc04", approver="human", until=("interrupted", "failed"))
    approval = paused["pending"][0]
    api.admin.post(
        f"/approvals/{approval['id']}/decision", json={"approve": False, "reason": "No evidence."}
    )
    detail = api.wait(paused["id"])
    assert detail["status"] == "completed" and "no recorded model response" in detail["final_text"]
    assert not [e for e in detail["events"] if e["type"] == "grant_consumed"]
    limit = sqlite3.connect(api.state.demo_db).execute(
        "select credit_limit from customers where id = 'C-0021'"
    ).fetchone()[0]  # fmt: skip
    assert limit == 40000


def test_uc05_swap_with_a_human_approver(api):
    paused = api.run("uc05", approver="human", until=("interrupted", "failed"))
    first = paused["pending"][0]
    api.admin.post(f"/approvals/{first['id']}/decision", json={"approve": True, "reason": "60k ok"})
    detail = api.wait(paused["id"])
    assert detail["status"] == "completed"
    assert api.anon.get(f"/approvals/{first['id']}").json()["status"] == "approved"  # unused
    swapped = [a for a in api.anon.get("/approvals", params={"status": "pending"}).json()]
    assert len(swapped) == 1 and swapped[0]["args"]["new_limit"] == 600000
    assert swapped[0]["args_hash"] != first["args_hash"]


def test_uc05_uc06_uc07_scripted(api):
    assert api.run("uc05")["status"] == "completed"
    budget = api.run("uc06")
    assert any("budget_exceeded" in line for line in budget["timeline"])
    usage = api.anon.get(f"/agents/{AGENT}/usage").json()
    assert usage["max_tool_calls_per_session"] == 30
    assert usage["sessions"][0]["run_id"] == budget["id"]
    assert usage["sessions"][0]["tool_calls"] == 30 and usage["tokens_today"] > 0
    killed = api.run("uc07")
    assert killed["status"] == "halted"
    assert any("KILL SWITCH" in line for line in killed["timeline"])


def test_kill_revokes_pending_and_halts_the_parked_run(api):
    paused = api.run("uc04", approver="human", until=("interrupted", "failed"))
    killed = api.admin.post(f"/agents/{AGENT}/kill", json={"reason": "Drill."})
    assert killed.status_code == 200
    body = killed.json()
    assert body["revoked_approvals"] == [paused["pending"][0]["id"]]
    assert body["halted_runs"] == [paused["id"]]
    assert api.anon.get(f"/runs/{paused['id']}").json()["status"] == "halted"
    switches = {s["scope"]: s for s in api.anon.get("/killswitch").json()}
    assert switches[AGENT]["active"] and switches[AGENT]["actor"] == "approver@bank.example"
    # the next scenario run resets the demo, so the agent can act again
    assert api.run("uc02")["status"] == "completed"


def test_global_kill_and_reactivate(api):
    assert api.admin.post("/killswitch/global/kill", json={"reason": "Drill."}).status_code == 200
    assert api.anon.get("/overview").json()["global_kill"] is True
    assert api.anon.get(f"/agents/{AGENT}").json()["killed_by"] == "global"
    ok = api.admin.post("/killswitch/global/reactivate", json={"reason": "Drill over."})
    assert ok.status_code == 200
    assert api.anon.get("/overview").json()["global_kill"] is False


def test_unknown_scenario_and_run(api):
    assert api.anon.post("/runs", json={"scenario": "uc99"}).status_code == 404
    assert api.anon.get("/runs/run-nope").status_code == 404
    assert api.anon.get("/approvals/APR-nope").status_code == 404
    gone = api.admin.post("/approvals/APR-nope/decision", json={"approve": True, "reason": "x"})
    assert gone.status_code == 404
    assert api.anon.get("/runs").json()[0]["scenario"]


# --- policies (UC-08) ----------------------------------------------------------------------------
def test_policy_change_new_version_diff_and_decisions_use_the_new_hash(api):
    before = api.anon.get(f"/agents/{AGENT}/policies").json()
    edited = SEED_POLICY.replace("args.new_limit > 50000", "args.new_limit > 30000").replace(
        'version_note: "', 'version_note: "lower approval threshold; '
    )
    assert edited != SEED_POLICY
    created = api.admin.post(f"/agents/{AGENT}/policies", json={"content_yaml": edited})
    assert created.status_code == 201
    new = created.json()
    assert new["version"] == before[0]["version"] + 1 and new["active"]
    assert new["content_hash"] != before[0]["content_hash"]
    assert new["created_by"] == "approver@bank.example"
    assert "lower approval threshold" in new["version_note"]

    versions = api.anon.get(f"/agents/{AGENT}/policies").json()
    assert [v["active"] for v in versions[:2]] == [True, False]  # the old version is retained
    old = api.anon.get(f"/agents/{AGENT}/policies/{before[0]['version']}").json()
    assert old["content_yaml"] == SEED_POLICY
    diff = api.anon.get(
        f"/agents/{AGENT}/policies/diff",
        params={"from_version": old["version"], "to_version": new["version"]},
    ).json()
    assert (
        "-" in diff["diff"] and "30000" in diff["diff"] and diff["to_hash"] == new["content_hash"]
    )

    api.run("uc02")
    decision = api.anon.get("/audit/events", params={"event_type": "tool_decision",
                                                     "limit": 1}).json()[0]  # fmt: skip
    assert decision["payload"]["policy_hash"] == new["content_hash"]

    same = api.admin.post(f"/agents/{AGENT}/policies", json={"content_yaml": edited})
    assert same.status_code == 409
    restored = api.admin.post(f"/agents/{AGENT}/policies", json={"content_yaml": SEED_POLICY})
    assert restored.status_code == 201 and restored.json()["content_hash"] == old["content_hash"]


@pytest.mark.parametrize(
    "bad",
    [
        "not: [valid",
        "agent: someone-else\nrules: []",
        yaml.safe_dump(
            {
                "agent": AGENT,
                "rules": [{"id": "R", "tool": "t", "effect": "allow", "when": "__import__('os')"}],
            }
        ),  # fmt: skip
    ],
)
def test_invalid_policies_are_rejected_and_never_stored(api, bad):
    count = len(api.anon.get(f"/agents/{AGENT}/policies").json())
    assert (
        api.admin.post(f"/agents/{AGENT}/policies", json={"content_yaml": bad}).status_code == 422
    )
    assert len(api.anon.get(f"/agents/{AGENT}/policies").json()) == count
    assert api.anon.get(f"/agents/{AGENT}/policies/999").status_code == 404


# --- audit ---------------------------------------------------------------------------------------
def test_audit_events_filter_and_verify(api):
    events = api.anon.get("/audit/events", params={"limit": 5}).json()
    assert len(events) == 5 and events[0]["seq"] > events[-1]["seq"]
    newer = api.anon.get("/audit/events", params={"after_seq": events[1]["seq"]}).json()
    assert [e["seq"] for e in newer] == [events[0]["seq"]]
    only = api.anon.get("/audit/events", params={"agent_id": AGENT, "event_type": "model_call"})
    assert {e["event_type"] for e in only.json()} == {"model_call"}
    check = api.anon.get("/audit/verify").json()
    assert check["ok"] and check["events"] >= events[0]["seq"]
    overview = api.anon.get("/overview").json()
    assert overview["audit_ok"] and overview["decisions"]["OK"] > 0 and overview["redactions"] > 0
    assert overview["overhead_p95_ms"] is not None


def test_tampering_shows_up_in_verify_and_overview(tmp_path):
    with ApiServer(tmp_path) as server:
        server.run("uc02")
        with sqlite3.connect(tmp_path / "bastion.db") as conn:
            conn.execute("update audit_events set actor = 'someone-else' where seq = 3")
        check = server.anon.get("/audit/verify").json()
        assert check["ok"] is False and check["first_broken_seq"] == 3
        overview = server.anon.get("/overview").json()
        assert overview["audit_ok"] is False and overview["audit_first_broken_seq"] == 3


def test_a_second_run_is_refused_while_one_is_in_progress(tmp_path):
    with ApiServer(tmp_path) as server:
        first = server.anon.post("/runs", json={"scenario": "uc06"})
        second = server.anon.post("/runs", json={"scenario": "uc02"})
        assert first.status_code == 202 and second.status_code == 409
        assert server.wait(first.json()["id"])["status"] in ("completed", "halted")
