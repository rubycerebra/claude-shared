---
name: Todoist API version
description: Always use Todoist v1 API (/api/v1/) — the shared helper already wraps it; never curl /rest/v2/
type: feedback
originSessionId: a6c93fbc-09fb-497d-8129-ed22c742381e
metadata:
  node_type: memory
  type: feedback
  project: TODO
  source_file: feedback_todoist_api.md
  migrated_on: 2026-05-17
---
Always use Todoist **v1 API**: `https://api.todoist.com/api/v1/`

The `/rest/v2/` endpoints are deprecated and return "This endpoint is deprecated."

**Why:** The shared helper at `~/.claude/scripts/shared/todoist_helper.py` already uses `API_BASE = "https://api.todoist.com/api/v1"` — use it instead of curling directly. This is the project standard.

**How to apply:** When making any Todoist API call, either import from `shared.todoist_helper` or use `/api/v1/` base URL directly. Never use `/rest/v2/`.
