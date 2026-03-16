# NUC WSL2 Transfer Checklist (2026-03-16)

## Purpose

Make `TODO-3pyn.1` executable this week by turning the WSL2 migration path into a concrete checklist.

**Primary source-of-truth beads**
- `TODO-3pyn` — NUC migration focus day (epic)
- `TODO-3pyn.1` — portability hardening package
- `TODO-3pyn.2` — cutover smoke test + rollback rehearsal

**Context plan**
- `claude-shared/reports/2026-02-system-sweep/NUC-MIGRATION-PLAN-2026-02-17.md`

**Doctor command**
- `python3 ~/.claude/scripts/wsl2-doctor.py`
- deeper runtime validation: `python3 ~/.claude/scripts/wsl2-doctor.py --require-running --with-smoke`

**Windows host prep**
- `claude-shared/reports/2026-02-system-sweep/windows/README.md`
- `claude-shared/reports/2026-02-system-sweep/windows/register-claude-wsl-logon-task.ps1`
- `claude-shared/reports/2026-02-system-sweep/windows/run-claude-wsl-runtime-now.ps1`
- `claude-shared/reports/2026-02-system-sweep/windows/setup-claude-tailscale-serve.ps1`

## Current readiness snapshot (captured 2026-03-16)

These checks were run before writing this checklist:

- `python3 ~/.claude/scripts/wsl2-doctor.py` → **ready_with_warnings** (expected Mac preflight: not Linux/WSL)
- `bash ~/.claude/scripts/health-check.sh` → **SYSTEM HEALTHY**
- `python3 ~/.claude/scripts/system-ops-audit.py` → **daemon OK, API OK**
- `python3 ~/.claude/scripts/daemon-smoke-test.py` → **pass**
- `python3 ~/.claude/scripts/dashboard-smoke-tests.py` → **all smoke tests passed**
- `bash ~/.claude/scripts/check-apple-notes-sync.sh --json` → **status ok, mode applescript**

Additional live state from `system-ops-audit.py` on 2026-03-16:

- API health URL responding: `http://127.0.0.1:8765/v1/health`
- Cloudflare tunnel present
- Tailscale serve proxy present for `http://127.0.0.1:8765`

## Important assumptions for this migration

1. **Target runtime:** Windows NUC host + **WSL2** Linux distro.
2. **Primary action surface:** **Todoist**.
3. **Apple Notes role:** **secondary Mac-only output bridge** for summaries/embeds.
4. **Cutover model:** one active automation writer at a time for cache/generated artefacts.

## Host responsibility split

| Host | Responsibilities | Must stay local? |
|---|---|---|
| **NUC / WSL2** | daemon, cache generation, dashboard generation, API server, Todoist automation, remote access target | Yes |
| **Mac** | Apple Notes sync/embed, `osascript`-based helpers, optional manual QA | Yes |
| **Both** | synced project files for reading/editing | Shared |

## Single-writer rules for cutover

After cutover, do **not** let both Mac and NUC automation write these at the same time:

| Artefact | Writer after cutover |
|---|---|
| `~/.claude/cache/session-data.json` | **NUC / WSL2 only** |
| `~/.claude/cache/session-brief-*.md` | **NUC / WSL2 only** |
| `~/Documents/Claude Projects/claude-shared/dashboard.html` | **NUC / WSL2 only** |
| API server on port `8765` | **NUC / WSL2 only** |
| Apple Notes note body / embeds | **Mac only** |
| `~/.claude/secrets.json` and local token/config files | **Per-host local, not synced** |

## Checklist A — preflight results (2026-03-16)

Checks run at session start on 2026-03-16. All six checks completed without hanging.

| Check | Exit | Result | Notes |
|---|---|---|---|
| `wsl2-doctor.py` | 0 | ⚠ READY WITH WARNINGS | 22 pass, 2 warn, 0 fail. Warnings: non-Linux host (expected preflight), cache stale 22m |
| `health-check.sh` | 0 | ⚠ WARNINGS: 1 | All core checks pass; 1 warning: cache stale 22m |
| `system-ops-audit.py` | 0 | ✅ PASS | daemon OK, API OK — full report at `system-audit/2026-03-16.md` |
| `daemon-smoke-test.py` | 0 | ✅ PASS | No output issues; clean exit |
| `dashboard-smoke-tests.py` | 0 | ✅ PASS | All 11 smoke tests passed (note: Codex API paused 60m — missing `api.responses.write` scope, non-blocking) |
| `check-apple-notes-sync.sh --json` | 0 | ✅ PASS | `status:ok`, `mode:applescript`, fallback scripts and syntax checks all good |

