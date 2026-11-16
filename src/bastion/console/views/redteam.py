"""Red-Team: the eval scoreboard and every case behind it."""

import streamlit as st

from bastion.console import common
from bastion.console.client import ApiError

SUITES = {
    "redteam": "Red-team (must be blocked)",
    "benign": "Benign (must go through)",
    "assessor": "Assessor (risk tier)",
    "assessor-reviewer": "Reviewer (seeded errors)",
}


def _value(row: dict, value) -> str:
    if row["kind"] == "rate":
        return f"{value:.0%}"
    if row["kind"] == "ms":
        return f"{value:g} ms"
    if row["kind"] == "bool":
        return "yes" if value else "no"
    return f"{value:g}"


def render() -> None:
    st.title("Red-Team")
    st.caption(
        "Attacks that must be blocked, ordinary work that must still go through, and the "
        "accuracy of the classification agents. The same suites gate every commit in CI."
    )
    try:
        result = common.api().get("/evals/latest")
    except ApiError as exc:
        if exc.status != 404:
            raise
        st.info("No eval results yet. Run `make eval`.")
        return

    if result["passed"]:
        st.success("Eval gate: PASS. Every threshold is met.", icon="✅")
    else:
        st.error("Eval gate: FAIL. At least one threshold is breached.", icon="🚫")
    st.caption(
        f"Run at {result['generated_at'][:19].replace('T', ' ')} UTC · mode `{result['mode']}` "
        "(no model calls: the gateway layer has no model, the agent layers replay recordings)"
    )
    cols = st.columns(len(result["counts"]))
    for col, (suite, count) in zip(cols, result["counts"].items(), strict=True):
        col.metric(SUITES.get(suite, suite), f"{count['passed']} / {count['total']}")

    st.subheader("Thresholds")
    common.table(
        [
            {
                "Metric": row["label"],
                "Value": _value(row, row["value"]),
                "Threshold": f"{row['op']} {_value(row, row['threshold'])}",
                "Gate": "pass" if row["pass"] else "FAIL",
            }
            for row in result["thresholds"]
        ]
    )

    failing = [case for case in result["cases"] if not case["pass"]]
    if failing:
        st.subheader(f"Failing cases ({len(failing)})")
        for case in failing:
            st.error(
                f"**{case['id']}** {case.get('title', '')}\n\nExpected: {case['expected']}\n\n"
                f"Got: {case['actual']} {case.get('error') or ''}"
            )

    st.subheader("All cases")
    choice = st.radio(
        "Suite",
        list(result["counts"]),
        horizontal=True,
        format_func=lambda s: SUITES.get(s, s),
        label_visibility="collapsed",
    )
    cases = [case for case in result["cases"] if case["suite"] == choice]
    common.table(
        [
            {
                "": "✅" if case["pass"] else "❌",
                "ID": case["id"],
                "Category": case.get("category", ""),
                "Layer": case.get("layer", ""),
                "Attack / request": case.get("title") or case["id"],
                "Expected": case["expected"],
                "What happened": case["actual"],
            }
            for case in cases
        ],
        height=min(38 * (len(cases) + 1), 720),
    )
    st.caption(
        "Layer `gateway`: scripted calls with no model, so the result does not depend on what "
        "a model happens to do. Layer `agent`: a recorded agent run replayed through the gateway."
    )
