---
name: Verify watchdog script changes actually deployed
description: Previous session promised CPU monitoring in coreaudiod watchdog but only delivered memory monitoring - always verify script content matches the promise
type: feedback
originSessionId: 61ce7b68-9efd-4e7b-8fed-a15c77f3b9ab
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_verify_watchdog_changes.md
  migrated_on: 2026-05-17
---
After writing a watchdog or automation script, verify the deployed version contains the promised functionality - don't just report it done.

**Why:** On 2026-05-02 a session promised coreaudiod CPU monitoring but only shipped memory monitoring. Jim had to kill coreaudiod manually the next day because the watchdog wasn't catching CPU spikes. This eroded trust.

**How to apply:** After writing any script that runs via launchd/cron, run it once manually and confirm the log output shows the new behaviour before reporting done. Quote the log line as evidence.
