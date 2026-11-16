"""Safe evaluator for policy conditions (ADR-003). No eval(), no exec().

A condition is parsed with `ast` and checked against an explicit whitelist when the policy
loads; anything else is rejected. Evaluation walks the tree. Any error at evaluation time
raises ConditionError, which the policy engine turns into `deny` (fail closed).

Grammar: literals, lists/tuples of literals, `and` / `or` / `not`, comparisons, `in` / `not in`,
`+ - * / %` on numbers, `args.<field>`, and calls to the whitelisted functions below.
"""

import ast
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

MAX_LENGTH = 500
MAX_NODES = 100

CONTEXT_NAMES = frozenset({"args", "agent", "tier", "deny_count_10m", "category"})


class ConditionError(Exception):
    """The condition is not allowed, or could not be evaluated."""


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _need_str(name: str, *values: Any) -> None:
    if not all(isinstance(v, str) for v in values):
        raise ConditionError(f"{name}() needs string arguments")


def _len(value: Any) -> int:
    if not isinstance(value, str | list | tuple | dict):
        raise ConditionError("len() needs a string or a list")
    return len(value)


def _lower(value: Any) -> str:
    _need_str("lower", value)
    return value.lower()


def _startswith(value: Any, prefix: Any) -> bool:
    _need_str("startswith", value, prefix)
    return value.startswith(prefix)


def _endswith(value: Any, suffix: Any) -> bool:
    _need_str("endswith", value, suffix)
    return value.endswith(suffix)


def _contains(container: Any, item: Any) -> bool:
    if isinstance(container, str):
        _need_str("contains", item)
        return item in container
    if isinstance(container, list | tuple):
        return item in container
    raise ConditionError("contains() needs a string or a list")


def _pct_change(old: Any, new: Any) -> float:
    """Percentage change from old to new. From zero, any increase counts as infinite."""
    if not (_is_number(old) and _is_number(new)):
        raise ConditionError("pct_change() needs numbers")
    if old == 0:
        return 0.0 if new == 0 else math.inf
    return (new - old) / abs(old) * 100


def _now_hour() -> int:
    return datetime.now(UTC).hour


FUNCTIONS: dict[str, tuple[Callable[..., Any], int]] = {
    "len": (_len, 1),
    "lower": (_lower, 1),
    "startswith": (_startswith, 2),
    "endswith": (_endswith, 2),
    "contains": (_contains, 2),
    "pct_change": (_pct_change, 2),
    "now_hour": (_now_hour, 0),
}

_ARITHMETIC: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}
_ORDERING: dict[type, Callable[[Any, Any], bool]] = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}
_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn, *_ORDERING)


def _validate(node: ast.AST) -> None:
    """Reject every construct outside the whitelist. Runs once, at policy load."""
    match node:
        case ast.Expression(body=body):
            _validate(body)
        case ast.Constant(value=value):
            if not (value is None or isinstance(value, str | int | float | bool)):
                raise ConditionError(f"literal of type {type(value).__name__} is not allowed")
        case ast.List(elts=elts) | ast.Tuple(elts=elts):
            for elt in elts:
                _validate(elt)
        case ast.Name(id=name):
            if name not in CONTEXT_NAMES:
                raise ConditionError(f"unknown name '{name}'")
        case ast.Attribute(value=ast.Name(id="args"), attr=attr):
            if attr.startswith("_"):
                raise ConditionError(f"attribute '{attr}' is not allowed")
        case ast.Attribute():
            raise ConditionError("attribute access is only allowed on 'args'")
        case ast.BoolOp(op=ast.And() | ast.Or(), values=values):
            for value in values:
                _validate(value)
        case ast.UnaryOp(op=ast.Not() | ast.USub(), operand=operand):
            _validate(operand)
        case ast.BinOp(left=left, op=op, right=right):
            if type(op) not in _ARITHMETIC:
                raise ConditionError(f"operator {type(op).__name__} is not allowed")
            _validate(left)
            _validate(right)
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            for op in ops:
                if not isinstance(op, _COMPARE_OPS):
                    raise ConditionError(f"comparison {type(op).__name__} is not allowed")
            _validate(left)
            for comparator in comparators:
                _validate(comparator)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=keywords):
            if name not in FUNCTIONS:
                raise ConditionError(f"unknown function '{name}'")
            if keywords or any(isinstance(a, ast.Starred) for a in args):
                raise ConditionError(f"{name}() takes positional arguments only")
            if len(args) != FUNCTIONS[name][1]:
                raise ConditionError(f"{name}() takes {FUNCTIONS[name][1]} argument(s)")
            for arg in args:
                _validate(arg)
        case _:
            raise ConditionError(f"{type(node).__name__} is not allowed in a condition")


