"""Agents, kill switch and usage."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from bastion.api.auth import Actor, Guarded, State
from bastion.api.schemas import AgentOut, KillOut, KillSwitchOut, Reason, UsageOut
from bastion.api.state import AppState
from bastion.db import session_scope
from bastion.gateway.policy_engine import PolicyLoadError
from bastion.models import Agent, Usage
from bastion.oversight.killswitch import GLOBAL, KillSwitchError

router = APIRouter(tags=["agents"])


def agent_out(state: AppState, agent: Agent) -> AgentOut:
    row = state.gateway.policies.active_row(agent.id)
    out = AgentOut.model_validate(agent)
    out.has_token = agent.token_hash is not None
    out.policy_version = row.version if row else None
    out.policy_hash = row.content_hash if row else None
    out.killed_by = state.gateway.killswitch.active_scope(agent.id)
    return out


def get_agent_or_404(state: AppState, agent_id: str) -> Agent:
    agent = state.gateway.registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    return agent


@router.get("/agents")
def list_agents(state: State) -> list[AgentOut]:
    return [agent_out(state, agent) for agent in state.gateway.registry.list_agents()]


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, state: State) -> AgentOut:
    return agent_out(state, get_agent_or_404(state, agent_id))


@router.get("/killswitch")
def killswitch_status(state: State) -> list[KillSwitchOut]:
    return [KillSwitchOut.model_validate(row) for row in state.gateway.killswitch.status()]


def _kill(state: AppState, scope: str, body: Reason, who: str) -> KillOut:
    try:
        return KillOut(**state.gateway.killswitch.kill(scope, reason=body.reason, actor=who))
    except KillSwitchError as exc:
        raise HTTPException(400, str(exc)) from exc


def _reactivate(state: AppState, scope: str, body: Reason, who: str) -> dict[str, str]:
    try:
        state.gateway.killswitch.reactivate(scope, reason=body.reason, actor=who)
    except KillSwitchError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"scope": scope, "status": "reactivated"}


@router.post("/agents/{agent_id}/kill", dependencies=[Guarded])
def kill_agent(agent_id: str, body: Reason, state: State, who: Actor) -> KillOut:
    get_agent_or_404(state, agent_id)
    return _kill(state, agent_id, body, who)


@router.post("/agents/{agent_id}/reactivate", dependencies=[Guarded])
def reactivate_agent(agent_id: str, body: Reason, state: State, who: Actor) -> dict[str, str]:
    get_agent_or_404(state, agent_id)
    return _reactivate(state, agent_id, body, who)


@router.post("/killswitch/global/kill", dependencies=[Guarded])
def kill_all(body: Reason, state: State, who: Actor) -> KillOut:
    return _kill(state, GLOBAL, body, who)


@router.post("/killswitch/global/reactivate", dependencies=[Guarded])
def reactivate_all(body: Reason, state: State, who: Actor) -> dict[str, str]:
    return _reactivate(state, GLOBAL, body, who)


@router.get("/agents/{agent_id}/usage")
def usage(agent_id: str, state: State) -> UsageOut:
    get_agent_or_404(state, agent_id)
    try:
        policy = state.gateway.policies.active(agent_id)
    except PolicyLoadError:
        policy = None
    budgets = policy.budgets if policy else None
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    tokens = func.coalesce(func.sum(Usage.tokens_in + Usage.tokens_out), 0)
    with session_scope(state.engine) as session:
        today = {
            kind: (calls, toks, cost)
            for kind, calls, toks, cost in session.execute(
                select(Usage.kind, func.count(), tokens, func.coalesce(func.sum(Usage.cost_usd), 0))
                .where(Usage.agent_id == agent_id, Usage.ts >= midnight)
                .group_by(Usage.kind)
            )
        }
        per_run = session.execute(
            select(Usage.run_id, Usage.kind, func.count(), tokens, func.max(Usage.ts))
            .where(Usage.agent_id == agent_id)
            .group_by(Usage.run_id, Usage.kind)
        ).all()
    sessions: dict[str, dict] = {}
    for run_id, kind, calls, toks, last in per_run:
        entry = sessions.setdefault(
            run_id, {"run_id": run_id, "tool_calls": 0, "tokens": 0, "last_ts": last}
        )
        entry["last_ts"] = max(entry["last_ts"], last)
        if kind == "tool":
            entry["tool_calls"] = calls
        else:
            entry["tokens"] = int(toks)
    recent = sorted(sessions.values(), key=lambda e: e["last_ts"], reverse=True)[:12]
    tool, model = today.get("tool", (0, 0, 0.0)), today.get("model", (0, 0, 0.0))
    return UsageOut(
        agent_id=agent_id,
        tool_calls_today=tool[0],
        model_calls_today=model[0],
        tokens_today=int(model[1]),
        cost_usd_today=round(float(model[2]), 6),
        max_cost_usd_per_day=budgets.max_cost_usd_per_day if budgets else None,
        max_tool_calls_per_session=budgets.max_tool_calls_per_session if budgets else None,
        max_tokens_per_session=budgets.max_tokens_per_session if budgets else None,
        sessions=recent,
    )
