"""Shared console plumbing: the API client, the mode banner, the footer, guarded actions."""

import os
from collections.abc import Callable
from typing import Any

import streamlit as st

from bastion import DISCLAIMER
from bastion.console.client import Api, ApiError

MODE_TEXT = {
    "replay": "**REPLAY mode** · model responses come from recorded fixtures (no API key, no "
    "cost). The gateway, policy engine, tools, approvals and audit log are all live.",
    "record": "**RECORD mode** · scenarios call the model API and save new fixtures.",
    "live": "**LIVE mode** · scenarios call the model API.",
}


@st.cache_resource
def _api(base_url: str) -> Api:
    return Api(base_url)


def api() -> Api:
    client = _api(os.environ.get("BASTION_API_URL", "http://127.0.0.1:8000"))
    client.passcode = st.session_state.get("passcode", "")
    client.actor = st.session_state.get("actor", "")
    return client


def meta() -> dict[str, Any]:
    return api().get("/meta")


def banner(info: dict[str, Any]) -> None:
    st.info(MODE_TEXT.get(info["mode"], info["mode"]), icon="⏺️")


def footer() -> None:
    st.divider()
    st.caption(f"Bastion · {DISCLAIMER} All data is synthetic.")


def can_mutate(info: dict[str, Any]) -> bool:
    return bool(info["mutations_enabled"] and st.session_state.get("passcode"))


def explain_locked(info: dict[str, Any]) -> None:
    if not info["mutations_enabled"]:
        st.caption(
            "🔒 Read-only deployment: no passcode is configured on the server, so approvals, "
            "the kill switch and policy changes are disabled. Recorded scenarios can still run."
        )
    elif not st.session_state.get("passcode"):
        st.caption("🔒 Enter the passcode in the sidebar to approve, kill or change policy.")


def act(label: str, call: Callable[[], Any]) -> Any | None:
    """Run a mutating API call; show the outcome; return the result or None on failure."""
    try:
        result = call()
    except ApiError as exc:
        st.error(f"{label} failed: {exc.detail}")
        return None
    st.toast(f"{label}: done")
    return result
