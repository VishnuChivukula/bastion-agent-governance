"""The condition evaluator is the part of the policy engine that touches untrusted text."""

import math

import pytest

from bastion.gateway import conditions
from bastion.gateway.conditions import ConditionError, compile_condition


def ev(source, **context):
    return compile_condition(source).evaluate(context)


ARGS = {"new_limit": 60000, "current_limit": 40000, "to": "ops@bank.example", "tags": ["a", "b"]}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("args.new_limit > 50000", True),
        ("args.new_limit >= 60000 and args.new_limit <= 60000", True),
        ("args.new_limit < 50000", False),
        ("args.new_limit == 60000", True),
        ("args.new_limit != 60000", False),
        ("40000 < args.new_limit < 70000", True),
        ("40000 < args.new_limit < 50000", False),
        ("args.new_limit > 50000 or pct_change(args.current_limit, args.new_limit) > 20", True),
        ("pct_change(args.current_limit, args.new_limit) > 20", True),
        ("pct_change(args.current_limit, args.new_limit) == 50", True),
        ("not (args.new_limit > 50000)", False),
        ("endswith(args.to, '@bank.example')", True),
        ("startswith(args.to, 'ops@')", True),
        ("contains(args.to, 'bank')", True),
        ("contains(args.tags, 'a')", True),
        ("'a' in args.tags", True),
        ("'z' not in args.tags", True),
        ("'bank' in args.to", True),
        ("args.to in ['ops@bank.example', 'risk@bank.example']", True),
        ("args.to in ('x@bank.example',)", False),
        ("lower('ABC') == 'abc'", True),
        ("len(args.tags) == 2", True),
        ("len(args.to) > 5", True),
        ("args.new_limit - args.current_limit == 20000", True),
        ("args.new_limit + 1 == 60001", True),
        ("args.new_limit * 2 == 120000", True),
        ("args.new_limit / 2 == 30000", True),
        ("args.new_limit % 7 == 3", True),
        ("-args.new_limit < 0", True),
        ("'a' < 'b'", True),
        ("True", True),
        ("False or True", True),
        ("True and False", False),
        ("category == 'exfiltration'", True),
        ("deny_count_10m >= 3", True),
        ("tier == 'high' and agent == 'loan-ops-agent'", True),
        ("0 <= now_hour() <= 23", True),
        ("1 == 1.0", True),
    ],
)
def test_allowed_expressions(source, expected):
    context = {
        "args": ARGS,
        "category": "exfiltration",
        "deny_count_10m": 3,
        "tier": "high",
        "agent": "loan-ops-agent",
    }
    assert ev(source, **context) is expected


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('id')",
        "__import__('os')",
        "eval('1')",
        "exec('1')",
        "open('/etc/passwd')",
        "getattr(args, 'x')",
        "args.__class__",
        "args._private",
        "args.a.b",
        "tier.upper()",
        "args.to.lower()",
        "().__class__.__bases__",
        "[x for x in args.tags]",
        "lambda: 1",
        "args.new_limit if True else 0",
        "args['new_limit']",
        "2 ** 100",
        "1 << 2",
        "1 | 2",
        "~1",
        "+1 > 0",
        "1 is 1",
        "f'{args.to}'",
        "b'bytes' == 1",
        "{'a': 1}",
        "{1, 2}",
        "x := 1",
        "unknown_name > 1",
        "os.system",
        "len(args.to, 2)",
        "len()",
        "len(*args.tags)",
        "lower(value='x')",
        "pct_change(1)",
        "1; 2",
        "import os",
        "",
        "   ",
        "((((",
        "1 + ",
        "a" * 501,
        " or ".join(["True"] * 120),
        "1+" * 60 + "1 > 0",
    ],
)
def test_everything_else_is_rejected_at_load(source):
    with pytest.raises(ConditionError):
        compile_condition(source)


def test_non_string_condition_is_rejected():
    with pytest.raises(ConditionError):
        compile_condition(None)


@pytest.mark.parametrize(
    "source",
    [
        "args.missing > 1",  # missing argument
        "args.new_limit > 'abc'",  # mixed ordering
        "args.to > 5",
        "args.new_limit / 0 > 1",  # division by zero
        "args.new_limit % 0 == 1",
        "args.to + 1 == 2",  # arithmetic on a string
        "-args.to == 1",
        "args.new_limit",  # not a bool
        "args.to",
        "len(args.new_limit) > 1",
        "lower(args.new_limit) == 'x'",
        "startswith(args.new_limit, 'x')",
        "endswith(args.to, 5)",
        "contains(args.new_limit, 1)",
        "contains(args.to, 5)",
        "5 in args.new_limit",
        "pct_change(args.to, 1) > 1",
        "not args.new_limit",
        "args.new_limit and True",
        "False or args.missing > 1",
        "category == 'x'",  # name not provided in this context
        "True > False",  # bools are not numbers
        "args.flag + 1 > 1",
    ],
)
def test_evaluation_errors_raise_so_the_engine_can_fail_closed(source):
    with pytest.raises(ConditionError):
        ev(source, args={**ARGS, "flag": True})


def test_missing_args_namespace_is_an_error():
    with pytest.raises(ConditionError):
        ev("args.x == 1")
    with pytest.raises(ConditionError):
        ev("args.x == 1", args="not a mapping")


def test_bool_is_not_equal_to_one():
    assert ev("args.flag == 1", args={"flag": True}) is False
    assert ev("args.flag != 1", args={"flag": True}) is True
    assert ev("args.flag == True", args={"flag": True}) is True
    assert ev("args.x == None", args={"x": None}) is True
    assert ev("args.x == 'None'", args={"x": None}) is False


def test_short_circuit_skips_the_failing_branch():
    assert ev("True or args.missing > 1", args={}) is True
    assert ev("False and args.missing > 1", args={}) is False


def test_pct_change_from_zero_fails_safe():
    assert conditions._pct_change(0, 0) == 0.0
    assert conditions._pct_change(0, 10) == math.inf
    assert ev("pct_change(args.a, args.b) > 20", args={"a": 0, "b": 1}) is True
    assert conditions._pct_change(100, 80) == -20
    assert conditions._pct_change(-100, -50) == 50


def test_condition_repr_and_source():
    condition = compile_condition("  tier == 'high' ")
    assert condition.source == "  tier == 'high' "
    assert "tier" in repr(condition)


def test_no_eval_or_exec_in_the_module():
    import inspect
    import re

    source = inspect.getsource(conditions)
    assert not re.search(r"(?<![\w.])(eval|exec)\(", source.replace("eval(), no exec()", ""))
