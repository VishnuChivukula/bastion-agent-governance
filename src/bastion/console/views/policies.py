"""Policies: the policy in force, its history, diffs, and activating a new version (UC-08)."""

import streamlit as st

from bastion.console import common
from bastion.console.format import short_hash


def render() -> None:
    api = common.api()
    info = st.session_state["meta"]
    st.title("Policies")
    agents = [a["id"] for a in api.get("/agents")]
    if not agents:
        st.caption("No agents registered.")
        return
    agent_id = st.selectbox("Agent", agents)
    versions = api.get(f"/agents/{agent_id}/policies")
    if not versions:
        st.warning("No policy: every tool call from this agent is denied (default deny).")
        return
    active = next(v for v in versions if v["active"])
    current = api.get(f"/agents/{agent_id}/policies/{active['version']}")
    st.success(
        f"In force: version {active['version']} · sha256 `{active['content_hash']}` · "
        f"activated by {active['created_by']}",
        icon="📜",
    )
    st.caption(
        "Ordered rules, first match wins, no match means deny. Every gateway decision records "
        "this hash and the rule that fired."
    )
    tab_view, tab_history, tab_edit = st.tabs(["Policy in force", "Version history", "Change"])

    with tab_view:
        st.code(current["content_yaml"], language="yaml")

    with tab_history:
        common.table(
            [
                {
                    "Version": v["version"],
                    "In force": "✔" if v["active"] else "",
                    "Hash": short_hash(v["content_hash"], 16),
                    "Note": v["version_note"],
                    "By": v["created_by"],
                    "Created": v["created_at"][:19].replace("T", " "),
                }
                for v in versions
            ]
        )
        numbers = [v["version"] for v in versions]
        if len(numbers) > 1:
            left, right = st.columns(2)
            old = left.selectbox("Compare version", numbers, index=1)
            new = right.selectbox("with version", numbers, index=0)
            if old != new:
                diff = api.get(
                    f"/agents/{agent_id}/policies/diff", from_version=old, to_version=new
                )
                st.code(diff["diff"] or "(no differences)", language="diff")
            if (
                common.can_mutate(info)
                and old != active["version"]
                and st.button(f"Roll back: activate the content of version {old} again")
            ):
                content = api.get(f"/agents/{agent_id}/policies/{old}")["content_yaml"]
                if common.act(
                    "Roll back",
                    lambda: api.post(f"/agents/{agent_id}/policies", {"content_yaml": content}),
                ):
                    st.rerun()
        else:
            st.caption("Only one version so far. Activate a change to see a diff here.")

    with tab_edit:
        if not common.can_mutate(info):
            common.explain_locked(info)
            return
        st.caption(
            "Activating stores a new version with a new hash and writes an audit event. Invalid "
            "policies are rejected and never stored. Try lowering the R-003 threshold from "
            "50000 to 30000."
        )
        if info["mode"] == "replay":
            st.caption(
                "Replay note: recorded scenarios assume the seed policy. A change that alters "
                "what the agent sees can lead a scenario off its recording; roll back from "
                "Version history to restore it."
            )
        text = st.text_area(
            "Policy YAML",
            value=current["content_yaml"],
            height=520,
            key=f"edit-{active['version']}",
        )
        if st.button("Validate and activate", type="primary") and common.act(
            "Policy activation",
            lambda: api.post(f"/agents/{agent_id}/policies", {"content_yaml": text}),
        ):
            st.rerun()
