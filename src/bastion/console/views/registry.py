"""Registry: the agents Bastion governs, and their kill switches."""

import streamlit as st

from bastion.console import common
from bastion.console.format import short_hash


def render() -> None:
    api = common.api()
    info = st.session_state["meta"]
    st.title("Registry")
    switches = {s["scope"]: s for s in api.get("/killswitch")}

    for agent in api.get("/agents"):
        with st.container(border=True):
            killed = agent["killed_by"]
            state = "🛑 KILLED" if killed else f"🟢 {agent['status']}"
            st.markdown(f"### {agent['name']} · `{agent['id']}` · {state}")
            cols = st.columns(4)
            cols[0].metric("Risk tier", agent["tier"] or "unclassified")
            cols[1].metric("Owner", agent["owner"].split("@")[0])
            cols[2].metric(
                "Policy in force",
                f"v{agent['policy_version']}" if agent["policy_version"] else "none",
            )
            cols[3].metric("Gateway token", "issued" if agent["has_token"] else "not issued")
            st.caption(
                f"Owner {agent['owner']} · policy hash `{short_hash(agent['policy_hash'], 16)}` "
                "· tokens are shown once at issue and stored only as a hash."
            )
            if killed:
                switch = switches.get(killed, {})
                st.error(
                    f"Stopped by the {'global' if killed == 'global' else 'agent'} kill switch "
                    f"({switch.get('actor', '?')}): {switch.get('reason', '')}"
                )
            if not common.can_mutate(info):
                common.explain_locked(info)
                continue
            if killed == agent["id"]:
                reason = st.text_input(
                    "Reason for reactivating (required)", key=f"re-{agent['id']}"
                )
                if st.button("Reactivate agent", key=f"reactivate-{agent['id']}") and common.act(
                    "Reactivate",
                    lambda agent=agent, reason=reason: api.post(
                        f"/agents/{agent['id']}/reactivate", {"reason": reason}
                    ),
                ):
                    st.rerun()
            elif not killed:
                reason = st.text_input("Reason for stopping (required)", key=f"kill-{agent['id']}")
                if st.button(
                    "🛑 Kill agent", key=f"killbtn-{agent['id']}", type="primary"
                ) and common.act(
                    "Kill switch",
                    lambda agent=agent, reason=reason: api.post(
                        f"/agents/{agent['id']}/kill", {"reason": reason}
                    ),
                ):
                    st.rerun()

    st.subheader("Global kill switch")
    st.caption("Stops every agent at once: all tool and model calls are denied.")
    active = switches.get("global", {}).get("active", False)
    if active:
        st.error(f"ACTIVE: {switches['global']['reason']} ({switches['global']['actor']})")
    if common.can_mutate(info):
        reason = st.text_input("Reason (required)", key="global-reason")
        label, path = (
            ("Reactivate all agents", "/killswitch/global/reactivate")
            if active
            else ("🛑 Kill ALL agents", "/killswitch/global/kill")
        )
        if st.button(label, key="global-btn") and common.act(
            label, lambda: api.post(path, {"reason": reason})
        ):
            st.rerun()
