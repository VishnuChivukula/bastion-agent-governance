**Bastion Kit · GOVERNANCE_MAPPING.md**

# Bastion v0.1: Governance Mapping Rules

## The VERIFY rule (mandatory)
1. Every regulatory reference in code, docs, knowledge files or evidence packs carries `[VERIFY]`.
2. Every such reference is listed in `docs/VERIFY.md` as: `| file | reference | claim made | status: unverified |`. Vishnu reviews and flips it to `verified` or corrects it.
3. Paraphrase in your own words. Do not paste passages of the EU AI Act, NIST documents or ISO standards. ISO/IEC 42001 is copyrighted: reference clause numbers and titles only, and **never invent Annex A control IDs**.
4. Bastion **supports evidence for** obligations; it does not "make a system compliant". Use that wording.
5. Note in the evidence pack that obligations differ for **providers** and **deployers** under the EU AI Act, and that a bank using a third-party agent is typically a deployer `[VERIFY]`.

## Capability → framework mapping (starting point; all items `[VERIFY]`)
| Bastion capability | EU AI Act | NIST AI RMF | ISO/IEC 42001 (clause level) | Other |
|---|---|---|---|---|
| Registry + Assessor/Reviewer classification + sign-off | Art. 6 & Annex III (high-risk classification); Art. 5 (prohibited practices) | MAP (context, categorisation) | 6.1 actions to address risks; 8.4 AI system impact assessment | — |
| Policy-as-code, default deny, versioning | Art. 9 (risk management system) | GOVERN (policies), MANAGE (risk treatment) | 8.3 AI risk treatment | — |
| Hash-chained audit log + verify | Art. 12 (record-keeping / logging); Art. 26 deployer log retention | MEASURE (traceability), GOVERN (accountability) | 7.5 documented information; 9.1 monitoring | DORA ICT logging expectations (optional mention) |
| Human approvals bound to args; HITL/HOTL | Art. 14 (human oversight); Art. 26 (deployer oversight duties) | MANAGE (human oversight), GOVERN (roles) | 8.1 operational planning and control | — |
| Kill switch | Art. 14 (ability to intervene / stop) | MANAGE (deactivation, response) | 8.1; 10.2 nonconformity & corrective action | — |
| PII redaction / DLP | Art. 10 (data governance) — relevance to deployers is limited; also GDPR data minimisation | MAP / MANAGE (privacy risk) | 6.1; 8.2 AI risk assessment | GDPR Art. 5(1)(c) |
| Red-team suite + CI gate | Art. 15 (accuracy, robustness, cybersecurity) | MEASURE (testing, evaluation) | 9.1 monitoring, measurement, analysis and evaluation | NIST AI 600-1 GenAI Profile (prompt injection, info security) |
| Incidents lifecycle | Art. 72 post-market monitoring; Art. 73 serious incident reporting (provider-side) | MANAGE (incident response) | 10.2 nonconformity and corrective action | DORA ICT incident management (optional mention) |
| Agent card / transparency | Art. 13 (information to deployers); Art. 50 (transparency for certain AI systems) | GOVERN, MAP | 7.4 communication | — |
| Budgets / cost caps | — (operational control) | MANAGE (resource allocation) | 8.1 | AI FinOps |
| Evidence pack | Art. 11 & Annex IV (technical documentation) — partial support only | GOVERN (documentation) | 7.5 documented information | — |

## Evidence pack outline (FR-50)
1. Cover: agent name, generation timestamp, Bastion version, policy hash, disclaimer
2. System description: from the agent card
3. Risk classification: Assessor output, Reviewer critique, final tier, sign-off (who/when/override reason)
4. Controls in force: policy summary table (rule, effect, condition, category)
5. Human oversight: approvals count, approved/rejected/expired, median decision time, overrides, kill-switch events
6. Robustness: latest red-team and benign results with run timestamp
7. Incidents: list with lifecycle timestamps
8. Usage and budgets: tokens, cost, caps hit
9. Record-keeping: audit event count, integrity verification result
10. Framework mapping: the table above, filtered to evidence actually present, with `[VERIFY]` markers
11. Limitations and disclaimer

PDF: header = `Bastion Evidence Pack — <agent name>`, footer = `Page X of Y`.

---
*GOVERNANCE_MAPPING.md · Page 1 of 1*
