# Bastion

**Runtime governance control plane for AI agents.** Every tool call an agent makes passes through a policy-enforcing MCP gateway: risk classification at registration, human approvals bound to exact arguments, kill switch, budgets, PII redaction, a tamper-evident audit log, incidents, red-team evals in CI and auto-generated regulatory evidence packs.

> **Disclaimer:** reference implementation; not production; not legal advice. All data is synthetic.

## Status

Under active construction, built in vertical slices. Current state: [`docs/PROGRESS.md`](docs/PROGRESS.md).

| Read | For |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | What is being built (requirements) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How, plus decision records in [`docs/adr/`](docs/adr/) |
| [`docs/USE_CASES.md`](docs/USE_CASES.md) | Scenarios and acceptance criteria |
| [`docs/SLICES.md`](docs/SLICES.md) | Build order |

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (it provides Python 3.12).

```bash
make setup   # install dependencies and git hooks
make check   # lint + tests
make help    # all targets
```

No API key is needed: the default mode is `replay`, which answers model calls from recorded fixtures.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
