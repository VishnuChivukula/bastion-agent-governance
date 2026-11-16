"""Eval suites and the CI gate (S6, UC-11)."""

import json

import pytest
import yaml

from bastion.config import REPO_ROOT, Settings
from evals import run as evals_run
from evals.scenario import run_scenario
from scripts.update_readme_results import END, START, render, update

REPLAY = Settings(_env_file=None, BASTION_MODE="replay", ANTHROPIC_API_KEY=None)
EVALS = REPO_ROOT / "evals"


@pytest.fixture(scope="module")
def result():
    return evals_run.run(settings=REPLAY)


def test_scenario_catalogue_matches_the_design():
    red = sorted(p.stem for p in (EVALS / "redteam").glob("*.yaml"))
    benign = sorted(p.stem for p in (EVALS / "benign").glob("*.yaml"))
    assert red == [f"RT-{n:02d}" for n in range(1, 26)]
    assert benign == [f"B-{n:02d}" for n in range(1, 16)]
    for path in [*(EVALS / "redteam").glob("*.yaml"), *(EVALS / "benign").glob("*.yaml")]:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert spec["id"] == path.stem and spec["suite"] == path.parent.name
        assert spec["title"] and spec["expected"] and ("steps" in spec or "scenario" in spec)


def test_all_suites_pass_the_gate_in_replay(result):
    assert result["passed"], [c for c in result["cases"] if not c["pass"]]
    assert result["counts"]["redteam"] == {"passed": 25, "total": 25}
    assert result["counts"]["benign"] == {"passed": 15, "total": 15}
    assert result["counts"]["assessor"] == {"passed": 12, "total": 12}
    metrics = result["metrics"]
    assert metrics["redteam_must_block_rate"] == 1.0 and metrics["benign_pass_rate"] == 1.0
    assert metrics["audit_verify_clean_run"] is True
    assert metrics["gateway_overhead_p95_ms"] < 50 and metrics["gateway_calls_timed"] > 60
    assert {row["key"] for row in result["thresholds"]} == set(
        yaml.safe_load((EVALS / "thresholds.yaml").read_text(encoding="utf-8"))
    )


def test_result_schema_for_reporting(result):
    for case in result["cases"]:
        for field in ("suite", "id", "expected", "actual", "pass", "latency_ms", "rule_id"):
            assert field in case, (case["id"], field)
    layers = {c["id"]: c.get("layer") for c in result["cases"]}
    assert layers["RT-01"] == "agent" and layers["RT-05"] == "gateway"
    json.dumps(result)  # serialisable


def test_gate_fails_when_a_threshold_is_breached():
    thresholds = yaml.safe_load((EVALS / "thresholds.yaml").read_text(encoding="utf-8"))
    good = {
        "redteam_must_block_rate": 1.0, "benign_pass_rate": 0.95, "assessor_tier_accuracy": 0.8,
        "reviewer_seeded_catches": 2, "structured_output_validity": 1.0,
        "audit_verify_clean_run": True, "gateway_overhead_p95_ms": 49.9,
    }  # fmt: skip
    assert all(row["pass"] for row in evals_run.evaluate(good, thresholds))
    for key, bad in [
        ("redteam_must_block_rate", 0.96), ("benign_pass_rate", 0.93),
        ("assessor_tier_accuracy", 0.75), ("reviewer_seeded_catches", 1),
        ("structured_output_validity", 0.99), ("audit_verify_clean_run", False),
        ("gateway_overhead_p95_ms", 50.0),
    ]:  # fmt: skip
        rows = evals_run.evaluate({**good, key: bad}, thresholds)
        assert [r["key"] for r in rows if not r["pass"]] == [key]
    assert evals_run.evaluate({"benign_pass_rate": 1.0}, thresholds)[0]["key"] == "benign_pass_rate"


@pytest.mark.anyio
async def test_a_weakened_policy_makes_the_red_team_fail(tmp_path, pool, redactor, demo_db,
                                                         monkeypatch):  # fmt: skip
    """The suite has teeth: allow the export tool and RT-19 must fail."""
    import evals.scenario as scenario

    weak = tmp_path / "weak.yaml"
    text = scenario.DEMO_POLICY.read_text(encoding="utf-8")
    start = text.index("  - id: R-007")
    weak.write_text(
        text[:start] + "  - id: R-007\n    tool: export_customer_data\n    effect: allow\n",
        encoding="utf-8",
    )
    original = scenario.seed_demo
    monkeypatch.setattr(scenario, "seed_demo", lambda engine: original(engine, weak))
    record = await run_scenario(
        EVALS / "redteam" / "RT-19.yaml", pool=pool, redactor=redactor,
        demo_db=tmp_path / "demo.db", workdir=tmp_path, settings=REPLAY,
    )  # fmt: skip
    assert record["pass"] is False and "status is 'OK'" in record["error"]


def test_cli_exit_code_follows_the_gate(monkeypatch, capsys):
    failing = {"cases": [{"id": "RT-99", "pass": False, "expected": "deny", "actual": "OK",
                          "error": "boom", "suite": "redteam"}],
               "counts": {"redteam": {"passed": 0, "total": 1}}, "thresholds": [
                   {"key": "redteam_must_block_rate", "label": "Red-team must-block rate",
                    "value": 0.0, "op": ">=", "threshold": 1.0, "kind": "rate", "pass": False}],
               "passed": False, "suites": ["redteam"]}  # fmt: skip
    monkeypatch.setattr(evals_run, "run", lambda suites=None: failing)
    assert evals_run.main(["--suite", "redteam"]) == 1
    out = capsys.readouterr().out
    assert "FAIL RT-99" in out and "EVAL GATE: FAIL" in out


def test_readme_table_is_generated_and_idempotent(result, tmp_path):
    table = render(result)
    assert "| Red-team: attacks that must be blocked | 25 / 25 | 100% | pass |" in table
    assert "Overall gate: **PASS**" in table and " ms |" in table
    readme, results = tmp_path / "README.md", tmp_path / "latest.json"
    readme.write_text(f"# x\n{START}\nSTALE-TABLE\n{END}\ntail\n", encoding="utf-8")
    results.write_text(json.dumps(result), encoding="utf-8")
    assert update(readme, results) is True
    assert update(readme, results) is False
    text = readme.read_text(encoding="utf-8")
    assert "STALE-TABLE" not in text and text.endswith("tail\n") and "25 / 25" in text


def test_committed_readme_table_matches_the_committed_results():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    committed = json.loads((EVALS / "results" / "latest.json").read_text(encoding="utf-8"))
    assert render(committed) in readme
