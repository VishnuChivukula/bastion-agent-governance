"""Request and response models of the control-plane API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Meta(BaseModel):
    version: str
    mode: str
    mutations_enabled: bool
    local_dev: bool
    disclaimer: str
    demo_policy_is_seed: bool = True  # recorded scenarios assume the seed policy
    low_memory: bool = False
    pii_engine: str = "presidio"  # "light" in low-memory mode
    pdf_enabled: bool = True


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class AgentOut(_Out):
    id: str
    name: str
    owner: str
    status: str
    tier: str | None
    created_at: str
    has_token: bool = False
    policy_version: int | None = None
    policy_hash: str | None = None
    killed_by: str | None = None  # "global", the agent id, or None


class PolicyVersionOut(_Out):
    agent_id: str | None
    version: int
    content_hash: str
    active: bool
    created_by: str
    created_at: str
    version_note: str = ""


class PolicyDetail(PolicyVersionOut):
    content_yaml: str


class PolicyIn(BaseModel):
    content_yaml: str = Field(min_length=1, max_length=100_000)


class PolicyDiff(BaseModel):
    from_version: int
    to_version: int
    from_hash: str
    to_hash: str
    diff: str


class ApprovalOut(_Out):
    id: str
    agent_id: str
    run_id: str | None
    tool: str
    args_hash: str
    args: dict[str, Any]
    rule_id: str | None
    status: str
    decided_by: str | None
    reason: str | None
    created_at: str
    decided_at: str | None
    expires_at: str


class DecisionIn(Reason):
    approve: bool


class DecisionOut(BaseModel):
    approval: ApprovalOut
    run_resumed: str | None = None


class KillOut(BaseModel):
    scope: str
    revoked_approvals: list[str]
    halted_runs: list[str]


class KillSwitchOut(_Out):
    scope: str
    active: bool
    reason: str
    actor: str
    ts: str


class IncidentOut(_Out):
    id: int
    agent_id: str
    severity: str
    rule_id: str
    status: str
    summary: str
    notes: list[dict[str, Any]]
    opened_at: str
    closed_at: str | None


class IncidentAdvance(BaseModel):
    status: Literal["acknowledged", "contained", "resolved"]
    note: str = Field(min_length=1, max_length=2000)


class ScenarioOut(BaseModel):
    id: str
    use_case: str
    title: str
    prompt: str
    what_to_watch: str
    needs_approval: bool


class RunIn(BaseModel):
    scenario: str
    # scripted: the scenario script plays the approver. human: the run waits for a decision
    # in the console (which needs the passcode).
    approver: Literal["scripted", "human"] = "scripted"


class RunOut(_Out):
    id: str
    agent_id: str
    scenario: str | None
    status: str
    started_at: str
    ended_at: str | None
    final_text: str | None = None


class RunDetail(RunOut):
    title: str = ""
    what_to_watch: str = ""
    prompt: str = ""
    error: str | None = None
    pending: list[ApprovalOut] = []
    timeline: list[str] = []
    events: list[dict[str, Any]] = []


class AuditEventOut(BaseModel):
    seq: int
    ts: str
    actor: str
    event_type: str
    agent_id: str | None
    payload: dict[str, Any]
    hash: str


class UsageOut(BaseModel):
    agent_id: str
    tool_calls_today: int
    model_calls_today: int
    tokens_today: int
    cost_usd_today: float
    max_cost_usd_per_day: float | None
    max_tool_calls_per_session: int | None
    max_tokens_per_session: int | None
    sessions: list[dict[str, Any]]  # the most recent runs: tool calls and tokens per run


class Overview(BaseModel):
    agents: int
    agents_killed: int
    global_kill: bool
    pending_approvals: int
    open_incidents: int
    decisions: dict[str, int]  # OK / DENIED / PENDING_APPROVAL / TOOL_ERROR
    redactions: int
    model_calls: int
    audit_events: int
    audit_ok: bool
    audit_first_broken_seq: int | None
    overhead_p95_ms: float | None
