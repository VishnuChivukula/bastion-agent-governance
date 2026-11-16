"""Incidents: opened by policy rules, worked through a fixed lifecycle."""

import streamlit as st

from bastion.console import common

NEXT = {"open": "acknowledged", "acknowledged": "contained", "contained": "resolved"}
ICON = {"low": "🟦", "medium": "🟨", "high": "🟧", "critical": "🟥"}


def render() -> None:
    api = common.api()
    info = st.session_state["meta"]
    st.title("Incidents")
    st.caption("Lifecycle: open → acknowledged → contained → resolved. Every step needs a note.")
    incidents = api.get("/incidents")
    if not incidents:
        st.caption("No incidents. Run **UC-03** (prompt injection) to see one open.")
        return
    show_resolved = st.toggle("Show resolved", value=False)
    shown = [i for i in incidents if show_resolved or i["status"] != "resolved"]
    if not shown:
        st.caption("No open incidents.")
    for incident in shown:
        with st.container(border=True):
            st.markdown(
                f"{ICON.get(incident['severity'], '⬜')} **#{incident['id']} · "
                f"{incident['rule_id']}** · severity **{incident['severity']}** · status "
                f"**{incident['status']}** · `{incident['agent_id']}`"
            )
            st.write(incident["summary"])
            st.caption(f"Opened {incident['opened_at'][:19].replace('T', ' ')} UTC")
            for note in incident["notes"]:
                st.caption(f"↳ {note['status']} by {note['actor']}: {note['note']}")
            step = NEXT.get(incident["status"])
            if step is None:
                continue
            if not common.can_mutate(info):
                common.explain_locked(info)
                continue
            note = st.text_input("Note (required)", key=f"note-{incident['id']}")
            if st.button(f"Mark {step}", key=f"advance-{incident['id']}") and common.act(
                f"Incident #{incident['id']} → {step}",
                lambda incident=incident, step=step, note=note: api.post(
                    f"/incidents/{incident['id']}/advance", {"status": step, "note": note}
                ),
            ):
                st.rerun()
