**Bastion Kit · design/TRACEABILITY.md**

# Bastion traceability matrix

> Reference implementation; not production; not legal advice. All data is synthetic.

This matrix links each requirement in [`SPEC.md`](../SPEC.md) and each use case in [`USE_CASES.md`](../USE_CASES.md) to the code that implements it and the tests and eval scenarios that verify it. It was built by reading the source and the test bodies, not the design documents. Where the code differs from the wording of the specification, the status says so.

## How to read the tables

| Column | Meaning |
|---|---|
| ID | Requirement id from SPEC.md |
| Requirement | Short paraphrase, not the full text |
| Modules | Implementing files under `src/bastion/` unless a path starts elsewhere |
| Tests | `file::function` in `tests/`, the most direct one to four |
| Eval scenario ids | Red-team (RT-xx), benign (B-xx) or assessor suite C (`evals/assessor_suite.py`) |
| Status | See below |

Status values:

| Status | Meaning |
|---|---|
| `met` | Implemented as specified and exercised by at least one test |
| `partly met` | Implemented in part; the missing part is named |
| `not met` | Not implemented |
| `met differently` | Implemented, but the code differs from the spec wording; the difference is named |

Test counts are not repeated here; run `make check` for the current figure. `file::function` names without a directory are in `tests/`.

## Registry and classification

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-01 | Register an agent from an agent card (id, owner, purpose, context, users, data categories with personal and special-category flags, tools, autonomy level, models) | `registry/models.py::AgentCard`, `registry/classification.py::submit_card`, `api/routers/registry.py::register` | `test_classification.py::test_sample_cards_are_valid_and_synthetic`, `test_classification.py::test_sign_off_guards`, `test_api.py::test_register_classify_and_sign_off_through_the_api` | Suite C (12 cards) | `met` |
| FR-02 | Assessor proposes a tier with rationale, cited provisions marked `[VERIFY]`, obligations, confidence 0 to 1, open questions, as structured output | `registry/assessor_graph.py::assess`, `registry/models.py::Assessment` | `test_classification.py::test_uc01_demo_agent_is_classified_high_and_signed_off_in_replay`, `test_classification.py::test_invalid_structured_output_is_rejected_and_the_agent_stays_a_draft`, `test_classification.py::test_a_refusal_or_truncation_is_not_parsed` | Suite C: tier accuracy, structured validity | `met`. Each cited provision must contain `[VERIFY]`: enforced by a validator on `Assessment.cited_provisions` (`test_classification.py::test_a_citation_without_the_verify_marker_is_rejected`) as well as requested in the prompt |
| FR-03 | Reviewer critiques independently; on disagreement the Assessor revises once; remaining disagreement shown to the human | `registry/assessor_graph.py::review`, `revise`, `build_graph`; `registry/models.py::Classification.unresolved_disagreement` | `test_classification.py::test_agreement_needs_two_model_calls_and_no_revision`, `test_classification.py::test_disagreement_triggers_exactly_one_revision`, `test_classification.py::test_remaining_disagreement_is_shown_to_the_human` | Suite C: reviewer seeded-error catches (`seeded_errors.yaml`) | `met` |
| FR-04 | Human sign-off: accept or override with a mandatory reason; `prohibited` blocks; no credential before sign-off | `registry/classification.py::sign_off`, `registry/service.py::Registry.issue_token`, `api/routers/registry.py::sign_off` | `test_classification.py::test_override_needs_a_reason`, `test_classification.py::test_prohibited_blocks_registration`, `test_classification.py::test_no_credential_before_sign_off`, `test_classification.py::test_sign_off_is_claimed_once` | none | `met` |
| FR-05 | Tier selects a default policy template; an agent-specific policy may override; token issued once, stored hashed | `registry/classification.py::policy_for`, `policies/templates/*.yaml`, `registry/service.py::issue_token`, `hash_token` | `test_classification.py::test_accepting_the_tier_applies_its_template`, `test_classification.py::test_templates_are_valid_default_deny_policies`, `test_registry.py::test_token_is_shown_once_and_only_its_hash_is_stored`, `test_classification.py::test_uc01_demo_agent_is_classified_high_and_signed_off_in_replay` (agent-specific path) | none | `met`. Templates carry no tool rules, so a template-based agent is deny-all until a policy with rules is activated |

