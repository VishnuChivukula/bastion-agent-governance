"""Evidence pack: what Bastion can show an auditor about one agent (FR-50, UC-09).

`collect` reads the live database; `render_html` turns it into a self-contained HTML document;
`bastion.evidence.pdf` prints that document to PDF. The pack supports evidence for
obligations. It does not make a system compliant, and it is not legal advice.
"""

import json
import statistics
from datetime import UTC, datetime
from typing import Any

import yaml
from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel
from sqlalchemy import Engine, func, select

from bastion import DISCLAIMER, __version__
from bastion.audit.log import AuditLog
from bastion.audit.verify import verify_chain
from bastion.config import REPO_ROOT
from bastion.db import session_scope
from bastion.gateway.policy_engine import Policy, PolicyLoadError
from bastion.models import Approval, AuditEvent, Incident, Usage
from bastion.registry.classification import ClassificationService, RegistrationRecord
from bastion.registry.service import PolicyStore

EVAL_RESULTS = REPO_ROOT / "evals" / "results" / "latest.json"

# docs/GOVERNANCE_MAPPING.md, one entry per capability. Every reference is unverified.
MAPPING: list[dict[str, str]] = [
    {
        "key": "classification",
        "capability": "Registry, two-agent classification and human sign-off",
        "eu": "Art. 6 and Annex III (high-risk classification); Art. 5 (prohibited practices)",
        "nist": "MAP",
        "iso": "6.1; 8.4",
    },
    {
        "key": "policy",
        "capability": "Policy-as-code, default deny, versioning",
        "eu": "Art. 9 (risk management system)",
        "nist": "GOVERN, MANAGE",
        "iso": "8.3",
    },
    {
        "key": "audit",
        "capability": "Hash-chained audit log and verification",
        "eu": "Art. 12 (record-keeping); Art. 26 (deployer log retention)",
        "nist": "MEASURE, GOVERN",
        "iso": "7.5; 9.1",
    },
    {
        "key": "approvals",
        "capability": "Human approvals bound to exact arguments",
        "eu": "Art. 14 (human oversight); Art. 26 (deployer oversight duties)",
        "nist": "MANAGE, GOVERN",
        "iso": "8.1",
    },
    {
        "key": "killswitch",
        "capability": "Kill switch",
        "eu": "Art. 14 (ability to intervene or stop)",
        "nist": "MANAGE",
        "iso": "8.1; 10.2",
    },
    {
        "key": "redaction",
        "capability": "PII redaction and outbound DLP",
        "eu": "Art. 10 (data governance; limited relevance to deployers); GDPR Art. 5(1)(c)",
        "nist": "MAP, MANAGE",
        "iso": "6.1; 8.2",
    },
    {
        "key": "redteam",
        "capability": "Red-team suite and CI gate",
        "eu": "Art. 15 (accuracy, robustness, cybersecurity)",
        "nist": "MEASURE",
        "iso": "9.1",
    },
    {
        "key": "incidents",
        "capability": "Incident lifecycle",
        "eu": "Art. 72 (post-market monitoring, provider side); Art. 73 (serious incident "
        "reporting, provider side)",
        "nist": "MANAGE",
        "iso": "10.2",
    },
    {
        "key": "card",
        "capability": "Agent card",
        "eu": "Art. 13 (information to deployers, provider side); Art. 50 (transparency)",
        "nist": "GOVERN, MAP",
        "iso": "7.4",
    },
    {
        "key": "budgets",
        "capability": "Budgets and cost caps",
        "eu": "none (operational control)",
        "nist": "MANAGE",
        "iso": "8.1",
    },
    {
        "key": "pack",
        "capability": "This evidence pack",
        "eu": "Art. 11 and Annex IV (technical documentation; partial support only)",
        "nist": "GOVERN",
        "iso": "7.5",
    },
]

LIMITATIONS = [
    "Bastion is a reference implementation, not a production system. Nothing in this pack is "
    "legal advice or a statement that the agent or its operator meets any legal requirement.",
    "The pack supports evidence for obligations; it does not make a system compliant.",
    "Every regulatory reference is a paraphrased starting point that has not been verified "
    "against the primary source.",
    "The risk tier was proposed by two AI agents from short paraphrased notes and signed by a "
    "human. It is decision support, not a legal classification.",
    "The audit chain shows whether stored events were modified, deleted or reordered. It has no "
    "external anchor, so removal of the most recent events would not be detected.",
    "Approver and operator names are self-declared in v0.1 (one shared passcode, no SSO).",
    "Only tool calls routed through the Bastion gateway and model calls made through its SDK "
    "wrapper are recorded. Activity outside those paths is not covered.",
    "PII masking is pattern and NER based and can miss values.",
    "All data in this demonstration is synthetic.",
]


