# Test Matrix

## Baseline before refactor changes
- HEALTH: broader selected pytest baseline had 2 pre-existing failures
- WORK: no automated baseline tests configured
- TODO: baseline selected test passed
- claude-shared: baseline selected tests passed

## Fresh verification for current slice
- Shared-core compile:
  - `python3 -m py_compile src/claude_core/*.py scripts/deploy-claude-core.py`
  - result: success
- Shared-core tests:
  - `python3 -m pytest tests/test_claude_core_device_roles.py tests/test_claude_core_session_context.py tests/test_claude_core_runtime_deploy.py tests/test_claude_core_health_metrics.py`
  - result: `11 passed in 0.09s`
- Shared-core tests (phase-04, includes hooks module):
  - `python3 -m pytest tests/`
  - result: `29 passed in 0.36s`
- HEALTH wrapper regression:
  - `python3 -m pytest tests/test_parse_diarium.py`
  - result: `5 passed in 0.09s`
- TODO regression:
  - `python3 -m pytest tests/test_beads_integrity_watchdog_shadow.py`
  - result: `2 passed in 0.06s`
- Wrapper import smoke:
  - HEALTH: `parse_autosleep.py`, `parse_apple_health.py`, `sleep_fallback.py`
  - TODO: `parse_autosleep.py`, `parse_apple_health.py`
  - WORK: `parse_autosleep.py`
  - result: imports resolved via `claude_core.health_metrics`

## Known pre-existing HEALTH failures
- `tests/test_pipeline_state.py::test_pipeline_state_is_ready_when_voice_markdown_exists`
- `tests/test_diarium_cache_bridge.py::test_exporter_routes_through_shared_renderer_and_canonical_order`
