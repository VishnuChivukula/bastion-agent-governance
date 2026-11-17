"""Human approvals bound to exact arguments (ADR-002, FR-20).

An approval is keyed by (agent_id, tool, args_hash). `ApprovalStore` creates pending
approvals; `ApprovalService` adds decisions, single-use grants, expiry and revocation.
A grant is an approval in status `approved`; using it moves it to `consumed`.
"""

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, func, select, update

from bastion.db import session_scope
from bastion.models import Approval, iso, utcnow

DEFAULT_TTL_SECONDS = 30 * 60


class ApprovalStore:
    def __init__(self, engine: Engine, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.engine = engine
        self.ttl_seconds = ttl_seconds

    def request(
        self,
        *,
        agent_id: str,
        run_id: str | None,
        tool: str,
        args_hash: str,
        args_redacted: dict[str, Any],
        rule_id: str | None,
    ) -> tuple[Approval, bool]:
        """Return (approval, created). An unexpired pending approval for the same call is reused."""
        now = utcnow()
        with session_scope(self.engine) as session:
            existing = session.scalar(
                select(Approval).where(
                    Approval.agent_id == agent_id,
                    Approval.tool == tool,
                    Approval.args_hash == args_hash,
                    Approval.status == "pending",
                    Approval.expires_at > iso(now),
                )
            )
            if existing is not None:
                return existing, False
            ordinal = session.scalar(
                select(func.count())
                .select_from(Approval)
                .where(
                    Approval.agent_id == agent_id,
                    Approval.tool == tool,
                    Approval.args_hash == args_hash,
                )
            )
            # Deterministic id: stable across fresh databases, so replayed model fixtures match.
            digest = hashlib.sha256(f"{agent_id}|{tool}|{args_hash}|{ordinal}".encode()).hexdigest()
            approval = Approval(
                id=f"APR-{digest[:10]}",
                agent_id=agent_id,
                run_id=run_id,
                tool=tool,
                args_hash=args_hash,
                args_redacted_json=json.dumps(args_redacted, sort_keys=True),
                rule_id=rule_id,
                status="pending",
                created_at=iso(now),
                expires_at=iso(now + timedelta(seconds=self.ttl_seconds)),
            )
            session.add(approval)
            return approval, True

    def get(self, approval_id: str) -> Approval | None:
        with session_scope(self.engine) as session:
            return session.get(Approval, approval_id)


class ApprovalError(Exception):
    pass


class ApprovalService(ApprovalStore):
    """Decisions, single-use grants, expiry and revocation (FR-21, ADR-002)."""

    def __init__(self, engine: Engine, audit=None, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        super().__init__(engine, ttl_seconds)
        from bastion.audit.log import AuditLog

        self.audit = audit or AuditLog(engine)

    def expire_stale(self) -> int:
        """Mark pending approvals and unused grants past their TTL as expired."""
        from sqlalchemy import update

        with session_scope(self.engine) as session:
            result = session.execute(
                update(Approval)
                .where(Approval.status.in_(("pending", "approved")), Approval.expires_at <= iso())
                .values(status="expired")
            )
            return result.rowcount

    def decide(self, approval_id: str, *, approve: bool, decided_by: str, reason: str) -> Approval:
        if not reason or not reason.strip():
            raise ApprovalError("a reason is required")
        self.expire_stale()
        with session_scope(self.engine) as session:
            approval = session.get(Approval, approval_id)
            if approval is None:
                raise ApprovalError(f"unknown approval '{approval_id}'")
            # One conditional UPDATE: a kill switch revoking at the same moment cannot be
            # overwritten by this decision.
            claimed = session.execute(
                update(Approval)
                .where(Approval.id == approval_id, Approval.status == "pending")
                .values(
                    status="approved" if approve else "rejected",
                    decided_by=decided_by,
                    reason=reason.strip(),
                    decided_at=iso(),
                )
            )
            if claimed.rowcount != 1:
                session.refresh(approval)
                raise ApprovalError(f"approval is {approval.status}, not pending")
            session.refresh(approval)
        self.audit.append(
            "approval_decided",
            actor=decided_by,
            agent_id=approval.agent_id,
            payload={
                "approval_id": approval.id,
                "decision": approval.status,
                "tool": approval.tool,
                "args_hash": approval.args_hash,
                "reason": approval.reason,
            },
        )
        return approval

    def consume_grant(self, agent_id: str, tool: str, args_hash: str) -> Approval | None:
        """Use the grant for exactly this call, once. Returns None if there is none."""
        from sqlalchemy import update

        self.expire_stale()
        with session_scope(self.engine) as session:
            grant = session.scalar(
                select(Approval).where(
                    Approval.agent_id == agent_id,
                    Approval.tool == tool,
                    Approval.args_hash == args_hash,
                    Approval.status == "approved",
                )
            )
            if grant is None:
                return None
            claimed = session.execute(
                update(Approval)
                .where(Approval.id == grant.id, Approval.status == "approved")
                .values(status="consumed")
            )
            if claimed.rowcount != 1:  # pragma: no cover - lost a race for the same grant
                return None
            grant.status = "consumed"
        self.audit.append(
            "grant_consumed",
            actor=agent_id,
            agent_id=agent_id,
            payload={"approval_id": grant.id, "tool": tool, "args_hash": args_hash},
        )
        return grant

    def revoke_open(self, agent_id: str | None, *, reason: str, actor: str) -> list[str]:
        """Revoke pending approvals and unused grants (kill switch). None = every agent."""
        with session_scope(self.engine) as session:
            stmt = select(Approval).where(Approval.status.in_(("pending", "approved")))
            if agent_id is not None:
                stmt = stmt.where(Approval.agent_id == agent_id)
            rows = list(session.scalars(stmt))
            for row in rows:
                row.status = "revoked"
                row.reason = reason
                row.decided_at = iso()
        for row in rows:
            self.audit.append(
                "approval_revoked",
                actor=actor,
                agent_id=row.agent_id,
                payload={"approval_id": row.id, "reason": reason},
            )
        return [row.id for row in rows]

    def all(self, *, status: str | None = None, agent_id: str | None = None) -> list[Approval]:
        self.expire_stale()
        with session_scope(self.engine) as session:
            stmt = select(Approval).order_by(Approval.created_at.desc())
            if status:
                stmt = stmt.where(Approval.status == status)
            if agent_id:
                stmt = stmt.where(Approval.agent_id == agent_id)
            return list(session.scalars(stmt))
