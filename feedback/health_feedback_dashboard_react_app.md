---
name: Dashboard is a React app, not a browser
description: Jim uses the dashboard as a React app (not a web browser). Reload instructions must be app-specific, not browser-specific.
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_dashboard_react_app.md
  migrated_on: 2026-05-17
---

Jim always accesses the dashboard as a React app — never as a conventional browser tab. Do NOT say "hard refresh" or "open in browser" or give browser-specific instructions (Cmd+Shift+R, F5, etc.).

**Why:** Jim found "hard refresh" unclear and confusing because it implies a browser context he doesn't use.

**How to apply:** After dashboard changes, say "reload the app" or describe the app-specific reload gesture. If unsure of the exact reload method (PWA Cmd+R, dev server auto-reload, Electron quit+reopen), ask Jim once and save it to memory.