## Gateway

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-10 | MCP streamable-HTTP endpoint `/mcp` authenticates the agent token and proxies to the downstream servers named in the policy | `gateway/server.py::BearerAuth`, `build_mcp_route`; `gateway/mcp_proxy.py::DownstreamPool`, `Gateway`; `registry/service.py::authenticate` | `test_gateway_http.py::test_allowed_call_returns_redacted_result`, `test_gateway_http.py::test_rt23_missing_or_invalid_token_is_401_and_audited`, `test_gateway_http.py::test_rotated_token_stops_working`, `test_api.py::test_gateway_is_mounted_and_needs_an_agent_token` | RT-23 | `met` |
| FR-11 | `tools/list` shows only tools a rule can allow or route to approval; direct calls to hidden tools are still evaluated and denied | `gateway/policy_engine.py::Policy.visible_tools`, `gateway/mcp_proxy.py::Gateway.list_tools` | `test_gateway.py::test_discovery_hides_denied_tools`, `test_gateway.py::test_agent_without_policy_sees_nothing_and_is_denied`, `test_gateway_http.py::test_agent_discovers_only_permitted_tools`, `test_gateway_http.py::test_hidden_tool_called_directly_is_denied` | RT-07, RT-19 | `met`. The demo agent ships its own tool manifest that includes the export tool so UC-03 can show a blocked attempt (PROGRESS, 2026-11-16) |
| FR-12 | YAML policy, ordered rules, first match wins, default deny; safe condition language; order kill switch, budget, rules | `gateway/policy_engine.py::Policy.evaluate`, `gateway/conditions.py::compile_condition`, `gateway/mcp_proxy.py::_decide_and_forward` | `test_policy_engine.py::test_first_match_wins`, `test_policy_engine.py::test_default_deny`, `test_conditions.py::test_everything_else_is_rejected_at_load`, `test_conditions.py::test_no_eval_or_exec_in_the_module` | RT-04, RT-07, RT-25 | `met`. Actual order: kill switch, tool-name check, policy load, budget, tool lookup, schema validation, rules, input scan, grant check. The extra checks sit between the specified ones (see LLD §2.1) |
| FR-13 | Validate arguments against the tool schema, reject unknown fields, strict typing (no numeric strings or Unicode digits), exact tool names | `gateway/normalize.py::validate_and_normalise`, `harden_schema`, `is_valid_tool_name`, `args_hash` | `test_gateway.py::test_rt08_to_rt12_malformed_arguments_are_denied`, `test_gateway.py::test_rt05_rt06_tool_names_match_exactly`, `test_gateway.py::test_rt10_float_form_is_compared_numerically`, `test_normalize.py::test_harden_schema_closes_nested_objects_without_mutating_the_original` | RT-05, RT-06, RT-08 to RT-12 | `met`. The schema is the one the downstream server advertises; Bastion closes objects but does not author schemas |
| FR-14 | `redact_output` masks PII in results; `scan_input` runs DLP with action `deny`, `require_approval` or `redact` | `gateway/redaction.py::BaseRedactor`, `Redactor`, `LightRedactor`; `gateway/mcp_proxy.py::_forward`, `_decide_and_forward` | `test_gateway.py::test_lookup_is_allowed_and_pii_is_masked`, `test_gateway.py::test_rt17_internal_email_with_iban_in_body_needs_approval`, `test_gateway.py::test_rt18_internal_email_with_card_number_in_subject_needs_approval`, `test_low_memory.py::test_light_engine_agrees_with_presidio_on_all_demo_and_eval_text` | RT-17, RT-18; B-02, B-03, B-09 to B-11 | `partly met`: four entity types only (e-mail, phone, IBAN, card); the seed policy uses `scan_input` with `require_approval` only. The `deny` and `redact` actions are implemented in `Gateway._decide_and_forward` and `ScanAction` but no test or scenario uses them |
| FR-15 | Policy versions are content-hashed; activation and changes audited; every decision records policy hash and rule id | `registry/service.py::PolicyStore.activate`, `active`; `api/routers/policies.py`; `gateway/mcp_proxy.py::_audit_decision` | `test_gateway.py::test_policy_change_is_versioned_and_decisions_reference_the_new_hash`, `test_gateway.py::test_decision_is_audited_with_policy_hash_rule_and_latency`, `test_api.py::test_policy_change_new_version_diff_and_decisions_use_the_new_hash`, `test_api.py::test_invalid_policies_are_rejected_and_never_stored` | B-15, RT-25 | `met`. The API offers list, read, diff and activate-new-version. There is no update-in-place, delete or deactivate; versions are immutable and a rollback is a new activation of old text (console Policies page). This is not full CRUD, and the specification does not ask for it |

