"""Registration, classification and human sign-off (FR-01..FR-05, UC-01).

submit card ─▶ draft ─▶ assessing ─▶ awaiting_signoff ─▶ active (policy + token)
                                                    └──▶ blocked (tier: prohibited)
"""

from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import Engine, select, update

from bastion.audit.log import AuditLog
from bastion.config import REPO_ROOT, Settings, get_settings
from bastion.db import session_scope
from bastion.llm import GovernedAnthropic
from bastion.llm.governance import GovernanceHook
from bastion.models import Agent, iso
from bastion.models import AgentCard as AgentCardRow
from bastion.models import Assessment as AssessmentRow
from bastion.registry.assessor_graph import ASSESSOR_ID, REVIEWER_ID, AssessorDeps, classify
from bastion.registry.models import TIERS, AgentCard, Assessment, Classification, Review
from bastion.registry.service import PolicyStore, Registry, RegistryError

POLICIES_DIR = REPO_ROOT / "policies"


class SignOffResult(BaseModel):
    agent_id: str
    status: str  # active / blocked
    final_tier: str
    proposed_tier: str
    overridden: bool
    template: str | None = None
    policy_source: str | None = None  # "template" or "agent-specific"
    policy_hash: str | None = None
    token: str | None = None  # shown once; only its hash is stored


class RegistrationRecord(BaseModel):
    agent_id: str
    status: str
    tier: str | None
    card: AgentCard | None = None
    classification: Classification | None = None
    proposed_tier: str | None = None
    unresolved_disagreement: bool = False
    final_tier: str | None = None
    signed_off_by: str | None = None
    signed_at: str | None = None
    override_reason: str | None = None


