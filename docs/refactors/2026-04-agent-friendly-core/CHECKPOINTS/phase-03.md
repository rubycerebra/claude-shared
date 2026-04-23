# Phase 03 checkpoint — sleep fallback consolidation

## Completed
- Moved the HEALTH `sleep_fallback.py` orchestration logic into `claude_core.health_metrics`.
- Converted `HEALTH/.helpers/sleep_fallback.py` into a thin wrapper around `claude_core.health_metrics.sleep_fallback_main`.
- Kept fallback-chain exports (`get_sleep_data`, `print_human`) available through the wrapper boundary.

## Verification
- `python3 -m pytest tests/test_claude_core_device_roles.py tests/test_claude_core_session_context.py tests/test_claude_core_runtime_deploy.py tests/test_claude_core_health_metrics.py`
  - result: `11 passed in 0.09s`
- Wrapper import smoke:
  - HEALTH: `parse_autosleep.py`, `parse_apple_health.py`, `sleep_fallback.py`
  - TODO: `parse_autosleep.py`, `parse_apple_health.py`
  - WORK: `parse_autosleep.py`
  - result: all imported successfully through `claude_core.health_metrics`

## Next recommended slice
1. Split hook / session-start surfaces by device role.
2. Then harden deploy + compatibility shims for `claude_core` into `~/.claude/scripts`.
