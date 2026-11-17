"""Registration, classification by two agents and human sign-off (S5, UC-01)."""

import json

import pytest

from bastion.audit.verify import verify_chain
from bastion.config import REPO_ROOT, Settings
from bastion.gateway.policy_engine import Policy
from bastion.registry.assessor_graph import AssessmentError, load_knowledge
from bastion.registry.classification import ClassificationService, load_card, sample_cards
from bastion.registry.models import ASSESSMENT_SCHEMA, AgentCard
from bastion.registry.service import RegistryError
from bastion.seed import DEMO_AGENT_ID, DEMO_CARD, seed_demo_classified

REPLAY = Settings(_env_file=None, BASTION_MODE="replay", ANTHROPIC_API_KEY=None)


def assessment(tier="high", confidence=0.8):
    return {
        "tier": tier,
        "rationale": "Because of the card.",
        "cited_provisions": ["Annex III [VERIFY]"],
        "likely_obligations": ["Keep logs."],
        "confidence": confidence,
        "open_questions": [],
    }


def review(verdict="agree", tier="high"):
    return {"verdict": verdict, "recommended_tier": tier, "challenges": [], "summary": "Fine."}


class Scripted:
    """A model transport that answers from a list and records every request."""

    def __init__(self, *answers, stop_reason="end_turn"):
        self.answers = list(answers)
        self.requests = []
        self.stop_reason = stop_reason

    def create(self, params):
        self.requests.append(params)
        answer = self.answers.pop(0)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return {
            "id": "msg_test",
            "model": params["model"],
            "content": [{"type": "text", "text": text}],
            "stop_reason": self.stop_reason,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }


def card(agent_id="test-agent") -> AgentCard:
    data = load_card(DEMO_CARD).model_dump()
    return AgentCard(**{**data, "id": agent_id})


def service(engine, *answers, **kwargs):
    return ClassificationService(engine, settings=REPLAY, transport=Scripted(*answers, **kwargs))


def kinds(svc, agent_id):
    events = svc.audit.events(agent_id=agent_id, newest_first=False)
    return [e.event_type for e in events]


# --- UC-01 in replay --------------------
def test_uc01_demo_agent_is_classified_high_and_signed_off_in_replay(engine):
    classification, signoff = seed_demo_classified(engine, REPLAY)
    assert classification.proposed.tier == "high"
    assert any(
        "Annex III" in p and "[VERIFY]" in p for p in classification.proposed.cited_provisions
    )
    assert all("[VERIFY]" in p for p in classification.proposed.cited_provisions)
    assert classification.review.summary  # the Reviewer output is on record
    assert signoff.status == "active" and signoff.final_tier == "high" and not signoff.overridden
    assert signoff.template == "high" and signoff.policy_source == "agent-specific"
    assert signoff.token and len(signoff.token) >= 40

    svc = ClassificationService(engine, settings=REPLAY)
    record = svc.get_record(DEMO_AGENT_ID)
    assert record.signed_off_by and record.signed_at and record.final_tier == "high"
    assert svc.registry.authenticate(signoff.token) == DEMO_AGENT_ID
    agent = svc.registry.get_agent(DEMO_AGENT_ID)
    assert agent.token_hash and signoff.token not in agent.token_hash  # stored hashed
    trail = kinds(svc, DEMO_AGENT_ID)
    for kind in ("agent_registered", "agent_card_submitted", "assessment_completed",
                 "signoff_recorded", "policy_activated", "token_issued"):  # fmt: skip
        assert kind in trail
    model_calls = svc.audit.events(event_type="model_call")
    assert {e.actor for e in model_calls} == {"bastion-assessor", "bastion-reviewer"}
    assert verify_chain(engine).ok
    assert seed_demo_classified(engine, REPLAY) is None  # idempotent


def test_sample_cards_are_valid_and_synthetic():
    cards = sample_cards()
    assert len(cards) == 12 and len({c.id for c in cards}) == 12
    for sample in cards:
        assert sample.owner.endswith(".example")