class EvidencePack(BaseModel):
    document_name: str
    generated_at: str
    bastion_version: str
    disclaimer: str
    agent: dict[str, Any]
    registration: RegistrationRecord | None
    policy: dict[str, Any] | None
    oversight: dict[str, Any]
    robustness: dict[str, Any] | None
    incidents: list[dict[str, Any]]
    usage: dict[str, Any]
    records: dict[str, Any]
    mapping: list[dict[str, str]]
    mapping_omitted: list[str]
    limitations: list[str]


class UnknownAgent(Exception):
    pass


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _policy(engine: Engine, agent_id: str) -> dict[str, Any] | None:
    store = PolicyStore(engine)
    row = store.active_row(agent_id)
    if row is None:
        return None
    out: dict[str, Any] = {
        "version": row.version,
        "hash": row.content_hash,
        "activated_by": row.created_by,
        "activated_at": row.created_at,
        "versions": len(store.versions(agent_id)),
        "rules": [],
        "incident_rules": [],
        "budgets": {},
        "note": "",
        "valid": True,
    }
    try:
        policy = Policy.from_yaml(row.content_yaml)
    except PolicyLoadError:
        out["valid"] = False
        return out
    out["note"] = policy.version_note
    out["budgets"] = policy.budgets.model_dump()
    out["rules"] = [
        {
            "id": r.id,
            "tool": r.tool,
            "effect": r.effect,
            "when": r.when or "always",
            "category": r.category or "",
            "data": ", ".join(
                filter(
                    None,
                    [
                        f"mask in output: {', '.join(r.redact_output)}" if r.redact_output else "",
                        f"scan input for {', '.join(r.scan_input.entities)} → {r.scan_input.action}"
                        if r.scan_input
                        else "",
                    ],
                )
            ),
        }
        for r in policy.rules
    ]
    out["incident_rules"] = [
        {"id": r.id, "when": r.when, "severity": r.severity, "action": r.on_incident or "none"}
        for r in policy.incident_rules
    ]
    return out


def _events(engine: Engine, agent_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(AuditEvent.event_type, AuditEvent.ts, AuditEvent.payload_json)
            .where(AuditEvent.agent_id == agent_id)
            .order_by(AuditEvent.seq)
        ).all()
    return [(r.event_type, r.ts, json.loads(r.payload_json)) for r in rows]