**Remote access endpoints** (from `system-ops-audit.py`, 2026-03-16 20:24):

- Cloudflare tunnel: `https://recruitment-indoor-builder-aged.trycloudflare.com`
- Tailscale serve: `https://jamess-macbook-pro.tail649c3c.ts.net` (tailnet only) → proxies `http://127.0.0.1:8765`
- Local API: `http://127.0.0.1:8765/v1/health`

**Items still needing manual confirmation:**

- NUC Windows admin access — cannot be verified from Mac; confirm when physically/remotely on the NUC
- Sync transport decision (Syncthing preferred vs git fallback) — a decision, not a check
- Secrets backup — confirm `~/.claude/secrets.json` and `~/.claude/config/api-token.txt` are backed up before transfer

---

## Key decisions recorded (2026-03-16)

- Remote access method: Jump Desktop ✓
- Sync transport: Syncthing (shared with planned Obsidian setup)
- Claude Code: already installed on NUC — validation can use remote CLI directly

---

## Checklist A — preflight on the current Mac setup

- [x] Confirm NUC Windows admin access is available. (Jump Desktop — confirmed working)
- [ ] Decide WSL distro (`Ubuntu` is the simplest default).
- [x] Decide sync transport: (Syncthing chosen — also planned for future Obsidian sync setup)
  - [x] **Preferred:** Syncthing (Syncthing chosen — also planned for future Obsidian sync setup)
  - [ ] Fallback: git/manual pull-push workflow

  Note: Claude Code is already installed on the NUC, which simplifies initial validation — remote CLI path is live without extra setup.
- [x] Record current remote access endpoints from the latest system audit.
- [x] Back up local secrets/config before copying anything:
  - [x] `~/.claude/secrets.json`
  - [x] `~/.claude/config/api-token.txt`
  - [ ] any provider-specific env/token notes

  > Backed up to `~/.claude/backups/nuc-migration-2026-03-16/` on 2026-03-16 (includes `secrets.json`, `api-token.txt`, `daemon.env`). Transfer manually — not via git/Syncthing.
- [x] Run and save baseline checks on Mac:
  - [x] `python3 ~/.claude/scripts/wsl2-doctor.py`
  - [x] `bash ~/.claude/scripts/health-check.sh`
  - [x] `python3 ~/.claude/scripts/system-ops-audit.py`
  - [x] `python3 ~/.claude/scripts/daemon-smoke-test.py`
  - [x] `python3 ~/.claude/scripts/dashboard-smoke-tests.py`
  - [x] `bash ~/.claude/scripts/check-apple-notes-sync.sh --json`
- [ ] Optional stronger baseline:
  - [ ] `bash ~/.claude/scripts/tomorrow-readiness-check.sh`

## Checklist B — bootstrap WSL2 on the NUC

- [ ] Install/enable WSL2 on Windows.
- [ ] Create the Linux distro.
- [ ] Make sure the synced files will be reachable from both:
  - [ ] Windows host (for PowerShell/VNC-side setup)
  - [ ] WSL home (for runtime scripts)
- [ ] Install base packages inside WSL2:
  - [ ] `python3`
  - [ ] `python3-venv`
  - [ ] `git`
  - [ ] `curl`
  - [ ] `lsof`
- [ ] Sync/clone the required trees into WSL2:
  - [ ] `~/.claude/daemon/`
  - [ ] `~/.claude/scripts/`
  - [ ] `~/Documents/Claude Projects/`
- [ ] Create the daemon venv in WSL2 and install requirements.
- [ ] Copy **only the needed secrets** onto the NUC/WSL2 side; do not rely on git for secrets.
- [ ] Ensure these local files exist on WSL2 if needed:
  - [ ] `~/.claude/secrets.json`
  - [ ] `~/.claude/config/api-token.txt`
  - [ ] provider keys/env vars

## Checklist C — define startup/service parity

- [ ] Decide startup mode:
  - [ ] **Preferred for first cutover given existing VNC workflow:** Windows logon task → `wsl.exe -d <distro> ...`
  - [ ] Later hardening option: `systemd` enabled inside WSL2 — see **Checklist C2** below
