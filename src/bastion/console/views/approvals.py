"""Approvals: decide the actions that policy sends to a human."""

import pandas as pd
import streamlit as st

from bastion.console import common
from bastion.console.format import clock, short_hash


def decision_form(approval: dict, info: dict, key: str = "") -> None:
    """One pending approval with approve / reject controls. Used here and on Run Scenario."""
    api = common.api()
    with st.container(border=True):
        st.markdown(
            f"**{approval['tool']}** requested by `{approval['agent_id']}` · rule "
            f"`{approval['rule_id']}` · `{approval['id']}`"
        )
        st.json(approval["args"], expanded=True)
        st.caption(
            f"Arguments hash `{short_hash(approval['args_hash'], 16)}` · expires "
            f"{clock(approval['expires_at'])} UTC. Approval creates a single-use grant for "
            "exactly these arguments; a call with different arguments needs a new approval."
        )
        if not common.can_mutate(info):
            common.explain_locked(info)
            return
        slot = f"{key}{approval['id']}"
        reason = st.text_input("Reason (required)", key=f"reason-{slot}")
        approve, reject, _ = st.columns([1, 1, 4])
        for column, label, value in ((approve, "Approve", True), (reject, "Reject", False)):
            if column.button(
                label, key=f"{label}-{slot}", type="primary" if value else "secondary"
            ) and common.act(
                label,
                lambda value=value: api.post(
                    f"/approvals/{approval['id']}/decision", {"approve": value, "reason": reason}
                ),
            ):
                st.rerun()


def render() -> None:
    api = common.api()
    info = st.session_state["meta"]
    st.title("Approvals")
    pending = api.get("/approvals", status="pending")
    st.subheader(f"Waiting for a decision ({len(pending)})")
    if not pending:
        st.caption(
            "Nothing is waiting. Run **UC-04** on the Run Scenario page with the approver set "
            "to *me* to see a run pause here."
        )
    for approval in pending:
        decision_form(approval, info)

    history = [a for a in api.get("/approvals") if a["status"] != "pending"]
    st.subheader("History")
    if history:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Approval": a["id"],
                        "Tool": a["tool"],
                        "Status": a["status"],
                        "Decided by": a["decided_by"] or "-",
                        "Reason": a["reason"] or "-",
                        "Args hash": short_hash(a["args_hash"]),
                        "Created": a["created_at"][:19].replace("T", " "),
                    }
                    for a in history
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "`approved` = a grant that has not been used · `consumed` = the identical call ran "
            "once · `revoked` = withdrawn by the kill switch or a demo reset."
        )
    else:
        st.caption("No decisions yet.")
