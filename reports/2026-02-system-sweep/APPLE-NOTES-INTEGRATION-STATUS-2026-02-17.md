# Apple Notes Integration Status (2026-02-17)

## Outcome

Direct MCP dependency is not required for core daily sync.
The active reliable path is AppleScript fallback.

## Active mode

Validation command:

```bash
bash ~/.claude/scripts/check-apple-notes-sync.sh --json
```

Current result:

```json
{"status":"ok","mode":"applescript","mcp_configured":0,"fallback_scripts":1,"sync_script_syntax":1,"embed_script_syntax":1,"notes_probe_ok":1}
```

## Operational path in use

1. Regenerate dashboard:
   - `~/Documents/Claude Projects/claude-shared/trigger-dashboard.sh --no-open`
2. Sync to Apple Notes:
   - `~/.claude/scripts/sync-journal-to-apple-notes.sh`
3. Dashboard embed:
   - `~/.claude/scripts/embed-dashboard-in-notes.py`

## New support added

- Apple Notes tagging utility now supports ID-based note references:
  - `~/.claude/scripts/apple-notes-tag.py`

Example:

```bash
python3 ~/.claude/scripts/apple-notes-tag.py "id:x-coredata://.../ICNote/2026-01-23" --add oyster,transport --dry-run
```

## Conclusion

The issue is treated as resolved via stable AppleScript-first fallback with a health-check gate.
