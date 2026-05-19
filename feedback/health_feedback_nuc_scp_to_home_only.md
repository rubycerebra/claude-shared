---
name: NUC SCP workaround files go to home dir only
description: SCP workaround scripts to home dir, never to the scripts git repo
type: feedback
originSessionId: 23d9746a-7d97-4720-9efa-5fffd5f87a0d
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_nuc_scp_to_home_only.md
  migrated_on: 2026-05-17
---
During debugging sessions, SCP workaround .ps1 files to `C:\Users\James Cherry\` (home), never to `C:\SyncData\claude-scripts\`. Files placed in the scripts repo as untracked copies will block subsequent `git pull` operations with "untracked files would be overwritten" errors.

**Why:** Happened twice in 2026-05 -- source_policy.py and preflight-check.py both appeared as untracked NUC files blocking pulls because they were created locally before being committed on Mac.

**How to apply:** When writing a .ps1 helper to run remotely on the NUC via SCP, always target `C:\Users\James Cherry\<name>.ps1`. Never target `C:\SyncData\claude-scripts\`.
