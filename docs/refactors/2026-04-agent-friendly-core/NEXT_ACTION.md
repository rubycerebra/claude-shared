# Next Action

## Completed in this session (phase-11)
- Decomposed `diarium_ingest.py` (2,170 LOC → 1,305 LOC) into 5 submodules:
  - `diarium/media.py` (109 LOC) — image/media extraction from DOCX/ZIP
  - `diarium/text.py` (370 LOC) — text extraction, HTML→text, cleanup, strip functions
  - `diarium/keywords.py` (191 LOC) — mental health keyword detection (7 domains)
  - `diarium/todos.py` (192 LOC) — todo extraction, categorisation, estimation
  - `diarium/location.py` (111 LOC) — already extracted in phase-07
- `diarium_ingest.py` retains: parse_diarium_entry, structured extractors, get_analysis_context, file discovery, main
- All 84 tests pass — no regressions

## Previously completed
- Phase-10: health_metrics.py decomposed (736 → 76 LOC re-exports + 4 submodules)
- Phase-09: dead code cleanup, format_memory migration, submodule tests, session-end hook dedup

## Do next (post phase-11)
1. **Centralise hardcoded paths into `claude_core.config`.** Many scripts and CLAUDE.md files reference `~/.claude/cache/`, `~/.claude/scripts/`, Google Drive paths, etc. as hardcoded strings. Move these into `config.py` so agents can look up paths programmatically instead of scanning for them.
2. **Version-control runtime scripts.** Move `~/.claude/scripts/api-server.py` and `~/.claude/scripts/run-sequenced-codex.py` source-of-truth into `claude-shared`.
3. **Triage 13 unrelated pending files** in `~/.claude/scripts` working tree.

## Bead updates needed
- `TODO-isgj` — note phase-11 complete; diarium_ingest fully decomposed.
