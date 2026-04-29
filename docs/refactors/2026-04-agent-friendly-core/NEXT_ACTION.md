# Next Action

## Completed in this session (phase-13)
- Version-controlled `run-sequenced-codex.py` (717 LOC) into `claude-shared/scripts/`
- Added `deploy_runtime_scripts()` to `runtime_deploy.py` and `--scripts` CLI flag
- `api-server.py` (12,850 LOC) deferred — depends on full `shared/` library (26 files, 6,401 LOC)
- Triaged pending files — clean, no orphans

## Previously completed
- Phase-12: Path centralisation (18 SharedPaths properties, 8 modules wired)
- Phase-11: diarium_ingest.py decomposed (2,170 → 1,305 LOC + 5 submodules)
- Phase-10: health_metrics.py decomposed (736 → 76 LOC re-exports + 4 submodules)
- Phase-09: dead code cleanup, format_memory migration, submodule tests, session-end hook dedup

## Remaining work (parked — diminishing returns)
1. **api-server.py version control** — requires migrating `shared/` library (6,401 LOC, 26 modules) first. Large scope, low urgency — the server works.
2. **shared/ library migration** — `ai_service.py` (2,007 LOC), `todoist_helper.py` (330 LOC), etc. Candidate for `claude_core.shared` but substantial effort.
3. **Further hook conversions** — 60 remaining hooks work fine as shell. Convert opportunistically when modifying them.

## Refactor summary (phases 01-13)
- **claude_core package**: 12 modules + 9 submodules, 4,700+ LOC of canonical logic
- **Wrappers**: 21 project wrappers across HEALTH/WORK/TODO replacing full-copy duplicates
- **Tests**: 84 passing (up from 0 at start)
- **Hooks converted**: 5 (2 session-start, 3 session-end)
- **Path centralisation**: 18 properties in SharedPaths, 8 modules wired
- **Runtime scripts versioned**: run-sequenced-codex.py
- **Deploy tool**: handles both claude_core package and standalone scripts

## Bead updates needed
- `TODO-isgj` — note phase-13 complete; refactor roadmap substantially done.
