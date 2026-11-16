"""Console smoke tests: every page renders against a real API, and the main clicks work (S4)."""

import pytest
from streamlit.testing.v1 import AppTest

from bastion.config import REPO_ROOT
from bastion.console.client import Api, ApiError
from bastion.console.format import clock, describe, short_hash
from tests.apiserver import PASSCODE, ApiServer

APP = str(REPO_ROOT / "src" / "bastion" / "console" / "app.py")
PAGES = ["overview", "run_scenario", "live_activity", "approvals", "incidents", "registry",
         "policies"]  # fmt: skip


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with ApiServer(tmp_path_factory.mktemp("console")) as api:
        api.run("uc03")  # leaves a denial, an open incident and a killed agent
        yield api


def open_page(server, page, monkeypatch, passcode=None) -> AppTest:
    monkeypatch.setenv("BASTION_API_URL", server.url)
    monkeypatch.setenv("BASTION_CONSOLE_START_PAGE", page)
    at = AppTest.from_file(APP, default_timeout=60)
    if passcode:
        at.session_state["passcode"] = passcode
        at.session_state["actor"] = "approver@bank.example"
    at.run()
    assert not at.exception, at.exception
    return at


def text_of(at: AppTest) -> str:
    parts = []
    for kind in ("title", "subheader", "markdown", "caption", "info", "success", "error",
                 "warning", "code"):  # fmt: skip
        parts += [str(element.value) for element in getattr(at, kind)]
    return "\n".join(parts)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_banner_and_disclaimer(server, page, monkeypatch):
    at = open_page(server, page, monkeypatch)
    text = text_of(at)
    assert "REPLAY mode" in text
    assert "Reference implementation; not production; not legal advice." in text
    assert not at.error or page in ("overview", "registry")  # killed-agent notices only


def test_overview_shows_integrity_and_decisions(server, monkeypatch):
    at = open_page(server, "overview", monkeypatch)
    assert any("hash chain verified" in s.value for s in at.success)
    metrics = {m.label: m.value for m in at.metric}
    assert int(metrics["Denied"]) >= 1 and int(metrics["Open incidents"]) == 1
    assert metrics["Agents killed"] == "1"


def test_mutating_controls_are_hidden_without_the_passcode(server, monkeypatch):
    at = open_page(server, "registry", monkeypatch)
    assert not at.button
    assert any("Enter the passcode" in c.value for c in at.caption)


def test_registry_reactivate_needs_a_reason_then_works(server, monkeypatch):
    at = open_page(server, "registry", monkeypatch, PASSCODE)
    assert any("KILLED" in m.value for m in at.markdown)
    at.button(key="reactivate-loan-ops-agent").click().run()
    assert any("Reactivate failed" in e.value for e in at.error)
    at.text_input(key="re-loan-ops-agent").set_value("Poisoned note removed.")
    at.button(key="reactivate-loan-ops-agent").click().run()
    assert server.anon.get("/agents/loan-ops-agent").json()["status"] == "active"
    event = server.anon.get("/audit/events", params={"event_type": "killswitch_reactivated"})
    assert event.json()[0]["actor"] == "approver@bank.example"


def test_incident_can_be_acknowledged_from_the_console(server, monkeypatch):
    at = open_page(server, "incidents", monkeypatch, PASSCODE)
    number = server.anon.get("/incidents").json()[0]["id"]
    at.text_input(key=f"note-{number}").set_value("Looking into it.")
    at.button(key=f"advance-{number}").click().run()
    assert server.anon.get("/incidents").json()[0]["status"] == "acknowledged"


def test_run_scenario_page_starts_a_run_and_shows_the_timeline(server, monkeypatch):
    at = open_page(server, "run_scenario", monkeypatch)
    at.button[0].click().run()  # UC-02 is selected by default
    run_id = at.session_state["run_id"]
    server.wait(run_id)
    at.run()
    text = text_of(at)
    assert "Completed" in text and "R-001" in text
    assert at.chat_message  # the agent's summary


def test_approval_from_the_run_page_resumes_the_run(server, monkeypatch):
    paused = server.run("uc04", approver="human", until=("interrupted", "failed"))
    at = open_page(server, "approvals", monkeypatch, PASSCODE)
    approval = paused["pending"][0]["id"]
    assert any(approval in m.value for m in at.markdown)
    at.text_input(key=f"reason-{approval}").set_value("Ref 8812 checked.")
    at.button(key=f"Approve-{approval}").click().run()
    assert server.wait(paused["id"])["status"] == "completed"
    assert server.anon.get(f"/approvals/{approval}").json()["status"] == "consumed"


def test_policies_page_shows_the_policy_in_force(server, monkeypatch):
    at = open_page(server, "policies", monkeypatch, PASSCODE)
    assert any("R-007" in c.value for c in at.code)
    assert any("In force: version" in s.value for s in at.success)
    assert at.text_area  # the editor is offered with the passcode


def test_console_reports_an_unreachable_api(monkeypatch):
    monkeypatch.setenv("BASTION_API_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("Cannot reach the Bastion API" in e.value for e in at.error)
    assert any("not legal advice" in c.value for c in at.caption)


# --- client and formatting -----------------------------------------------------------------------
def test_api_client_errors(server):
    api = Api(server.url)
    with pytest.raises(ApiError) as missing:
        api.get("/agents/nope")
    assert missing.value.status == 404 and "unknown agent" in missing.value.detail
    with pytest.raises(ApiError) as invalid:
        api.passcode = PASSCODE
        api.post("/agents/loan-ops-agent/kill", {"reason": ""})
    assert invalid.value.status == 422 and "reason" in invalid.value.detail


def test_describe_covers_every_event_type_in_a_real_log(server):
    events = server.anon.get("/audit/events", params={"limit": 1000}).json()
    kinds = {e["event_type"] for e in events}
    assert {"tool_decision", "incident_opened", "killswitch_activated", "model_call"} <= kinds
    for event in events:
        icon, text = describe(event)
        assert icon and text and "None" not in text, (event["event_type"], text)
    deny = next(e for e in events if e["payload"].get("status") == "DENIED")
    assert describe(deny)[0] == "🔴" and "category exfiltration" in describe(deny)[1]
    assert describe({"event_type": "something_new", "payload": {}}) == ("•", "something new")
    assert short_hash(None) == "-" and short_hash("abcdef", 3) == "abc…"
    assert clock("2026-11-16T10:11:12.000000+00:00") == "10:11:12"


def test_registry_shows_the_classification_record(server, monkeypatch):
    at = open_page(server, "registry", monkeypatch)
    text = text_of(at)
    assert "Assessor proposes" in text and "Reviewer" in text and "[VERIFY]" in text
    assert any("Signed off as **high**" in s.value for s in at.success)


def test_register_and_sign_off_from_the_console(server, monkeypatch):
    at = open_page(server, "registry", monkeypatch, PASSCODE)
    labels = [b.label for b in at.button]
    assert "Submit card and classify" in labels
    at.selectbox[0].set_value("Code Review Assistant · code-review-agent").run()
    next(b for b in at.button if b.label == "Submit card and classify").click().run()
    record = server.anon.get("/registry/agents/code-review-agent").json()
    assert record["status"] == "awaiting_signoff" and record["proposed_tier"] == "minimal"
    at.button(key="signoff-code-review-agent").click().run()
    assert server.anon.get("/agents/code-review-agent").json()["status"] == "active"
    assert any("shown once" in w.value for w in at.warning)
    assert at.code  # the token
