# Daemon + Dashboard Refactor Plan — 2026-02-17

## Scope Audited
- `~/.claude/daemon/data_collector.py` (7,325 lines)
- `~/.claude/scripts/write-ai-insights.py` (1,055 lines)
- `~/Documents/Claude Projects/claude-shared/generate-dashboard.py` (2,787 lines)

## 1) End-to-End Data Flow (Diarium -> Cache -> Insights -> Dashboard)

### A. Collection and cache assembly (daemon)
- Entry point: `DataCollector.update_cache()` in `~/.claude/daemon/data_collector.py:2909`
- Diarium parse/clean: `fetch_diarium()` -> `_ai_clean_diarium_data()` in `~/.claude/daemon/data_collector.py:6290`
- Base cache object assembled in memory, then enrichment pipeline runs.

### B. Insight generation and cache writes
- Morning + updates insights:
  - `_generate_daily_insights()` in `~/.claude/daemon/data_collector.py:4628`
  - `_generate_updates_insights()` in `~/.claude/daemon/data_collector.py:4919`
  - Both call `write-ai-insights.py` subprocess.
- Daily guidance / tomorrow guidance:
  - `_generate_daily_guidance()` in `~/.claude/daemon/data_collector.py:5159`
  - `_generate_tomorrow_guidance()` in `~/.claude/daemon/data_collector.py:5830`
  - Both read and write `session-data.json` directly.

### C. Mirror reload and final cache write
- Daemon reloads `ai_insights` from disk into in-memory `data` in `~/.claude/daemon/data_collector.py:3014`
- Daemon writes final cache snapshot in `~/.claude/daemon/data_collector.py:3174`

### D. Dashboard render path
- Dashboard entry: `main()` in `~/Documents/Claude Projects/claude-shared/generate-dashboard.py:2552`
- Date-scoped insight read: `get_ai_day()` calls throughout render logic.
- Render output: `dashboard.html`.

## 2) Handoff Points and What Can Break

1. Diarium parse -> cleaned fields
- Risk: parser fallback shape mismatch can silently reduce field richness.
- Handoff: `fetch_diarium()` to in-memory `data["diarium"]`.

2. Daemon -> subprocess insight writer
- Risk: cache clobber race across multiple writers (daemon write, guidance write, insight subprocess write).
- Handoff: subprocess writes in `write-ai-insights.py`.

3. Disk reload -> in-memory merge
- Risk: if reload/normalisation is skipped or partial, daemon final write can overwrite fresh AI fields.
- Handoff: `~/.claude/daemon/data_collector.py:3014` and `~/.claude/daemon/data_collector.py:3174`.

4. ai_insights mirror -> dashboard date view
- Risk: stale top-level mirror fields can bleed historical text if not forced to today scope.
- Handoff: `generate-dashboard.py` main load path.

## 3) Root Cause + Fix for Stale Insights Bleed-Through

### Root cause
- `ai_insights` has two shapes in play:
  - canonical `by_date[YYYY-MM-DD]`
  - legacy/top-level mirror (`latest_summary`, `entries`, etc.)
- If top-level mirror drifts from `by_date`, stale yesterday text can leak into consumers that read top-level keys.

### Fix implemented (this session)
1. Added normaliser:
- `normalize_ai_cache_for_date()` in `~/.claude/scripts/shared/cache_dates.py:130`

2. Forced dashboard to use today-normalised ai cache before rendering:
- import and usage in `~/Documents/Claude Projects/claude-shared/generate-dashboard.py:27`
- normalisation call in `~/Documents/Claude Projects/claude-shared/generate-dashboard.py:2567`

### Validation performed
- Injected synthetic yesterday marker into both:
  - `ai_insights.by_date[yesterday]`
  - stale top-level mirror fields
- Regenerated dashboard.
- Result: marker absent in `dashboard.html` (`marker_found False`).

## 4) Dead Code / Low-Value Paths

1. Unused method
- `~/.claude/daemon/data_collector.py:4208` (`_auto_embed_dashboard_in_notes`) has no call sites.
- Current flow uses `sync_journal_to_apple_notes()` instead.

2. Unused computed variables in guidance path
- `hints`, `cal_events`, and `cross_day` are built but not used in prompt or output:
  - `~/.claude/daemon/data_collector.py:5274`
  - `~/.claude/daemon/data_collector.py:5359`
  - `~/.claude/daemon/data_collector.py:5363`

## 5) Duplicated Logic to Consolidate

1. ai_insights normalisation duplicated across modules:
- `~/.claude/daemon/data_collector.py:111`+ (`_empty_ai_day`, `_normalize_ai_day`, prune/mirror helpers)
- `~/.claude/scripts/write-ai-insights.py:82`+ (same family of helpers)
- `~/.claude/scripts/shared/cache_dates.py:18`+ (dashboard-side coercion)

2. Dashboard rendering logic duplicated conceptually with Apple Notes renderer
- `generate-dashboard.py` contains explicit "matches embed-dashboard" sections.
- This increases divergence risk for date-gating and section ordering.

## 6) Subtle Bugs / Race Conditions

1. Multi-writer cache race (highest risk)
- Writers:
  - daemon final write: `~/.claude/daemon/data_collector.py:3174`
  - guidance write: `~/.claude/daemon/data_collector.py:5550`, `~/.claude/daemon/data_collector.py:6059`
  - insights subprocess write: `~/.claude/scripts/write-ai-insights.py:1018`
- No file locking or atomic merge protocol across writers.

2. Time-source inconsistency (medium risk)
- Dashboard uses both `datetime.now()` display date and effective date gating.
- Around 00:00-03:00 this can look inconsistent to user if UI date != effective data day.

3. Parser fallback schema drift (medium risk)
- `fetch_diarium()` text fallback returns a narrower schema than JSON parser branch.
- Downstream code relies on richer keys and must compensate.

## 7) Prioritised Implementation Order (Future Sessions)

### Session 1 (P1, 1 session)
- Introduce a single shared `ai_state` module used by daemon + writer + dashboard helper.
- Remove duplicated normalise/prune/mirror implementations.
- Add regression tests for date-scoped reads and source replacement semantics.

### Session 2 (P1, 1-2 sessions)
- Add cache write lock + atomic write helper for all writers.
- Migrate writers to one helper API (`load -> merge -> fsync+replace`).
- Add collision simulation test (concurrent writes).

### Session 3 (P2, 1 session)
- Remove dead method `_auto_embed_dashboard_in_notes` or wire intentionally (not both).
- Remove unused `hints/cal_events/cross_day` or include them in prompt explicitly.

### Session 4 (P2, 1-2 sessions)
- Extract dashboard/Apple Notes shared render model to reduce duplication.
- Keep two presenters (HTML/Notes), one data synthesis pipeline.

### Session 5 (P3, 1 session)
- Normalise overnight UX: explicit “Effective date” in header when 00:00-03:00.
- Keep date display and gating semantics obvious to avoid stale-data confusion.

## 8) What Was Fixed Now vs Deferred

### Fixed now
- Stale insight bleed-through hardening in dashboard load path (today-normalised ai cache).
- Regression-style validation executed with synthetic stale marker injection.

### Deferred (documented backlog)
- Writer lock/atomic cache protocol
- ai_insights normalisation consolidation
- Dead-code cleanup and renderer dedup
