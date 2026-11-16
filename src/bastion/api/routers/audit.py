"""Audit log (read-only), chain verification and the overview numbers."""

import json

from fastapi import APIRouter
from sqlalchemy import func, select

from bastion.api.auth import State
from bastion.api.schemas import AuditEventOut, Overview
from bastion.audit.verify import VerifyResult, verify_chain
from bastion.db import session_scope
from bastion.models import Agent, Approval, AuditEvent, Incident
from bastion.oversight.killswitch import GLOBAL

router = APIRouter(tags=["audit"])


@router.get("/audit/events")
def events(
    state: State,
    agent_id: str | None = None,
    event_type: str | None = None,
    after_seq: int = 0,
    limit: int = 200,
) -> list[AuditEventOut]:
    """Newest first. `after_seq` returns only events newer than a sequence number."""
    stmt = select(AuditEvent).where(AuditEvent.seq > after_seq)
    if agent_id:
        stmt = stmt.where(AuditEvent.agent_id == agent_id)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    stmt = stmt.order_by(AuditEvent.seq.desc()).limit(min(max(limit, 1), 1000))
    with state.engine.connect() as conn:
        rows = conn.execute(stmt).all()
    return [
        AuditEventOut(
            seq=r.seq,
            ts=r.ts,
            actor=r.actor,
            event_type=r.event_type,
            agent_id=r.agent_id,
            payload=json.loads(r.payload_json),
            hash=r.hash,
        )
        for r in rows
    ]


@router.get("/audit/verify")
def verify(state: State) -> VerifyResult:
    """Recompute the hash chain (FR-31). `ok: false` names the first broken sequence number."""
    return verify_chain(state.engine)


@router.get("/overview")
def overview(state: State) -> Overview:
    check = verify_chain(state.engine)
    with session_scope(state.engine) as session:
        agents = session.scalar(select(func.count()).select_from(Agent))
        killed = session.scalar(
            select(func.count()).select_from(Agent).where(Agent.status == "killed")
        )
        pending = session.scalar(
            select(func.count()).select_from(Approval).where(Approval.status == "pending")
        )
        incidents = session.scalar(
            select(func.count()).select_from(Incident).where(Incident.status != "resolved")
        )
        model_calls = session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == "model_call"
            )
        )  # fmt: skip
        payloads = session.scalars(
            select(AuditEvent.payload_json)
            .where(AuditEvent.event_type == "tool_decision")
            .order_by(AuditEvent.seq.desc())
            .limit(5000)
        ).all()
    decisions: dict[str, int] = {}
    redactions = 0
    overheads: list[float] = []
    for raw in payloads:
        payload = json.loads(raw)
        decisions[payload["status"]] = decisions.get(payload["status"], 0) + 1
        redactions += sum((payload.get("redactions") or {}).values())
        overheads.append(float(payload.get("overhead_ms") or 0.0))
    overheads.sort()
    p95 = overheads[min(len(overheads) - 1, int(len(overheads) * 0.95))] if overheads else None
    return Overview(
        agents=agents,
        agents_killed=killed,
        global_kill=state.gateway.killswitch.is_active(GLOBAL),
        pending_approvals=pending,
        open_incidents=incidents,
        decisions=decisions,
        redactions=redactions,
        model_calls=model_calls,
        audit_events=check.events,
        audit_ok=check.ok,
        audit_first_broken_seq=check.first_broken_seq,
        overhead_p95_ms=p95,
    )
