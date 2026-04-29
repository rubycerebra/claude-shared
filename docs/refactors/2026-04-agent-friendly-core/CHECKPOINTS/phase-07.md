# Phase 07 checkpoint — first registered hook conversion

## Completed
- Added `claude_core.hooks.main` CLI with `check-role <mac|nuc|unknown>` subcommand (exit 0 on match, 1 on mismatch, 2 on unknown keyword).
- Added 4 CLI tests (monkeypatching `current_device_role`). Full suite now **41 passed**.
- Converted `~/.claude/hooks/icloud-prefetch.sh` — registered SessionStart hook — to guard itself with `python3 -m claude_core.hooks check-role mac` so it no-ops on NUC. First registered hook to consume `claude_core`.
- Redeployed `claude_core` to `~/.claude/scripts/claude_core` via `deploy-claude-core.py`. Idempotent (only `hooks.py` changed).

## Verification
- `python3 -m pytest tests/` → 41 passed.
- `PYTHONPATH=~/.claude/scripts python3 -m claude_core.hooks check-role mac` → rc 0.
- `PYTHONPATH=~/.claude/scripts python3 -m claude_core.hooks check-role nuc` → rc 1.
- `bash ~/.claude/hooks/icloud-prefetch.sh` → rc 0, silent (gate passed on Mac, prefetch ran).

## Next recommended slice
1. Port the cooldown + lockfile orchestration from `sequenced-autopilot-session-start.sh` to a `python3 -m claude_core.hooks sequenced-gate` CLI; make the bash wrapper thin.
2. Convert more registered hooks that are implicitly Mac-only (`mac-data-bridge.py` calls, any osascript-using hooks) to use `check-role` guards.
3. Version-control `~/.claude/scripts/*.py` key files (api-server.py, run-sequenced-codex.py) so changes no longer live only on disk — they should ideally originate in `claude-shared` and deploy.
