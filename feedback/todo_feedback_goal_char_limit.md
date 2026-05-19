---
name: feedback-goal-char-limit
description: /goal command has a 4000-character limit on the goal condition — truncate/compress before invoking
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd40a4ed-00f6-43ca-9e2a-eca413848829
  project: TODO
  source_file: feedback_goal_char_limit.md
  migrated_on: 2026-05-17
---

When constructing a `/goal` invocation, the goal condition text MUST stay under 4000 characters. If the planned goal text is longer, compress it (tighten phrasing, drop redundant context, abbreviate phase headers) BEFORE invoking — do not just paste the long version and let the command bounce back with "Goal condition is limited to 4000 characters (got N)".

**Why:** On 2026-05-17, a 6252-char goal hit the limit and Jim had to manually intervene. Wasted a turn re-compressing it.

**How to apply:** Before calling `/goal` (or the underlying `loop` skill in dynamic mode), do a rough char count of the planned condition. If >~3800, compress: drop preamble, shorten bullet prose, collapse "Read first" lists into one comma-separated line, use abbreviations for repeated bead IDs, drop hedging language. Preserve: phase structure, MUST/MUST NOT lists, Done-when criteria, stop conditions.
