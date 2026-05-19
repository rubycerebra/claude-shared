---
name: vexp fallback chain — grep before Explore agents
description: When vexp run_pipeline fails or returns no useful results, fall back to bash grep before spawning Explore agents
type: feedback
originSessionId: f949eef8-f92c-43fd-8671-55002a89fa50
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_vexp_fallback.md
  migrated_on: 2026-05-17
---
When `mcp__vexp__run_pipeline` fails or returns no useful results, fall back to bash grep before spawning Explore agents.

**Why:** Code search chain is: repowise → vexp → bash grep → Explore agents.

**How to apply:** On vexp run_pipeline failure or zero useful pivots, use bash grep next. Only escalate to Explore agents if grep also yields insufficient results.
