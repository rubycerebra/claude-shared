# Next Action

## Completed in this session (phase-10)
- Decomposed `health_metrics.py` (736 LOC) into 4 submodules:
  - `health/autosleep.py` (149 LOC) — AutoSleep CSV parser + CLI
  - `health/apple.py` (253 LOC) — Apple Health CSV parser + CLI
  - `health/fallback.py` (332 LOC) — Sleep fallback orchestrator (AutoSleep → Apple Health → HealthFit)
  - `health/discovery.py` (112 LOC) — already extracted in phase-07
- `health_metrics.py` is now 76 lines of re-exports for backward compatibility
- All 84 tests pass — no regressions

## Previously completed (phase-09)
- Dead code cleanup, format_memory migration, submodule tests, session-end hook dedup

## Do next (post phase-10)
1. **Decompose `diarium_ingest.py`** (2,170 LOC). Clusters identified:
   - images/media extraction (~5 functions)
   - todo extraction (~5 functions)
   - text cleaning/parsing (~10 functions)
   - mental health keyword analysis (~5 functions)
   - core entry parsing (remaining ~15 functions — stays in main module)
2. **Version-control runtime scripts.** Move `~/.claude/scripts/api-server.py` and `~/.claude/scripts/run-sequenced-codex.py` source-of-truth into `claude-shared`.
3. **Triage 13 unrelated pending files** in `~/.claude/scripts` working tree.

## Bead updates needed
- `TODO-isgj` — note phase-10 complete; health_metrics fully decomposed.
