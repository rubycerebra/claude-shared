---
name: feedback-beads-syncthing-race
description: Beads closures can revert mid-session when Syncthing pulls a stale .beads/issues.jsonl from another machine — verify after closing and re-close if needed
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0c1cba48-58ea-4cb5-85cd-cd65940734d1
  project: TODO
  source_file: feedback_beads_syncthing_race.md
  migrated_on: 2026-05-17
---

When working through a batch of `bd close` operations, verify final status with `bd show <id>` afterwards. Closures occasionally revert to OPEN if Syncthing pulls a stale `.beads/issues.jsonl` from another machine (WORK laptop, NUC) between commands.

**Why:** During the 2026-05-15 session of clearing the TODO P2 backlog, two beads I'd closed early (TODO-9fq, TODO-qe1) were reverted to OPEN by the time I ran the final `bd show` check. The `auto-imported X issues from .beads/issues.jsonl` messages on every `bd` invocation show that each command re-reads the jsonl into an empty DB; if a Syncthing pull lands between my close and the next command, my closure is overwritten by the older state.

**How to apply:**
- After batch `bd close` operations, run `bd show <id>` for each closed ID before claiming the bead is done.
- If a closure reverted, re-close with a note explaining "first close was reverted by Syncthing pull."
- This race isn't deterministic — closures persist if no pull happens in the window, so don't panic-rerun every time. Just verify.
- Long-term fix could be `bd export` after each close, but cost/benefit unclear given the race window is small. Links: [[user_health_journey]] not relevant here; no related memories yet.
