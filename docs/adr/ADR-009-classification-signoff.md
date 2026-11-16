# ADR-009: Classification graph ends with a proposal; sign-off is a durable database state

**Status:** accepted · 2026-11-17

## Context
ARCHITECTURE §6.4 sketched registration as one LangGraph run that pauses at `interrupt(await_signoff)`. Sign-off can come days after the assessment, from a different person, possibly after a restart. Structured output was assumed to be available through forced tool use.

## Decision
- **The graph is `retrieve → assess → review → (revise once)` and then ends.** Its result is stored in `assessments` and the agent moves to `awaiting_signoff`. Sign-off is an ordinary service call (`ClassificationService.sign_off`) guarded by that status. No checkpoint has to be kept alive, and the wait survives restarts.
- **Structured output uses `output_config.format` (JSON schema)** and is validated again with Pydantic (bounds such as `confidence` 0–1 are not expressible in the schema). The configured smart model rejects forced `tool_choice`. A response that stops for any reason other than `end_turn` (refusal, truncation) is an error, never parsed.
- **Retrieval is "all four notes".** The knowledge base is four short paraphrased notes in `knowledge/`; ranking would add nothing. The notes are part of the prompt, so editing one requires re-recording fixtures.
- **Revision happens at most once.** If the Reviewer still recommends a different tier afterwards, the record is flagged `unresolved_disagreement` and the human decides.
- **Sign-off rules:** accepting the proposed tier needs no reason; any other tier needs one. `prohibited` sets the agent to `blocked` with no policy and no token. Otherwise the tier's template (`policies/templates/<tier>.yaml`) is activated, unless `policies/<agent-id>.yaml` exists, which takes precedence. The token is returned once and stored as a hash.
- **Templates contain no tool rules.** A newly signed-off agent is default-deny for every tool; the template sets budgets and incident rules for the tier. Tool rules are added as a reviewed policy version.
- **The Assessor and Reviewer are governed like any agent:** their model calls go through `GovernedAnthropic` (global kill switch, usage, audit) under the ids `bastion-assessor` and `bastion-reviewer`.
- **Seeding:** in replay mode the demo agent goes through this real flow at start-up, from fixtures, signed off by a named seed approver. In other modes it is seeded directly so start-up never calls a model API.

## Consequences
- The classification is decision support. The tier that counts is the one a human signed, and overrides are recorded with their reason.
- Registration of arbitrary cards needs live mode; replay covers the twelve sample cards exactly as written.
- Server-side refusal fallbacks are not configured: a refused classification surfaces as an error for a human to handle.