## Oversight

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-20 | `require_approval` creates a pending approval bound to agent, tool and args hash, TTL default 30 minutes; the agent receives `PENDING_APPROVAL` with the approval id | `oversight/approvals.py::ApprovalStore.request`, `DEFAULT_TTL_SECONDS`; `gateway/mcp_proxy.py::_pending` | `test_gateway.py::test_large_limit_increase_needs_approval_and_does_not_execute`, `test_gateway.py::test_different_arguments_get_a_different_approval`, `test_gateway_http.py::test_approval_gated_call_returns_pending`, `test_oversight.py::test_rt15_grant_expires_after_ttl` | RT-02, RT-03, RT-15 | `met` |
| FR-21 | Approve or reject with a reason; approval creates a single-use grant consumed by the identical call; changed arguments need a new approval | `oversight/approvals.py::ApprovalService.decide`, `consume_grant`; `api/routers/oversight.py::decide` | `test_oversight.py::test_uc04_approved_call_executes_once_with_the_identical_arguments`, `test_oversight.py::test_rt13_uc05_approve_then_swap_does_not_execute`, `test_oversight.py::test_rt14_consumed_grant_cannot_be_reused`, `test_oversight.py::test_rt16_grant_for_one_agent_is_useless_to_another` | RT-13 to RT-16; B-14 | `met` |
| FR-22 | Kill switch per agent and global: deny-all at once, pending approvals revoked, active runs halted, reactivation with a reason, all audited | `oversight/killswitch.py::KillSwitchService`, `approvals.py::revoke_open`, `api/routers/agents.py` | `test_oversight.py::test_rt22_uc07_kill_switch_denies_revokes_and_halts`, `test_oversight.py::test_global_kill_switch_stops_every_agent`, `test_api.py::test_kill_revokes_pending_and_halts_the_parked_run`, `test_api.py::test_global_kill_and_reactivate` | RT-22 | `partly met`: "active runs halted" sets run rows in `running` or `interrupted` to `halted` and denies the agent's next tool call and model call. It does not cancel a running task, recall a call already executing downstream, or resume a parked run (`KillSwitchService.kill`; PROGRESS "Deferred / known gaps") |
| FR-23 | Budgets per agent, per session and per day, for tokens, cost and tool calls; model calls enforced via the SDK wrapper, tool calls at the gateway | `gateway/budgets.py::BudgetTracker`, `gateway/policy_engine.py::Budgets`, `llm/governance.py::GovernanceHook`, `api/routers/agents.py::usage` | `test_gateway.py::test_rt20_call_31_in_a_session_is_denied`, `test_gateway.py::test_invented_run_ids_share_one_budget_bucket`, `test_oversight.py::test_rt21_token_cap_blocks_the_next_model_call_and_is_audited`, `test_oversight.py::test_daily_cost_cap_blocks_model_calls` | RT-20, RT-21 | `partly met`: exactly three caps exist, each on one window: `max_tool_calls_per_session`, `max_tokens_per_session`, `max_cost_usd_per_day`. There is no per-day tool-call or token cap and no per-session cost cap. The token check runs before the call, so the call that crosses the cap completes. Model budgets apply only to calls made through `GovernedAnthropic` |

