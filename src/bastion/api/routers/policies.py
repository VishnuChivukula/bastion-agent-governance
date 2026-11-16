"""Policy versions: list, read, diff and activate a new version (FR-15, UC-08)."""

import difflib

import yaml
from fastapi import APIRouter, HTTPException

from bastion.api.auth import Actor, Guarded, State
from bastion.api.routers.agents import get_agent_or_404
from bastion.api.schemas import PolicyDetail, PolicyDiff, PolicyIn, PolicyVersionOut
from bastion.api.state import AppState
from bastion.gateway.policy_engine import Policy, PolicyLoadError
from bastion.models import PolicyRow

router = APIRouter(tags=["policies"])


def _note(row: PolicyRow) -> str:
    try:
        return str((yaml.safe_load(row.content_yaml) or {}).get("version_note", ""))
    except (yaml.YAMLError, AttributeError):
        return ""


def _version(state: AppState, agent_id: str, version: int) -> PolicyRow:
    for row in state.gateway.policies.versions(agent_id):
        if row.version == version:
            return row
    raise HTTPException(404, f"agent '{agent_id}' has no policy version {version}")


@router.get("/agents/{agent_id}/policies")
def list_versions(agent_id: str, state: State) -> list[PolicyVersionOut]:
    get_agent_or_404(state, agent_id)
    return [
        PolicyVersionOut.model_validate(row).model_copy(update={"version_note": _note(row)})
        for row in state.gateway.policies.versions(agent_id)
    ]


@router.get("/agents/{agent_id}/policies/diff")
def diff_versions(agent_id: str, from_version: int, to_version: int, state: State) -> PolicyDiff:
    old, new = _version(state, agent_id, from_version), _version(state, agent_id, to_version)
    lines = difflib.unified_diff(
        old.content_yaml.splitlines(),
        new.content_yaml.splitlines(),
        fromfile=f"v{old.version} ({old.content_hash[:12]})",
        tofile=f"v{new.version} ({new.content_hash[:12]})",
        lineterm="",
    )
    return PolicyDiff(
        from_version=old.version,
        to_version=new.version,
        from_hash=old.content_hash,
        to_hash=new.content_hash,
        diff="\n".join(lines),
    )


@router.get("/agents/{agent_id}/policies/{version}")
def get_version(agent_id: str, version: int, state: State) -> PolicyDetail:
    row = _version(state, agent_id, version)
    return PolicyDetail.model_validate(row).model_copy(update={"version_note": _note(row)})


@router.post("/agents/{agent_id}/policies", status_code=201, dependencies=[Guarded])
def activate(agent_id: str, body: PolicyIn, state: State, who: Actor) -> PolicyDetail:
    """Validate the YAML and make it the policy in force. Invalid policies are never stored."""
    get_agent_or_404(state, agent_id)
    current = state.gateway.policies.active_row(agent_id)
    if current is not None and current.content_yaml == body.content_yaml:
        raise HTTPException(409, "this is already the policy in force")
    try:
        proposed = Policy.from_yaml(body.content_yaml)
        in_force = state.gateway.policies.active(agent_id)
    except PolicyLoadError as exc:
        raise HTTPException(422, f"invalid policy: {exc}") from exc
    if in_force is None or proposed.downstream != in_force.downstream:
        # `downstream.command` is a process the gateway starts. It is set when an agent is
        # onboarded (seed / registry), never through the policy editor.
        raise HTTPException(
            422,
            "invalid policy: the `downstream` section cannot be changed through the API; "
            "tool servers are fixed when the agent is onboarded",
        )
    try:
        row = state.gateway.policies.activate(agent_id, body.content_yaml, created_by=who)
    except PolicyLoadError as exc:
        raise HTTPException(422, f"invalid policy: {exc}") from exc
    return PolicyDetail.model_validate(row).model_copy(update={"version_note": _note(row)})
