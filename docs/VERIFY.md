# VERIFY register

Every regulatory reference in this repository carries a `[VERIFY]` marker and has a row here (see `docs/GOVERNANCE_MAPPING.md`, "The VERIFY rule"). References are paraphrased starting points written by an AI assistant. **Each stays `unverified` until the repository owner has checked it against the primary source** and flipped it to `verified` or corrected it.

Bastion supports evidence for obligations; it does not make a system compliant. Reference implementation; not production; not legal advice.

## How to review

1. Work through the table below against the primary sources. Rows 1–29 are the base claims; rows 30 and above say where those claims are repeated (README, knowledge notes, evidence pack, showcase docs), so correcting a base row means correcting its repeats.
2. Flip `unverified` to `verified`, or correct the claim in the named file and note the change here.
3. Model-written citations (row 36) cannot be verified once and for all: they are regenerated whenever fixtures are re-recorded. The control is that each must carry `[VERIFY]` (checked by the assessor suite) and that a human signs the tier.
4. The price table (P1) is the only non-regulatory item.

## Regulatory references

| # | File | Reference | Claim made | Status |
|---|---|---|---|---|
| 1 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 6 and Annex III | Basis for classifying a system as high-risk; registry and classification support evidence here | unverified |
| 2 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 5 | Prohibited practices; a `prohibited` tier blocks registration | unverified |
| 3 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 9 | Risk management system; policy-as-code, default deny and versioning support evidence | unverified |
| 4 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 12 | Record-keeping / logging; hash-chained audit log supports evidence | unverified |
| 5 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 26 | Deployer duties incl. log retention and human oversight | unverified |
| 6 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 14 | Human oversight incl. ability to intervene or stop; approvals and kill switch support evidence | unverified |
| 7 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 10 | Data governance; relevance to deployers is limited | unverified |
| 8 | docs/GOVERNANCE_MAPPING.md | GDPR Art. 5(1)(c) | Data minimisation; PII redaction supports evidence | unverified |
| 9 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 15 | Accuracy, robustness, cybersecurity; red-team suite and CI gate support evidence | unverified |
| 10 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 72 | Post-market monitoring; incident lifecycle supports evidence | unverified |
| 11 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 73 | Serious incident reporting (provider-side) | unverified |
| 12 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 13 | Information to deployers; agent card supports evidence | unverified |
| 13 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 50 | Transparency for certain AI systems | unverified |
| 14 | docs/GOVERNANCE_MAPPING.md | EU AI Act Art. 11 and Annex IV | Technical documentation; evidence pack gives partial support only | unverified |
| 15 | docs/GOVERNANCE_MAPPING.md | EU AI Act provider vs deployer roles | A bank using a third-party agent is typically a deployer | unverified |
| 16 | docs/GOVERNANCE_MAPPING.md | NIST AI RMF functions GOVERN / MAP / MEASURE / MANAGE | Function-level mapping of each capability (see table) | unverified |
| 17 | docs/GOVERNANCE_MAPPING.md | NIST AI 600-1 (Generative AI Profile) | Covers prompt injection and information security risks | unverified |
| 18 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 6.1 | Actions to address risks and opportunities | unverified |
| 19 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 7.4 | Communication | unverified |
| 20 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 7.5 | Documented information | unverified |
| 21 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 8.1 | Operational planning and control | unverified |
| 22 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 8.2 | AI risk assessment | unverified |
| 23 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 8.3 | AI risk treatment | unverified |
| 24 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 8.4 | AI system impact assessment | unverified |
| 25 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 9.1 | Monitoring, measurement, analysis and evaluation | unverified |
| 26 | docs/GOVERNANCE_MAPPING.md | ISO/IEC 42001 clause 10.2 | Nonconformity and corrective action | unverified |
| 27 | docs/GOVERNANCE_MAPPING.md | DORA | ICT logging and ICT incident management expectations (optional mention) | unverified |
| 28 | docs/USE_CASES.md (UC-01), docs/SPEC.md | EU AI Act Annex III | A credit-related agent (creditworthiness / credit limits) falls under a high-risk use case | unverified |
| 30 | README.md (Governance mapping summary) | EU AI Act Art. 5, 6, Annex III, Art. 9, 11, Annex IV, Art. 13, 15, 50, 10, 12, 14, 26, 72, 73; GDPR Art. 5(1)(c); NIST AI RMF functions; ISO/IEC 42001 clauses 6.1, 7.5, 8.1, 8.2, 8.3, 9.1, 10.2; provider vs deployer | Repeats rows 3–8, 10, 11, 15, 16, 18, 20–23, 25, 26 for the capabilities built so far | unverified |
| 29 | docs/EVALS.md (Suite C) | EU AI Act Art. 5, Art. 6, Annex III, Art. 50 | Gold tiers for the 12 synthetic agent cards | unverified |
| 31 | knowledge/eu-ai-act-art5-prohibited.md | EU AI Act Art. 5 | Outline of the prohibited practices (manipulation, exploiting vulnerabilities, social scoring, crime prediction by profiling, untargeted facial scraping, emotion inference at work and in education, sensitive biometric categorisation, real-time remote biometric identification) | unverified |
| 32 | knowledge/eu-ai-act-art6-high-risk.md | EU AI Act Art. 6 and Annex I | Two routes to high-risk; the exception for narrow procedural, preparatory and similar tasks; the exception not applying to profiling; documentation of reliance on the exception | unverified |
| 33 | knowledge/eu-ai-act-annex3-use-cases.md | EU AI Act Annex III | Outline of the listed areas, incl. creditworthiness (with the fraud-detection exception), life and health insurance pricing, recruitment, education and exam monitoring | unverified |
| 34 | knowledge/eu-ai-act-art50-transparency.md | EU AI Act Art. 50 | Disclosure of AI interaction, marking of synthetic content, deepfake disclosure, informing people exposed to emotion recognition; "minimal" as Bastion's label for systems with no specific obligation | unverified |
| 35 | evals/assessor/gold.yaml | EU AI Act Art. 5, Art. 6, Annex III, Art. 50 | Gold tier per synthetic card (same as row 29, now in the repo as data) | unverified |
| 36 | fixtures/llm/*.json, registry classification records | Provisions cited by the Assessor and Reviewer agents | Model-written citations; each is required to carry `[VERIFY]` and is decision support only | unverified |
| 37 | src/bastion/evidence/generator.py (`MAPPING`), src/bastion/evidence/templates/pack.html.j2, docs/samples/evidence-pack-loan-ops-agent.{html,pdf} | The capability → framework mapping (rows 1–27) and the provider / deployer note (row 15) | Printed in every evidence pack, each cell marked `[VERIFY]`; rows appear only where the pack holds evidence | unverified |
| 38 | docs/THREAT_MODEL.md | EU AI Act Art. 9, 12, 14, 15, 26; NIST AI RMF functions; NIST AI 600-1; ISO/IEC 42001 clauses 8.1, 9.1; DORA | Relates the threats and controls to robustness, oversight and record-keeping expectations (repeats rows 3–6, 9, 16, 17, 21, 25, 27) | unverified |
| 39 | docs/SHOWCASE.md, docs/DEMO_SCRIPT.md | EU AI Act Art. 9, 12, 14, 15; ISO/IEC 42001 clause 8.1; DORA ICT incident management; provider vs deployer; the three frameworks by name | Talking points and narrative for bank audiences (repeats rows 3, 4, 6, 9, 15, 21, 27) | unverified |

No ISO/IEC 42001 Annex A control identifiers are cited anywhere in this repository; references are at clause level only.

## Non-regulatory items to verify

| # | File | Item | Claim made | Status |
|---|---|---|---|---|
| P1 | config/prices.yaml | Model prices | `claude-haiku-5-5` $0.10 / $0.50 and `claude-sonnet-5-5` $2.00 / $10.00 per million input / output tokens | unverified |
