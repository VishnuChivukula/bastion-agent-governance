# Security policy

Bastion is a **reference implementation; not production; not legal advice.** It runs on synthetic data only.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** on this repository (Security → Report a vulnerability). Do not open a public issue for a suspected vulnerability. You can expect an acknowledgement within a few days.

## Scope

In scope: bypasses of the policy engine (default-deny, condition evaluation, argument normalisation), approval-grant replay or swap, kill-switch bypass, audit-log tampering that `verify` does not detect, and secret leakage.

Out of scope: hardening expected of a production deployment (multi-tenancy, SSO/RBAC, network isolation). See `docs/SPEC.md` §7.

## Secrets

No secrets belong in this repository. `.env` is gitignored, and gitleaks runs in pre-commit and CI.
