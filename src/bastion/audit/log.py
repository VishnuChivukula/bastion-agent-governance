"""Append-only, hash-chained audit log (FR-30).

    hash = sha256(prev_hash || canonical_json(event_without_hash))

Each append runs in its own short transaction that takes the SQLite write lock first, so two
writers can never read the same chain head. The chain gives tamper *evidence*: SQLite cannot
prevent a privileged user from editing rows, but `verify` will report the first broken link.
"""

import hashlib
import json
from typing import Any

from sqlalchemy import Engine, select

from bastion.llm.fixtures import canonical_json
from bastion.models import AuditEvent, iso

GENESIS_HASH = "0" * 64


def event_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(body)).encode("utf-8")).hexdigest()


def event_body(seq: int, ts: str, actor: str, event_type: str, agent_id: str | None, payload: Any):
    return {
        "seq": seq,
        "ts": ts,
        "actor": actor,
        "event_type": event_type,
        "agent_id": agent_id,
        "payload": payload,
    }


class AuditLog:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(
        self,
        event_type: str,
        *,
        actor: str,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        payload = payload or {}
        payload_json = canonical_json(payload)
        with self.engine.connect().execution_options(immediate=True) as conn, conn.begin():
            head = conn.execute(
                select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)
            ).first()
            seq, prev_hash = (head.seq + 1, head.hash) if head else (1, GENESIS_HASH)
            ts = iso()
            digest = event_hash(
                prev_hash,
                event_body(seq, ts, actor, event_type, agent_id, json.loads(payload_json)),
            )
            row = {
                "seq": seq,
                "ts": ts,
                "actor": actor,
                "event_type": event_type,
                "agent_id": agent_id,
                "payload_json": payload_json,
                "prev_hash": prev_hash,
                "hash": digest,
            }
            conn.execute(AuditEvent.__table__.insert().values(**row))
        return AuditEvent(**row)

    def events(
        self,
        *,
        agent_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
        newest_first: bool = True,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent)
        if agent_id:
            stmt = stmt.where(AuditEvent.agent_id == agent_id)
        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        order = AuditEvent.seq.desc() if newest_first else AuditEvent.seq.asc()
        with self.engine.connect() as conn:
            rows = conn.execute(stmt.order_by(order).limit(limit)).all()
        return [AuditEvent(**row._mapping) for row in rows]
