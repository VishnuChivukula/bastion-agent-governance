"""Human approvals bound to exact arguments (ADR-002, FR-20).

A pending approval is keyed by (agent_id, tool, args_hash). Decisions, single-use grants,
expiry and revocation are added in slice S3.
"""

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, func, select

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
