---
name: Dashboard verify is mandatory after all dashboard work
description: Must run /dashboard-verify after any fix or change that could affect the dashboard UI — no exceptions
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_dashboard_verify_mandatory.md
  migrated_on: 2026-05-17
---

Always run `/dashboard-verify` after completing any work that touches the dashboard (api-server.py, React source, cache logic, calendar filtering, etc.).

**Why:** Jim repeatedly experienced the "say it's fixed, check the app, still broken" loop because I was validating only the server-side API response, not the actual browser view. localStorage caching and server restarts can leave the UI showing stale data even after the code is correct.

**How to apply:** After every dashboard-related fix or change:
1. Make the fix
2. Run `/dashboard-verify` — it builds if needed, takes Playwright screenshots, and shows the actual browser state
3. Read the screenshots and confirm the issue is resolved visually
4. Only then declare the work done

Never claim a dashboard fix is complete without Playwright screenshot evidence.
