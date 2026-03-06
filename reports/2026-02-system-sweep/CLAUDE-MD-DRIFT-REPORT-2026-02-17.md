# CLAUDE.md Drift Report (2026-02-17)

## Command run

```bash
python3 ~/.claude/scripts/sync-claude-md.py
```

## Tool update completed

The drift detector now targets the active 3-project model.

File updated:
- `~/.claude/scripts/sync-claude-md.py`

Changes made:

1. Project scope is: `HEALTH`, `WORK`, `TODO`.
2. Section-presence differences are now reported separately (informational), not auto-failed as drift.
3. Brief filename pattern uses only `session-brief-HEALTH.md`, `session-brief-WORK.md`, `session-brief-TODO.md`.

## Current drift output summary

True drift sections reported:

1. Inlined Guardrails
2. Data Access: Brief First
3. Stale Data Protocol (HEALTH vs WORK/TODO)
4. Cross-Project Sync
5. Model Selection
6. Formatting (ADHD/Autism)

## Interpretation

- There is no separate `CLAUDE` project in the active model.
- Claude-specific maintenance should be tracked in `TODO` with labels (for example: `claude`, `claude-maintenance`).
- `Stale Data Protocol` mismatch between `HEALTH` and `WORK/TODO` is likely a real sync candidate.

## Recommended next sync action

If you want strict parity where intended, start by aligning:

- `Stale Data Protocol` across `HEALTH`, `WORK`, `TODO`.
