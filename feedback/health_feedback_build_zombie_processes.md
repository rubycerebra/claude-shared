---
name: Dashboard build zombie processes
description: vite build hangs because cold builds take ~90s — always run synchronously with timeout:180000, never run_in_background
type: feedback
originSessionId: cb9455eb-7639-4cb7-b33e-d6597da67df1
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_build_zombie_processes.md
  migrated_on: 2026-05-17
---
The dashboard cold build takes **87–90 seconds** (not 4s). The "4s" seen in some runs is because an esbuild service from a prior build was still warm. This matters critically for how you run builds:

**Root cause of hangs:** Running deploy with `run_in_background: true` gives only a ~2-minute background timeout. A 90s build + overhead frequently hits that limit. The process gets killed (exit 143/SIGTERM), orphaning the esbuild service subprocess. The orphaned service holds an IPC socket. The next build tries to connect to it, hangs indefinitely.

**Why:** Background runner kills the parent bash process but not the esbuild service child. The prebuild `pkill` patterns were too narrow (`vite build`, `esbuild.*service`) — didn't catch all esbuild variants.

**How to apply — mandatory rules:**
1. **ALWAYS run `bash ~/.claude/scripts/deploy-dashboard.sh` with `timeout: 180000`** — never `run_in_background: true`
2. **Before any manual build, kill broadly:**
   ```bash
   pkill -9 -f "vite" 2>/dev/null; pkill -9 -f "esbuild" 2>/dev/null; pkill -9 -f "rollup" 2>/dev/null; true
   ```
3. The deploy script now uses `pkill -9` with broad patterns + `sleep 1` — this is the fix baked in permanently
4. After killing, wait 1 second before starting a new build

**Evidence of cold vs warm build time:**
- Warm (esbuild service alive): ~4s
- Cold (no running service): ~87s

**Fixed deploy script:** `~/.claude/scripts/deploy-dashboard.sh` — now uses `pkill -9 -f "vite/esbuild/rollup"` + `sleep 1` before every build.
