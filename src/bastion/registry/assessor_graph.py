"""Risk classification by two agents (FR-02, FR-03, docs/ARCHITECTURE.md §6.4).

    load_card → retrieve → assess → review ──agree──▶ END
                                       │
                                   disagree
                                       ▼
                                    revise (once) ──▶ END

The graph stops with a proposal. The human sign-off is a separate, durable step recorded in
the database (ADR-009), so it survives restarts and never depends on a held-open graph.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from bastion.config import REPO_ROOT
from bastion.llm import GovernedAnthropic
from bastion.registry.models import (
    ASSESSMENT_SCHEMA,
    REVIEW_SCHEMA,
    AgentCard,
    Assessment,
    Classification,
    Review,
)

KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
ASSESSOR_ID = "bastion-assessor"
REVIEWER_ID = "bastion-reviewer"
MAX_TOKENS = 8000

_COMMON = """Bastion is a governance control plane for AI agents. Before an agent may act, its \
owner submits an agent card and the agent is classified into one of four tiers under the EU AI \
Act: prohibited, high, limited or minimal.

Work only from the agent card and the knowledge notes below. The notes are paraphrased \
summaries, not the legal text, and every regulatory reference is unverified: write "[VERIFY]" \
after each provision you cite (for example "Annex III, creditworthiness [VERIFY]"). Never quote \
legal text and never invent article, annex or clause numbers that are not in the notes. \
Classify the use described, not the technology. This is decision support for a human approver, \
not legal advice.

<knowledge_notes>
{knowledge}
</knowledge_notes>"""

ASSESSOR_SYSTEM = (
    """You are the Assessor agent of Bastion. You propose a risk tier for an agent card.

"""
    + _COMMON
    + """

Return:
- tier: the single best-fitting tier.
- rationale: three to six sentences tying facts in the card to the notes.
- cited_provisions: the provisions relied on, each ending with [VERIFY].
- likely_obligations: the main obligations that would follow, in plain words, for the \
organisation deploying the agent. Say "supports evidence for", never "ensures compliance".
- confidence: 0 to 1. Lower it when the card leaves the decisive facts open.
- open_questions: what the human approver should ask the owner before signing off."""
)

REVIEWER_SYSTEM = (
    """You are the Reviewer agent of Bastion. You independently challenge the Assessor's \
proposed risk tier for an agent card. You are a second line of defence: form your own view \
from the card first, then compare. Do not defer to the Assessor, and do not disagree for the \
sake of it.

"""
    + _COMMON
    + """

Return:
- verdict: "agree" if the proposed tier is the best fit, otherwise "disagree".
- recommended_tier: the tier you would sign off.
- challenges: specific weaknesses in the assessment: facts in the card it ignored, notes it \
misapplied, obligations it missed. Empty if there are none.
- summary: two or three sentences for the human approver."""
)


class AssessmentError(Exception):
    """The model did not return a usable structured answer."""


def load_knowledge(directory: Path = KNOWLEDGE_DIR) -> str:
    """All knowledge notes, in a fixed order (they are short: no ranking is needed)."""
    notes = sorted(p for p in directory.glob("eu-ai-act-*.md"))
    if not notes:
        raise AssessmentError(f"no knowledge notes found in {directory}")
    return "\n\n".join(p.read_text(encoding="utf-8").strip() for p in notes)


def card_text(card: AgentCard) -> str:
    return json.dumps(card.model_dump(), indent=2, ensure_ascii=False)


class State(TypedDict, total=False):
    card: AgentCard
    knowledge: str
    assessment: Assessment
    review: Review
    revised: Assessment | None


@dataclass
class AssessorDeps:
    assessor: GovernedAnthropic
    reviewer: GovernedAnthropic
    model: str
    knowledge_dir: Path = KNOWLEDGE_DIR


def _structured[T: BaseModel](
    llm: GovernedAnthropic, model: str, system: str, user: str, schema: dict, out: type[T]
) -> T:
    response = llm.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=MAX_TOKENS,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason != "end_turn":
        raise AssessmentError(f"model stopped with '{response.stop_reason}'")
    try:
        return out.model_validate_json(response.text)
    except ValidationError as exc:
        raise AssessmentError(f"structured output failed validation: {exc}") from exc


def assess(deps: AssessorDeps, card: AgentCard, knowledge: str) -> Assessment:
    user = f"<agent_card>\n{card_text(card)}\n</agent_card>\n\nPropose the risk tier."
    return _structured(
        deps.assessor, deps.model, ASSESSOR_SYSTEM.format(knowledge=knowledge), user,
        ASSESSMENT_SCHEMA, Assessment,
    )  # fmt: skip


def review(deps: AssessorDeps, card: AgentCard, knowledge: str, proposal: Assessment) -> Review:
    user = (
        f"<agent_card>\n{card_text(card)}\n</agent_card>\n\n"
        f"<assessment>\n{proposal.model_dump_json(indent=2)}\n</assessment>\n\n"
        "Review the assessment."
    )
    return _structured(
        deps.reviewer, deps.model, REVIEWER_SYSTEM.format(knowledge=knowledge), user,
        REVIEW_SCHEMA, Review,
    )  # fmt: skip


def revise(
    deps: AssessorDeps, card: AgentCard, knowledge: str, first: Assessment, critique: Review
) -> Assessment:
    user = (
        f"<agent_card>\n{card_text(card)}\n</agent_card>\n\n"
        f"<your_first_assessment>\n{first.model_dump_json(indent=2)}\n</your_first_assessment>\n\n"
        f"<reviewer_critique>\n{critique.model_dump_json(indent=2)}\n</reviewer_critique>\n\n"
        "The Reviewer disagreed. Reconsider once. Change the tier if the critique is right; "
        "keep it and answer the challenges in the rationale if it is not. Give your final "
        "assessment."
    )
    return _structured(
        deps.assessor, deps.model, ASSESSOR_SYSTEM.format(knowledge=knowledge), user,
        ASSESSMENT_SCHEMA, Assessment,
    )  # fmt: skip


def build_graph(deps: AssessorDeps):
    def retrieve(state: State) -> State:
        return {"knowledge": load_knowledge(deps.knowledge_dir)}

    def assess_node(state: State) -> State:
        return {"assessment": assess(deps, state["card"], state["knowledge"])}

    def review_node(state: State) -> State:
        return {"review": review(deps, state["card"], state["knowledge"], state["assessment"])}

    def revise_node(state: State) -> State:
        return {
            "revised": revise(
                deps, state["card"], state["knowledge"], state["assessment"], state["review"]
            )
        }

    def after_review(state: State) -> str:
        return "revise" if state["review"].verdict == "disagree" else END

    graph = StateGraph(State)
    graph.add_node("retrieve", retrieve)
    graph.add_node("assess", assess_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "assess")
    graph.add_edge("assess", "review")
    graph.add_conditional_edges("review", after_review, ["revise", END])
    graph.add_edge("revise", END)
    return graph.compile()


def classify(deps: AssessorDeps, card: AgentCard) -> Classification:
    state: dict[str, Any] = build_graph(deps).invoke({"card": card})
    return Classification(
        assessment=state["assessment"], review=state["review"], revised=state.get("revised")
    )
