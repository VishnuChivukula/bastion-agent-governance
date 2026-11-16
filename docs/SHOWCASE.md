**Bastion Kit · SHOWCASE.md**

# Bastion showcase material

> Reference implementation; not production; not legal advice. All data is synthetic.

Launch copy, interview talking points and a pre-sales narrative. Facts are limited to what the README says is built. Regulatory references carry `[VERIFY]` and are listed in [`VERIFY.md`](VERIFY.md).

## LinkedIn launch post

```text
Agents now act, not just answer. They update records, send email and export data. Most governance tooling describes an agent; very little controls it at the moment it acts.

I built Bastion, an open-source reference implementation of a runtime governance control plane for AI agents. It does three things:

1. Enforcement at the tool call. Every call passes an MCP gateway with default-deny policy-as-code. A poisoned customer note that says to export all customers is denied, an incident opens and the agent is stopped.

2. Approvals bound to exact arguments. A human approves a 60,000 credit limit; a call with 600,000 hashes differently and cannot use that approval.

3. Evidence you can hand to an auditor. A hash-chained audit log, red-team results that gate CI and a generated evidence pack.

It runs with no API key: make demo replays recorded model responses while the gateway, policy and audit run live.

Reference implementation, not production, not legal advice. All data is synthetic.

Repo link in the comments.

#AIGovernance #AIAgents #ModelRisk #EUAIAct #OpenSource
```

<!-- Character count: 1,081 including spaces and line breaks (counted by hand; the limit is 1,300). -->

## 60-second pitch

Agents now act. They update customer records, send email and export data, and most governance tooling only describes them in an inventory or a questionnaire. Bastion controls them at the moment of action. Every tool call an agent makes passes through an MCP gateway that checks a policy written as data. A tool with no matching rule is denied. Large or risky actions pause for a human, and the approval is tied to the exact arguments, so approving a 60,000 limit does not authorise 600,000. A kill switch stops an agent in one click, and every decision lands in a hash-chained audit log. Twenty-five red-team scenarios and fifteen benign ones run on every commit, and the build fails if a threshold is missed. From the live records Bastion generates an evidence pack for an auditor. It runs with no API key through recorded model responses. It is a reference implementation, not production, and not legal advice.

<!-- About 156 spoken words. -->

## Five interview talking points

### 1. Approvals bound to exact arguments, single use

- **Design decision:** an approval is bound to agent, tool and the sha256 of the canonical, normalised arguments. It creates a single-use grant with a TTL.
- **Trade-off:** the agent must re-issue the identical call, so argument normalisation has to be deterministic.
- **Evidence:** [ADR-002](adr/ADR-002-args-bound-approval-grants.md); red-team scenario RT-13 (`evals/redteam/RT-13.yaml`, approve 60,000, execute 600,000) and RT-14..RT-16; code in `src/bastion/oversight/approvals.py`.
- **For production:** put approver identity behind SSO and RBAC, and add four-eyes rules for the largest actions.

### 2. A custom AST evaluator instead of `eval` or OPA

- **Design decision:** policy conditions are parsed with Python's `ast` module and walked by an evaluator that accepts a fixed whitelist of node types and functions. Errors fail closed as `deny` with `condition_error`. Ruff rules S102 and S307 forbid `eval` and `exec`.
- **Trade-off:** less expressive than Rego, and the project owns a small language.
- **Evidence:** [ADR-003](adr/ADR-003-custom-condition-evaluator.md); RT-25 (`evals/redteam/RT-25.yaml`, a condition containing `__import__`); `src/bastion/gateway/conditions.py`.
- **For production:** evaluate OPA or Cedar for large policy estates, and keep this evaluator's fail-closed tests as the conformance suite.

### 3. Replay fixtures so the demo and CI need no key

- **Design decision:** model calls are recorded once to fixtures keyed by a hash of the whole request. Replay returns them, and the gateway, policy, tools, approvals and audit stay live.
- **Trade-off:** any change to prompts, tool schemas, policy redaction rules or demo data needs a re-record with a key.
- **Evidence:** [ADR-004](adr/ADR-004-llm-replay-fixtures.md); `fixtures/llm/`; `make demo` in a fresh clone.
- **For production:** keep replay for regression, and add a smaller live canary suite against the real model on a schedule.

### 4. Evals as a gate, with a benign suite to measure false positives

