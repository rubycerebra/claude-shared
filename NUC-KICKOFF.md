# NUC Migration — Kickoff Brief
**Prepared: 2026-03-16 | Pick up: tomorrow on the NUC**

> Paste this into your Claude Code session on the NUC to orient it immediately.

---

## Prompt to paste into the NUC Claude Code session

```
We're doing the NUC WSL2 migration — Checklist B. Here's the full context:

**Goal:** Bootstrap WSL2 on this NUC so it can run the Mac daemon, API server,
and dashboard generation. This moves the always-on automation off the Mac.

**Full checklist:**
claude-shared/reports/2026-02-system-sweep/NUC-WSL2-TRANSFER-CHECKLIST-2026-03-16.md

**Checklist A is complete.** Start at Checklist B.

**Key decisions already made:**
- Runtime: WSL2 (Ubuntu) on this Windows NUC
- Sync transport: Syncthing (install on both Mac and NUC)
- Remote access: Jump Desktop ✓
- Primary task surface: Todoist
- Apple Notes: Mac-only bridge, secondary

**What I need you to do — Checklist B in order:**
1. Check if WSL2 is already installed: `wsl --status` and `wsl -l -v`
2. If not: enable WSL2 via PowerShell (`wsl --install -d Ubuntu`)
3. If Ubuntu distro doesn't exist: `wsl --install -d Ubuntu`
4. Install Syncthing on Windows side (winget or direct download)
5. Guide me through setting up Syncthing to sync from the Mac:
   - ~/.claude/daemon/
   - ~/.claude/scripts/
   - ~/Documents/Claude Projects/
6. Once synced, inside WSL2:
   - Install base packages: python3, python3-venv, git, curl, lsof
   - Create daemon venv: python3 -m venv ~/.claude/daemon/venv
   - pip install -r ~/.claude/daemon/requirements.txt
7. Copy secrets manually (do NOT sync these):
   - ~/.claude/secrets.json
   - ~/.claude/config/api-token.txt
   - ~/.claude/daemon/.env
   Backup is at: ~/.claude/backups/nuc-migration-2026-03-16/ on the Mac
8. Run: python3 ~/.claude/scripts/wsl2-doctor.py
   (should show ready_with_warnings or better)

**Systemd service files are ready** at ~/.claude/scripts/systemd/:
- claude-daemon.service
- claude-api.service
- claude.target
- install-systemd-services.sh

Run install-systemd-services.sh after WSL2 is stable.

**Bead tracking this work:** Health-14

Start by running `wsl --status` and report what you see.
```

---

## What's already done (Checklist A — complete)

| Item | Status |
|---|---|
| NUC admin access | ✅ Jump Desktop |
| WSL distro decision | ✅ Ubuntu |
| Sync transport decision | ✅ Syncthing |
| Remote access endpoints recorded | ✅ Cloudflare + Tailscale |
| Secrets backed up on Mac | ✅ `~/.claude/backups/nuc-migration-2026-03-16/` |
| Mac baseline checks | ✅ All green (wsl2-doctor, health-check, system-ops-audit, daemon-smoke-test, dashboard-smoke-tests, apple-notes-sync) |

## Mac is ready and waiting

- Daemon: running
- API server: running (port 8765)
- Dashboard: generating
- All scheduled tasks: healthy
- Mac can stay running during NUC bootstrap — no cutover until Checklist F

## Rollback is simple

If anything goes wrong, Mac stays primary. Stop the NUC side, restart Mac daemon:
```bash
bash ~/.claude/scripts/restart-daemon.sh
```

## Syncthing note

Syncthing will also be used for a future Obsidian setup. Set it up once — it'll serve both purposes.
