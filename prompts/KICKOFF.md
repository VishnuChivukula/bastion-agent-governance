**Bastion Kit · prompts/KICKOFF.md**

Paste everything below the line into Claude Code (Fable selected, plan mode on).

---

You are building **Bastion** in this folder, end to end. I will only click approvals and do the human-only steps in START_HERE.md. You do everything else: architecture, specs, code, tests, evals, docs, git, GitHub and deploy config.

1. **Read first:** CLAUDE.md, then every file in `docs/` in the order CLAUDE.md lists, then `policies/loan-ops-agent.yaml`, `.claude/settings.json` and `.claude/agents/*`.

2. **Preflight** (read-only). Check and report as a short table: `git --version`, `gh auth status`, `uv --version`, whether uv can provide Python 3.12, `docker --version` (optional), and whether an API key is configured. For the key, run only:
   `uv run --with python-dotenv python -c "import os;from dotenv import dotenv_values as d;print('KEY_SET' if (os.getenv('ANTHROPIC_API_KEY') or d('.env').get('ANTHROPIC_API_KEY')) else 'KEY_MISSING')"`
   Never print or read the key value.

3. **Plan (plan mode):** propose the final file tree, the slice order from `docs/SLICES.md` (respect the cut line), any deviations from ARCHITECTURE.md with reasons, and the human actions you will need from me and when. Ask questions only if they are truly blocking. Then wait for my approval.

4. **Execute after approval:** start with S0 and go slice by slice **without waiting for me** unless you are blocked or need a human-only step. After every slice: `make check` green → update `docs/PROGRESS.md` → commit (Conventional Commits) → `git push` → print a 3-line status (done / next / human action needed).

5. **Usage discipline:** delegate prose and bulk text to the `doc-writer` subagent; run the `reviewer` subagent at the end of S4 and S9b. Avoid re-reading large files unnecessarily. When context gets long, update PROGRESS with the exact next step, commit, push, and tell me to `/clear` and paste `prompts/RESUME.md`.

Start with step 1 now.

---
*prompts/KICKOFF.md · Page 1 of 1*
