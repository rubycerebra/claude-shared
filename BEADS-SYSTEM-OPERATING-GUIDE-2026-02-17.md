# Beads System Operating Guide (2026-02-17)

Generated: 2026-02-17 09:32 GMT

This document explains:

1. What beads were completed.
2. What those completions changed in your system.
3. How to use the system now.
4. What to run going forward (daily/weekly/monthly).

---

## 1) Completed Beads Snapshot

### A) Previously completed in the same maintenance cycle

Confirmed closed:

- `TODO-lxm` - dashboard reliability + stale-data audit.
- `TODO-rni` - HRV/sleep injected into AI guidance.
- `TODO-2ch` - context-aware therapy hinting.
- `TODO-2ps` - weekly digest extraction fix.
- `TODO-d95` - application tracker generator + daemon integration.
- `TODO-3gw` - handoff template + file lookup validation.
- `TODO-f8y` - Apple Notes fallback path + health checks.
- `TODO-jaa` - Todoist/Akiflow sync scaffold (disabled until token config).
- `TODO-2` - Apple Notes historical backfill automation.
- `TODO-3` - Letterboxd/Plex status research + recommendation.
- `TODO-ugu` (epic) - proactive fitness/mental-health coach phases complete.

### B) Completed in this continuation

#### HEALTH

- `HEALTH-15` - export/review Apple Health, Streaks, Finch evidence.
- `HEALTH-16` - habit streak review + archived-prune confirmation.
- `HEALTH-17` - weekly accomplishments update in `wins.md`.
- `HEALTH-18` - weekly digest generation + completed-homework archive check.

#### WORK

- `WORK-3` - Word cover letter generator implementation and validation.
- `WORK-4` - `_JOB_ALERTS.md` documentation created and validated.
- `WORK-5` - interview refresh pack for responsibilities + expectations.
- `WORK-6` - role responsibilities + recent releases confidence grounding.
- `WORK-pbv` - job automation hardening (scrapers + Readwise + export-memory verification).

### C) Board state now

- HEALTH: no open issues.
- WORK: no open issues.
- TODO: no open issues.

---

## 2) What This Means for Your System

### Data reliability is materially better

- Dashboard and stale-data handling have been audited and repaired.
- Weekly digest generation now has fallbacks and no longer silently empties.
- Apple Notes sync has a verified fallback route if MCP path fails.

### Job pipeline is now more operational, not ad hoc

- Application tracker generation + daemon sync exists.
- Job scrapers (BFI/ICO/Arts Council/Guardian-Readwise) are live.
- Readwise direct scraper now works even without `python-dotenv` installed in system Python.
- Word cover letters now generate real `.docx` output locally.

### Health maintenance workflow is now executable and closed-loop

- Friday chores were fully executed and recorded with evidence comments.
- `wins.md` and weekly digest were both updated in-place.
- Therapy archive flow is runnable and idempotent ("no completed items" handled cleanly).

---

## 3) New/Updated Assets You Should Know

### Core automation and scripts

- `~/.claude/scripts/generate-cover-letter.py`
- `~/.claude/daemon/scrapers/readwise_scraper.py`
- `~/.claude/scripts/sync-recurring-beads.py`

### New operational docs

- `~/Documents/CV/Applications/_JOB_ALERTS.md`
- `~/Documents/CV/Applications/2026-02-17_Vertigo_Interview_Refresh_Quick.md`
- `~/Documents/Claude Projects/claude-shared/RECURRING-BEADS.md`
- `~/.claude/config/recurring-beads.json`

### Updated working outputs

- `~/Documents/Claude Projects/claude-shared/wins.md`
- `~/Documents/Claude Projects/claude-shared/weekly-digest-2026-W08.md`

---

## 4) How to Use It (Practical Commands)

### A) Generate a Word cover letter

```bash
python3 ~/.claude/scripts/generate-cover-letter.py \
  --company "Vertigo Releasing" \
  --role "Technical Manager" \
  --type coordinator \
  --why "the all-rights model and Visions Home Video growth"
```

Outputs:

- Text source: `..._cover_letter.txt`
- Word doc: `..._cover_letter.docx`

### B) Validate job automation quickly

```bash
python3 ~/.claude/daemon/job_scrapers.py
python3 ~/.claude/daemon/scrapers/readwise_scraper.py
python3 ~/.claude/scripts/export-memory.py
```

### C) Sync recurring beads (new)

Preview:

```bash
python3 ~/.claude/scripts/sync-recurring-beads.py --dry-run
```

Create due recurring beads:

```bash
python3 ~/.claude/scripts/sync-recurring-beads.py
```

---

## 5) Recurring Procedure Setup

Configured recurring rules (`~/.claude/config/recurring-beads.json`):

- Weekly Friday HEALTH chores:
  - Export/review health data
  - Review/prune streaks
  - Update `wins.md`
  - Weekly insight digest
- Monthly day-1 WORK chore:
  - Job alerts + scraper review

Script behavior:

1. Checks if a matching open bead already exists.
2. Checks if a matching bead already closed in current period.
3. Creates only when due and not already satisfied.

This avoids duplicate recurring tasks.

---

## 6) Forward Operating Checklist

### Daily

1. Use Beads UI to process ready issues.
2. Keep daemon running.
3. If job-search day: run scraper check once before application work.

### Friday (weekly maintenance)

1. Run HEALTH recurring chores.
2. Confirm `wins.md` updated.
3. Confirm weekly digest regenerated and emotional arc completed.

### Day 1 of month

1. Run monthly job alerts review.
2. Validate Readwise + scraper sources.
3. Refresh `_JOB_ALERTS.md` if sources/filters changed.

---

## 7) Known Notes / Constraints

- `beads-ui` project dropdown was reinstated during this session.
- `generate-cover-letter.py` produces `.docx`; PDF export remains a manual final step in Word.
- Readwise may still return broad/non-target roles; filtering remains your review step unless further scoring rules are added.

---

## 8) Suggested Next Improvements (Optional)

1. Add scoring rules to prioritize scraper results against your target profile automatically.
2. Auto-run `sync-recurring-beads.py` from a daily launchd job.
3. Add a script to append a closed-beads weekly summary into this folder automatically.
