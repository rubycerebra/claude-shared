---
name: Syncthing NUC-first edit workflow
description: Syncthing syncs ~/.claude/scripts bidirectionally — editing on Mac causes revert cycles; always edit on NUC
type: feedback
originSessionId: 92e14c12-fe9d-44ed-9bc7-fdacf0ec8764
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_syncthing_nuc_edit_workflow.md
  migrated_on: 2026-05-17
---
Edit `~/.claude/scripts/api_server/app.py` (and other synced scripts) ON THE NUC via SSH, not on Mac.

**Why:** Syncthing syncs `~/.claude/scripts` bidirectionally between Mac and NUC every 30 seconds (folder id `v2yoe-skvgy`). When you edit on Mac, Syncthing pushes the edit to NUC, NUC's git sees it as a local change, next `git stash` reverts it, and Syncthing pushes the old version back to Mac. Files keep reverting.

**How to apply:** For any file in `~/.claude/scripts/api_server/` that needs changing: SSH to NUC, edit with `echo`/`sed`/`python3 -c` or push via the obey rule pattern. Then `git add`, `git commit`, `git push` from NUC. Mac will get the correct version via both Syncthing and a Mac-side `git pull`.

Alternatively: commit from Mac (so HEAD is correct), force NUC to `git checkout origin/main -- <file>` to sync, then Syncthing will stabilise with the committed version on both sides.
