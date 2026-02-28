# Recurring Beads Setup

Last updated: 2026-02-17

This setup auto-creates weekly/monthly beads when they are due.

## Files

- Config: `~/.claude/config/recurring-beads.json`
- Script: `~/.claude/scripts/sync-recurring-beads.py`

## Current Recurring Rules

### Weekly (Friday)

- HEALTH: Friday: Export and review health data
- HEALTH: Friday: Review and prune habit streaks
- HEALTH: Friday: Update wins.md with weekly accomplishments
- HEALTH: Friday: Weekly insight digest

### Monthly (Day 1)

- WORK: Monthly: Job alerts and scraper review

## Manual Run (Optional)

Dry-run preview:

```bash
python3 ~/.claude/scripts/sync-recurring-beads.py --dry-run
```

Create due beads:

```bash
python3 ~/.claude/scripts/sync-recurring-beads.py
```

## Behavior

For each due rule, the script:

1. Checks if an open bead with the same title already exists.
2. Checks if a matching bead was already closed in the same recurrence period.
3. Creates a new bead only if neither condition is true.

This prevents duplicate recurring tasks.

## Automation Status

Recurring sync is live via macOS `launchd`:

- Agent: `~/Library/LaunchAgents/com.claude.sync-recurring-beads.plist`
- Runs daily at 08:05 local time
- Runs at login (`RunAtLoad=true`)
- Logs:
  - `~/.claude/logs/sync-recurring-beads.log`
  - `~/.claude/logs/sync-recurring-beads-error.log`

This means recurring beads are created automatically when due; manual runs are now fallback only.