class ClassificationService:
    def __init__(
        self,
        engine: Engine,
        audit: AuditLog | None = None,
        *,
        settings: Settings | None = None,
        policies_dir: Path = POLICIES_DIR,
        transport=None,
    ) -> None:
        self.engine = engine
        self.audit = audit or AuditLog(engine)
        self.settings = settings or get_settings()
        self.registry = Registry(engine, self.audit)
        self.policies = PolicyStore(engine, self.audit)
        self.policies_dir = policies_dir
        self._transport = transport  # tests inject a scripted model here

    # --- model plumbing ------------------------------------------------------------------------
    def deps(self) -> AssessorDeps:
        def client(agent_id: str) -> GovernedAnthropic:
            return GovernedAnthropic(
                agent_id,
                settings=self.settings,
                transport=self._transport,
                mode="live" if self._transport is not None else None,
                hooks=[GovernanceHook(self.engine, self.audit)],
            )

        return AssessorDeps(
            assessor=client(ASSESSOR_ID), reviewer=client(REVIEWER_ID),
            model=self.settings.model_smart,
        )  # fmt: skip

    # --- steps ---------------------------------------------------------------------------------
    def submit_card(self, card: AgentCard, *, actor: str) -> None:
        """Register a draft agent from its card (FR-01). No credential exists yet."""
        self.registry.create_agent(
            card.id, name=card.name, owner=card.owner, status="draft", actor=actor
        )
        with session_scope(self.engine) as session:
            session.add(AgentCardRow(agent_id=card.id, version=1, card_json=card.model_dump_json()))
        self.audit.append(
            "agent_card_submitted",
            actor=actor,
            agent_id=card.id,
            payload={
                "autonomy_level": card.autonomy_level,
                "tools_requested": card.tools_requested,
                "personal_data": card.personal_data,
                "special_category_data": card.special_category_data,
            },
        )

    def _set_status(self, agent_id: str, status: str, tier: str | None = None) -> None:
        with session_scope(self.engine) as session:
            agent = session.get(Agent, agent_id)
            agent.status = status
            if tier is not None:
                agent.tier = tier

    def run_assessment(self, agent_id: str) -> Classification:
        """Assessor proposes, Reviewer challenges, Assessor revises once (FR-02, FR-03)."""
        card = self.get_card(agent_id)
        agent = self.registry.get_agent(agent_id)
        if card is None or agent is None:
            raise RegistryError(f"unknown agent '{agent_id}'")
        if agent.status not in ("draft", "awaiting_signoff"):
            raise RegistryError(f"agent '{agent_id}' is {agent.status}; it cannot be assessed")
        self._set_status(agent_id, "assessing")
        try:
            result = classify(self.deps(), card)
        except BaseException:
            self._set_status(agent_id, agent.status)
            raise
        with session_scope(self.engine) as session:
            session.add(
                AssessmentRow(
                    agent_id=agent_id,
                    assessor_json=result.assessment.model_dump_json(),
                    reviewer_json=result.review.model_dump_json(),
                    revised_json=result.revised.model_dump_json() if result.revised else None,
                )
            )
        self._set_status(agent_id, "awaiting_signoff")
        self.audit.append(
            "assessment_completed",
            actor=ASSESSOR_ID,
            agent_id=agent_id,
            payload={
                "assessor_tier": result.assessment.tier,
                "reviewer_verdict": result.review.verdict,
                "reviewer_tier": result.review.recommended_tier,
                "revised_tier": result.revised.tier if result.revised else None,
                "proposed_tier": result.proposed.tier,
                "confidence": result.proposed.confidence,
                "unresolved_disagreement": result.unresolved_disagreement,
            },
        )
        return result

    def register(self, card: AgentCard, *, actor: str) -> Classification:
        self.submit_card(card, actor=actor)
        return self.run_assessment(card.id)

    def sign_off(
        self, agent_id: str, *, tier: str, approver: str, override_reason: str | None = None
    ) -> SignOffResult:
        """Human decision (FR-04). Accept the proposed tier, or override it with a reason.
        `prohibited` blocks the agent; otherwise a policy is activated and the token issued."""
        if tier not in TIERS:
            raise RegistryError(f"unknown tier '{tier}'")
        record = self.get_record(agent_id)
        if record is None:
            raise RegistryError(f"unknown agent '{agent_id}'")
        if record.status != "awaiting_signoff" or record.classification is None:
            raise RegistryError(f"agent '{agent_id}' is {record.status}, not awaiting sign-off")
        proposed = record.classification.proposed.tier
        overridden = tier != proposed
        reason = (override_reason or "").strip()
        if overridden and not reason:
            raise RegistryError(
                f"overriding the proposed tier '{proposed}' with '{tier}' needs a reason"
            )
        signed_at = iso()
        blocked = tier == "prohibited"
        with session_scope(self.engine) as session:
            # One conditional UPDATE decides who signs: two concurrent sign-offs cannot both win.
            claimed = session.execute(
                update(Agent)
                .where(Agent.id == agent_id, Agent.status == "awaiting_signoff")
                .values(status="blocked" if blocked else "active", tier=tier)
            )
            if claimed.rowcount != 1:
                raise RegistryError(f"agent '{agent_id}' is no longer awaiting sign-off")
            row = session.scalar(
                select(AssessmentRow)
                .where(AssessmentRow.agent_id == agent_id)
                .order_by(AssessmentRow.id.desc())
            )
            row.final_tier, row.signed_off_by, row.signed_at = tier, approver, signed_at
            row.override_reason = reason or None
        self.audit.append(
            "signoff_recorded",
            actor=approver,
            agent_id=agent_id,
            payload={
                "final_tier": tier,
                "proposed_tier": proposed,
                "overridden": overridden,
                "override_reason": reason or None,
                "outcome": "blocked" if blocked else "active",
            },
        )
        result = SignOffResult(
            agent_id=agent_id, status="blocked" if blocked else "active", final_tier=tier,
            proposed_tier=proposed, overridden=overridden,
        )  # fmt: skip
        if blocked:
            return result  # no policy, no credential (FR-04)
        text, source = self.policy_for(agent_id, tier)
        policy = self.policies.activate(agent_id, text, created_by=approver)
        result.template, result.policy_source = tier, source
        result.policy_hash = policy.content_hash
        result.token = self.registry.issue_token(agent_id, actor=approver)
        return result

    def policy_for(self, agent_id: str, tier: str) -> tuple[str, str]:
        """The tier's template, unless an agent-specific policy overrides it (FR-05)."""
        specific = self.policies_dir / f"{agent_id}.yaml"
        if specific.is_file():
            return specific.read_text(encoding="utf-8"), "agent-specific"
        template = (self.policies_dir / "templates" / f"{tier}.yaml").read_text(encoding="utf-8")
        return template.replace("__AGENT_ID__", agent_id), "template"

    # --- reads ---------------------------------------------------------------------------------
    def get_card(self, agent_id: str) -> AgentCard | None:
        with session_scope(self.engine) as session:
            raw = session.scalar(
                select(AgentCardRow.card_json)
                .where(AgentCardRow.agent_id == agent_id)
                .order_by(AgentCardRow.version.desc())
            )
        return AgentCard.model_validate_json(raw) if raw else None

    def get_record(self, agent_id: str) -> RegistrationRecord | None:
        agent = self.registry.get_agent(agent_id)
        if agent is None:
            return None
        record = RegistrationRecord(
            agent_id=agent.id, status=agent.status, tier=agent.tier, card=self.get_card(agent_id)
        )
        with session_scope(self.engine) as session:
            row = session.scalar(
                select(AssessmentRow)
                .where(AssessmentRow.agent_id == agent_id)
                .order_by(AssessmentRow.id.desc())
            )
        if row is not None and row.assessor_json and row.reviewer_json:
            record.classification = Classification(
                assessment=Assessment.model_validate_json(row.assessor_json),
                review=Review.model_validate_json(row.reviewer_json),
                revised=Assessment.model_validate_json(row.revised_json)
                if row.revised_json
                else None,
            )
            record.proposed_tier = record.classification.proposed.tier
            record.unresolved_disagreement = record.classification.unresolved_disagreement
        if row is not None:
            record.final_tier, record.signed_off_by = row.final_tier, row.signed_off_by
            record.signed_at, record.override_reason = row.signed_at, row.override_reason
        return record


def load_card(path: Path) -> AgentCard:
    import yaml

    return AgentCard.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sample_cards(directory: Path = REPO_ROOT / "evals" / "assessor" / "cards") -> list[AgentCard]:
    return [load_card(path) for path in sorted(directory.glob("*.yaml"))]
