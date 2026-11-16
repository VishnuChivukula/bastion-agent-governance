import json
import threading

import pytest
from typer.testing import CliRunner

from bastion.audit.log import GENESIS_HASH, AuditLog
from bastion.audit.verify import verify_chain
from bastion.cli import app
from bastion.config import get_settings


def fill(engine, n=5):
    log = AuditLog(engine)
    for i in range(n):
        log.append("tool_decision", actor="loan-ops-agent", agent_id="loan-ops-agent",
                   payload={"i": i, "tool": "lookup_customer"})  # fmt: skip
    return log


def test_chain_links_and_verifies(engine):
    log = fill(engine)
    events = log.events(newest_first=False)
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[0].prev_hash == GENESIS_HASH
    assert all(b.prev_hash == a.hash for a, b in zip(events, events[1:], strict=False))
    result = verify_chain(engine)
    assert result.ok and result.events == 5 and result.head_hash == events[-1].hash


def test_empty_log_verifies(engine):
    result = verify_chain(engine)
    assert result.ok and result.events == 0


def run_sql(engine, sql):
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


@pytest.mark.parametrize(
    ("sql", "seq", "reason"),
    [
        ("UPDATE audit_events SET payload_json = '{\"i\":99}' WHERE seq = 3", 3, "modified"),
        ("UPDATE audit_events SET actor = 'someone-else' WHERE seq = 2", 2, "modified"),
        ("UPDATE audit_events SET event_type = 'harmless' WHERE seq = 4", 4, "modified"),
        ("UPDATE audit_events SET ts = '2020-01-01T00:00:00+00:00' WHERE seq = 1", 1, "modified"),
        ("UPDATE audit_events SET payload_json = 'not json' WHERE seq = 5", 5, "modified"),
        ("DELETE FROM audit_events WHERE seq = 3", 3, "sequence gap"),
        ("DELETE FROM audit_events WHERE seq = 1", 1, "sequence gap"),
        ("UPDATE audit_events SET hash = 'f00d' WHERE seq = 2", 2, "modified"),
        ("UPDATE audit_events SET prev_hash = 'f00d' WHERE seq = 4", 4, "prev_hash"),
    ],
)
def test_rt24_tampering_is_detected_at_the_first_broken_event(engine, sql, seq, reason):
    fill(engine)
    run_sql(engine, sql)
    result = verify_chain(engine)
    assert not result.ok
    assert result.first_broken_seq == seq
    assert reason in result.reason


def test_reordering_is_detected(engine):
    fill(engine)
    for sql in (
        "UPDATE audit_events SET seq = 99 WHERE seq = 2",
        "UPDATE audit_events SET seq = 2 WHERE seq = 3",
        "UPDATE audit_events SET seq = 3 WHERE seq = 99",
    ):
        run_sql(engine, sql)
    result = verify_chain(engine)
    assert not result.ok and result.first_broken_seq == 2


def test_recomputing_one_hash_still_breaks_the_next_link(engine):
    """An attacker who edits an event and fixes its own hash is caught at the following event."""
    from bastion.audit.log import event_body, event_hash

    log = fill(engine)
    target = log.events(newest_first=False)[2]
    forged = event_hash(
        target.prev_hash,
        event_body(target.seq, target.ts, target.actor, target.event_type, target.agent_id,
                   {"i": 99}),
    )  # fmt: skip
    run_sql(engine, "UPDATE audit_events SET payload_json = '{\"i\":99}', "
                    f"hash = '{forged}' WHERE seq = 3")  # fmt: skip
    result = verify_chain(engine)
    assert not result.ok and result.first_broken_seq == 4


def test_concurrent_appends_keep_one_unbroken_chain(engine):
    log = AuditLog(engine)
    errors = []

    def worker(n):
        try:
            for i in range(20):
                log.append("tool_decision", actor=f"agent-{n}", payload={"i": i})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    result = verify_chain(engine)
    assert result.ok and result.events == 120


def test_events_filter_and_payload_round_trip(engine):
    log = AuditLog(engine)
    log.append("policy_activated", actor="approver", agent_id="a", payload={"note": "naïve ✓"})
    log.append("tool_decision", actor="a", agent_id="b")
    assert [e.event_type for e in log.events(agent_id="a")] == ["policy_activated"]
    assert (
        json.loads(log.events(event_type="policy_activated")[0].payload_json)["note"] == "naïve ✓"
    )
    assert len(log.events(limit=1)) == 1
    assert verify_chain(engine).ok


def test_cli_verify_audit_exit_codes(engine, tmp_path, monkeypatch):  # UC-10
    fill(engine)
    monkeypatch.setenv("BASTION_DB_PATH", str(tmp_path / "bastion.db"))
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        clean = CliRunner().invoke(app, ["verify-audit"])
        assert clean.exit_code == 0 and "OK: 5 events" in clean.output
        run_sql(engine, "UPDATE audit_events SET actor = 'x' WHERE seq = 2")
        broken = CliRunner().invoke(app, ["verify-audit"])
        assert broken.exit_code == 1 and "BROKEN at seq 2" in broken.output
    finally:
        get_settings.cache_clear()