# --- the two-agent flow --------------------
def test_agreement_needs_two_model_calls_and_no_revision(engine):
    svc = service(engine, assessment("limited"), review("agree", "limited"))
    result = svc.register(card(), actor="owner@bank.example")
    assert result.revised is None and result.proposed.tier == "limited"
    assert not result.unresolved_disagreement
    assert len(svc._transport.requests) == 2
    first = svc._transport.requests[0]
    assert first["model"] == REPLAY.model_smart
    assert first["output_config"]["format"]["schema"] == ASSESSMENT_SCHEMA
    assert "temperature" not in first and "tool_choice" not in first
    assert load_knowledge() in first["system"]
    assert "test-agent" in first["messages"][0]["content"]
    assert svc.registry.get_agent("test-agent").status == "awaiting_signoff"


def test_disagreement_triggers_exactly_one_revision(engine):
    svc = service(engine, assessment("minimal"), review("disagree", "high"), assessment("high"))
    result = svc.register(card(), actor="owner@bank.example")
    assert result.assessment.tier == "minimal" and result.revised.tier == "high"
    assert result.proposed.tier == "high" and not result.unresolved_disagreement
    assert len(svc._transport.requests) == 3
    assert "reviewer_critique" in svc._transport.requests[2]["messages"][0]["content"]


def test_remaining_disagreement_is_shown_to_the_human(engine):
    svc = service(engine, assessment("minimal"), review("disagree", "high"), assessment("limited"))
    result = svc.register(card(), actor="owner@bank.example")
    assert result.unresolved_disagreement
    record = svc.get_record("test-agent")
    assert record.unresolved_disagreement and record.proposed_tier == "limited"


@pytest.mark.parametrize(
    "bad",
    ["not json", {"tier": "severe"}, assessment(confidence=1.7), {**assessment(), "extra": 1}],
)
def test_invalid_structured_output_is_rejected_and_the_agent_stays_a_draft(engine, bad):
    svc = service(engine, bad)
    with pytest.raises(AssessmentError):
        svc.register(card(), actor="owner@bank.example")
    assert svc.registry.get_agent("test-agent").status == "draft"
    assert svc.get_record("test-agent").classification is None


def test_a_refusal_or_truncation_is_not_parsed(engine):
    svc = service(engine, assessment(), stop_reason="refusal")
    with pytest.raises(AssessmentError, match="refusal"):
        svc.register(card(), actor="owner@bank.example")


# --- sign-off --------------------
def test_no_credential_before_sign_off(engine):
    svc = service(engine, assessment("limited"), review("agree", "limited"))
    svc.register(card(), actor="owner@bank.example")
    agent = svc.registry.get_agent("test-agent")
    assert agent.token_hash is None and agent.tier is None
    assert svc.policies.active_row("test-agent") is None
    with pytest.raises(RegistryError, match="no token before sign-off"):
        svc.registry.issue_token("test-agent")


def test_accepting_the_tier_applies_its_template(engine):
    svc = service(engine, assessment("limited"), review("agree", "limited"))
    svc.register(card(), actor="owner@bank.example")
    result = svc.sign_off("test-agent", tier="limited", approver="approver@bank.example")
    assert result.status == "active" and result.policy_source == "template"
    assert result.template == "limited" and result.token
    policy = svc.policies.active("test-agent")
    assert policy.agent == "test-agent" and policy.version_note == "tier template: limited"
    assert policy.rules == [] and policy.budgets.max_tool_calls_per_session == 60  # default deny
    record = svc.get_record("test-agent")
    assert record.signed_off_by == "approver@bank.example" and record.override_reason is None


def test_override_needs_a_reason(engine):
    svc = service(engine, assessment("limited"), review("agree", "limited"))
    svc.register(card(), actor="owner@bank.example")
    for reason in (None, "", "   "):
        with pytest.raises(RegistryError, match="needs a reason"):
            svc.sign_off("test-agent", tier="high", approver="a@bank.example",
                         override_reason=reason)  # fmt: skip
    assert svc.registry.get_agent("test-agent").status == "awaiting_signoff"
    result = svc.sign_off(
        "test-agent", tier="high", approver="a@bank.example", override_reason="Affects credit."
    )
    assert result.overridden and result.final_tier == "high" and result.proposed_tier == "limited"
    assert svc.policies.active("test-agent").version_note == "tier template: high"
    event = svc.audit.events(event_type="signoff_recorded")[0]
    assert json.loads(event.payload_json)["override_reason"] == "Affects credit."