- [ ] On the Windows host, review:
  - [ ] `claude-shared/reports/2026-02-system-sweep/windows/README.md`
  - [ ] `register-claude-wsl-logon-task.ps1`
  - [ ] `run-claude-wsl-runtime-now.ps1`
- [ ] Create daemon service/start command.
- [ ] Create API service/start command.
- [ ] Keep Tailscale on the Windows host as the primary remote path.
- [ ] Treat VNC as the admin/setup path for the Windows host.
- [ ] Keep Cloudflare as manual backup only, not the primary path.
- [ ] Write down the exact start/stop commands for:
  - [ ] daemon
  - [ ] API
  - [ ] tunnel/proxy
  - [ ] restart

## Checklist C2 — systemd hardening path (fully headless follow-up)

> **When to use:** After the first stable cutover via logon task, if you want services to start without any Windows login (true pre-login / fully headless boot path).
>
> **Prerequisite:** WSL2 distro must have systemd enabled. Add to `/etc/wsl.conf` inside WSL2:
> ```ini
> [boot]
> systemd=true
> ```
> Then restart WSL2: `wsl --shutdown` from a Windows terminal, then relaunch the distro.

### Unit files (pre-built, committed to scripts/)

| File | Purpose |
|------|---------|
| `~/.claude/scripts/systemd/claude-daemon.service` | Runs `data_collector.py` via daemon venv; `Restart=on-failure` |
| `~/.claude/scripts/systemd/claude-api.service` | Runs `api-server.py` via daemon venv; depends on daemon service |
| `~/.claude/scripts/systemd/claude.target` | Groups both services; target used by `WantedBy` |

### Setup (one command inside WSL2)

```bash
bash ~/.claude/scripts/install-systemd-services.sh
```

This script:
1. Checks you are on Linux with a live systemd user session
2. Copies the three unit files to `~/.config/systemd/user/`
3. Runs `systemctl --user daemon-reload`
4. Enables `claude.target`, `claude-daemon.service`, `claude-api.service`
5. Prints status and quick-reference commands

### Day-to-day commands (inside WSL2)

```bash
# Start everything
systemctl --user start claude.target

# Stop everything
systemctl --user stop claude.target

# Check status
systemctl --user status claude-daemon claude-api

# Tail logs via journald
journalctl --user -u claude-daemon -u claude-api -f

# Or use the existing bash wrappers (still work alongside systemd)
bash ~/.claude/scripts/wsl2-start-runtime.sh
bash ~/.claude/scripts/wsl2-stop-runtime.sh
```

### Checklist steps

- [ ] Add `systemd=true` under `[boot]` in `/etc/wsl.conf` inside WSL2.
- [ ] Restart the distro: `wsl --shutdown` from Windows, then reopen WSL2.
- [ ] Confirm systemd is live: `systemctl --user status` should return without error.
- [ ] Run the installer: `bash ~/.claude/scripts/install-systemd-services.sh`
- [ ] Start services: `systemctl --user start claude.target`
- [ ] Verify daemon: `systemctl --user status claude-daemon`
- [ ] Verify API: `curl http://127.0.0.1:8765/v1/health`
- [ ] Enable linger so services survive without an active login session:
  - [ ] `loginctl enable-linger "$USER"` (run as root or with sudo if needed)
- [ ] Confirm services auto-start after `wsl --shutdown` + relaunch (no Windows login required).

## Checklist D — bring-up validation inside WSL2

- [ ] Start daemon in WSL2.
- [ ] Start API server in WSL2.
- [ ] On the Windows host, configure Tailscale serve:
  - [ ] `setup-claude-tailscale-serve.ps1`
- [ ] Verify API:
  - [ ] `curl http://127.0.0.1:8765/health`
  - [ ] `curl http://127.0.0.1:8765/v1/health`
- [ ] Run the WSL-safe doctor:
  - [ ] `python3 ~/.claude/scripts/wsl2-doctor.py --require-running`
- [ ] Force a dashboard/cache refresh:
  - [ ] `~/Documents/Claude\\ Projects/claude-shared/trigger-dashboard.sh --no-open`
- [ ] Run validation scripts from WSL2:
  - [ ] `python3 ~/.claude/scripts/wsl2-doctor.py --require-running --with-smoke`
  - [ ] `python3 ~/.claude/scripts/system-ops-audit.py`
  - [ ] `python3 ~/.claude/scripts/daemon-smoke-test.py`
  - [ ] `python3 ~/.claude/scripts/dashboard-smoke-tests.py`
