# Next Action

## Do next (post phase-08)
1. **Continue large_file_decomposition.** Patterns proven for `diarium_ingest.py` and `health_metrics.py` — extract remaining groups one at a time with regression check after each:
   - diarium: images, text-extract, cleanup, parser, analysis, discovery
   - health_metrics: autosleep parser, apple_health parser, fallback orchestrator
2. **Version-control runtime scripts.** Move `~/.claude/scripts/api-server.py` and `~/.claude/scripts/run-sequenced-codex.py` source-of-truth into `claude-shared`, deploy via `deploy-claude-core.py` extension. Currently changes live only on disk.
3. **Triage 13 unrelated pending files** in `~/.claude/scripts` working tree — left there from prior sessions, awaiting Jim's decision.

## Bead updates needed before next slice
- `TODO-isgj` — note phases 05–08 complete; remaining work is decomposition continuation + runtime-script version-control.
