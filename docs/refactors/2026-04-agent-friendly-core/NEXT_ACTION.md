# Next Action

## Completed in this session (phase-09)
- Deleted dead code: `dashboard_pipeline.py` stub, `sleep_fallback 2.py` duplicate
- Migrated `format_memory.py` (HEALTH + TODO) → `claude_core.session_context.format_memory_main`
- Added 36 tests for `diarium/location.py` and `health/discovery.py` (suite now 84 passed)
- Extracted session-end commit/push logic into `claude_core.hooks.session_end_commit_push` + `check_gate`
- Converted all 3 session-end.sh hooks to thin callers (HEALTH 75→12 lines, TODO 38→12, WORK 38→11)

## Do next (post phase-09)
1. **Continue large_file_decomposition.** Patterns proven for `diarium_ingest.py` and `health_metrics.py` — extract remaining groups one at a time with regression check after each:
   - diarium: images, text-extract, cleanup, parser, analysis, discovery
   - health_metrics: autosleep parser, apple_health parser, fallback orchestrator
2. **Version-control runtime scripts.** Move `~/.claude/scripts/api-server.py` and `~/.claude/scripts/run-sequenced-codex.py` source-of-truth into `claude-shared`, deploy via `deploy-claude-core.py` extension. Currently changes live only on disk.
3. **Triage 13 unrelated pending files** in `~/.claude/scripts` working tree — left there from prior sessions, awaiting Jim's decision.

## Bead updates needed before next slice
- `TODO-isgj` — note phase-09 complete; remaining work is decomposition continuation + runtime-script version-control.
