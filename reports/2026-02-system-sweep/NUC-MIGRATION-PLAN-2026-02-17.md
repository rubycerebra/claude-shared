# NUC Migration Plan (2026-02-17, refreshed 2026-03-16)

## Objective

Move Claude daemon and maintenance automation to an always-on Intel NUC while keeping:

1. Local files accessible on Mac.
2. Daily output reliable when laptop is closed.
3. Todoist as the primary task/action surface.
4. Apple Notes available as a secondary summary/export bridge when wanted.

## Current constraints

- `~/.claude/daemon/data_collector.py` and most scripts are portable to Linux userspace.
- Apple Notes write path today uses AppleScript (`sync-journal-to-apple-notes.sh`, `embed-dashboard-in-notes.py`) and is macOS-only.
- Some MCP workflows assume local macOS context.
- Official Claude Code Remote Control now exists in research preview for web/iOS, but the originating desktop session must remain open; useful for mobile access, not a replacement for an always-on runtime.
- Existing Tailscale/Cloudflare setup helps expose dashboard/API, but not a full always-on Claude terminal path by itself.

## Recommended architecture

Use a split model:

1. **Windows NUC host + WSL2 (always on):** run daemon, cache generation, scheduled jobs, API integrations, and dashboard/API stack inside WSL2.
2. **Todoist primary control plane:** task capture, completion, and automation should land in Todoist first.
3. **Mac (event-driven bridge):** perform Apple Notes writes only when needed.
4. **File sync layer:** keep project files and cache available on both.

This keeps the always-on workload in WSL2, avoids forcing Apple Notes automation into Linux, and removes Apple Notes from being a blocker for core reliability.

## Phase 1 - WSL2 core runtime (low-risk)

### Deliverables

- WSL2 distro on the NUC with Python venv + daemon runtime.
- Startup model defined: `systemd` inside WSL2 or a Windows Task Scheduler/service wrapper invoking `wsl.exe`.
- Shared folder sync between Mac and NUC/WSL2.

### Implementation

1. Install/enable WSL2 on the NUC and create an Ubuntu/Debian distro.
2. Install daemon runtime in WSL2:
   - clone/sync `~/.claude/daemon/`
   - create venv
   - install `requirements.txt`
3. Enable startup inside WSL2. Preferred: `systemd` in WSL2. Fallback: Windows Task Scheduler launching `wsl.exe -d <distro> ...`.
4. Add `systemd` unit inside WSL2 (example):

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

5. Enable + start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now claude-data-collector
```

6. Sync files Mac <-> NUC using Syncthing (preferred) or git pull/push automation, with single-writer rules for generated/cache artefacts.

### Decision points

- Sync transport: Syncthing vs git automation.
- WSL2 startup model: `systemd` vs Windows wrapper.
- Whether cache folder sync is one-way (NUC -> Mac) or bidirectional.

## Phase 2 - Todoist-first bridge + Apple Notes secondary output

### Deliverables

- Todoist is the primary task/action surface for the system.
- Apple Notes remains optional for daily summaries, embeds, or human-readable context.
- Mac-only AppleScript writes are decoupled from core runtime success.

### Practical approach

1. NUC/WSL2 continues generating cache, dashboard artifacts, API outputs, and Todoist-facing automation.
2. Mac LaunchAgent monitors synced trigger/cache changes only for Apple Notes-related outputs.
3. Mac runs:
   - `~/.claude/scripts/sync-journal-to-apple-notes.sh`
   - `~/.claude/scripts/embed-dashboard-in-notes.py`
4. If the Mac is unavailable, the system still works via Todoist + dashboard/API; only Apple Notes mirroring is deferred.

### Alternative if no Mac should be involved

- Skip Apple Notes as a live dependency and rely on Todoist + dashboard/API.
- Optional later: iOS Shortcut / shared markdown export for selective Notes publication.

## Phase 3 - hardening + observability

### Deliverables

- Health checks and failure alerts.
- Daily verification logs.
- Recovery playbook.

### Checks

- WSL2/runtime availability (Windows host up, distro reachable).
- Daemon status (`systemctl is-active` or equivalent wrapper health).
- Cache freshness threshold.
- Todoist sync/API health.
- Apple Notes bridge success marker (only as secondary signal).
- Sync health (last successful file sync timestamp).
- WSL-safe doctor command:
  - `python3 ~/.claude/scripts/wsl2-doctor.py`
  - `python3 ~/.claude/scripts/wsl2-doctor.py --require-running --with-smoke`

## Planning changes since the original draft

- Active execution is now tracked in `TODO-3pyn`, `TODO-3pyn.1`, and `TODO-3pyn.2`; `TODO-7l2.5` is archive/planning context only.
- Likely runtime path is now Windows NUC + WSL2 rather than a generic VM.
- Todoist has become the primary source of truth for tasks/actions; Apple Notes should be treated as secondary.
- Official Claude Code remote control is promising for phone/web access, but it still depends on a live desktop session and does not remove the need for an always-on host.

## Security and secrets

- Store API tokens on the NUC/WSL2 side in `~/.claude/secrets.json` with strict permissions (`chmod 600`).
- Prefer service-specific scoped tokens.
- Keep OAuth refresh tokens out of git and synced only when required.

## Recommended execution order

1. Stand up WSL2 daemon + sync only (no Apple Notes changes).
2. Validate 7 days of stable cache/dashboard/API generation and Todoist flows.
3. Add macOS Apple Notes bridge trigger as secondary output.
4. Enable monitoring + alerting.
5. Test remote access and rollback.

## Execution checklist

For the concrete week-of-transfer checklist, use:

- `claude-shared/reports/2026-02-system-sweep/NUC-WSL2-TRANSFER-CHECKLIST-2026-03-16.md`
- Windows host prep:
  - `claude-shared/reports/2026-02-system-sweep/windows/README.md`

## Success criteria

- Cache updates continue when laptop lid is closed.
- Todoist remains authoritative for task/action flow.
- Mac has local project files and fresh cache.
- Apple Notes sync, if enabled, runs via the Mac bridge without being required for core system health.
- Recovery from reboot/network outage is automatic.

## File references

- Planning beads:
  - `TODO-7l2.5` (archive/planning context)
  - `TODO-3pyn`
  - `TODO-3pyn.1`
  - `TODO-3pyn.2`
- Concrete execution checklist:
  - `claude-shared/reports/2026-02-system-sweep/NUC-WSL2-TRANSFER-CHECKLIST-2026-03-16.md`
- Windows host prep:
  - `claude-shared/reports/2026-02-system-sweep/windows/README.md`
  - `claude-shared/reports/2026-02-system-sweep/windows/register-claude-wsl-logon-task.ps1`
  - `claude-shared/reports/2026-02-system-sweep/windows/run-claude-wsl-runtime-now.ps1`
  - `claude-shared/reports/2026-02-system-sweep/windows/setup-claude-tailscale-serve.ps1`
- Research source: `~/Documents/Claude Projects/claude-shared/handoff-archive/handoff-2026-02-05/1-NUC-RESEARCH.txt`
- Daemon: `~/.claude/daemon/data_collector.py`
- WSL runtime scripts:
  - `~/.claude/scripts/wsl2-start-runtime.sh`
  - `~/.claude/scripts/wsl2-stop-runtime.sh`
  - `~/.claude/scripts/wsl2-doctor.py`
- Notes bridge scripts:
  - `~/.claude/scripts/sync-journal-to-apple-notes.sh`
  - `~/.claude/scripts/embed-dashboard-in-notes.py`
