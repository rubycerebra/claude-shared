---
name: NUC/Mac drift prevention
description: Every Mac-side change must be evaluated for NUC server-side impact — prevent drift between the two environments
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_nuc_mac_drift_prevention.md
  migrated_on: 2026-05-17
---

When making changes on the Mac, always consider the ramifications on the NUC server side. The NUC is the always-on runtime (daemon, API server, health receiver). Syncthing keeps files in sync, but not everything syncs (venvs are .stignore'd, systemd services are NUC-only, config paths differ).

**Why:** The two environments can drift silently. A Mac-side change that looks fine locally may break the NUC runtime, or the NUC may keep running stale code/config because the change didn't propagate. Jim has already been burned by this with dashboard divergence.

**How to apply:**
- **Scripts/daemon code:** Changes sync via Syncthing, but the NUC daemon/API must be restarted to pick them up. Flag this to Jim: "NUC services will need a restart to pick this up."
- **Config files:** Check if the config exists on both sides and whether paths differ (Mac `~/` vs NUC `/mnt/c/SyncData/` or WSL2 `~/`).
- **Dependencies/venvs:** These are .stignore'd. If a new Python dependency is added, flag that NUC venv needs `pip install` separately.
- **Dashboard builds:** `npm run build` output (`dist/`) syncs, but verify the NUC is serving the updated dist, not a cached version.
- **Systemd services:** Only exist on NUC. Mac has no equivalent. If adding a new service or changing service config, that's NUC-only work.
- **New files/directories:** Check .stignore on both sides to ensure they'll actually sync.
- **Default stance:** After any change that affects runtime behavior, end with a note about NUC impact — even if it's "this syncs automatically, no NUC action needed."

**Post-change NUC checklist** (run mentally after every commit touching runtime paths):
1. □ Will Syncthing sync this? (check .stignore, run `check-nuc-sync.sh`)
2. □ NUC service restart needed? (requires admin — ask Jim to restart via RDP: `nssm restart claude-daemon` / `nssm restart claude-api`) — ⛔ NOT systemctl, NOT WSL
3. □ New pip dependency? → flag for NUC venv install (`C:\SyncData\claude-venv-win`)
4. □ Path differences? (Mac `~/` vs NUC `C:\SyncData\` — Windows paths, not WSL)
5. □ Config divergence risk? (secrets.json, config.yaml, daemon/config.json)

**Pre-commit hook:** `.git/hooks/pre-commit` in HEALTH repo scans staged files for NUC-impacting paths and prints a warning banner with this checklist. Non-blocking.

**Syncthing health check:** `~/.claude/scripts/check-nuc-sync.sh` queries local Syncthing API — shows NUC connection status + per-folder sync state. Run ad-hoc or integrate into `/audit`.

**vexp observation protocol:** After any NUC-impacting change, call `save_observation` with the impact details so future sessions automatically surface "last time you touched X, it needed a NUC restart." This ensures cross-session awareness without relying on chat memory.
