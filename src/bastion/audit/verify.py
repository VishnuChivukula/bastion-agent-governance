"""Verify the audit hash chain (FR-31): detects modification, deletion and reordering."""

import json

from pydantic import BaseModel
from sqlalchemy import Engine, select

from bastion.audit.log import GENESIS_HASH, event_body, event_hash
from bastion.models import AuditEvent


class VerifyResult(BaseModel):
    ok: bool
    events: int
    first_broken_seq: int | None = None
    reason: str | None = None
    head_hash: str = GENESIS_HASH


def verify_chain(engine: Engine) -> VerifyResult:
    with engine.connect() as conn:
        rows = conn.execute(select(AuditEvent).order_by(AuditEvent.seq.asc())).all()

    prev_hash = GENESIS_HASH
    expected_seq = 1
    for row in rows:
        if row.seq != expected_seq:
            return VerifyResult(
                ok=False,
                events=len(rows),
                first_broken_seq=expected_seq,
                reason=f"sequence gap: expected seq {expected_seq}, found {row.seq} "
                "(event deleted or reordered)",
            )
        if row.prev_hash != prev_hash:
            return VerifyResult(
                ok=False,
                events=len(rows),
                first_broken_seq=row.seq,
                reason="prev_hash does not match the previous event's hash",
            )
        try:
            payload = json.loads(row.payload_json)
        except ValueError:
            payload = row.payload_json
        body = event_body(row.seq, row.ts, row.actor, row.event_type, row.agent_id, payload)
        if event_hash(prev_hash, body) != row.hash:
            return VerifyResult(
                ok=False,
                events=len(rows),
                first_broken_seq=row.seq,
                reason="event content does not match its hash (event modified)",
            )
        prev_hash = row.hash
        expected_seq += 1
    return VerifyResult(ok=True, events=len(rows), head_hash=prev_hash)
