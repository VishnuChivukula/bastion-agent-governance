**Bastion Kit · prompts/DEPLOY_DONE.md**

Paste below the line once Render (or Railway) shows your public URL. Replace the URL.

---

The deploy is live at: https://REPLACE-ME.onrender.com

1. Fetch `<url>/_stcore/health` and confirm it answers `ok` (the console is the public port; the API's `/healthz` is internal to the container). On Render's free plan the first request after a sleep can take a minute. If the check fails, tell me exactly which setting or variable to change.
2. Add the live demo link and a "Live demo (replay mode, no cost)" badge to the top of the README, plus a note that mutating actions need a passcode.
3. Run `gh repo edit --homepage <url>`.
4. Update `docs/PROGRESS.md`, commit, push.

---
*prompts/DEPLOY_DONE.md · Page 1 of 1*