## Audit

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-30 | Append-only hash-chained log of every model call, tool decision, approval action, policy change, kill-switch action, incident and registry event | `audit/log.py::AuditLog.append`, `event_hash`; event sources in `gateway/mcp_proxy.py`, `llm/governance.py`, `oversight/`, `incidents/service.py`, `registry/` | `test_audit.py::test_chain_links_and_verifies`, `test_audit.py::test_concurrent_appends_keep_one_unbroken_chain`, `test_console.py::test_describe_covers_every_event_type_in_a_real_log`, `test_oversight.py::test_uc04_approved_call_executes_once_with_the_identical_arguments` | Clean-run check `audit_verify_clean_run` in `evals/run.py` | `met`. The log is append-only by convention: the code only inserts, but SQLite does not forbid updates, hence tamper evidence rather than prevention |
| FR-31 | `verify` (CLI and API) detects modification, deletion or reordering and reports the first broken link | `audit/verify.py::verify_chain`, `cli.py` (`verify-audit`), `api/routers/audit.py::verify` | `test_audit.py::test_rt24_tampering_is_detected_at_the_first_broken_event`, `test_audit.py::test_reordering_is_detected`, `test_audit.py::test_cli_verify_audit_exit_codes`, `test_api.py::test_tampering_shows_up_in_verify_and_overview` | RT-24 | `met`. Deletion of the newest events is not detectable (no external anchor; ADR-005) |

## Incidents

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-40 | Policy rules open incidents (three denials in 10 minutes; exfiltration-category denial); lifecycle open, acknowledged, contained, resolved with notes; optional `on_incident: kill` | `incidents/service.py::IncidentService`, `gateway/policy_engine.py::IncidentRule`, `gateway/mcp_proxy.py::_run_incident_rules`, `api/routers/oversight.py::advance` | `test_oversight.py::test_ir1_opens_once_after_three_denials`, `test_oversight.py::test_incident_lifecycle_moves_forward_only_with_notes`, `test_gateway.py::test_rt01_exfiltration_deny_opens_a_high_incident_and_kills_the_agent`, `test_console.py::test_incident_can_be_acknowledged_from_the_console` | RT-01 | `met`. Incident rules are evaluated after a gateway denial only, and kill-switch denials are not counted |

## Evidence

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-50 | Evidence pack per agent in HTML and PDF; header with document name, footer `Page X of Y`; sections for card, classification, policy hash, oversight, budgets, incidents, red-team, audit integrity, mapping, limitations, disclaimer, timestamp | `evidence/generator.py::collect`, `render_html`, `evidence/templates/pack.html.j2`, `evidence/pdf.py::html_to_pdf`, `api/routers/evidence.py`, `evidence/cli.py` | `test_evidence.py::test_html_has_every_section_the_hash_and_the_disclaimer`, `test_evidence.py::test_pdf_has_the_document_name_header_and_page_x_of_y_footer`, `test_evidence.py::test_every_regulatory_reference_in_the_mapping_is_marked_verify`, `test_evidence.py::test_eval_results_for_another_policy_are_not_presented_as_evidence` | none | `met` on the default profile. In low-memory mode the PDF route answers 503 and only HTML is produced (ADR-010; `test_low_memory.py::test_evidence_is_html_only`) |

