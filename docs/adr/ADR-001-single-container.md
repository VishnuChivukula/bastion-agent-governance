# ADR-001: Single container, two processes

**Status:** accepted · 2026-11-16

## Context
The showcase must run with one command locally and deploy to a single small hosted service at no cost.

## Decision
One container runs two processes under `honcho`: the FastAPI control-plane API (which also mounts the MCP gateway at `/mcp`) and the Streamlit console. The demo tools MCP server is spawned by the gateway over stdio.

## Consequences
- Simple to run, deploy and reason about; one SQLite file is shared by both processes.
- Not horizontally scalable, and the gateway shares a failure domain with the API. Acceptable for a reference implementation; a production design would separate the enforcement point.
- Fallback: if mounting the MCP app inside FastAPI proves awkward, the gateway becomes a third process on port 8100 (to be recorded in a new ADR).
