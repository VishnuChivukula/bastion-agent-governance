"""Registry: agent cards, classification by the Assessor and Reviewer, human sign-off (UC-01)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from bastion.api.auth import Actor, Guarded, State
from bastion.llm.client import ReplayMissError
from bastion.registry.assessor_graph import AssessmentError
from bastion.registry.classification import RegistrationRecord, SignOffResult, sample_cards
from bastion.registry.models import AgentCard, Tier
from bastion.registry.service import RegistryError

router = APIRouter(tags=["registry"])


class SignOffIn(BaseModel):
    tier: Tier
    override_reason: str | None = Field(None, max_length=2000)


@router.get("/registry/samples")
def samples() -> list[AgentCard]:
    """Synthetic agent cards. Their classifications are recorded, so they work in replay."""
    return sample_cards()


@router.get("/registry/agents/{agent_id}")
def record(agent_id: str, state: State) -> RegistrationRecord:
    found = state.classification.get_record(agent_id)
    if found is None:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    return found


@router.post("/registry/agents", status_code=201, dependencies=[Guarded])
def register(card: AgentCard, state: State, who: Actor) -> RegistrationRecord:
    """Submit an agent card and run the classification. The agent then waits for sign-off;
    it has no policy and no gateway credential until a human signs off."""
    service = state.classification
    existing = service.get_record(card.id)
    try:
        if existing is None:
            service.submit_card(card, actor=who)
        elif existing.status != "draft" or existing.card != card:
            raise HTTPException(409, f"agent '{card.id}' already exists ({existing.status})")
        service.run_assessment(card.id)  # a draft whose assessment failed earlier is retried
    except RegistryError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ReplayMissError as exc:
        raise HTTPException(
            409,
            "The card is registered as a draft, but replay mode has no recorded classification "
            "for it. Use one of the sample cards unchanged, or run in live mode.",
        ) from exc
    except AssessmentError as exc:
        raise HTTPException(502, f"classification failed: {exc}") from exc
    return service.get_record(card.id)


@router.post("/registry/agents/{agent_id}/signoff", dependencies=[Guarded])
def sign_off(agent_id: str, body: SignOffIn, state: State, who: Actor) -> SignOffResult:
    """Accept the proposed tier, or override it with a reason. `prohibited` blocks the agent.
    Otherwise the policy is activated and the gateway token is returned, once."""
    if state.classification.get_record(agent_id) is None:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    try:
        return state.classification.sign_off(
            agent_id, tier=body.tier, approver=who, override_reason=body.override_reason
        )
    except RegistryError as exc:
        raise HTTPException(409, str(exc)) from exc
