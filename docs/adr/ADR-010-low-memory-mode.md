# ADR-010: Low-memory mode for small hosts (Render free tier)

**Status:** accepted · 2026-11-17

## Context
The public demo has to run on a free host with 512 MB of RAM, 0.1 CPU and an ephemeral disk, which sleeps after 15 idle minutes. Measured before this change, the container's three Python processes (API + gateway, console, demo tools server) plus the process manager used more than 500 MB after one scenario and a console session, and the PDF renderer adds a headless browser on top. The largest costs were Presidio with its spaCy model in the API (about 150 MB), the console importing the server stack through a shared constants module (about 120 MB), and pandas with pyarrow in the console (about 70 MB).

## Decision
`BASTION_LOW_MEMORY=true` selects a small-host profile. Without it nothing changes.

- **PII engine.** `LightRedactor` replaces Presidio: regular expressions with checksum validation for IBANs (mod 97) and card numbers (Luhn), an e-mail pattern, and the `phonenumbers` library with the same regions and leniency Presidio uses. Presidio and spaCy are imported lazily, so the process never loads them. A test asserts that both engines return identical spans for every string in the demo data and the eval scenarios, across the entity sets the policy uses; that is what keeps the recorded model fixtures valid in this mode.
- **No headless browser.** `GET /agents/{id}/evidence.pdf` answers `503` with an explanation; the HTML pack is complete and a sample PDF is in the repository. `/meta` reports `low_memory`, `pii_engine` and `pdf_enabled`, and the console says so in its banner.
- **Console.** Header names moved to `bastion/headers.py`, which imports nothing, so the console no longer loads FastAPI, SQLAlchemy, MCP or the gateway. In this profile tables are rendered as markdown and the budget chart as progress bars, so pandas and pyarrow are never imported.
- **Demo data.** Generated once into a pristine snapshot and restored from it on every reset (in a short-lived subprocess in this profile), so Faker is not held in a long-running process. The tools server imports the generator only if its database is missing.
- **Applies to every mode:** lazy imports of Presidio, Faker, Playwright and the Anthropic SDK; `MALLOC_ARENA_MAX=2` in the image.
- **Guard rail.** CI runs the image with `--memory=512m` in this profile, drives the console with a real browser from outside the container, runs UC-03, and fails if the container was OOM-killed, if a process died, or if resident memory exceeds 450 MB.

## Consequences
- Measured after the change, with a browser session that visited every page, ran a scenario and generated a pack: about 260 MB resident in total (macOS; CI prints the Linux figure on every run).
- Known differences outside the demo corpus are not ruled out. Two found in review were closed and added to the equivalence test (lower-case IBANs; an IBAN glued to following letters). Others may exist.
- The light engine is narrower than Presidio. It covers the same four entity types by pattern and checksum and has no path to NER-based entities (names, locations) or to Presidio's wider recogniser set. Equality is proven only for the synthetic demo data and eval inputs. It is a demo-hosting profile, not a recommendation for real data.
- A deployment in this profile cannot produce the PDF. The control it demonstrates (header with the document name, `Page X of Y`) is shown by the committed sample and by CI on the default profile.
- On 0.1 CPU the first request after a sleep takes a while: the platform starts the container, then the first scenario loads the agent stack. The README says so.
- Two PII engines must be kept in agreement; the equivalence test fails if they drift on the demo corpus.
