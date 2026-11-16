"""Database tables (docs/ARCHITECTURE.md §4). Timestamps are ISO-8601 UTC strings."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="microseconds")


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String)
    # draft / assessing / awaiting_signoff / active / killed / blocked
    status: Mapped[str] = mapped_column(String, default="draft")
    tier: Mapped[str | None] = mapped_column(String, nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(String, default=iso)


class AgentCard(Base):
    __tablename__ = "agent_cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    card_json: Mapped[str] = mapped_column(Text)


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    assessor_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    signed_off_by: Mapped[str | None] = mapped_column(String, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class PolicyRow(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_yaml: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=iso)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    scenario: Mapped[str | None] = mapped_column(String, nullable=True)
    # running / interrupted / completed / halted / failed
    status: Mapped[str] = mapped_column(String, default="running")
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str] = mapped_column(String, default=iso)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool: Mapped[str] = mapped_column(String)
    args_hash: Mapped[str] = mapped_column(String)
    args_redacted_json: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # pending / approved / rejected / expired / revoked / consumed
    status: Mapped[str] = mapped_column(String, default="pending")
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=iso)
    decided_at: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[str] = mapped_column(String)

    __table_args__ = (Index("ix_approvals_lookup", "agent_id", "tool", "args_hash", "status"),)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String)
    rule_id: Mapped[str] = mapped_column(String)
    # open / acknowledged / contained / resolved
    status: Mapped[str] = mapped_column(String, default="open")
    summary: Mapped[str] = mapped_column(Text)
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
    opened_at: Mapped[str] = mapped_column(String, default=iso)
    closed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # model / tool
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[str] = mapped_column(String, default=iso)


class KillSwitch(Base):
    __tablename__ = "killswitch"
    scope: Mapped[str] = mapped_column(String, primary_key=True)  # "global" or an agent id
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String, default="")
    ts: Mapped[str] = mapped_column(String, default=iso)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String, index=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)
