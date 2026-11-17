**Bastion Kit · requirements/Bastion-Requirements-Brief.md**

# Bastion requirements brief

> Reference implementation; not production; not legal advice. All data and examples are synthetic.

## The problem

Banks are moving from chatbots to agents that act: they change records, send messages and move data. Most governance tooling describes an agent in an inventory or a questionnaire. Very little controls what the agent does at the moment it acts, or produces evidence that a control worked on a given day.

## What Bastion does

Bastion is a runtime governance control plane for AI agents. Every tool call an agent makes passes through one gateway that applies policy written as data, and every decision is recorded.

| Step | What happens | Built |
|---|---|---|
| Classify before deploy | Two AI agents propose and challenge a risk tier for the agent; a human signs off; only then are a policy and a credential issued | Yes |
| Enforce at the tool call | Default-deny rules allow, deny or hold each call; arguments are validated; e-mail addresses, phone numbers, IBANs and card numbers are masked before the model sees them | Yes |
| Keep a human in control | Risky actions wait for an approval that is bound to the exact arguments and can be used once; a kill switch stops an agent at once; budgets cap runaway loops | Yes |
| Prove it | A tamper-evident audit log, incidents, a red-team suite that gates every code change, and an evidence pack generated from the live records | Yes |

## Top use cases

| Use case | Autonomy | Indicative risk tier [VERIFY] | Status |
|---|---|---|---|
| Loan operations agent (lookups, credit-limit changes, internal email) | Act with approval | High | Built: one governed agent, six scripted scenarios |
| Coding agents in engineering teams | Act with approval | Minimal | Roadmap P1: Claude Code / Agent SDK adapter |
| KYC/AML onboarding desk; AML alert triage assistant | Suggest (customer contact held for approval) | Limited or high, depending on who decides | Roadmap P2 |
| Cost allocation and budget reporting across agents (AI FinOps) | n/a | n/a | Roadmap P3 |
| Credit memo drafting; customer service with account actions; trade operations reconciliation; internal policy copilot | Varies | Varies | Roadmap (no phase assigned) |

Risk tiers are indicative decision support, not a legal classification. Every regulatory reference in the requirements documents is an unverified starting point marked `[VERIFY]`.

## Controls an agent gets behind the gateway

Policy rules (allow, deny, require approval) · approvals bound to exact arguments · kill switch per agent and global · budgets (tool calls and tokens per session, cost per day) · masking of e-mail addresses, phone numbers, IBANs and card numbers · hash-chained audit log · incident rules · eval suites as a release gate · evidence pack. These support evidence for human-oversight, record-keeping and robustness expectations; they do not make a system compliant.

## Status

Working reference implementation, open source. Measured today: 25 of 25 red-team scenarios blocked and 15 of 15 benign scenarios allowed against the demo policy; gateway overhead p95 under 50 ms; 424 automated tests. It runs with no model API key, on recorded model responses. It is not production software: one shared passcode instead of SSO, a single-node database, synthetic data only.

## See the demo

`git clone https://github.com/VishnuChivukula/bastion-agent-governance.git`, then `make setup`, `make demo` (terminal, about a minute) or `make serve` (console at http://localhost:8501). The three-minute script is in [`docs/DEMO_SCRIPT.md`](../DEMO_SCRIPT.md).

## Read more

[`FRD-Enterprise.md`](FRD-Enterprise.md) for risk, compliance and business readers · [`FRD-AI-Native.md`](FRD-AI-Native.md) for architects and engineering leads · [`../design/`](../design/) for how it is built.

---
*requirements/Bastion-Requirements-Brief.md · Page 1 of 1*
