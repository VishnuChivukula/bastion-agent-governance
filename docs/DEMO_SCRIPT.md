**Bastion Kit · DEMO_SCRIPT.md**

# Bastion demo script

> Reference implementation; not production; not legal advice. All data is synthetic.

A presenter's script for a 3-minute demo and a 10-minute version. Scenario definitions are in [`USE_CASES.md`](USE_CASES.md); the scenario code is in `demo/loan_ops_agent/scenarios.py`.

## Setup

| Item | Detail |
|---|---|
| Local | `make setup`, then `make serve`. Console at http://localhost:8501, passcode `bastion-local` (accepted only under `make serve`). No API key is needed: model responses come from recorded fixtures. |
| Hosted | The replay-mode deployment, if one is linked in the README. Without a configured passcode it is read-only apart from the recorded scenarios. |
| Pages used | Registry, Run Scenario, Approvals, Incidents, Live Activity, Policies, Evidence, Red-Team |
| Before you start | Open the console and click through each page once so the first click on stage is not a cold load. Check the Registry page: the global kill switch must be off. |

Things to know before presenting:

- Starting a scenario **resets the demo agent**: it rebuilds the synthetic data, releases the agent's own kill switch, resolves its open incidents and revokes its open approvals. All of this is audited. It never releases the global kill switch.
- Only one scenario runs at a time. A second start answers `409`.
- On the hosted free-tier demo the container sleeps after 15 idle minutes. The first load after a sleep takes about a minute, and the first scenario after that is slower than later ones. Wake it before the audience arrives.
- In the low-memory profile the PII engine is the built-in pattern engine and the evidence pack is HTML only (no PDF). Use a local `make serve` if you want to show the PDF.

## The 3-minute version

| Time | Page and clicks | What the audience sees | What to say |
|---|---|---|---|
| 0:00 | README hero and the architecture diagram | The one-line description and the flowchart: agent, gateway, policy, approvals, audit | "Agents now act, not just answer. Bastion governs what they do at the moment they act." |
| 0:20 | **Registry**: open the classification record for `loan-ops-agent` | Assessor proposal (`high`), Reviewer critique, the sign-off with approver and timestamp | "Before deployment, two agents classify risk: one proposes, one challenges. A human signs off. Credit decisions come out high-risk." |
| 0:50 | **Run Scenario**: choose UC-02, click Run scenario. Then **Live Activity** | `ALLOW R-001` and the redaction count; the summary shows masked email, phone and IBAN | "Normal work flows through. PII is masked before the model ever sees it." |
| 1:10 | **Run Scenario**: UC-03, Run scenario. Then **Incidents** | A poisoned note, then `DENY R-007 (exfiltration)`, incident IR-2 at high severity, the agent halted | "A poisoned customer note tries to export every customer. The policy denies it, an incident opens and the agent is stopped." |
| 1:40 | **Run Scenario**: UC-04, Run scenario. Then **Approvals**; then UC-05 | UC-04 pauses at a pending approval for 60,000, the scripted approver approves, the identical call executes. UC-05: the call with 600,000 creates a new pending approval and nothing executes | "Large limit increases need a human, and the approval is tied to the exact arguments. Approve 60,000 and a call with 600,000 is a different request." |
| 2:15 | **Registry**: kill switch, or UC-07 on **Run Scenario** | The agent's next call is denied (`killswitch`), the run halts | "One click stops an agent. Its next call is denied and the stop is audited." |
| 2:30 | **Evidence**: preview the pack. Then **Red-Team** | Policy hash, oversight figures, incidents, audit integrity, framework mapping marked `[VERIFY]`. Scoreboard: 25/25 red-team, 15/15 benign | "Every action is in a hash-chained log, and the evidence pack supports evidence for the EU AI Act, NIST AI RMF and ISO/IEC 42001 expectations. The red-team suite gates every commit." |
| 2:55 | Back to the README | The disclaimer line | "Reference implementation, open source, not production and not legal advice. The repo link is in the comments." |

## The 10-minute version

Use the same opening, then add the following. Times are approximate.

