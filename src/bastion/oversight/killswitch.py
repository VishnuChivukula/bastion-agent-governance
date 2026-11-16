"""Kill switch, per agent and global (FR-22): immediate deny-all, checked before anything else."""

from sqlalchemy import Engine, select, update

from bastion.audit.log import AuditLog
from bastion.db import session_scope
from bastion.incidents.service import IncidentService
from bastion.models import Agent, KillSwitch, Run, iso
from bastion.oversight.approvals import ApprovalService

GLOBAL = "global"


class KillSwitchError(Exception):
    pass


class KillSwitchService:
    def __init__(
        self,
        engine: Engine,
        audit: AuditLog | None = None,
        approvals: ApprovalService | None = None,
        incidents: IncidentService | None = None,
    ) -> None:
        self.engine = engine
        self.audit = audit or AuditLog(engine)
        self.approvals = approvals or ApprovalService(engine, self.audit)
        self.incidents = incidents or IncidentService(engine, self.audit)

    def active_scope(self, agent_id: str) -> str | None:
        """'global', the agent id, or None if the agent may act."""
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(KillSwitch.scope).where(
                    KillSwitch.active.is_(True), KillSwitch.scope.in_((GLOBAL, agent_id))
                )
            ).all()
        if GLOBAL in rows:
            return GLOBAL
        return agent_id if rows else None

    def status(self) -> list[KillSwitch]:
        with session_scope(self.engine) as session:
            return list(session.scalars(select(KillSwitch).order_by(KillSwitch.scope)))

    def kill(self, scope: str, *, reason: str, actor: str) -> dict:
        if not reason or not reason.strip():
            raise KillSwitchError("a reason is required")
        agent_id = None if scope == GLOBAL else scope
        with session_scope(self.engine) as session:
            if agent_id is not None and session.get(Agent, agent_id) is None:
                raise KillSwitchError(f"unknown agent '{agent_id}'")
            row = session.get(KillSwitch, scope) or KillSwitch(scope=scope)
            row.active, row.reason, row.actor, row.ts = True, reason.strip(), actor, iso()
            session.add(row)
            agents = (
                select(Agent.id)
                if agent_id is None
                else select(Agent.id).where(Agent.id == agent_id)
            )
            affected = list(session.scalars(agents.where(Agent.status == "active")))
            session.execute(update(Agent).where(Agent.id.in_(affected)).values(status="killed"))
            run_filter = Run.status.in_(("running", "interrupted"))
            if agent_id is not None:
                run_filter = run_filter & (Run.agent_id == agent_id)
            halted = list(session.scalars(select(Run.id).where(run_filter)))
            session.execute(
                update(Run).where(Run.id.in_(halted)).values(status="halted", ended_at=iso())
            )
        revoked = self.approvals.revoke_open(agent_id, reason=f"kill switch: {reason}", actor=actor)
        self.audit.append(
            "killswitch_activated",
            actor=actor,
            agent_id=agent_id,
            payload={
                "scope": scope,
                "reason": reason,
                "revoked_approvals": revoked,
                "halted_runs": halted,
            },
        )
        for affected_id in affected if agent_id is None else [agent_id]:
            if not self.incidents.has_open(affected_id):
                self.incidents.open(
                    affected_id,
                    rule_id="KILLSWITCH",
                    severity="high",
                    summary=f"Kill switch activated by {actor}: {reason}",
                    actor=actor,
                )
        return {"scope": scope, "revoked_approvals": revoked, "halted_runs": halted}

    def reactivate(self, scope: str, *, reason: str, actor: str) -> None:
        if not reason or not reason.strip():
            raise KillSwitchError("a reason is required to reactivate")
        with session_scope(self.engine) as session:
            row = session.get(KillSwitch, scope)
            if row is None or not row.active:
                raise KillSwitchError(f"kill switch for '{scope}' is not active")
            row.active, row.reason, row.actor, row.ts = False, reason.strip(), actor, iso()
            still_killed = set(
                session.scalars(select(KillSwitch.scope).where(KillSwitch.active.is_(True)))
            )
            if GLOBAL not in still_killed:
                stmt = update(Agent).where(Agent.status == "killed")
                if scope != GLOBAL:
                    stmt = stmt.where(Agent.id == scope)
                else:
                    stmt = stmt.where(Agent.id.not_in(still_killed))
                session.execute(stmt.values(status="active"))
        self.audit.append(
            "killswitch_reactivated",
            actor=actor,
            agent_id=None if scope == GLOBAL else scope,
            payload={"scope": scope, "reason": reason},
        )
