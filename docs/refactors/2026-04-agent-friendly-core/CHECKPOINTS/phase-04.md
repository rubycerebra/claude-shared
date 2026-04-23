# Phase 04 checkpoint — hook / session-start device boundary

## Completed
- Inventoried `~/.claude/hooks` and settings.json SessionStart registrations in `SURFACE_MAP.hooks.yaml`.
  - Key finding: `hooks/session-start.sh` is **orphaned** — SessionStart registers 14 hooks directly in `settings.json`, not via the wrapper script. The wrapper is kept for audit compliance and is a safe proof-of-conversion target for a later slice.
- Added `claude_core.hooks` with orchestration primitives extracted from bash duplication:
  - `CooldownGate` — replaces the ad-hoc `last_epoch` bash math in `sequenced-autopilot-session-start.sh`.
  - `LockFile` context manager — replaces the bash lock pattern, with stale-PID recovery via `pid_is_alive`.
  - `dispatch_by_role(mac=..., nuc=..., fallback=...)` — replaces per-hook device branches in `lumen-reindex.sh` / `wsl-guard.sh`.
- Added `tests/test_claude_core_hooks.py` (10 tests) covering cooldown first-run/within-window/after-window/malformed-state; lockfile held/blocked/stale-recovery; dispatch mac/nuc/fallback.

## Verification
- `python3 -m pytest tests/ ` → **29 passed in 0.36s** (11 prior + 10 new hooks + 8 misc already-added).
- `python3 -m py_compile src/claude_core/*.py scripts/deploy-claude-core.py` → success.
- `python3 scripts/deploy-claude-core.py --dry-run` → plan still resolves target at `~/.claude/scripts/claude_core`.

## Deferred
- Actual conversion of `hooks/session-start.sh` → dispatcher into `claude_core.hooks`. Low-value on its own (orphaned file); worth combining with the first registered-hook conversion so the proof has real blast-radius discipline.
- Integrating `CooldownGate` / `LockFile` into `sequenced-autopilot-session-start.sh`. Non-trivial bash→python refactor; separate slice.

## Next recommended slice
1. Pick one registered SessionStart hook with device branching (recommend `lumen-reindex.sh` — smallest surface) and route it through `claude_core.hooks.dispatch_by_role`.
2. Then harden `scripts/deploy-claude-core.py` so `claude_core` lands in `~/.claude/scripts` via an idempotent copy with manifest verification.
