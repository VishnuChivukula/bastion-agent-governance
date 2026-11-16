"""Evidence: generate, preview and download the evidence pack for an agent (UC-09)."""

import streamlit as st
import streamlit.components.v1 as components

from bastion.console import common
from bastion.console.client import ApiError


def render() -> None:
    api = common.api()
    st.title("Evidence")
    st.caption(
        "One document per agent, generated from the live records: what the agent is, how it "
        "was classified and by whom, the policy in force, what was allowed, denied and "
        "approved, incidents, test results and the integrity of the audit log. It supports "
        "evidence for obligations; it does not make a system compliant."
    )
    agents = api.get("/agents")
    if not agents:
        st.caption("No agents registered.")
        return
    agent_id = st.selectbox("Agent", [a["id"] for a in agents])
    if st.button("Generate evidence pack", type="primary"):
        st.session_state["evidence_agent"] = agent_id
    if st.session_state.get("evidence_agent") != agent_id:
        st.caption("Tip: run a few scenarios first so the pack has decisions to show.")
        return

    pack = api.get(f"/agents/{agent_id}/evidence")
    html = api.get_bytes(f"/agents/{agent_id}/evidence.html")
    records = pack["records"]
    if records["chain_ok"]:
        st.success(
            f"Audit integrity: hash chain verified over {records['events_total']} events.",
            icon="🔗",
        )
    else:
        st.error(
            f"AUDIT LOG INTEGRITY FAILURE at event #{records['first_broken_seq']}. The pack "
            "says so on its cover.",
            icon="⛓️‍💥",
        )
    policy = pack["policy"]
    cols = st.columns(4)
    cols[0].metric("Risk tier", pack["agent"]["tier"] or "not signed off")
    cols[1].metric("Policy version", policy["version"] if policy else "none")
    cols[2].metric("Tool decisions", pack["oversight"]["decisions_total"])
    cols[3].metric("Incidents", len(pack["incidents"]))
    if policy:
        st.caption(f"Policy hash `{policy['hash']}` · generated {pack['generated_at']}")

    left, right = st.columns(2)
    left.download_button(
        "Download HTML", html, file_name=f"evidence-pack-{agent_id}.html", mime="text/html"
    )
    try:
        if not st.session_state["meta"]["pdf_enabled"]:
            raise ApiError(
                503,
                "switched off on this small deployment (no headless browser). The HTML pack "
                "is complete; a sample PDF is in the repository under docs/samples/.",
            )
        pdf = api.get_bytes(f"/agents/{agent_id}/evidence.pdf")
    except ApiError as exc:
        right.caption(f"PDF: {exc.detail}")
    else:
        right.download_button(
            "Download PDF", pdf, file_name=f"evidence-pack-{agent_id}.pdf",
            mime="application/pdf", type="primary",
        )  # fmt: skip
        st.caption(f"PDF header: “{pack['document_name']}” · footer: “Page X of Y” on every page.")
    st.subheader("Preview")
    components.html(html.decode("utf-8"), height=1100, scrolling=True)
