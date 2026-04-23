# Claude Start Here — shared-core refactor

## Current status
- Work is in progress on branch `codex/claude-core-refactor` in 4 worktrees:
  - `/Users/jamescherry/.config/superpowers/worktrees/claude-shared/claude-core-refactor`
  - `/Users/jamescherry/.config/superpowers/worktrees/HEALTH/claude-core-refactor`
  - `/Users/jamescherry/.config/superpowers/worktrees/WORK/claude-core-refactor`
  - `/Users/jamescherry/.config/superpowers/worktrees/TODO/claude-core-refactor`
- Canonical tracking bead: `TODO-isgj`
- Tracking beads: `HEALTH-o2s1`, `HEALTH-74g`

## Implemented in this slice
- Created `claude-shared/pyproject.toml`
- Created `claude-shared/src/claude_core/`
- Added shared-core modules:
  - `config.py`
  - `device_roles.py`
  - `runtime_deploy.py`
  - `session_context.py`
  - `external_integrations.py`
  - `todo_integrity.py`
  - `diarium_ingest.py`
  - `health_metrics.py`
  - `dashboard_pipeline.py` placeholder
- Added deploy CLI:
  - `scripts/deploy-claude-core.py`
- Added handoff files including:
  - `CLAUDE-CODE-CONTINUE.md`
  - `SURFACE_MAP.shared.yaml`
- Added repo docs to HEALTH / WORK / TODO:
  - `SURFACE_MAP.yaml`
  - `ARCHITECTURE.md`
  - short refactor pointer in each `CLAUDE.md`
- Replaced duplicate helper copies with wrappers:
  - HEALTH: `import_conversation.py`, `format_non_code_context.py`, `parse_alter.py`, `akiflow_tracker.py`, `parse_diarium.py`
  - WORK: `import_conversation.py`, `akiflow_tracker.py`, `parse_diarium.py`
  - TODO: `import_conversation.py`, `format_non_code_context.py`, `parse_alter.py`, `akiflow_tracker.py`
- Completed the next near-duplicate migration slice:
  - moved `parse_autosleep.py` logic into `claude_core.health_metrics`
  - moved `parse_apple_health.py` logic into `claude_core.health_metrics`
  - converted HEALTH / TODO `parse_apple_health.py` to wrappers
  - converted HEALTH / WORK / TODO `parse_autosleep.py` to wrappers
- Consolidated the fallback orchestrator boundary:
  - moved HEALTH `sleep_fallback.py` logic into `claude_core.health_metrics`
  - converted HEALTH `.helpers/sleep_fallback.py` to a wrapper

## Fresh verification evidence
- Shared-core package checks:
  - `cd /Users/jamescherry/.config/superpowers/worktrees/claude-shared/claude-core-refactor && python3 -m py_compile src/claude_core/*.py scripts/deploy-claude-core.py`
  - result: success
- Shared-core tests:
  - `python3 -m pytest tests/test_claude_core_device_roles.py tests/test_claude_core_session_context.py tests/test_claude_core_runtime_deploy.py`
  - result: `4 passed in 0.03s`
- Shared-core health metrics tests:
  - `python3 -m pytest tests/test_claude_core_device_roles.py tests/test_claude_core_session_context.py tests/test_claude_core_runtime_deploy.py tests/test_claude_core_health_metrics.py`
  - result: `11 passed in 0.09s`
- HEALTH wrapper regression:
  - `cd /Users/jamescherry/.config/superpowers/worktrees/HEALTH/claude-core-refactor && python3 -m pytest tests/test_parse_diarium.py`
  - result: `5 passed in 0.09s`
- TODO regression:
  - `cd /Users/jamescherry/.config/superpowers/worktrees/TODO/claude-core-refactor && python3 -m pytest tests/test_beads_integrity_watchdog_shadow.py`
  - result: `2 passed in 0.06s`
- Wrapper syntax checks:
  - HEALTH / WORK / TODO changed wrapper files compiled successfully with `python3 -m py_compile`
- Wrapper import smoke:
  - imported HEALTH / TODO / WORK health parser wrappers plus HEALTH `sleep_fallback.py`
  - result: wrapper exports resolve through `claude_core.health_metrics` successfully
- Deploy dry run:
  - `python3 scripts/deploy-claude-core.py --dry-run`
  - result points target at `/Users/jamescherry/.claude/scripts/claude_core`

## Known baseline note
- HEALTH still had 2 pre-existing failures before this refactor on a broader selected suite:
  - `tests/test_pipeline_state.py::test_pipeline_state_is_ready_when_voice_markdown_exists`
  - `tests/test_diarium_cache_bridge.py::test_exporter_routes_through_shared_renderer_and_canonical_order`
- Do not attribute those two failures to this refactor unless they are re-run and change.

## Immediate next action
1. Update beads with the fallback migration results
2. Tackle the next boundary:
   - hook / session-start device-adapter split, or
   - deploy path hardening for `claude_core` into `~/.claude/scripts`
3. Consider archiving duplicate backups like `sleep_fallback 2.py` once the canonical surface is stable
4. Then continue broader migration + decomposition work
