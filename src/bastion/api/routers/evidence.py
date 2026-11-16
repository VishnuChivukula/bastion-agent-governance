"""Evidence pack routes. The generator arrives in slice S7; until then this answers 501."""

from fastapi import APIRouter, HTTPException

from bastion.api.auth import State
from bastion.api.routers.agents import get_agent_or_404

router = APIRouter(tags=["evidence"])


@router.get("/agents/{agent_id}/evidence")
def evidence(agent_id: str, state: State) -> None:
    get_agent_or_404(state, agent_id)
    raise HTTPException(501, "Evidence packs are not implemented yet (slice S7).")
