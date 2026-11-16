"""Overview: is governance working right now?"""

import streamlit as st

from bastion.console import common
from bastion.console.format import short_hash


def render() -> None:
    api = common.api()
    st.title("Overview")
    data = api.get("/overview")

    if data["audit_ok"]:
        st.success(
            f"Audit log intact: {data['audit_events']} events, hash chain verified.", icon="🔗"
        )
    else:
        st.error(
            f"AUDIT LOG INTEGRITY FAILURE: the hash chain breaks at event "
            f"#{data['audit_first_broken_seq']}. Records from that point on cannot be trusted.",
            icon="⛓️‍💥",
        )
    if data["global_kill"]:
        st.error("The GLOBAL kill switch is active: every agent is stopped.", icon="🛑")

    decisions = data["decisions"]
    cols = st.columns(6)
    cols[0].metric("Tool calls allowed", decisions.get("OK", 0))
    cols[1].metric("Denied", decisions.get("DENIED", 0))
    cols[2].metric("Sent for approval", decisions.get("PENDING_APPROVAL", 0))
    cols[3].metric("Approvals waiting", data["pending_approvals"])
    cols[4].metric("Open incidents", data["open_incidents"])
    cols[5].metric("PII values masked", data["redactions"])
    cols = st.columns(6)
    cols[0].metric("Agents", data["agents"])
    cols[1].metric("Agents killed", data["agents_killed"])
    cols[2].metric("Model calls", data["model_calls"])
    p95 = data["overhead_p95_ms"]
    cols[3].metric("Gateway overhead p95", f"{p95:.1f} ms" if p95 is not None else "-")

    st.subheader("Agents")
    agents = api.get("/agents")
    common.table(
        [
            {
                "Agent": a["id"],
                "Status": a["status"],
                "Risk tier": a["tier"] or "-",
                "Owner": a["owner"],
                "Policy": f"v{a['policy_version']} · {short_hash(a['policy_hash'])}"
                if a["policy_version"]
                else "none (default deny)",
            }
            for a in agents
        ]
    )

    for agent in agents:
        usage = api.get(f"/agents/{agent['id']}/usage")
        st.subheader(f"Budgets · {agent['id']}")
        cols = st.columns(3)
        cap = usage["max_cost_usd_per_day"]
        cols[0].metric(
            "Model cost today",
            f"${usage['cost_usd_today']:.4f}",
            f"cap ${cap:.2f}/day" if cap is not None else "no cap",
            delta_color="off",
        )
        cols[1].metric("Tokens today", f"{usage['tokens_today']:,}")
        cols[2].metric("Tool calls today", usage["tool_calls_today"])
        sessions = [s for s in usage["sessions"] if s["run_id"] != "unbound"]
        cap = usage["max_tool_calls_per_session"]
        if sessions:
            st.caption(
                "Tool calls per run (most recent runs)"
                + (f". The gateway denies call number {cap + 1}." if cap is not None else ".")
            )
            common.bars(
                [(s["run_id"][-6:], s["tool_calls"]) for s in sessions], "Run", "Tool calls", cap
            )
            if cap is not None and any(s["tool_calls"] >= cap for s in sessions):
                st.warning(f"At least one run hit the session cap of {cap} tool calls.", icon="🧱")
