"""Approvals and incidents."""

import json

from fastapi import APIRouter, HTTPException

from bastion.api.auth import Actor, Guarded, State
from bastion.api.schemas import ApprovalOut, DecisionIn, DecisionOut, IncidentAdvance, IncidentOut
from bastion.incidents.service import IncidentError
from bastion.models import Approval, Incident
from bastion.oversight.approvals import ApprovalError

router = APIRouter(tags=["oversight"])


def approval_out(approval: Approval) -> ApprovalOut:
    return ApprovalOut(
        **{c: getattr(approval, c) for c in ApprovalOut.model_fields if c != "args"},
        args=json.loads(approval.args_redacted_json),
    )


def incident_out(incident: Incident) -> IncidentOut:
    return IncidentOut(
        **{c: getattr(incident, c) for c in IncidentOut.model_fields if c != "notes"},
        notes=json.loads(incident.notes_json),
    )


@router.get("/approvals")
def list_approvals(
    state: State, status: str | None = None, agent_id: str | None = None
) -> list[ApprovalOut]:
    rows = state.gateway.approvals.all(status=status, agent_id=agent_id)
    return [approval_out(row) for row in rows]


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, state: State) -> ApprovalOut:
    state.gateway.approvals.expire_stale()
    approval = state.gateway.approvals.get(approval_id)
    if approval is None:
        raise HTTPException(404, f"unknown approval '{approval_id}'")
    return approval_out(approval)


@router.post("/approvals/{approval_id}/decision", dependencies=[Guarded])
async def decide(approval_id: str, body: DecisionIn, state: State, who: Actor) -> DecisionOut:
    """Approve or reject. Approval creates a single-use grant for exactly these arguments;
    if this was the last open decision of a paused run, the run resumes.

    (async on purpose: resuming a run creates a task on the server's event loop.)"""
    if state.gateway.approvals.get(approval_id) is None:
        raise HTTPException(404, f"unknown approval '{approval_id}'")
    try:
        approval = state.gateway.approvals.decide(
            approval_id, approve=body.approve, decided_by=who, reason=body.reason
        )
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    resumed = state.runs.on_decision(approval)
    return DecisionOut(approval=approval_out(approval), run_resumed=resumed)


@router.get("/incidents")
def list_incidents(state: State, agent_id: str | None = None) -> list[IncidentOut]:
    return [incident_out(row) for row in state.gateway.incidents.all(agent_id=agent_id)]


@router.post("/incidents/{incident_id}/advance", dependencies=[Guarded])
def advance(incident_id: int, body: IncidentAdvance, state: State, who: Actor) -> IncidentOut:
    try:
        incident = state.gateway.incidents.advance(
            incident_id, body.status, actor=who, note=body.note
        )
    except IncidentError as exc:
        code = 404 if "unknown incident" in str(exc) else 409
        raise HTTPException(code, str(exc)) from exc
    return incident_out(incident)
