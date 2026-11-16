"""Turn audit events into one readable line each (Live Activity, run timelines)."""

from typing import Any

ICONS = {"OK": "🟢", "DENIED": "🔴", "PENDING_APPROVAL": "🟡", "TOOL_ERROR": "🟠"}


def short_hash(value: str | None, length: int = 12) -> str:
    return f"{value[:length]}…" if value else "-"


def clock(ts: str) -> str:
    """HH:MM:SS (UTC) from an ISO timestamp."""
    return ts[11:19] if len(ts) >= 19 else ts


def describe(event: dict[str, Any]) -> tuple[str, str]:
    """(icon, text) for one audit event as returned by `GET /audit/events`."""
    kind, p = event["event_type"], event.get("payload", {})
    if kind == "tool_decision":
        status = p.get("status", "")
        label = {
            "OK": "ALLOW",
            "DENIED": "DENY",
            "PENDING_APPROVAL": "NEEDS APPROVAL",
            "TOOL_ERROR": "TOOL ERROR",
        }.get(status, status)
        if status == "OK" and p.get("effect") == "require_approval":
            label = "ALLOW (approved grant)"
        reasons = p.get("reasons") or [""]
        rule = p.get("rule_id") or reasons[-1].split(":")[0] or "default deny"
        text = f"{label} · {rule} · {p.get('tool')}"
        if p.get("category"):
            text += f" · category {p['category']}"
        masked = sum((p.get("redactions") or {}).values())
        if masked:
            text += f" · {masked} PII value{'s' if masked != 1 else ''} masked"
        if p.get("approval_id"):
            text += f" · {p['approval_id']}"
        text += f" · {p.get('overhead_ms', 0):.1f} ms"
        return ICONS.get(status, "⚪"), text
    simple = {
        "model_call": lambda: (
            "🧠",
            f"model call · {p.get('model')} · {p.get('tokens_in', 0) + p.get('tokens_out', 0)} "
            f"tokens{' · replayed' if p.get('replayed') else ''}",
        ),
        "model_call_blocked": lambda: ("⛔", f"model call blocked · {p.get('reason')}"),
        "approval_requested": lambda: (
            "🟡",
            f"approval requested · {p.get('approval_id')} · {p.get('tool')} · {p.get('rule_id')}",
        ),
        "approval_decided": lambda: (
            "✅" if p.get("decision") == "approved" else "❌",
            f"approval {p.get('decision')} · {p.get('approval_id')} · {p.get('reason')}",
        ),
        "approval_revoked": lambda: (
            "↩️",
            f"approval revoked · {p.get('approval_id')} · {p.get('reason')}",
        ),
        "grant_consumed": lambda: ("🎟️", f"grant consumed (single use) · {p.get('approval_id')}"),
        "incident_opened": lambda: (
            "🚨",
            f"incident #{p.get('incident_id')} opened · {p.get('rule_id')} · "
            f"severity {p.get('severity')}",
        ),
        "incident_updated": lambda: (
            "📝",
            f"incident #{p.get('incident_id')} {p.get('from')} → {p.get('to')}",
        ),
        "killswitch_activated": lambda: (
            "🛑",
            f"KILL SWITCH on {p.get('scope')} · {p.get('reason')}",
        ),
        "killswitch_reactivated": lambda: (
            "▶️",
            f"reactivated {p.get('scope')} · {p.get('reason')}",
        ),
        "policy_activated": lambda: (
            "📜",
            f"policy v{p.get('version')} activated · {short_hash(p.get('policy_hash'))}",
        ),
        "run_started": lambda: ("🏁", f"run started · {p.get('scenario')} · {p.get('run_id')}"),
        "run_status": lambda: ("•", f"run {p.get('run_id')} → {p.get('status')}"),
        "agent_registered": lambda: ("🤖", f"agent registered · tier {p.get('tier')}"),
        "token_issued": lambda: ("🔑", "agent token issued (stored hashed)"),
        "auth_failed": lambda: ("🚫", f"gateway authentication failed · {p.get('reason')}"),
        "passcode_rejected": lambda: ("🚫", "console passcode rejected"),
    }
    if kind in simple:
        return simple[kind]()
    return "•", kind.replace("_", " ")
