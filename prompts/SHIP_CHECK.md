**Bastion Kit · prompts/SHIP_CHECK.md**

Paste below the line before you share the repo with anyone.

---

Run the final ship check and fix anything that fails:
1. Clone the GitHub repo fresh into a temp directory, run `make setup && make demo` with no API key in the environment, and report the result.
2. `gh run list --limit 5`: the latest run on main must be green.
3. Run the `reviewer` subagent on the whole repo. Fix every P0 and as many P1 items as you reasonably can.
4. Confirm: README GIF renders, live link works, results table populated, sample evidence PDF linked, disclaimer present, LICENSE present, `docs/VERIFY.md` complete.
5. Secret scan: `git log -p | grep -iE "sk-ant|api[_-]?key\s*=\s*['\"][^'\"]+"` must return nothing real.
6. Print the SPEC §8 checklist with ✅/❌ and the repo URL.

---
*prompts/SHIP_CHECK.md · Page 1 of 1*
