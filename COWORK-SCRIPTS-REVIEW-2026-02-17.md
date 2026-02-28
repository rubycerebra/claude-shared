# Cowork Scripts Review (2026-02-17)

## Scope reviewed

Path: `~/Documents/Claude Projects/claude-shared/`

Scripts reviewed:

- `claude-context-health.sh`
- `claude-context-work.sh`
- `claude-context-todo.sh`
- `generate-dashboard.py`
- `generate-notes-dashboard.py`
- `open-dashboard.sh`
- `test-sync.sh`
- `trigger-dashboard.sh`
- `verify-sync.sh`

## Validation results

1. Python syntax check: pass (`python3 -m py_compile *.py`).
2. Shell syntax check: pass (`bash -n *.sh`).
3. No blocking TODO/FIXME markers in active script logic.

## Improvement enacted

`verify-sync.sh` was outdated and referenced legacy worktree paths.

What was changed:

1. Switched checks to active projects:
   - `HEALTH`, `WORK`, `TODO`
2. Session brief checks now target only:
   - `session-brief-HEALTH.md`, `session-brief-WORK.md`, `session-brief-TODO.md`
3. Added integrated drift check output from `~/.claude/scripts/sync-claude-md.py`.
4. Kept Apple Notes integration mode check via `check-apple-notes-sync.sh`.

## Current risk notes

- CLAUDE.md drift can still exist across `HEALTH/WORK/TODO` and should be reviewed periodically.
- This is now visible in `verify-sync.sh` output and not hidden.

## Conclusion

Cowork scripts are operational.
One script (`verify-sync.sh`) was modernised to match the active 3-project architecture.