class Condition:
    """A validated condition. Build with `compile_condition`."""

    def __init__(self, source: str, tree: ast.Expression) -> None:
        self.source = source
        self._tree = tree

    def __repr__(self) -> str:
        return f"Condition({self.source!r})"

    def evaluate(self, context: Mapping[str, Any]) -> bool:
        """Evaluate to a strict bool; raises ConditionError otherwise."""
        try:
            result = self._eval(self._tree.body, context)
        except ConditionError:
            raise
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ConditionError(f"evaluation failed: {exc}") from exc
        if not isinstance(result, bool):
            raise ConditionError("condition must evaluate to true or false")
        return result

    def _eval(self, node: ast.AST, ctx: Mapping[str, Any]) -> Any:
        match node:
            case ast.Constant(value=value):
                return value
            case ast.List(elts=elts) | ast.Tuple(elts=elts):
                return [self._eval(elt, ctx) for elt in elts]
            case ast.Name(id=name):
                if name not in ctx:
                    raise ConditionError(f"'{name}' is not available in this context")
                return ctx[name]
            case ast.Attribute(attr=attr):
                args = ctx.get("args")
                if not isinstance(args, Mapping) or attr not in args:
                    raise ConditionError(f"argument '{attr}' is missing")
                return args[attr]
            case ast.BoolOp(op=op, values=values):
                is_and = isinstance(op, ast.And)
                for value_node in values:
                    value = self._eval(value_node, ctx)
                    if not isinstance(value, bool):
                        raise ConditionError("'and' / 'or' need true/false operands")
                    if value != is_and:  # short-circuit
                        return value
                return is_and
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                value = self._eval(operand, ctx)
                if not isinstance(value, bool):
                    raise ConditionError("'not' needs a true/false operand")
                return not value
            case ast.UnaryOp(operand=operand):  # USub
                value = self._eval(operand, ctx)
                if not _is_number(value):
                    raise ConditionError("unary minus needs a number")
                return -value
            case ast.BinOp(left=left, op=op, right=right):
                a, b = self._eval(left, ctx), self._eval(right, ctx)
                if not (_is_number(a) and _is_number(b)):
                    raise ConditionError("arithmetic needs numbers")
                return _ARITHMETIC[type(op)](a, b)
            case ast.Compare(left=left, ops=ops, comparators=comparators):
                current = self._eval(left, ctx)
                for op, comparator in zip(ops, comparators, strict=True):
                    other = self._eval(comparator, ctx)
                    if not self._compare(op, current, other):
                        return False
                    current = other
                return True
            case ast.Call(func=ast.Name(id=name), args=args):
                return FUNCTIONS[name][0](*(self._eval(arg, ctx) for arg in args))
        raise ConditionError(f"{type(node).__name__} is not allowed")  # pragma: no cover

    @staticmethod
    def _compare(op: ast.cmpop, a: Any, b: Any) -> bool:
        if isinstance(op, ast.Eq | ast.NotEq):
            # bool is not a number here: True == 1 must not hold.
            equal = type(a) is type(b) and a == b or (_is_number(a) and _is_number(b) and a == b)
            return equal if isinstance(op, ast.Eq) else not equal
        if isinstance(op, ast.In | ast.NotIn):
            found = _contains(b, a)
            return found if isinstance(op, ast.In) else not found
        both_numbers = _is_number(a) and _is_number(b)
        both_strings = isinstance(a, str) and isinstance(b, str)
        if not (both_numbers or both_strings):
            raise ConditionError("ordering needs two numbers or two strings")
        return _ORDERING[type(op)](a, b)


def compile_condition(source: str) -> Condition:
    if not isinstance(source, str) or not source.strip():
        raise ConditionError("condition is empty")
    if len(source) > MAX_LENGTH:
        raise ConditionError(f"condition is longer than {MAX_LENGTH} characters")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ConditionError(f"syntax error: {exc}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ConditionError("condition is too complex")
    _validate(tree)
    return Condition(source, tree)
