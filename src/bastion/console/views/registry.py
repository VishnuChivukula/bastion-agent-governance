"""Registry: the agents Bastion governs, how each was classified, and their kill switches."""

import json

import streamlit as st

from bastion.console import common
from bastion.console.client import ApiError
from bastion.console.format import short_hash

TIERS = ["prohibited", "high", "limited", "minimal"]
STATE = {
    "draft": "📝 draft",
    "assessing": "⚖️ assessing",
    "awaiting_signoff": "🖊️ awaiting sign-off",
    "active": "🟢 active",
    "blocked": "⛔ blocked (prohibited)",
    "killed": "🛑 KILLED",
}


def _assessment(title: str, a: dict) -> None:
    st.markdown(f"**{title}: `{a['tier']}`** · confidence {a['confidence']:.2f}")
    st.write(a["rationale"])
    if a["cited_provisions"]:
        st.caption("Provisions cited (unverified starting points, not legal advice):")
        for item in a["cited_provisions"]:
            st.caption(f"• {item}")
    with st.expander("Likely obligations and open questions"):
        for item in a["likely_obligations"]:
            st.markdown(f"- {item}")
        if a["open_questions"]:
            st.markdown("**Questions for the owner before sign-off**")
            for item in a["open_questions"]:
                st.markdown(f"- {item}")


def classification(record: dict) -> None:
    """The Assessor's proposal, the Reviewer's critique and the sign-off, as recorded."""
    found = record.get("classification")
    if not found:
        st.caption(
            "No classification on record: this agent was seeded directly (the classification "
            "could not be replayed in this mode)."
        )
        return
    left, right = st.columns(2)
    with left:
        _assessment("Assessor proposes", found["assessment"])
    with right:
        review = found["review"]
        st.markdown(
            f"**Reviewer {review['verdict']}s** · would sign off `{review['recommended_tier']}`"
        )
        st.write(review["summary"])
        for item in review["challenges"]:
            st.caption(f"• {item}")
    if found.get("revised"):
        st.divider()
        _assessment("Assessor, revised once after the critique", found["revised"])
    if record["unresolved_disagreement"]:
        st.warning(
            "The two agents still disagree after the one allowed revision. The human decides.",
            icon="⚖️",
        )
    if record.get("signed_off_by"):
        text = (
            f"Signed off as **{record['final_tier']}** by {record['signed_off_by']} on "
            f"{record['signed_at'][:19].replace('T', ' ')} UTC."
        )
        if record.get("override_reason"):
            text += f" Override of the proposed tier `{record['proposed_tier']}`: "
            text += record["override_reason"]
        st.success(text, icon="🖊️")


def signoff_form(api, agent_id: str, record: dict) -> None:
    proposed = record["proposed_tier"]
    st.markdown("**Human sign-off** · nothing is issued to this agent until you decide.")
    tier = st.selectbox(
        "Tier to sign off", TIERS, index=TIERS.index(proposed), key=f"tier-{agent_id}"
    )
    reason = ""
    if tier != proposed:
        reason = st.text_input(
            f"Reason for overriding the proposed tier `{proposed}` (required)",
            key=f"override-{agent_id}",
        )
    if tier == "prohibited":
        st.caption("Signing off `prohibited` blocks the agent: no policy, no credential.")
    if st.button("Sign off", key=f"signoff-{agent_id}", type="primary"):
        result = common.act(
            "Sign-off",
            lambda: api.post(
                f"/registry/agents/{agent_id}/signoff",
                {"tier": tier, "override_reason": reason or None},
            ),
        )
        if result:
            st.session_state[f"signed-{agent_id}"] = result
            st.rerun()


def token_notice(agent_id: str) -> None:
    result = st.session_state.pop(f"signed-{agent_id}", None)
    if not result:
        return
    if result["status"] == "blocked":
        st.error("Agent blocked: tier `prohibited`. No policy and no credential were issued.")
        return
    st.success(
        f"Activated at tier `{result['final_tier']}`. Policy: {result['policy_source']} "
        f"(`{short_hash(result['policy_hash'], 16)}`)."
    )
    st.warning("Gateway token: shown once, stored only as a hash. Copy it now.", icon="🔑")
    st.code(result["token"], language=None)


def kill_controls(api, agent: dict) -> None:
    killed = agent["killed_by"]
    if killed == agent["id"]:
        reason = st.text_input("Reason for reactivating (required)", key=f"re-{agent['id']}")
        if st.button("Reactivate agent", key=f"reactivate-{agent['id']}") and common.act(
            "Reactivate",
            lambda: api.post(f"/agents/{agent['id']}/reactivate", {"reason": reason}),
        ):
            st.rerun()
    elif not killed and agent["status"] == "active":
        reason = st.text_input("Reason for stopping (required)", key=f"kill-{agent['id']}")
        if st.button("🛑 Kill agent", key=f"killbtn-{agent['id']}", type="primary") and common.act(
            "Kill switch", lambda: api.post(f"/agents/{agent['id']}/kill", {"reason": reason})
        ):
            st.rerun()


def register_form(api, known: set[str]) -> None:
    st.subheader("Register an agent")
    st.caption(
        "Submit an agent card. The Assessor proposes an EU AI Act risk tier, the Reviewer "
        "challenges it, and the agent then waits for your sign-off. These are synthetic sample "
        "cards whose classifications are recorded, so they work in replay mode."
    )
    cards = [card for card in api.get("/registry/samples") if card["id"] not in known]
    if not cards:
        st.caption("Every sample card is already registered.")
        return
    by_name = {f"{card['name']} · {card['id']}": card for card in cards}
    card = by_name[st.selectbox("Sample agent card", list(by_name))]
    st.json(card, expanded=False)
    if st.button("Submit card and classify", type="primary"):
        with st.spinner("Assessor and Reviewer are working…"):
            try:
                api.post("/registry/agents", card)
            except ApiError as exc:
                st.error(f"Registration failed: {exc.detail}")
            else:
                st.rerun()


def render() -> None:
    api = common.api()
    info = st.session_state["meta"]
    can_mutate = common.can_mutate(info)
    st.title("Registry")
    st.caption(
        "Classify before deploy: no agent gets a policy or a gateway credential until two "
        "agents have classified it and a human has signed off."
    )
    switches = {s["scope"]: s for s in api.get("/killswitch")}
    agents = api.get("/agents")

    for agent in agents:
        record = api.get(f"/registry/agents/{agent['id']}")
        with st.container(border=True):
            killed = agent["killed_by"]
            state = STATE["killed"] if killed else STATE.get(agent["status"], agent["status"])
            st.markdown(f"### {agent['name']} · `{agent['id']}` · {state}")
            cols = st.columns(4)
            cols[0].metric("Risk tier", agent["tier"] or "not signed off")
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
            token_notice(agent["id"])
            with st.expander(
                "Classification record", expanded=agent["status"] == "awaiting_signoff"
            ):
                if record.get("card"):
                    st.caption("Agent card")
                    st.code(json.dumps(record["card"], indent=2), language="json")
                classification(record)
            if not can_mutate:
                common.explain_locked(info)
                continue
            if agent["status"] == "awaiting_signoff":
                signoff_form(api, agent["id"], record)
            else:
                kill_controls(api, agent)

    if can_mutate:
        register_form(api, {agent["id"] for agent in agents})

    st.subheader("Global kill switch")
    st.caption("Stops every agent at once: all tool and model calls are denied.")
    active = switches.get("global", {}).get("active", False)
    if active:
        st.error(f"ACTIVE: {switches['global']['reason']} ({switches['global']['actor']})")
    if can_mutate:
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
