---
name: PS1 em-dash encoding bug
description: Em-dash chars in PowerShell string literals cause parse errors when scripts are written on Mac and synced to NUC
type: feedback
originSessionId: 18dafaa4-14ba-487a-a22f-0f398ee66726
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_ps1_emdash.md
  migrated_on: 2026-05-17
---
Never use em-dash (`—`, U+2014) in PowerShell (.ps1) files that run on the NUC.

**Why:** Mac writes files as UTF-8. PowerShell 5.1 on Windows reads scripts as CP1252 by default. The UTF-8 byte sequence for `—` (0xE2 0x80 0x94) is misinterpreted as `â€"`, which terminates a string literal mid-line and causes a `TerminatorExpectedAtEndOfString` parser error. The error kills the entire script silently when run as a scheduled task.

**How to apply:** In any `.ps1` file destined for the NUC (synced via Syncthing from `~/.claude/scripts/`), replace all `—` with ` -` (space-hyphen). This applies to string literals AND comments — safer to use ASCII-only throughout. When writing new PS1 files, never use `—`, `→`, or any non-ASCII Unicode punctuation.
