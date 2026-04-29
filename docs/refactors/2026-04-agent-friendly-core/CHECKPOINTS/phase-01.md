# Phase 01 checkpoint

## Completed
- Set up isolated worktrees on `codex/claude-core-refactor`
- Created canonical beads and tracking beads
- Bootstrapped `claude-shared/src/claude_core`
- Added shared-core tests
- Added repo `SURFACE_MAP.yaml` and `ARCHITECTURE.md` files
- Added repo `CLAUDE.md` pointers to the handoff packet
- Replaced several duplicate helper copies with thin wrappers
- Added deploy CLI dry-run support in `scripts/deploy-claude-core.py`
- Added command-first Claude Code resume file

## Verified
- Shared-core compile: success
- Shared-core tests: `4 passed in 0.03s`
- HEALTH `test_parse_diarium.py`: `5 passed in 0.09s`
- TODO `test_beads_integrity_watchdog_shadow.py`: `2 passed in 0.06s`
- Wrapper syntax checks: success across changed wrapper files
- Deploy dry-run: success

## Still to do
- Update beads with this verification
- Choose next migration slice (`parse_autosleep.py` / `parse_apple_health.py` vs hook/device split)
- Decide when to do a real deploy into `~/.claude/scripts`
