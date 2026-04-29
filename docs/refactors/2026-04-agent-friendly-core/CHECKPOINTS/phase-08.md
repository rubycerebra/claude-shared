# Phase 08 checkpoint — sequenced-gate CLI + first decomposition slices

## Completed
- Added `sequenced_gate_status()` + `sequenced-gate` CLI subcommand to `claude_core.hooks`. Centralises the cooldown + live-PID-lock check the bash hook used to do inline. 7 new tests cover passes, cooldown block, lock block, dead-lock recovery, and CLI exit codes.
- Converted `~/.claude/hooks/sequenced-autopilot-session-start.sh` to call `python3 -m claude_core.hooks sequenced-gate`. Bash file shrank by ~20 lines; gate logic is now testable and reusable.
- **First decomposition slice — diarium**: extracted location helpers (`_normalise_location_key`, `load_known_locations`, `normalise_known_location`, `extract_location_from_diarium`) from `diarium_ingest.py` (100 KB) into `claude_core/diarium/location.py`. Re-exported from the parent module for backward compat.
- **First decomposition slice — health**: extracted CSV discovery + parsing primitives (12 functions) from `health_metrics.py` (29 KB) into `claude_core/health/discovery.py`. Same re-export pattern.
- Fixed 2 pre-existing settings.json bugs (Stop hook schema, unquoted UserPromptSubmit paths) — not refactor-related but discovered during this work.

## Verification
- `python3 -m pytest tests/` → **48 passed in 0.56s** (41 prior + 7 new sequenced-gate).
- HEALTH wrapper regression: `python3 -m pytest tests/test_parse_diarium.py` → 5 passed.
- Live `parse_duration('07:32:15')` via re-exported function → 7.5375 (correct).
- Live sequenced-gate via bash hook: backgrounded launch worked; immediate re-run blocked correctly with `[SEQUENCED] cooldown active (17s < 1200s)`.
- `deploy-claude-core.py` redeployed cleanly with new `claude_core/diarium/` and `claude_core/health/` subpackages — manifest now tracks 14 files (was 12), `--verify` passes.
- NUC verification: `findstr` confirms `walk_ancestor_pids` + `check-role` already present in NUC's deployed `claude_core/hooks.py` (Syncthing). NUC `api-server.py` no longer contains `datetime.utcnow`.

## Remaining inside this phase family
- Decompose more of `diarium_ingest.py` (images, text-extract, cleanup, parser, analysis, discovery groups still inline).
- Decompose more of `health_metrics.py` (autosleep, apple_health, fallback groups still inline).
- Version-control `~/.claude/scripts/api-server.py` and `run-sequenced-codex.py` so source-of-truth lives in `claude-shared` instead of only on disk.
- Convert remaining device-aware hooks if any surface (most registered SessionStart hooks are device-agnostic).

## Net session deliverables
- 8 phases of the agent-friendly-core refactor committed across claude-shared, HEALTH, WORK, TODO worktrees.
- `claude_core` deployed and verified on Mac AND NUC.
- Two registered SessionStart hooks now consume `claude_core` (icloud-prefetch + sequenced-autopilot).
- Two real backend bugs fixed: api-server `utcnow` deprecation flood, sequencer self-conflict abort.
- Two real settings.json bugs fixed: Stop hook schema, unquoted-path UserPromptSubmit hooks.
- Tests grew from 11 → 48 (4.4x) without touching production behaviour.
