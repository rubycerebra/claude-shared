---
name: don't background tasks unless there's parallel work
description: Use foreground Bash for long tasks unless I genuinely have independent work to do in parallel
type: feedback
originSessionId: c7728693-612f-4706-a2a8-b784204613e7
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_no_unnecessary_background.md
  migrated_on: 2026-05-17
---
Do not background a Bash command (`run_in_background: true`) unless I have independent work to do in parallel during the wait. Foreground is the default.

**Why:** Jim has no notification when a backgrounded task finishes — the harness only notifies me, the assistant, in my next turn. If Jim is waiting on the result, backgrounding just adds friction: he has to keep typing "any update?" to advance my turn so I check. Foreground execution means the result comes back inline and Jim sees it immediately.

**How to apply:**
- `session-wrap-up.sh`, builds, deploys, anything where the next step depends on completion → foreground.
- Watching a long process WHILE doing something else (e.g. running a build while drafting a doc) → background OK.
- If unsure, default to foreground. The harness's 2-min timeout can be raised explicitly if needed.
