---
name: NUC Syncthing conflict fix pattern
description: When api_server scripts have git merge conflicts, use atomic fix+restart on NUC to beat Syncthing revert race
type: feedback
originSessionId: ee9428a6-69ef-423c-8dd9-24b6a328aea6
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_nuc_syncthing_conflict_fix.md
  migrated_on: 2026-05-17
---
When api_server scripts have unresolved git merge conflict markers (`<<<<<<<`), the NUC API crashes with SyntaxError on startup. Syncthing reverts Mac-side fixes within 30s (NUC is master for C:\SyncData\claude-scripts\).

**Fix pattern — always fix NUC first, then restart atomically:**

1. SCP the fix script to `C:\Users\James Cherry\` (never to SyncData)
2. Run fix + restart in a single SSH command to beat Syncthing:
   ```bash
   sshpass -p 'Trekbike21' ssh "James Cherry"@100.73.88.14 \
     "python \"C:\\Users\\James Cherry\\fix_conflicts.py\" && schtasks /run /tn \\Claude\\ClaudeRestartApi"
   sleep 20 && curl -s http://100.73.88.14:8765/health
   ```
3. Fix Mac side after NUC confirms healthy (Syncthing will sync NUC→Mac once both match)

**Why:** NUC is Syncthing master. Mac edits reverted within 30s. Race condition = fix NUC → Mac files overwritten with NUC's clean version → Mac stays clean.

**Conflict resolution:** Keep "Updated upstream" side in all cases (run regex replace, not manual).

**How to apply:** Any time NUC API goes PAUSED and logs show SyntaxError with `<<<<<<< Updated upstream` in the traceback.
