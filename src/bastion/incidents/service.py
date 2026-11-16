"""Incidents: opened by policy rules, worked through a fixed lifecycle (FR-40)."""

import json
from datetime import timedelta

from sqlalchemy import Engine, select

from bastion.audit.log import AuditLog
from bastion.db import session_scope
from bastion.gateway.policy_engine import Policy
from bastion.models import AuditEvent, Incident, iso, utcnow

LIFECYCLE = ["open", "acknowledged", "contained", "resolved"]
DENY_WINDOW = timedelta(minutes=10)
# Denials caused by the kill switch itself are not fresh evidence about the agent.
_NOT_COUNTED = ("killswitch",)


class IncidentError(Exception):
    pass


class IncidentService:
    def __init__(self, engine: Engine, audit: AuditLog | None = None) -> None:
        self.engine = engine
        self.audit = audit or AuditLog(engine)

    def open(
        self, agent_id: str, *, rule_id: str, severity: str, summary: str, actor: str = "bastion"
    ) -> tuple[Incident, bool]:
        """Open an incident, or return the one already open for this agent and rule."""
        with session_scope(self.engine) as session:
            existing = session.scalar(
                select(Incident).where(
                    Incident.agent_id == agent_id,
                    Incident.rule_id == rule_id,
                    Incident.status != "resolved",
                )
            )
            if existing is not None:
                return existing, False
            incident = Incident(
                agent_id=agent_id, severity=severity, rule_id=rule_id, summary=summary
            )
            session.add(incident)
            session.flush()
        self.audit.append(
            "incident_opened",
            actor=actor,
            agent_id=agent_id,
            payload={
                "incident_id": incident.id,
                "rule_id": rule_id,
                "severity": severity,
                "summary": summary,
            },
        )
        return incident, True

    def has_open(self, agent_id: str) -> bool:
        with session_scope(self.engine) as session:
            return (
                session.scalar(
                    select(Incident.id).where(
                        Incident.agent_id == agent_id, Incident.status != "resolved"
                    )
                )
                is not None
            )

    def advance(self, incident_id: int, status: str, *, actor: str, note: str) -> Incident:
        """Move forward through open → acknowledged → contained → resolved, with a note."""
        if status not in LIFECYCLE:
            raise IncidentError(f"unknown status '{status}'")
        if not note or not note.strip():
            raise IncidentError("a note is required")
        with session_scope(self.engine) as session:
            incident = session.get(Incident, incident_id)
            if incident is None:
                raise IncidentError(f"unknown incident {incident_id}")
            if LIFECYCLE.index(status) <= LIFECYCLE.index(incident.status):
                raise IncidentError(f"cannot move from {incident.status} to {status}")
            previous = incident.status
            notes = json.loads(incident.notes_json)
            notes.append({"ts": iso(), "actor": actor, "status": status, "note": note.strip()})
            incident.notes_json = json.dumps(notes)
            incident.status = status
            if status == "resolved":
                incident.closed_at = iso()
        self.audit.append(
            "incident_updated",
            actor=actor,
            agent_id=incident.agent_id,
            payload={"incident_id": incident.id, "from": previous, "to": status, "note": note},
        )
        return incident

    def all(self, *, agent_id: str | None = None) -> list[Incident]:
        with session_scope(self.engine) as session:
            stmt = select(Incident).order_by(Incident.id.desc())
            if agent_id:
                stmt = stmt.where(Incident.agent_id == agent_id)
            return list(session.scalars(stmt))

    def deny_count_10m(self, agent_id: str) -> int:
        cutoff = iso(utcnow() - DENY_WINDOW)
        with session_scope(self.engine) as session:
            payloads = session.scalars(
                select(AuditEvent.payload_json).where(
                    AuditEvent.agent_id == agent_id,
                    AuditEvent.event_type == "tool_decision",
                    AuditEvent.ts >= cutoff,
                )
            ).all()
        count = 0
        for raw in payloads:
            payload = json.loads(raw)
            reasons = payload.get("reasons") or [""]
            if payload.get("status") == "DENIED" and not reasons[-1].startswith(_NOT_COUNTED):
                count += 1
        return count

    def evaluate_rules(
        self, agent_id: str, policy: Policy, *, category: str | None, trigger: str
    ) -> list[tuple[Incident, str | None]]:
        """Run the policy's incident rules after a denial. Returns newly opened incidents
        with their `on_incident` action."""
        context = {"deny_count_10m": self.deny_count_10m(agent_id), "category": category}
        opened = []
        for rule in policy.incident_rules:
            if not rule.matches(context):
                continue
            incident, created = self.open(
                agent_id,
                rule_id=rule.id,
                severity=rule.severity,
                summary=f"{rule.id} ({rule.when}) triggered by {trigger}",
                actor="bastion:incident-rule",
            )
            if created:
                opened.append((incident, rule.on_incident))
        return opened