- **Design decision:** 25 red-team scenarios must all be blocked, and 15 benign scenarios must pass at 95% or better, because a control that blocks everything is useless. An assessor suite of 12 cards checks the risk tiers, and 3 seeded wrong assessments test the Reviewer. CI fails on a threshold breach and when the README table is stale. A unit test weakens the policy and asserts the suite then fails.
- **Trade-off:** the injection cases test the gateway with the call an injected agent would make, not the model's own susceptibility, so they stay deterministic. The assessor gold tiers are unverified starting points.
- **Evidence:** [`docs/EVALS.md`](EVALS.md); `evals/thresholds.yaml`; `evals/redteam/`; `evals/benign/`.
- **For production:** grow the corpus from real incidents and add adversarial generation, with human review of every new case.

### 5. A low-memory profile with two PII engines proven equal on the demo corpus

- **Design decision:** a `BASTION_LOW_MEMORY=true` profile swaps Presidio and spaCy for a pattern engine (regular expressions with IBAN and Luhn checks, plus `phonenumbers`), drops the headless browser and trims the console. The whole container peaks at about 276 MB under a 512 MB limit.
- **Trade-off:** the light engine is narrower (no name or location detection), equality is proven only on the synthetic demo data and eval inputs, and there is no PDF in that profile. Two engines must be kept in agreement.
- **Evidence:** [ADR-010](adr/ADR-010-low-memory-mode.md); `tests/test_low_memory.py`; a CI job that runs the image under `--memory=512m` and fails on an OOM kill.
- **For production:** use the full engine, add a named-entity model, and test recall on real, labelled data under the bank's data-handling rules.

## Pre-sales demo narrative for bank audiences

Audience: second-line risk, model risk and internal audit at a European bank. Use after the 3-minute demo in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

**The problem in their terms.** An agent that calls tools is an actor inside the operating model, not only a model. The first line wants to deploy it, the second line must challenge and set limits, and the third line must be able to test afterwards what happened. Inventories and questionnaires describe intent. They do not show what an agent did at 14:02 on a Tuesday, who approved it, or whether the control was still working that day. Operational resilience adds a question: when an agent misbehaves, how fast can it be stopped, and is the stop recorded (DORA ICT incident management [VERIFY])?

**What the first line sees.** The owner submits an agent card in the Registry. The Assessor and Reviewer agents propose and challenge a risk tier, and a human signs it. The owner then receives a policy and a gateway token. This is the point to show that no credential exists before sign-off.

**What the second line sees.** The policy page shows ordered rules, default-deny, the hash in force, the diff between versions and roll-back. The Approvals page holds the human-in-the-loop step, with the exact arguments in front of the approver. The kill switch and incidents are there too. This maps to oversight and risk-management expectations (EU AI Act Art. 9 and Art. 14 [VERIFY]; ISO/IEC 42001 clause 8.1 [VERIFY]).

**What the third line sees.** The audit log is hash-chained and `make verify-audit` checks it. The evidence pack is generated from the live records and includes the policy hash, oversight figures, incidents, red-team results and the audit integrity result. The Red-Team page shows the suite that gates every commit. Internal audit can reperform the checks rather than rely on a screenshot. The pack supports evidence for record-keeping and robustness expectations (Art. 12 and Art. 15 [VERIFY]); it does not by itself show that any expectation is met.

**What Bastion deliberately is not.** It is not a compliance product, and it does not make a system compliant. It is not a model-risk tool: it does not validate model performance, fairness or drift. It is not legal advice. The risk tier is decision support from two models and a human signature, and every citation is unverified. It is a reference implementation, not production hardened: one shared passcode, SQLite on one node, and no external anchor for the audit chain. It governs only calls that pass through the gateway.

**Why show it anyway.** It makes the control points concrete. A workshop can argue about a real deny rule, a real approval screen and a real evidence page instead of a slide about "human oversight".

**Suggested workshop questions.**

1. Which agent actions in your bank are irreversible, and which should always need a named human?
2. Who owns the policy for an agent: the first line, the second line, or both with a four-eyes step?
3. What evidence would internal audit want to re-perform, and where does it live today?
4. How would you route every agent tool call through a single enforcement point, and what stops a direct route?
5. Which of your obligations differ because you are a deployer of a third-party agent rather than a provider (provider and deployer roles [VERIFY])?
6. What identity, retention and external-anchoring requirements would the audit log need before use on real data?

## Short descriptions

**GitHub repo description (113 characters):**

```text
Runtime governance control plane for AI agents: policy gateway, approvals, kill switch, audit log, evidence packs
```

**CV or portfolio blurb:**

Bastion is an open-source reference implementation of a runtime governance control plane for AI agents: an MCP gateway enforces default-deny policy, approvals bound to exact arguments, a kill switch and a hash-chained audit log, and it generates evidence packs from live records. I specified and built it in vertical slices with Claude Code, with red-team and benign eval suites gating CI.

---
*SHOWCASE.md · Page 1 of 1*