1. **0:00 Opening (1 min).** README hero, architecture diagram, and the sequence diagram showing deny, require approval and allow.
2. **1:00 UC-01 in the Registry (1.5 min).** Show the classification record for `loan-ops-agent`. Point out that no gateway token exists before sign-off, that an override of the proposed tier needs a recorded reason, and that a `prohibited` tier blocks registration. Optionally submit one of the twelve sample cards (replay covers only those) and walk through the Assessor, Reviewer and sign-off.
3. **2:30 UC-02 (45 s).** Run it. In Live Activity show `ALLOW R-001` and the redaction count.
4. **3:15 UC-03 (1.5 min).** Run it. Show the note, the `DENY R-007`, incident IR-2 (opened by the `exfiltration` category) and the automatic kill. Then reactivate the agent in the Registry; a reason is required.
5. **4:45 UC-04 with "approver: Me" (1.5 min).** On Run Scenario, answer "Who plays the approver?" with "Me" and enter the passcode. The run parks at the pending approval. Open Approvals, show the arguments and hash, approve with a reason, and watch the run resume and the grant be consumed once.
6. **6:15 UC-05 (45 s).** Run it. Show the second pending approval for 600,000 and the unused original grant.
7. **7:00 UC-06 (45 s).** Run it. After 30 tool calls the gateway denies with `budget_exceeded`; repeated denials open IR-1.
8. **7:45 UC-07 (30 s).** Run it. The scenario presses Kill after the first tool call; the next call is denied and the run halts.
9. **8:15 UC-08 on Policies (1.5 min).** Open the policy for `loan-ops-agent`. Change the R-003 threshold from `50000` to `30000` in the editor and click "Validate and activate". Show the new version and hash and the diff against the previous version. Then use the roll-back button to activate the earlier content again. Mention that later decisions cite the hash in force.
10. **9:45 Audit and close (1.5 min).** In a terminal run `make verify-audit`; it reports the chain as valid. Describe what a tamper looks like: the command reports the first broken sequence number and exits non-zero, and the console shows a red integrity banner. (The tamper itself is exercised by RT-24 and the audit tests, not by editing the live database on stage.) Finish with Evidence, Red-Team and the disclaimer.

Do the UC-08 edit after the scenarios, or roll back before running another one. Run Scenario warns when the policy in force is not the seed policy.

## Questions you will get

**Is this production-ready?** No. It is a reference implementation. Authentication is one shared passcode, the store is SQLite on one node, and the audit chain has no external anchor. The README Limitations section lists the rest.

**What happens if the agent bypasses the gateway?** Bastion does not govern it. Only calls routed through the gateway are enforced. In a real deployment the network and credentials must be arranged so that the gateway is the only route to the tools.

**Why not OPA/Rego?** Policies here are small, ordered rules edited by an approver, and the conditions run in a custom AST evaluator with a fixed whitelist of node types and functions, never `eval` or `exec` ([ADR-003](adr/ADR-003-custom-condition-evaluator.md)). The trade-off is lower expressiveness than Rego. A production deployment with many policy authors should weigh an established engine.

**How do you know the audit log was not edited?** Each event carries the hash of the previous one. `make verify-audit` recomputes the chain and detects modification, deletion and reordering. It does not detect truncation of the newest events, because there is no external anchor for the chain head. Anchoring the head outside the database is the fix and is not built.

**What does the risk tier mean legally?** Nothing by itself. It is decision support produced by two models from short paraphrased notes, and a human signs it. It is not a legal classification, every citation is marked `[VERIFY]`, and the gold tiers in the assessor suite are unverified. Obligations also differ for providers and deployers under the EU AI Act `[VERIFY]`.

**Does it work with models other than Claude, or frameworks other than LangGraph?** The gateway is an MCP server and is model-agnostic: any MCP client that presents a valid agent token is governed the same way. The demo agent uses LangGraph. Model-call budgets (tokens and daily cost) and the record-and-replay fixtures are implemented for the Anthropic SDK wrapper only. Another provider would need its own wrapper for those two parts.

## If something goes wrong on stage

| Symptom | Fix |
|---|---|
| A scenario ends with an explanatory message instead of a model reply after you edited a policy | Replay covers only the recorded paths, and a policy edit can change what the agent sees. Open Policies and roll back to the seed policy, then run the scenario again. |
| Starting a scenario answers `409` or the agent stays denied | The global kill switch is on, or another run is in progress. Reactivate the global switch in Registry (a reason is required); the demo reset never releases it. Wait for any running scenario to finish. |
| The hosted demo does not load | It is asleep on the free tier. Wait for the cold start (about a minute), then retry. Keep the local `make serve` as a fallback. |
| Approver "Me" is refused | No passcode is configured on that deployment. Use "The scenario script" instead. |
| Evidence PDF returns 503 | The low-memory profile has no headless browser. Show the HTML preview and the committed sample in `docs/samples/`. |

---
*DEMO_SCRIPT.md · Page 1 of 1*
