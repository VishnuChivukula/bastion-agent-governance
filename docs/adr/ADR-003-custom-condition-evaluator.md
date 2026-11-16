# ADR-003: Custom AST evaluator for policy conditions

**Status:** accepted · 2026-11-16

## Context
Policy rules carry conditions such as `args.new_limit > 50000`. Policies are data that an approver can edit, so evaluating them must never execute arbitrary code.

## Decision
Conditions are parsed with Python's `ast` module and walked by a small evaluator that accepts only an explicit whitelist of node types: literals, boolean and comparison operators, arithmetic, `in`, attribute access on `args`, and a fixed set of functions (`len, lower, startswith, endswith, contains, pct_change, now_hour`). `eval()` and `exec()` are never used (ruff rules S102 and S307 enforce this).

## Consequences
- Anything outside the whitelist is rejected when the policy loads; an error at evaluation time results in `deny` with reason `condition_error` (fail closed).
- Less expressive than OPA/Rego, which is out of scope for v0.1.
- The module is small enough to target 100% branch coverage.
