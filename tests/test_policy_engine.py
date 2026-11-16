import pytest

from bastion.config import REPO_ROOT
from bastion.gateway.policy_engine import Policy, PolicyLoadError

SEED = (REPO_ROOT / "policies" / "loan-ops-agent.yaml").read_text()
CTX = {"agent": "loan-ops-agent"}


@pytest.fixture(scope="module")
def policy():
    return Policy.from_yaml(SEED)


def test_seed_policy_loads_and_is_hashed(policy):
    assert policy.agent == "loan-ops-agent"
    assert len(policy.content_hash) == 64
    assert Policy.from_yaml(SEED).content_hash == policy.content_hash
    assert Policy.from_yaml(SEED + "\n# comment").content_hash != policy.content_hash
    assert policy.budgets.max_tool_calls_per_session == 30


def test_first_match_wins(policy):
    big = policy.evaluate("update_credit_limit", {"current_limit": 40000, "new_limit": 60000}, CTX)
    assert (big.effect, big.rule_id) == ("require_approval", "R-003")
    pct = policy.evaluate("update_credit_limit", {"current_limit": 10000, "new_limit": 12500}, CTX)
    assert (pct.effect, pct.rule_id) == ("require_approval", "R-003")
    small = policy.evaluate(
        "update_credit_limit", {"current_limit": 10000, "new_limit": 11000}, CTX
    )
    assert (small.effect, small.rule_id) == ("allow", "R-004")
    assert big.policy_hash == policy.content_hash


def test_boundaries_of_r003(policy):
    at = policy.evaluate("update_credit_limit", {"current_limit": 50000, "new_limit": 50000}, CTX)
    assert at.rule_id == "R-004"  # exactly 50,000 and 0% is not "greater than"
    exactly_20 = policy.evaluate(
        "update_credit_limit", {"current_limit": 10000, "new_limit": 12000}, CTX
    )
    assert exactly_20.rule_id == "R-004"
    from_zero = policy.evaluate("update_credit_limit", {"current_limit": 0, "new_limit": 10}, CTX)
    assert from_zero.rule_id == "R-003"


def test_default_deny(policy):
    decision = policy.evaluate("delete_customer", {}, CTX)
    assert decision.effect == "deny" and decision.rule_id is None
    assert decision.reasons == ["default_deny"]
    assert Policy.from_yaml("agent: a").evaluate("anything", {}, {}).effect == "deny"


def test_tool_match_is_exact(policy):
    for name in ("Lookup_Customer", "lookup_customer ", "lookup"):
        assert policy.evaluate(name, {}, CTX).reasons == ["default_deny"]


def test_condition_error_denies_and_does_not_fall_through(policy):
    decision = policy.evaluate("update_credit_limit", {"new_limit": "abc"}, CTX)
    assert decision.effect == "deny" and decision.rule_id == "R-003"
    assert decision.reasons[0].startswith("condition_error")
    missing = policy.evaluate("update_credit_limit", {}, CTX)
    assert missing.effect == "deny" and missing.reasons[0].startswith("condition_error")


def test_allow_carries_redactions_and_scan_but_deny_does_not(policy):
    allow = policy.evaluate("lookup_customer", {}, CTX)
    assert allow.redactions == ["EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"]
    email = policy.evaluate("send_email", {"to": "ops@bank.example"}, CTX)
    assert email.rule_id == "R-005" and email.scan_input.action == "require_approval"
    external = policy.evaluate("send_email", {"to": "x@elsewhere.example"}, CTX)
    assert external.rule_id == "R-006" and external.scan_input is None
    deny = policy.evaluate("export_customer_data", {}, CTX)
    assert deny.category == "exfiltration" and deny.redactions == []


def test_visible_tools_exclude_denied_ones(policy):
    assert policy.visible_tools() == {
        "lookup_customer",
        "get_customer_notes",
        "update_credit_limit",
        "send_email",
    }


def test_unconditional_deny(policy):
    assert policy.unconditional_deny("export_customer_data").rule_id == "R-007"
    assert policy.unconditional_deny("lookup_customer") is None
    assert policy.unconditional_deny("update_credit_limit") is None
    assert policy.unconditional_deny("nope") is None


def test_incident_rules_compile_and_match(policy):
    ir1, ir2 = policy.incident_rules
    assert ir1.matches({"deny_count_10m": 3, "category": None})
    assert not ir1.matches({"deny_count_10m": 2, "category": None})
    assert ir2.matches({"deny_count_10m": 0, "category": "exfiltration"})
    assert not ir2.matches({"deny_count_10m": 0, "category": None})
    assert not ir2.matches({})  # missing context never matches
    assert ir2.on_incident == "kill"


@pytest.mark.parametrize(
    "text",
    [
        "- just\n- a list",
        "agent: a\nrules:\n  - {id: R, tool: t, effect: maybe}",
        "agent: a\nrules:\n  - {id: R, tool: t, effect: allow, when: \"__import__('os')\"}",
        "agent: a\nrules:\n  - {id: R, tool: t, effect: allow, surprise: 1}",
        "agent: a\nrules:\n  - {id: R, tool: t, effect: allow}\n  - {id: R, tool: u, effect: deny}",
        "agent: a\nincident_rules:\n  - {id: I, when: 'eval(1)', severity: high}",
        "agent: a\nbudgets: {max_tool_calls_per_session: -1}",
        "agent: a\nunknown_section: 1",
        "rules: []",
        "agent: [unclosed",
    ],
)
def test_invalid_policies_do_not_load(text):
    with pytest.raises(PolicyLoadError):
        Policy.from_yaml(text)