- [ ] Verify the API returns real data:
  - [ ] `curl -H "Authorization: Bearer $(cat ~/.claude/config/api-token.txt)" http://127.0.0.1:8765/v1/today`
- [ ] Verify Todoist-facing flow still works:
  - [ ] dashboard loads Todoist data
  - [ ] API endpoints that read/update Todoist succeed

## Checklist E — Mac Apple Notes bridge

- [ ] Keep Apple Notes scripts on the Mac:
  - [ ] `~/.claude/scripts/sync-journal-to-apple-notes.sh`
  - [ ] `~/.claude/scripts/embed-dashboard-in-notes.py`
  - [ ] `~/.claude/scripts/check-apple-notes-sync.sh`
- [ ] Confirm the Mac can see the synced outputs from the NUC-generated files.
- [ ] Verify Apple Notes health after the NUC-generated data lands:
  - [ ] `bash ~/.claude/scripts/check-apple-notes-sync.sh --json`
- [ ] Treat Apple Notes failure as **non-blocking for core runtime** during early cutover.

## Checklist F — cutover day

- [ ] Stop Mac daemon before enabling the NUC as primary.
- [ ] Stop Mac API server before enabling the NUC as primary.
- [ ] If using the logon-task path, VNC into the NUC and sign into Windows first.
- [ ] Start NUC/WSL2 daemon + API.
- [ ] Run refresh from the NUC side.
- [ ] Verify:
  - [ ] fresh `session-data.json`
  - [ ] fresh `dashboard.html`
  - [ ] healthy API
  - [ ] Todoist-first task flow
  - [ ] remote access (Cloudflare/Tailscale)
- [ ] Run Apple Notes sync from the Mac only after synced outputs are confirmed good.
- [ ] Leave the Mac in bridge-only mode for at least the first shadow/cutover period.

## Checklist G — rollback

- [ ] Stop NUC/WSL2 daemon.
- [ ] Stop NUC/WSL2 API server.
- [ ] Disable NUC startup wrapper/service if needed.
- [ ] Restart daemon on the Mac:
  - [ ] `bash ~/.claude/scripts/restart-daemon.sh`
- [ ] Restart API on the Mac if required.
- [ ] Re-run Mac baseline checks:
  - [ ] `bash ~/.claude/scripts/health-check.sh`
  - [ ] `python3 ~/.claude/scripts/system-ops-audit.py`
  - [ ] `python3 ~/.claude/scripts/dashboard-smoke-tests.py`
- [ ] Resume Apple Notes sync from the Mac as normal.

## Known gaps / watchouts still to track

- **The WSL-safe doctor now exists, but it does not replace the Mac health check.**  
  Use `python3 ~/.claude/scripts/wsl2-doctor.py` for portability/runtime checks, and keep `~/.claude/scripts/health-check.sh` as the Mac-specific health check.

- **The first prepared Windows startup path is logon-based, not true pre-login boot automation.**  
  That is intentional because it matches the current VNC-admin workflow and is safer for the first move. If you later want a fully headless no-login boot path, that can be added after the first stable cutover.

- **Apple Notes bridge is intentionally Mac-only.**  
  `check-apple-notes-sync.sh`, `sync-journal-to-apple-notes.sh`, and `embed-dashboard-in-notes.py` should stay on the Mac side.

- **`daemon-smoke-test.py` still uses macOS notifications.**  
  Import validation is still useful on WSL2, but notification delivery would need a Windows/Linux-friendly replacement if you want alerts there.

- **If Codex/OpenAI provider is used on the NUC, verify token scopes first.**  
  The latest dashboard smoke run reported a backoff note for missing `api.responses.write` scope. That is not blocking the migration plan by itself, but it should be fixed before relying on that provider on the NUC.

## Ready-to-start-this-week definition

You are ready to begin the shift this week when all of the following are true:

- [ ] Mac baseline checks are green and recorded.
- [ ] WSL2 distro exists and has the synced code + venv.
- [ ] Secrets/config are present locally on the NUC/WSL2 side.
- [ ] Daemon + API can start in WSL2.
- [ ] `python3 ~/.claude/scripts/wsl2-doctor.py --require-running` is green enough for cutover.
- [ ] Dashboard/API/Todoist validation passes in WSL2.
- [ ] Apple Notes bridge is explicitly treated as secondary and left on the Mac.
- [ ] You have written down the rollback commands before attempting the cutover.
