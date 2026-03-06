# NUC Migration Plan (2026-02-17)

## Objective

Move Claude daemon and maintenance automation to an always-on Intel NUC while keeping:

1. Local files accessible on Mac.
2. Daily output reliable when laptop is closed.
3. Apple Notes updates possible without manual laptop use.

## Current constraints

- `~/.claude/daemon/data_collector.py` and most scripts are portable.
- Apple Notes write path today uses AppleScript (`sync-journal-to-apple-notes.sh`, `embed-dashboard-in-notes.py`) and is macOS-only.
- Some MCP workflows assume local macOS context.

## Recommended architecture

Use a split model:

1. **NUC (always on):** run daemon, cache generation, scheduled jobs, API integrations.
2. **Mac (event-driven bridge):** perform Apple Notes writes only.
3. **File sync layer:** keep project files and cache available on both.

This avoids forcing Apple Notes automation to Linux while still removing laptop-open dependency for core data refresh.

## Phase 1 - NUC core runtime (low-risk)

### Deliverables

- Python venv + daemon on NUC.
- `systemd` service for data collector.
- Shared folder sync between Mac and NUC.

### Implementation

1. Install daemon runtime on NUC:
   - clone/sync `~/.claude/daemon/`
   - create venv
   - install `requirements.txt`

2. Add `systemd` unit (example):

```ini
[Unit]
Description=Claude data collector
After=network-online.target

[Service]
Type=simple
ExecStart=/home/jim/.claude/daemon/venv/bin/python3 /home/jim/.claude/daemon/data_collector.py
WorkingDirectory=/home/jim/.claude/daemon
Restart=always
RestartSec=10
Environment=PATH=/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

3. Enable + start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now claude-data-collector
```

4. Sync files Mac <-> NUC using Syncthing (preferred) or git pull/push automation.

### Decision points

- Sync transport: Syncthing vs git automation.
- Whether cache folder sync is one-way (NUC -> Mac) or bidirectional.

## Phase 2 - Apple Notes bridge (required for full parity)

### Deliverables

- Keep Apple Notes write operations on macOS.
- Trigger macOS AppleScript jobs from NUC outputs.

### Practical approach

1. NUC continues generating cache and dashboard artifacts.
2. Mac LaunchAgent monitors synced trigger/cache changes.
3. Mac runs:
   - `~/.claude/scripts/sync-journal-to-apple-notes.sh`
   - `~/.claude/scripts/embed-dashboard-in-notes.py`

This lets notes update even when you are not actively using the laptop; only a signed-in Mac is needed.

### Alternative if no Mac should be involved

- Use iOS Shortcut + iCloud files to populate Notes from synced markdown.
- Trade-off: less control over exact formatting/attachments.

## Phase 3 - hardening + observability

### Deliverables

- Health checks and failure alerts.
- Daily verification logs.
- Recovery playbook.

### Checks

- Daemon status (`systemctl is-active`).
- Cache freshness threshold.
- Apple Notes bridge success marker.
- Sync health (last successful file sync timestamp).

## Security and secrets

- Store API tokens on NUC in `~/.claude/secrets.json` with strict permissions (`chmod 600`).
- Prefer service-specific scoped tokens.
- Keep OAuth refresh tokens out of git and synced only when required.

## Recommended execution order

1. Stand up NUC daemon + sync only (no Notes changes).
2. Validate 7 days of stable cache generation.
3. Add macOS Notes bridge trigger.
4. Enable monitoring + alerting.

## Success criteria

- Cache updates continue when laptop lid is closed.
- Mac has local project files and fresh cache.
- Apple Notes daily sync runs via bridge without manual intervention.
- Recovery from reboot/network outage is automatic.

## File references

- Research source: `~/Documents/Claude Projects/claude-shared/handoff-archive/handoff-2026-02-05/1-NUC-RESEARCH.txt`
- Daemon: `~/.claude/daemon/data_collector.py`
- Notes bridge scripts:
  - `~/.claude/scripts/sync-journal-to-apple-notes.sh`
  - `~/.claude/scripts/embed-dashboard-in-notes.py`
