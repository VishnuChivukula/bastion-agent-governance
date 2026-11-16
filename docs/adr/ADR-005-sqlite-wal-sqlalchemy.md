# ADR-005: SQLite (WAL) with SQLAlchemy 2.0

**Status:** accepted · 2026-11-16

## Context
The API process, the gateway and the console need shared state with no extra infrastructure.

## Decision
One SQLite database in WAL mode, accessed through SQLAlchemy 2.0. The audit log is an append-only table whose rows are hash-chained.

## Consequences
- Zero setup; the whole state is one file, which makes the demo reproducible.
- Single-writer semantics: fine for a demo, not for production throughput.
- SQLite cannot enforce append-only at the storage layer. Tamper **evidence** comes from the hash chain and `verify`, not from tamper prevention. A production system would also anchor the chain head externally.
- Known gap: truncating the newest events leaves a shorter but internally valid chain. Detecting that needs the chain head recorded somewhere else (for example in the evidence pack or an external store).
