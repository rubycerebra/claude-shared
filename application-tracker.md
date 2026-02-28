# Application Tracker

Primary tracker lives in:

- `~/Documents/CV/Applications/application-tracker.xlsx`

This workbook is generated/synced by:

- `~/.claude/scripts/create-application-tracker.py`

Its source data cache is:

- `~/.claude/cache/application-tracker-data.json`

Daemon integration:

- `~/.claude/daemon/data_collector.py` runs tracker sync during cache refresh and stores a summary under `application_tracker_excel` in `session-data.json`.
