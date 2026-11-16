"""Run Scenario: start a scripted scenario and watch Bastion's decisions."""

import streamlit as st

from bastion.console import common
from bastion.console.client import ApiError
from bastion.console.views.approvals import decision_form

STATUS = {
    "running": ("🔄", "Running"),
    "interrupted": ("⏸️", "Paused: waiting for a human approval"),
    "completed": ("✅", "Completed"),
    "halted": ("🛑", "Halted by Bastion"),
    "failed": ("⚠️", "Failed"),
}
ACTIVE = ("running", "interrupted")


def _line_style(line: str) -> str:
    for prefix, icon in (("ALLOW", "🟢"), ("DENY", "🔴"), ("APPROVAL", "🟡"), ("MODEL", "⛔")):
        if line.startswith(prefix):
            return f"{icon} {line}"
    return f"    {line}"


def follow(run_id: str) -> None:
    """Shows one run. Wrapped in a polling fragment while the run is in progress."""
    api = common.api()
    info = st.session_state["meta"]
    run = api.get(f"/runs/{run_id}")
    icon, label = STATUS.get(run["status"], ("•", run["status"]))
    previous = st.session_state.get("run_status")
    st.session_state["run_status"] = run["status"]

    st.subheader(f"{icon} {label}")
    st.caption(f"`{run['id']}` · {run['title']}")
    if run["timeline"]:
        st.code("\n".join(_line_style(line) for line in run["timeline"]), language=None)
    elif run["status"] == "running":
        st.caption("Starting the agent…")

    for approval in run["pending"]:
        st.markdown("**The agent is waiting for you.** Nothing has been executed.")
        decision_form(approval, info, key="run-")
    if run["final_text"]:
        with st.chat_message("assistant"):
            st.write(run["final_text"])
    if run["error"]:
        st.error(run["error"])
    if run["status"] not in ACTIVE:
        st.caption(
            "Next: **Live Activity** shows the full audit trail; **Incidents**, **Approvals** "
            "and **Registry** show what this run left behind."
        )
        if previous in ACTIVE:
            st.rerun()  # leave polling mode: rerun the page so the fragment stops refreshing


def render() -> None:
    api = common.api()
    info = st.session_state["meta"]
    st.title("Run Scenario")
    scenarios = api.get("/scenarios")
    by_id = {s["id"]: s for s in scenarios}
    choice = st.radio(
        "Scenario",
        list(by_id),
        format_func=lambda i: f"{by_id[i]['use_case']} · {by_id[i]['title']}",
    )
    scenario = by_id[choice]
    with st.container(border=True):
        st.markdown(f"**Task given to the agent:** {scenario['prompt']}")
        st.markdown(f"**What to watch:** {scenario['what_to_watch']}")

    approver = "scripted"
    if scenario["needs_approval"]:
        if common.can_mutate(info):
            who = st.radio(
                "Who plays the approver?",
                ["The scenario script", "Me"],
                horizontal=True,
                help="'Me' pauses the run until you approve or reject.",
            )
            approver = "human" if who == "Me" else "scripted"
        else:
            st.caption(
                "The scenario script plays the approver. With the passcode you can decide "
                "the approval yourself."
            )
    if not info["demo_policy_is_seed"] and info["mode"] == "replay":
        st.warning(
            "The policy in force is not the seed policy the scenarios were recorded with. A "
            "run may leave its recording and stop early; roll back on the Policies page to "
            "restore it.",
            icon="📜",
        )
    st.caption(
        "Starting a scenario first resets the demo: fresh bank data, kill switch released, "
        "open incidents resolved, open approvals revoked. The reset is audited."
    )
    if st.button("▶️ Run scenario", type="primary"):
        try:
            started = api.post("/runs", {"scenario": choice, "approver": approver})
        except ApiError as exc:
            st.error(exc.detail)
        else:
            st.session_state["run_id"] = started["id"]
            st.session_state["run_status"] = "running"

    run_id = st.session_state.get("run_id")
    if run_id:
        st.divider()
        polling = st.session_state.get("run_status") in ACTIVE
        st.fragment(run_every=1 if polling else None)(follow)(run_id)
