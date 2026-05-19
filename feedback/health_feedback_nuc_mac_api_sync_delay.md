---
name: feedback_nuc_mac_api_sync_delay
description: "After editing app.py on NUC, Syncthing may take >5 minutes to push to Mac — apply the same patch to Mac directly then restart Mac API, rather than waiting for sync"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d1f38a65-6c18-45b3-acbd-83bc13757d39
  project: HEALTH
  source_file: feedback_nuc_mac_api_sync_delay.md
  migrated_on: 2026-05-17
---

After editing `api_server/app.py` on the NUC via SSH, Syncthing does NOT always push to Mac promptly — observed 5+ minute delays. Do not wait for sync; apply the same patch directly to `/Users/jamescherry/.claude/scripts/api_server/app.py` on Mac and restart the Mac API immediately after the NUC edit.

**Why:** The Mac local API (`127.0.0.1:8765`) serves the dashboard. It runs the Mac copy of app.py. If the NUC edit doesn't sync, the Mac API keeps running old code and verifications will show the fix hasn't taken effect even though the NUC copy is correct.

**How to apply:** After any NUC app.py edit: run the same Python patch script on Mac, then `launchctl unload/load com.claude.api-server.plist`. Both NUC and Mac must be restarted — NUC via `schtasks /run /tn \\Claude\\ClaudeRestartApi`.
