"""Policy-as-code: YAML, ordered rules, first match wins, default deny (FR-12, FR-15)."""

import hashlib
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from bastion.gateway.conditions import Condition, ConditionError, compile_condition

Effect = Literal["allow", "deny", "require_approval"]
ScanAction = Literal["deny", "require_approval", "redact"]


class PolicyLoadError(Exception):
    """The policy document is invalid. It is never activated."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Downstream(_Strict):
    name: str
    command: list[str] = Field(min_length=1)


class Budgets(_Strict):
    max_tool_calls_per_session: int | None = Field(None, ge=0)
    max_tokens_per_session: int | None = Field(None, ge=0)
    max_cost_usd_per_day: float | None = Field(None, ge=0)


class ScanInput(_Strict):
    entities: list[str] = Field(min_length=1)
    action: ScanAction = "require_approval"


class Rule(_Strict):
    id: str
    tool: str
    effect: Effect
    when: str | None = None
    redact_output: list[str] = Field(default_factory=list)
    scan_input: ScanInput | None = None
    category: str | None = None
    _condition: Condition | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _compile(self) -> "Rule":
        if self.when is not None:
            try:
                self._condition = compile_condition(self.when)
            except ConditionError as exc:
                raise ValueError(f"rule {self.id}: invalid condition: {exc}") from exc
        return self


class IncidentRule(_Strict):
    id: str
    when: str
    severity: Literal["low", "medium", "high", "critical"]
    on_incident: Literal["kill"] | None = None
    _condition: Condition | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _compile(self) -> "IncidentRule":
        try:
            self._condition = compile_condition(self.when)
        except ConditionError as exc:
            raise ValueError(f"incident rule {self.id}: invalid condition: {exc}") from exc
        return self

    def matches(self, context: dict[str, Any]) -> bool:
        try:
            return self._condition.evaluate(context)  # type: ignore[union-attr]
        except ConditionError:
            return False


class Decision(BaseModel):
    effect: Effect
    rule_id: str | None = None
    policy_hash: str = ""
    reasons: list[str] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)  # entity types to mask in the output
    scan_input: ScanInput | None = None
    category: str | None = None


class Policy(_Strict):
    agent: str
    version_note: str = ""
    downstream: list[Downstream] = Field(default_factory=list)
    budgets: Budgets = Field(default_factory=Budgets)
    incident_rules: list[IncidentRule] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    _hash: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def _unique_ids(self) -> "Policy":
        for kind, items in (("rule", self.rules), ("incident rule", self.incident_rules)):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {kind} ids")
        return self

    @property
    def content_hash(self) -> str:
        return self._hash

    @classmethod
    def from_yaml(cls, text: str) -> "Policy":
        try:
            data = yaml.safe_load(text)
            if not isinstance(data, dict):
                raise PolicyLoadError("policy must be a YAML mapping")
            policy = cls.model_validate(data)
        except (yaml.YAMLError, ValidationError) as exc:
            raise PolicyLoadError(str(exc)) from exc
        policy._hash = content_hash(text)
        return policy

    def visible_tools(self) -> set[str]:
        """Tools an agent may discover: any rule that can allow or route to approval (FR-11)."""
        return {r.tool for r in self.rules if r.effect in ("allow", "require_approval")}

    def evaluate(self, tool: str, args: dict[str, Any], context: dict[str, Any]) -> Decision:
        """First matching rule wins. No match is a deny. A condition error is a deny."""
        ctx = {**context, "args": args}
        for rule in self.rules:
            if rule.tool != tool:  # exact match only
                continue
            if rule._condition is not None:
                try:
                    if not rule._condition.evaluate(ctx):
                        continue
                except ConditionError as exc:
                    return self._decision("deny", rule, [f"condition_error: {exc}"])
            return self._decision(rule.effect, rule, [f"matched {rule.id}"])
        return Decision(effect="deny", policy_hash=self._hash, reasons=["default_deny"])

    def unconditional_deny(self, tool: str) -> Decision | None:
        """The deny that applies to a tool whatever its arguments, if the policy has one.

        Used when arguments are malformed: an always-denied tool (e.g. an exfiltration tool)
        should still be reported under its own rule and category.
        """
        for rule in self.rules:
            if rule.tool == tool:
                if rule.when is None and rule.effect == "deny":
                    return self._decision("deny", rule, [f"matched {rule.id}"])
                return None
        return None

    def _decision(self, effect: Effect, rule: Rule, reasons: list[str]) -> Decision:
        return Decision(
            effect=effect,
            rule_id=rule.id,
            policy_hash=self._hash,
            reasons=reasons,
            redactions=list(rule.redact_output) if effect == "allow" else [],
            scan_input=rule.scan_input if effect == "allow" else None,
            category=rule.category,
        )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
