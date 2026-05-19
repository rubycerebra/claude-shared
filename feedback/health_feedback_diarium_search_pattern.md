---
name: feedback_diarium_search_pattern
description: "grep -i diary silently misses auto-generate-diarium.py — use grep -i diar or find -name \"*diar*\" to catch both diary and diarium files"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d1f38a65-6c18-45b3-acbd-83bc13757d39
  project: HEALTH
  source_file: feedback_diarium_search_pattern.md
  migrated_on: 2026-05-17
---

Use `grep -i diar` or `find -name "*diar*"` when searching for Diarium-related files — never `grep -i diary` alone.

**Why:** "diary" is NOT a substring of "diarium" (`d-i-a-r-y` vs `d-i-a-r-i-u-m`). `grep -i diary` silently misses files with only "diarium" in the name (e.g. `auto-generate-diarium.py`). This caused a complete miss of a fully-implemented script during planning, leading to a redundant design and lost trust.

**How to apply:** Any codebase search for diary/diarium files: use `grep -i diar` or `find -name "*diar*"`. Also applies to grep patterns in explore agent prompts — specify "search for both diary and diarium" explicitly.
