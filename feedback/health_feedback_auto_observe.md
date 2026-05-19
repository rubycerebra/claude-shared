---
name: Auto-save observations
description: Save vexp observations automatically without asking for confirmation
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_auto_observe.md
  migrated_on: 2026-05-17
---

Save observations via `mcp__vexp__save_observation` automatically whenever something worth preserving comes up — architectural decisions, important code paths, discovered gotchas, workflow patterns. Do not ask "Worth an /observe?" — just save it silently.

**Why:** Jim always says yes. The prompt is unnecessary friction.

**How to apply:** Any time you would have ended a response with "Worth an /observe? →", save the observation immediately and skip the prompt entirely.