## Evals

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-60 | Red-team, benign and assessor suites; scoreboard to JSON; README table regenerated automatically; CI fails on breached thresholds | `evals/run.py`, `evals/scenario.py`, `evals/assessor_suite.py`, `evals/thresholds.yaml`, `scripts/update_readme_results.py`, `.github/workflows/ci.yml` (job `eval`) | `test_evals.py::test_scenario_catalogue_matches_the_design`, `test_evals.py::test_all_suites_pass_the_gate_in_replay`, `test_evals.py::test_gate_fails_when_a_threshold_is_breached`, `test_evals.py::test_a_weakened_policy_makes_the_red_team_fail` | RT-01 to RT-25, B-01 to B-15, suite C | `met differently`: `make eval` regenerates the README table and writes `evals/results/latest.json`; CI runs `make eval` and then fails if `git diff --exit-code README.md` shows a difference. CI checks that the table is current; it does not regenerate it on `main` |

## Demo workload

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-70 | Loan Ops Agent (LangGraph), demo tools MCP server with 50 synthetic customers, six scripted scenarios | `demo/loan_ops_agent/graph.py`, `run.py`, `scenarios.py`, `demo/tools_server/__main__.py`, `demo/data/generate.py` (`N_CUSTOMERS = 50`) | `test_demo_scenarios.py::test_all_six_scenarios_ran`, `test_demo_scenarios.py::test_unmasked_pii_never_reached_the_model`, `test_demo_data_and_redaction.py::test_demo_data_is_deterministic_and_synthetic` | RT-01, B-01, B-14 (recorded runs) | `met` |
| FR-71 | LLM modes `replay` (default, fixtures, no key), `record`, `live` | `llm/client.py::GovernedAnthropic`, `llm/fixtures.py`, `config.py::Settings.mode` | `test_llm_client.py::test_record_then_replay_round_trip`, `test_llm_client.py::test_replay_miss_raises_with_record_hint`, `test_llm_client.py::test_replay_needs_no_api_key_or_sdk_client`, `test_config.py::test_defaults_are_replay_and_keyless` | none | `met` |

## API and console

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| FR-80 | FastAPI control-plane API with OpenAPI at `/docs` | `api/main.py::create_app`, `api/routers/*.py`, `api/schemas.py` | `test_api.py::test_healthz_meta_and_openapi`, `test_api.py::test_agent_is_seeded_with_policy`, `test_api.py::test_audit_events_filter_and_verify` | none | `met` |
| FR-81 | Streamlit console with Overview, Registry, Live Activity, Approvals, Incidents, Policies (version history), Evidence, Red-Team, Run Scenario | `console/app.py`, `console/pages/*.py` (nine pages), `console/views/*.py` | `test_console.py::test_every_page_renders_with_banner_and_disclaimer`, `test_console.py::test_policies_page_shows_the_policy_in_force`, `test_console.py::test_evidence_page_generates_a_pack_with_downloads`, `test_console.py::test_red_team_page_shows_the_scoreboard` | none | `met`. The console failure banner for a broken chain (`console/views/overview.py`) has no console-level test; the API-level tamper test covers the data |
| FR-82 | Public deploy defaults to replay; live mode and all mutating actions need `BASTION_PASSCODE`; visible mode banner | `api/auth.py`, `config.py::Settings.effective_passcode`, `api/routers/runs.py::start_run`, `console/common.py` | `test_api.py::test_mutations_need_the_passcode`, `test_api.py::test_mutations_are_disabled_without_a_configured_passcode`, `test_api.py::test_every_mutating_route_is_guarded`, `test_console.py::test_every_page_renders_with_banner_and_disclaimer` | none | `met differently`: starting a recorded scenario (`POST /runs`) is open in replay mode by design (ADR-008), and `POST /mcp` uses agent tokens. Read routes, including evidence generation, are open. Outside replay mode `/runs` needs the passcode. The live public URL does not exist yet: the README holds a placeholder and the Render deploy is a human step (PROGRESS) |

## Non-functional

