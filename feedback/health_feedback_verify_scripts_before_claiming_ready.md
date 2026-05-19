---
name: Verify scripts before claiming ready
description: Never present an untested script as "just needs running" — always verify with command output first
type: feedback
originSessionId: 15872824-e84c-4fb7-a93e-de2244825423
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_verify_scripts_before_claiming_ready.md
  migrated_on: 2026-05-17
---
Never claim a script is "ready to run" or present it as a one-step operation without evidence it has been tested. A script that exists in the repo may have never been executed, have missing dependencies, or fail silently.

**Why:** During HEALTH-70h1, presented `.repowise/reindex_ollama.py` as "just needs running, ~30-90 seconds, expected success" — it immediately failed with `ModuleNotFoundError: No module named 'httpx'`. Jim was frustrated by the wasted token spend on a false premise.

**How to apply:** Before describing a script as ready, either (a) quote actual prior run output, or (b) explicitly flag it as untested. Say "this script exists but hasn't been run — let's test it" rather than "just run this."