def collect(engine: Engine, agent_id: str) -> EvidencePack:
    service = ClassificationService(engine)
    agent = service.registry.get_agent(agent_id)
    if agent is None:
        raise UnknownAgent(agent_id)
    registration = service.get_record(agent_id)
    events = _events(engine, agent_id)
    decisions = [p for kind, _, p in events if kind == "tool_decision"]

    by_status: dict[str, int] = {}
    for payload in decisions:
        by_status[payload["status"]] = by_status.get(payload["status"], 0) + 1
    by_rule: dict[str, dict[str, int]] = {}
    for payload in decisions:
        reasons = payload.get("reasons") or [""]
        rule = payload.get("rule_id") or reasons[-1].split(":")[0] or "default deny"
        entry = by_rule.setdefault(rule, {})
        entry[payload["status"]] = entry.get(payload["status"], 0) + 1
    redactions = sum(sum((p.get("redactions") or {}).values()) for p in decisions)

    with session_scope(engine) as session:
        approvals = list(session.scalars(select(Approval).where(Approval.agent_id == agent_id)))
        incidents = list(
            session.scalars(
                select(Incident).where(Incident.agent_id == agent_id).order_by(Incident.id)
            )
        )
        tokens_in, tokens_out, cost, model_calls = session.execute(
            select(
                func.coalesce(func.sum(Usage.tokens_in), 0),
                func.coalesce(func.sum(Usage.tokens_out), 0),
                func.coalesce(func.sum(Usage.cost_usd), 0.0),
                func.count(),
            ).where(Usage.agent_id == agent_id, Usage.kind == "model")
        ).one()
        tool_calls = session.scalar(
            select(func.count())
            .select_from(Usage)
            .where(Usage.agent_id == agent_id, Usage.kind == "tool")
        )
    approval_counts: dict[str, int] = {}
    for approval in approvals:
        approval_counts[approval.status] = approval_counts.get(approval.status, 0) + 1
    decided = [
        _seconds(a.created_at, a.decided_at)
        for a in approvals
        if a.decided_at and a.decided_by and a.status in ("approved", "rejected", "consumed")
    ]
    kills = [
        {"ts": ts, "what": "activated" if kind == "killswitch_activated" else "reactivated",
         "reason": p.get("reason", ""), "scope": p.get("scope", "")}
        for kind, ts, p in events
        if kind in ("killswitch_activated", "killswitch_reactivated")
    ]  # fmt: skip
    budget_denials = sum(
        1 for p in decisions if (p.get("reasons") or [""])[-1].startswith("budget_exceeded")
    )
    model_blocked = sum(1 for kind, _, _ in events if kind == "model_call_blocked")

    robustness = None
    if EVAL_RESULTS.is_file():
        latest = json.loads(EVAL_RESULTS.read_text(encoding="utf-8"))
        robustness = {
            "generated_at": latest["generated_at"],
            "passed": latest["passed"],
            "counts": latest["counts"],
            "thresholds": latest["thresholds"],
            "failing": [c["id"] for c in latest["cases"] if not c["pass"]],
            "policy_hash": latest.get("policy_hash"),
        }

    check = verify_chain(engine)
    policy = _policy(engine, agent_id)
    if robustness is not None:
        # The suites exercise one policy. They say nothing about a different policy in force.
        robustness["matches_policy"] = bool(
            policy and robustness["policy_hash"] and policy["hash"] == robustness["policy_hash"]
        )
    present = {
        "classification": bool(registration and registration.classification),
        "policy": policy is not None,
        "audit": check.events > 0,
        "approvals": bool(approvals),
        "killswitch": bool(kills),
        "redaction": redactions > 0,
        "redteam": bool(robustness and robustness["matches_policy"]),
        "incidents": bool(incidents),
        "card": bool(registration and registration.card),
        "budgets": bool(policy and any(v is not None for v in policy["budgets"].values())),
        "pack": True,
    }
    return EvidencePack(
        document_name=f"Bastion Evidence Pack — {agent.name}",
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        bastion_version=__version__,
        disclaimer=DISCLAIMER,
        agent={
            "id": agent.id,
            "name": agent.name,
            "owner": agent.owner,
            "status": agent.status,
            "tier": agent.tier,
            "created_at": agent.created_at,
            "token_issued": agent.token_hash is not None,
        },  # fmt: skip
        registration=registration,
        policy=policy,
        oversight={
            "decisions": by_status,
            "decisions_total": len(decisions),
            "by_rule": by_rule,
            "approvals": approval_counts,
            "approvals_total": len(approvals),
            "median_decision_seconds": round(statistics.median(decided), 1) if decided else None,
            "signoff_override": bool(registration and registration.override_reason),
            "kills": kills,
            "redactions": redactions,
        },
        robustness=robustness,
        incidents=[
            {
                "id": i.id,
                "rule_id": i.rule_id,
                "severity": i.severity,
                "status": i.status,
                "summary": i.summary,
                "opened_at": i.opened_at,
                "closed_at": i.closed_at,
                "notes": json.loads(i.notes_json),
            }
            for i in incidents
        ],  # fmt: skip
        usage={
            "model_calls": model_calls,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "cost_usd": round(float(cost), 6),
            "tool_calls": tool_calls,
            "budget_denials": budget_denials,
            "model_calls_blocked": model_blocked,
        },
        records={
            "events_total": check.events,
            "events_agent": len(events),
            "chain_ok": check.ok,
            "first_broken_seq": check.first_broken_seq,
            "reason": check.reason,
            "head_hash": check.head_hash,
            "by_type": _count_types(events),
        },
        mapping=[row for row in MAPPING if present[row["key"]]],
        mapping_omitted=[row["capability"] for row in MAPPING if not present[row["key"]]],
        limitations=LIMITATIONS,
    )


def _count_types(events: list[tuple[str, str, dict[str, Any]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, _, _ in events:
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _when(value: str | None) -> str:
    return value[:19].replace("T", " ") + " UTC" if value else "-"


def _pct(value: float) -> str:
    return f"{value:.0%}"


def render_html(pack: EvidencePack) -> str:
    env = Environment(
        loader=PackageLoader("bastion.evidence", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["when"] = _when
    env.filters["pct"] = _pct
    env.filters["yaml"] = lambda value: yaml.safe_dump(value, sort_keys=False).strip()
    return env.get_template("pack.html.j2").render(p=pack)


def generate(engine: Engine, agent_id: str, *, actor: str = "system") -> tuple[EvidencePack, str]:
    """Collect and render, and record that a pack was produced."""
    pack = collect(engine, agent_id)
    html = render_html(pack)
    AuditLog(engine).append(
        "evidence_generated",
        actor=actor,
        agent_id=agent_id,
        payload={
            "policy_hash": pack.policy["hash"] if pack.policy else None,
            "audit_events": pack.records["events_total"],
            "chain_ok": pack.records["chain_ok"],
        },
    )
    return pack, html
