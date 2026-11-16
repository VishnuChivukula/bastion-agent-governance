**Bastion Kit · prompts/FIX_CI.md**

Paste below the line when GitHub shows a red ❌ on a commit.

---

CI is failing on main. Run `gh run list --limit 3`, then `gh run view <id> --log-failed`. Find the root cause and fix it properly: don't skip tests and don't loosen thresholds unless a threshold is wrong per `docs/EVALS.md`, in which case explain why. Run `make check` and `make eval` locally, push, and run `gh run watch` until green. Record what happened in `docs/PROGRESS.md` under Decisions.

---
*prompts/FIX_CI.md · Page 1 of 1*
