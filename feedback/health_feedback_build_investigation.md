---
name: Build performance investigation — first-principles required
description: When build is slow, run a fresh audit via run_pipeline rather than assuming the last known cause
type: feedback
originSessionId: 8565c89e-a35d-4be7-986a-239e1db6fc25
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_build_investigation.md
  migrated_on: 2026-05-17
---
When a build performance complaint comes in, do NOT assume it's the last known failure mode (zombie processes, Node version). Run `run_pipeline("why is the dashboard cold build slow")` first for a fresh first-principles audit.

**Why:** Codex found the barrel import issue in src/icons.ts that Claude missed because Claude reached for familiar fixes (zombie PIDs, Node mismatch) instead of auditing the build config from scratch. This wasted time and eroded trust.

**How to apply:** Any "build is slow" or "cold start is slow" complaint → run_pipeline with a broad build audit question before proposing a fix.
