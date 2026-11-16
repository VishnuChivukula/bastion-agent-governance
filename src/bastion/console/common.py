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
    text = MODE_TEXT.get(info["mode"], info["mode"])
    if info.get("low_memory"):
        text += (
            " Small-host profile: PII masking uses the built-in pattern engine and the "
            "evidence pack is HTML only."
        )
    st.info(text, icon="⏺️")


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


def low_memory() -> bool:
    return bool(st.session_state.get("meta", {}).get("low_memory"))


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(rows: list[dict[str, Any]], height: int | None = None) -> None:
    """A read-only table. Normally an interactive data frame; on a small host a plain markdown
    table, which avoids loading pandas and pyarrow into the console process (about 70 MB)."""
    if not rows:
        return
    if not low_memory():
        import pandas as pd

        kwargs = {"height": height} if height else {}
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", **kwargs)
        return
    columns = list(rows[0])
    lines = [
        "| " + " | ".join(_cell(c) or " " for c in columns) + " |",
        "|" + "---|" * len(columns),
        *("| " + " | ".join(_cell(row.get(c)) for c in columns) + " |" for row in rows),
    ]
    with st.container(height=height) if height else st.container():
        st.markdown("\n".join(lines))


def bars(points: list[tuple[str, int]], x: str, y: str, cap: int | None = None) -> None:
    """A small bar chart; progress bars on a small host (no chart stack to load)."""
    if not low_memory():
        import pandas as pd

        frame = pd.DataFrame({x: [p[0] for p in points], y: [p[1] for p in points]})
        st.bar_chart(frame, x=x, y=y, height=220)
        return
    top = max([cap or 0, *(value for _, value in points), 1])
    for label, value in points:
        st.progress(min(value / top, 1.0), text=f"{x} {label}: {value} {y.lower()}")
