"""Bastion console (FR-81). Run with `make serve`, or:

streamlit run src/bastion/console/app.py
"""

import os

import streamlit as st

from bastion.config import LOCAL_DEV_PASSCODE
from bastion.console import common
from bastion.console.client import ApiError

st.set_page_config(page_title="Bastion", page_icon="🛡️", layout="wide")

# The page shown first. Overridable so a link, a demo recording or a test can open another page.
START_PAGE = os.environ.get("BASTION_CONSOLE_START_PAGE", "overview")

PAGES = [
    st.Page(f"pages/{name}.py", title=title, icon=icon, url_path=name.replace("_", "-"),
            default=name == START_PAGE)
    for name, title, icon in [
        ("overview", "Overview", "📊"),
        ("run_scenario", "Run Scenario", "▶️"),
        ("live_activity", "Live Activity", "📡"),
        ("approvals", "Approvals", "✅"),
        ("incidents", "Incidents", "🚨"),
        ("registry", "Registry", "🤖"),
        ("policies", "Policies", "📜"),
        ("evidence", "Evidence", "📑"),
        ("red_team", "Red-Team", "🧪"),
    ]
]  # fmt: skip


def main() -> None:
    page = st.navigation(PAGES)
    try:
        info = common.meta()
    except ApiError as exc:
        st.title("🛡️ Bastion")
        st.error(exc.detail)
        st.caption("Start the API with `make serve`, then reload this page.")
        common.footer()
        return
    with st.sidebar:
        st.markdown("### 🛡️ Bastion")
        st.caption("Runtime governance control plane for AI agents")
        if info["local_dev"] and "passcode" not in st.session_state:
            st.session_state["passcode"] = LOCAL_DEV_PASSCODE
        st.text_input("Your name (recorded in the audit log)", key="actor",
                      placeholder="approver@bank.example")  # fmt: skip
        st.text_input("Passcode", key="passcode", type="password",
                      help="Needed to approve, kill, reactivate and change policy.")  # fmt: skip
        if info["local_dev"]:
            st.caption(f"Local development: the passcode is `{LOCAL_DEV_PASSCODE}`.")
        st.caption(f"v{info['version']} · mode `{info['mode']}`")
    common.banner(info)
    st.session_state["meta"] = info
    try:
        page.run()
    except ApiError as exc:
        st.error(exc.detail)
    common.footer()


main()