| ID | Requirement | Modules | Tests | Eval ids | Status |
|---|---|---|---|---|---|
| NFR-01 | Gateway overhead p95 under 50 ms locally, excluding the downstream tool | `gateway/mcp_proxy.py::Gateway.call_tool` (`overhead_ms`), `evals/run.py::p95` | `test_gateway_latency.py::test_gateway_overhead_p95_is_under_50_ms`, `test_evals.py::test_all_suites_pass_the_gate_in_replay` | Threshold `gateway_overhead_p95_ms` | `met` |
| NFR-02 | One-command run (`make demo`), one-command container (`make up`) | `Makefile`, `Dockerfile`, `docker-compose.yml` | CI job `docker` (build, health, UC-03 inside the container); no pytest covers `make up` | none | `met`. `make demo` is exercised by `test_demo_scenarios.py` against the same runner, not by invoking `make` |
| NFR-03 | At least 80% line coverage on `gateway/`, policy and `audit/` | `pyproject.toml` (`[tool.coverage.run]`), `Makefile::check` | none | none | `met (not enforced)`: coverage is measured per file on every `make check` (`pytest --cov`, branch mode, `src/bastion`). The files under `gateway/` and `audit/` and `gateway/policy_engine.py` are between 95% and 100%. No minimum is configured (no `fail_under`), so a regression would not fail CI |
| NFR-04 | CI makes no model API calls; deterministic and seeded | `.github/workflows/ci.yml` (`BASTION_MODE: replay`), `llm/client.py`, `demo/data/generate.py` | `test_llm_client.py::test_replay_needs_no_api_key_or_sdk_client`, `test_demo_data_and_redaction.py::test_demo_data_is_deterministic_and_synthetic`, `test_config.py::test_defaults_are_replay_and_keyless` | all suites run in replay | `met` |
| NFR-05 | No secrets in the repository; gitleaks in pre-commit and CI; Dependabot enabled | `.pre-commit-config.yaml`, `.github/workflows/ci.yml` (job `gitleaks`), `.github/dependabot.yml`, `.gitleaks.toml` | `test_config.py::test_secrets_do_not_appear_in_repr`, `test_config.py::test_preflight_reports_presence_not_value` | none | `met`. The tests cover the handling of secrets in code; the repository scan is the gitleaks job |
| NFR-06 | Every regulatory reference carries `[VERIFY]` and is tracked in `docs/VERIFY.md` | `docs/VERIFY.md`, `evidence/generator.py::MAPPING`, `knowledge/eu-ai-act-*.md` | `test_evidence.py::test_every_regulatory_reference_in_the_mapping_is_marked_verify`, `test_classification.py::test_knowledge_notes_carry_verify_markers_and_no_bare_references` | Suite C `verify_marked` (reported) | `partly met`: markers are tested in the evidence mapping and the knowledge notes. Nothing tests the prose documents, and rows for new documents are added by hand |
| NFR-07 | Clear README, architecture diagrams, ADRs, threat model and limitations | `README.md`, `docs/ARCHITECTURE.md`, `docs/adr/ADR-001` to `ADR-010`, `docs/design/SECURITY.md` | none | none | `met` (documentation; reviewed by reading, not by test) |

## Use cases

Make targets run in replay mode with no API key. The console runs with `make serve`.

