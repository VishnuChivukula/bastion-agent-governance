**Bastion Kit · prompts/DEPLOY_DONE.md**

Paste below the line after Railway shows your public domain. Replace the URL.

---

Railway deploy is live at: https://REPLACE-ME.up.railway.app

1. `curl -s <url>/healthz` (or fetch it) and confirm 200. Note: WebFetch can't reach localhost, but it can reach this URL. If the health check fails, tell me exactly which Railway setting or variable to change.
2. Add the live demo link and a "Live demo (replay mode, no cost)" badge to the top of the README, plus a note that mutating actions need a passcode.
3. Run `gh repo edit --homepage <url>`.
4. Update `docs/PROGRESS.md`, commit, push.

---
*prompts/DEPLOY_DONE.md · Page 1 of 1*
