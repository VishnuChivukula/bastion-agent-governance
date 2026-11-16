# ADR-002: Approvals are bound to exact arguments and are single-use

**Status:** accepted · 2026-11-16

## Context
If a human approves "a credit-limit change" in general, an agent (or an attacker steering it) can approve one value and execute another.

## Decision
A pending approval is bound to `(agent_id, tool, args_hash)`, where `args_hash` is the sha256 of the canonical JSON of the normalised arguments. Approval creates a single-use grant with a TTL. Only an identical call consumes it; any change to the arguments yields a different hash and a new pending approval.

## Consequences
- Defeats approve-then-swap and grant replay (USE_CASES UC-05; EVALS RT-13..RT-16).
- The agent must re-issue the identical call after approval, so argument normalisation has to be deterministic.
- Approvers see exactly what will execute (with PII redacted in the stored copy).
