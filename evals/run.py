"""Run the eval suites and enforce the thresholds (FR-60, UC-11).

    python -m evals.run            # suites A (red-team), B (benign), C (assessor); exit 1 on breach
    python -m evals.run --suite redteam

Everything runs offline: the gateway layer has no model, and the agent and assessor layers
replay recorded fixtures. Results go to `evals/results/latest.json`.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bastion import __version__
from bastion.audit.verify import verify_chain
from bastion.config import REPO_ROOT, Settings, get_settings
from bastion.gateway.mcp_proxy import DownstreamPool
from bastion.gateway.redaction import get_redactor
from evals import assessor_suite
from evals.scenario import Context, run_scenario

EVALS_DIR = REPO_ROOT / "evals"
RESULTS_PATH = EVALS_DIR / "results" / "latest.json"
SUITES = ("redteam", "benign", "assessor")


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


async def run_gateway_suites(suites: list[str], settings: Settings) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    redactor = get_redactor()
    with tempfile.TemporaryDirectory(prefix="bastion-eval-") as tmp:
        root = Path(tmp)
        demo_db = root / "demo.db"
        pool = DownstreamPool({"BASTION_DEMO_DB": str(demo_db)})
        try:
            warm = Context(root / "warm", pool, redactor, demo_db, settings)
            await warm.call({"tool": "lookup_customer", "args": {"customer_id": "C-0007"}}, None)
            warm.engine.dispose()  # tools server started, analyser loaded: timings are steady
            for suite in suites:
                for path in sorted((EVALS_DIR / suite).glob("*.yaml")):
                    workdir = root / path.stem
                    workdir.mkdir()
                    records.append(
                        await run_scenario(
                            path,
                            pool=pool,
                            redactor=redactor,
                            demo_db=demo_db,
                            workdir=workdir,
                            settings=settings,
                        )  # fmt: skip
                    )
        finally:
            await pool.aclose()
    return records


async def clean_run_verifies(settings: Settings) -> bool:
    """A scenario-free sanity check: an ordinary sequence of calls leaves an intact chain."""
    redactor = get_redactor()
    with tempfile.TemporaryDirectory(prefix="bastion-eval-") as tmp:
        root = Path(tmp)
        pool = DownstreamPool({"BASTION_DEMO_DB": str(root / "demo.db")})
        try:
            context = Context(root, pool, redactor, root / "demo.db", settings)
            for tool, args in (
                ("lookup_customer", {"customer_id": "C-0007"}),
                ("export_customer_data", {"destination": "x@external.example"}),
                ("delete_customer", {}),
            ):
                await context.call({"tool": tool, "args": args}, None)
            ok = verify_chain(context.engine).ok
            context.engine.dispose()
        finally:
            await pool.aclose()
    return ok


def evaluate(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per threshold: value, limit, pass. A metric that was not run is skipped."""
    rules = [
        ("redteam_must_block_rate", "Red-team must-block rate", ">=", "rate"),
        ("benign_pass_rate", "Benign pass rate", ">=", "rate"),
        ("assessor_tier_accuracy", "Assessor tier accuracy", ">=", "rate"),
        ("reviewer_seeded_catches", "Reviewer seeded-error catches", ">=", "count"),
        ("structured_output_validity", "Structured output validity", ">=", "rate"),
        ("audit_verify_clean_run", "Audit verify on a clean run", "==", "bool"),
        ("gateway_overhead_p95_ms", "Gateway overhead p95", "<", "ms"),
    ]
    rows = []
    for key, label, op, kind in rules:
        value = metrics.get(key)
        if value is None:
            continue
        limit = thresholds[key]
        ok = {">=": value >= limit, "==": value == limit, "<": value < limit}[op]
        rows.append({"key": key, "label": label, "value": value, "op": op, "threshold": limit,
                     "kind": kind, "pass": bool(ok)})  # fmt: skip
    return rows


def run(suites: list[str] | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    suites = list(suites or SUITES)
    thresholds = yaml.safe_load((EVALS_DIR / "thresholds.yaml").read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    gateway_suites = [s for s in suites if s in ("redteam", "benign")]
    if gateway_suites:
        records = asyncio.run(run_gateway_suites(gateway_suites, settings))
        latencies = [ms for r in records for ms in r.pop("latencies", [])]
        cases += records
        for suite, key in (("redteam", "redteam_must_block_rate"), ("benign", "benign_pass_rate")):
            mine = [r for r in records if r["suite"] == suite]
            if mine:
                metrics[key] = sum(r["pass"] for r in mine) / len(mine)
        metrics["gateway_overhead_p95_ms"] = round(p95(latencies), 2)
        metrics["gateway_calls_timed"] = len(latencies)
        metrics["audit_verify_clean_run"] = asyncio.run(clean_run_verifies(settings))
    if "assessor" in suites:
        result = assessor_suite.run(settings)
        cases += [
            {"category": "classification", "layer": "agent", "title": "", "latency_ms": None,
             "rule_id": None, "error": None, **case}
            for case in result["cases"]
        ]  # fmt: skip
        metrics["assessor_tier_accuracy"] = result["tier_accuracy"]
        metrics["reviewer_seeded_catches"] = result["reviewer_catches"]
        metrics["reviewer_seeded_total"] = result["reviewer_seeded"]
        metrics["structured_output_validity"] = result["structured_validity"]

    checks = evaluate(metrics, thresholds)
    counts = {}
    for case in cases:
        entry = counts.setdefault(case["suite"], {"passed": 0, "total": 0})
        entry["total"] += 1
        entry["passed"] += int(case["pass"])
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bastion_version": __version__,
        "mode": settings.mode,
        "suites": suites,
        "counts": counts,
        "metrics": metrics,
        "thresholds": checks,
        "passed": all(row["pass"] for row in checks),
        "cases": cases,
    }


def format_value(row: dict[str, Any], value: Any) -> str:
    if row["kind"] == "rate":
        return f"{value:.0%}"
    if row["kind"] == "ms":
        return f"{value:g} ms"
    if row["kind"] == "bool":
        return "pass" if value else "FAIL"
    return f"{value:g}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Bastion's eval suites.")
    parser.add_argument("--suite", action="append", choices=SUITES, help="default: all three")
    parser.add_argument("--no-write", action="store_true", help="do not write latest.json")
    args = parser.parse_args(argv)
    result = run(args.suite)
    for case in result["cases"]:
        if not case["pass"]:
            print(f"FAIL {case['id']:<8} expected: {case['expected']}")
            print(f"     got: {case['actual']} · {case.get('error')}")
    print()
    for suite, count in result["counts"].items():
        print(f"{suite:<18} {count['passed']}/{count['total']} passed")
    print()
    for row in result["thresholds"]:
        mark = "ok  " if row["pass"] else "FAIL"
        print(f"{mark} {row['label']:<32} {format_value(row, row['value']):>8}   "
              f"(threshold {row['op']} {format_value(row, row['threshold'])})")  # fmt: skip
    if not args.no_write and set(result["suites"]) == set(SUITES):
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(f"\nresults written to {RESULTS_PATH.relative_to(REPO_ROOT)}")
    print("\nEVAL GATE: " + ("PASS" if result["passed"] else "FAIL (thresholds breached)"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
