# Next Action

## Completed in this session (phase-12)
- Centralised hardcoded paths into `claude_core.config.SharedPaths` properties:
  - Cache: `session_data`, `health_live`, `diarium_images_dir`, `diarium_md_dir`, `akiflow_tracker_dir`
  - Config: `config_dir`, `daemon_config`, `transcription_fixes`, `secrets`
  - Scripts: `scripts_dir`, `shared_lib_dir`
  - External: `gdrive_roots`, `diarium_export_roots`, `apple_health_roots`, `alter_transcripts_dir`
  - Gates: `commit_gate_file`, `push_gate_file`, `daemon_config_candidates`
- Wired up 8 modules to use centralised paths instead of hardcoded `Path.home()` references:
  - `diarium_ingest.py`, `diarium/media.py`, `diarium/text.py`, `diarium/keywords.py`
  - `health/discovery.py`, `todo_integrity.py`, `external_integrations.py`
- All 84 tests pass — no regressions

## Previously completed
- Phase-11: diarium_ingest.py decomposed (2,170 → 1,305 LOC + 5 submodules)
- Phase-10: health_metrics.py decomposed (736 → 76 LOC re-exports + 4 submodules)
- Phase-09: dead code cleanup, format_memory migration, submodule tests, session-end hook dedup

## Do next (post phase-12)
1. **Version-control runtime scripts.** Move `~/.claude/scripts/api-server.py` and `~/.claude/scripts/run-sequenced-codex.py` source-of-truth into `claude-shared`.
2. **Triage 13 unrelated pending files** in `~/.claude/scripts` working tree.

## Bead updates needed
- `TODO-isgj` — note phase-12 complete; path centralisation done.