def test_prohibited_blocks_registration(engine):
    svc = service(engine, assessment("prohibited"), review("agree", "prohibited"))
    svc.register(card(), actor="owner@bank.example")
    result = svc.sign_off("test-agent", tier="prohibited", approver="a@bank.example")
    assert result.status == "blocked" and result.token is None and result.policy_hash is None
    agent = svc.registry.get_agent("test-agent")
    assert agent.status == "blocked" and agent.token_hash is None
    assert svc.policies.active_row("test-agent") is None
    with pytest.raises(RegistryError):
        svc.registry.issue_token("test-agent")
    with pytest.raises(RegistryError, match="not awaiting sign-off"):
        svc.sign_off("test-agent", tier="minimal", approver="a@bank.example",
                     override_reason="x")  # fmt: skip


def test_sign_off_guards(engine):
    svc = service(engine, assessment(), review())
    with pytest.raises(RegistryError, match="unknown agent"):
        svc.sign_off("nope", tier="high", approver="a@bank.example")
    with pytest.raises(RegistryError, match="unknown agent"):
        svc.run_assessment("nope")
    svc.register(card(), actor="owner@bank.example")
    with pytest.raises(RegistryError, match="unknown tier"):
        svc.sign_off("test-agent", tier="extreme", approver="a@bank.example")
    with pytest.raises(RegistryError, match="already exists"):
        svc.submit_card(card(), actor="owner@bank.example")
    svc.sign_off("test-agent", tier="high", approver="a@bank.example")
    with pytest.raises(RegistryError, match="cannot be assessed"):
        svc.run_assessment("test-agent")
    assert svc.get_record("nope") is None


@pytest.mark.parametrize("tier", ["high", "limited", "minimal"])
def test_templates_are_valid_default_deny_policies(tier):
    text = (REPO_ROOT / "policies" / "templates" / f"{tier}.yaml").read_text(encoding="utf-8")
    policy = Policy.from_yaml(text.replace("__AGENT_ID__", "some-agent"))
    assert policy.rules == [] and policy.downstream == []
    assert policy.evaluate("anything", {}, {"agent": "some-agent"}).effect == "deny"


def test_knowledge_notes_carry_verify_markers_and_no_bare_references():
    for path in (REPO_ROOT / "knowledge").glob("eu-ai-act-*.md"):
        text = path.read_text(encoding="utf-8")
        assert "[VERIFY]" in text and "not the legal text" in text, path.name


@pytest.mark.parametrize("reserved", ["global", "unbound"])
def test_reserved_names_cannot_be_agent_ids(engine, reserved):
    """`global` is the kill-switch scope for every agent: an agent must never own that name."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="reserved"):
        card(reserved)
    svc = service(engine)
    with pytest.raises(RegistryError, match="reserved"):
        svc.registry.create_agent(reserved, name="x", owner="o@bank.example")


def test_sign_off_is_claimed_once(engine):
    svc = service(engine, assessment("limited"), review("agree", "limited"))
    svc.register(card(), actor="owner@bank.example")
    svc.sign_off("test-agent", tier="limited", approver="a@bank.example")
    with pytest.raises(RegistryError):
        svc.sign_off("test-agent", tier="prohibited", approver="b@bank.example")
    agent = svc.registry.get_agent("test-agent")
    assert agent.status == "active" and agent.tier == "limited"


def test_a_citation_without_the_verify_marker_is_rejected(engine):
    """FR-02: the model's citations must carry [VERIFY]; one without it fails validation."""
    unmarked = {**assessment(), "cited_provisions": ["Annex III, creditworthiness"]}
    svc = service(engine, unmarked)
    with pytest.raises(AssessmentError, match="VERIFY"):
        svc.register(card(), actor="owner@bank.example")
    assert svc.registry.get_agent("test-agent").status == "draft"
