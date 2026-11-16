**Bastion Kit · prompts/LOW_USAGE.md**

Paste below the line when your usage meter is above ~85% and no reset is left.

---

Usage is almost out. Stop new feature work now and run the ship-now sequence:
1. Make `main` green (`make check`). If a half-finished slice breaks it, move that work to a branch `wip/<slice>` and leave it out of main.
2. Make sure `make demo` works with no key on main.
3. Update the README so it describes only what actually works today; move everything else to a "Roadmap" section.
4. Update `docs/PROGRESS.md`: status table, exact next step, deferred items.
5. Commit, push, and if no release exists yet run `gh release create v0.1.0 --generate-notes`.
6. Print a final summary: what shipped, the repo URL, what is left, and the exact prompt to resume later.

---
*prompts/LOW_USAGE.md · Page 1 of 1*