| ID | How to run it | Tests | Eval ids | Status |
|---|---|---|---|---|
| UC-01 Register and classify | `make demo` prints the replayed registration; console Registry page; API `POST /registry/agents` then `/signoff` | `test_classification.py::test_uc01_demo_agent_is_classified_high_and_signed_off_in_replay`, `test_api.py::test_register_classify_and_sign_off_through_the_api`, `test_console.py::test_register_and_sign_off_from_the_console` | Suite C | `met` |
| UC-02 Lookup with PII redaction | `make demo`; console Run Scenario (uc02) | `test_demo_scenarios.py::test_uc02_lookup_is_allowed_with_redaction`, `test_gateway.py::test_lookup_is_allowed_and_pii_is_masked`, `test_api.py::test_uc02_runs_without_a_passcode_in_replay` | B-01 to B-04 | `met` |
| UC-03 Injection, deny, incident | `make demo`; console Run Scenario (uc03); `make smoke` against a running instance | `test_demo_scenarios.py::test_uc03_injection_is_denied_opens_incident_and_kills`, `test_gateway.py::test_rt01_exfiltration_deny_opens_a_high_incident_and_kills_the_agent`, `test_api.py::test_uc03_denied_incident_and_kill` | RT-01, RT-19 | `met` |
| UC-04 Approval-gated increase | `make demo`; console Run Scenario (uc04) with the human approver and the passcode, then Approvals | `test_demo_scenarios.py::test_uc04_approval_pauses_then_identical_call_executes_once`, `test_oversight.py::test_uc04_approved_call_executes_once_with_the_identical_arguments`, `test_api.py::test_uc04_human_approval_resumes_the_run` | B-14 | `met` |
| UC-05 Approve-then-swap | `make demo`; console Run Scenario (uc05) | `test_demo_scenarios.py::test_uc05_swapped_arguments_do_not_execute`, `test_oversight.py::test_rt13_uc05_approve_then_swap_does_not_execute`, `test_api.py::test_uc05_swap_with_a_human_approver` | RT-13 | `met` |
| UC-06 Runaway loop, budget stop | `make demo`; console Run Scenario (uc06); Overview usage | `test_demo_scenarios.py::test_uc06_budget_stops_the_loop_after_30_calls`, `test_gateway.py::test_rt20_call_31_in_a_session_is_denied` | RT-20 | `met` |
| UC-07 Kill switch | `make demo`; console Run Scenario (uc07), or Kill on the Registry page with the passcode | `test_demo_scenarios.py::test_uc07_kill_switch_halts_the_run`, `test_oversight.py::test_rt22_uc07_kill_switch_denies_revokes_and_halts`, `test_console.py::test_registry_reactivate_needs_a_reason_then_works` | RT-22 | `partly met`: same limits as FR-22 on halting active runs |
| UC-08 Policy change management | Console Policies page (edit, activate, diff, roll back) with the passcode; API `POST /agents/{id}/policies` | `test_api.py::test_policy_change_new_version_diff_and_decisions_use_the_new_hash`, `test_gateway.py::test_policy_change_is_versioned_and_decisions_reference_the_new_hash` | B-15 | `met` |
| UC-09 Evidence pack | `make evidence AGENT=loan-ops-agent`; console Evidence page; sample in `docs/samples/` | `test_evidence.py::test_html_has_every_section_the_hash_and_the_disclaimer`, `test_evidence.py::test_pdf_has_the_document_name_header_and_page_x_of_y_footer`, `test_evidence.py::test_cli_writes_html_and_pdf` | none | `met` (PDF off in low-memory mode) |
| UC-10 Audit tamper detection | `make verify-audit`; console Overview integrity banner | `test_audit.py::test_cli_verify_audit_exit_codes`, `test_audit.py::test_rt24_tampering_is_detected_at_the_first_broken_event`, `test_api.py::test_tampering_shows_up_in_verify_and_overview` | RT-24 | `met`. The red banner code exists; no console test triggers it |
| UC-11 Red-team gate in CI | `make eval`; CI job `eval`; console Red-Team page | `test_evals.py::test_all_suites_pass_the_gate_in_replay`, `test_evals.py::test_gate_fails_when_a_threshold_is_breached`, `test_evals.py::test_cli_exit_code_follows_the_gate` | all RT and B scenarios | `met differently`: CI fails when must-block is below 100% or the benign pass rate is below 95%, but the README table is checked for freshness (`git diff --exit-code README.md`), not regenerated on `main` |

## How to keep this current

- Every slice updates the rows it touches, in the same commit as the code and tests.
- A new requirement or use case gets a row before it is built; a new test is added to the row it verifies.
- When a gap is closed, change the status and delete the explanation. When a limit is found, change the status and name it.
- Cite `file::function` for tests so a rename shows up in review; check names with `grep -rn "def test_" tests/`.
- Keep the status honest: if a test does not cover the behaviour the row claims, the row says `partly met`.
- Review this file together with [`SECURITY.md`](SECURITY.md), which shares the red-team ids.

---
*design/TRACEABILITY.md · Page 1 of 1*
