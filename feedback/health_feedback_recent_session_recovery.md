---
name: feedback_recent_session_recovery
description: "For finding what was built in recent sessions, use git log --stat not QMD — QMD has indexing lag for same-day/yesterday sessions"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d1f38a65-6c18-45b3-acbd-83bc13757d39
  project: HEALTH
  source_file: feedback_recent_session_recovery.md
  migrated_on: 2026-05-17
---

For "what was built recently / yesterday?", use `git log --since="2 days ago" --stat` across `~/.claude/scripts` and relevant repos — NOT QMD session search.

**Why:** QMD indexes session summaries with a delay. A session from yesterday or today may not be indexed yet. Searching QMD for a recent session ID returns empty even when the work is fully committed. This caused a planning failure where an implemented script (`auto-generate-diarium.py`) was missed entirely, leading to a redundant plan and user frustration.

**How to apply:** When the user says "what did we do yesterday" or references a session ID: first run `git log --since="2 days ago" --stat` in `~/.claude/scripts` and the primary project repo. Read the changed files directly. Only use QMD for older sessions (>2 days).
