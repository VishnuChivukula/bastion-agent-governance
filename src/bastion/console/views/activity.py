"""Live Activity: the audit log as it is written. Refreshes itself."""

import streamlit as st

from bastion.console import common
from bastion.console.format import clock, describe, short_hash

FILTERS = {
    "Everything": None,
    "Tool decisions": "tool_decision",
    "Model calls": "model_call",
    "Approvals": "approval_decided",
    "Incidents": "incident_opened",
    "Kill switch": "killswitch_activated",
    "Policy changes": "policy_activated",
}


@st.fragment(run_every=2)
def feed(event_type: str | None, limit: int) -> None:
    events = common.api().get("/audit/events", event_type=event_type, limit=limit)
    if not events:
        st.caption("Nothing yet. Start a scenario from **Run Scenario**.")
        return
    rows = []
    for event in events:
        icon, text = describe(event)
        rows.append(
            {
                "#": event["seq"],
                "Time (UTC)": clock(event["ts"]),
                "": icon,
                "What happened": text,
                "Actor": event["actor"],
                "Hash": short_hash(event["hash"], 10),
            }
        )
    common.table(rows, height=560)
    st.caption(f"Newest first · refreshes every 2 seconds · latest event #{events[0]['seq']}")


def render() -> None:
    st.title("Live Activity")
    st.caption(
        "Every decision Bastion makes is appended to a hash-chained audit log. Each row links "
        "to the one before it, so edits and deletions are detectable."
    )
    left, right = st.columns([3, 1])
    choice = left.radio("Show", list(FILTERS), horizontal=True, label_visibility="collapsed")
    limit = right.selectbox("Rows", [50, 200, 1000], label_visibility="collapsed")
    feed(FILTERS[choice], limit)
