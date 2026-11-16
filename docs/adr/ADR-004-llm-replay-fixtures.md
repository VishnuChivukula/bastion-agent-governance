# ADR-004: Record/replay fixtures for model calls

**Status:** accepted · 2026-11-16

## Context
`make demo`, CI and the public demo must run with no API key, at zero cost, deterministically.

## Decision
All model calls go through `GovernedAnthropic`. Modes: `replay` (default; fixtures only, a miss raises `ReplayMissError`), `record` (call the API, save the response), `live`. A fixture is stored at `fixtures/llm/<key>.json`, where the key is the sha256 of the canonical JSON of the request.

## Deviations from ARCHITECTURE.md §7
- **No `temperature=0`.** The configured models (`claude-haiku-5-5`, `claude-sonnet-5-5`) reject non-default sampling parameters, so none is sent. Determinism comes from replay, not from sampling settings.
- **The key covers the whole request**, not a fixed field list, so parameters such as `output_config` (structured output) also distinguish fixtures. Parameters set to `None` are dropped before hashing.

## Consequences
- Replay needs neither a key nor the network, and never constructs the SDK client.
- Any change to a prompt, tool schema or tool result changes the key and needs a re-record. Tool results must therefore be deterministic (seeded data; volatile ids and timestamps are kept out of what the model sees or normalised before hashing).
- Governance controls attach as call hooks: `before_call` can block (budget, kill switch); `after_call` records usage and audit events.
