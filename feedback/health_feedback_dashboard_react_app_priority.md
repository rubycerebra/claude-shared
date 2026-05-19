---
name: Dashboard = React app only
description: All dashboard work must target the React dashboard-app, never legacy HTML. The React app at localhost:8765/app is the ONLY place Jim looks.
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_dashboard_react_app_priority.md
  migrated_on: 2026-05-17
---

The React dashboard app (`~/Documents/Health/dashboard-app/`) is the ONLY dashboard Jim uses. It runs at `http://localhost:8765/app/` served by the Mac's api-server.py.

**Why:** Jim made changes via a Windows Claude session (design review) that were applied to the NUC side but never made it to the Mac React app. This caused confusion and wasted a full debugging session chasing "caching" issues when the real problem was that the code branches diverged.

**How to apply:**
- When editing dashboard UI: edit `dashboard-app/src/App.tsx` and `styles.css` FIRST
- After edits: `cd ~/Documents/Health/dashboard-app && npm run build` — verify new JS hash in output
- Never edit `claude-shared/dashboard.html` (deprecated legacy snapshot)
- Never assume NUC-side changes have synced to the Mac — always verify the Mac's source
- If Jim mentions a "design review" or "Windows Claude" change, check the Mac React source to see if those changes actually landed
- The api-server.py serves from `~/Documents/Health/dashboard-app/dist/` on Mac — that's the only dist that matters
