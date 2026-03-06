# 🔍 Beads Audit — 17 February 2026

**Codex 5.3 Post-Session Assessment**

---

## 🏷️ TL;DR

- ✅ **Codex completed 23+ items** across HEALTH, TODO, and WORK — mostly refiling, planning docs, and system hardening
- 🔴 **Stale insights bug (HEALTH-yyc) was closed but recurred today** — fix needs validation
- 🔴 **WORK has 5 invisible beads** — bd CLI shows 0 open, but JSONL has 5 genuinely open job search tasks
- 🔴 **TODO has ~8 invisible beads** — bd CLI shows 3 open, JSONL shows 11 open (including new fitness coach epic)
- 🟡 **4 decisions need Jim's input** — Codex provider, standalone app, NUC migration, anxiety score format

---

## 📊 System State at a Glance

| Project | bd CLI Open | JSONL Open | Discrepancy | Concern |
|---------|-------------|------------|-------------|---------|
| HEALTH  | 0           | 4          | ⚠️ 4 Friday chores show open in JSONL but closed in bd | See below |
| WORK    | 0           | 5          | 🔴 5 job tasks invisible to bd | bd doesn't route WORK |
| TODO    | 3           | 11         | 🔴 8 items invisible to bd list | Includes new fitness epic |

**Total visible work:** 3 items
**Total actual work:** ~20 items

---

## ✅ What Codex Actually Did (Verified)

### Infrastructure & System

| Item | Status | Notes |
|------|--------|-------|
| Diary `updates` reactive flow | ✅ Done | Daemon + dashboard now hash updates for reruns |
| Anxiety reduction score pipeline | ✅ Done | 0-10 scale in `ai_insights.by_date`, weekly digest reports average |
| Beads UI hardening | ✅ Done | Clean stop/start, workspace validation, healthcheck passed |
| Epic structure (TODO-7l2) | ✅ Done | 10 children completed, 3 deferred |
| Recurring bead sync | ✅ Done | `sync-recurring-beads.py` + `recurring-beads.json` |
| Fitness coach Phase 1 | ✅ Done | `fetch_fitness_data()` parses fitness-log.md, session brief has coaching section |

### New Scripts Created

| Script | Purpose | Tested? |
|--------|---------|---------|
| `generate-cover-letter.py` | Word doc cover letter generation | 🟡 Unknown |
| `readwise_scraper.py` | Readwise job listing sync | 🟡 Unknown |
| `sync-recurring-beads.py` | Recurring bead automation | ✅ LaunchAgent configured |

### Planning Documents

| Document | Location | Decision Needed? |
|----------|----------|-----------------|
| Codex AI Insights Spike | `claude-shared/CODEX-AI-INSIGHTS-SPIKE-2026-02-17.md` | 🟡 Yes — go/no-go |
| Standalone Feedback App Roadmap | `claude-shared/STANDALONE-FEEDBACK-APP-ROADMAP-2026-02-17.md` | 🟡 Yes — go/no-go |
| NUC Migration Plan | Referenced in TODO-7l2.5 | ⏸️ Deferred to March |

### Beads Refiled (Housekeeping)

Codex moved system/infra beads out of HEALTH into their correct projects:

| Bead | From | To | Reason |
|------|------|----|--------|
| HEALTH-1vi (Akiflow) | HEALTH | TODO-jaa | Claude maintenance |
| HEALTH-5ec (Opus audit) | HEALTH | TODO-lxm | Claude maintenance |
| HEALTH-axr (Handoff template) | HEALTH | TODO-3gw | TODO project work |
| HEALTH-bpw (Job search) | HEALTH | WORK-pbv | WORK project work |
| HEALTH-ci0 (Letterboxd) | HEALTH | TODO-3 | Duplicate |
| WORK-2 (App tracker) | WORK | TODO-d95 | Claude maintenance |
| WORK-74s (Apple Notes MCP) | WORK | TODO-f8y | Claude maintenance |

---

## 🔴 Concerns & Red Flags

### 1. Stale Insights Bug — Closed But Not Fixed

**Bead:** HEALTH-yyc (P1 bug)
**Status:** Closed by Codex
**Reality:** Jim hit the same bug again today.

The fix was supposedly date-scoped cache isolation in `write-ai-insights.py`. But if insights are still bleeding through from previous days, the fix either:
- Wasn't applied to the right code path
- Doesn't survive daemon refresh cycles
- Only fixed one of two insight generation paths (daily vs evening fallback)

**🎯 Action needed:** Validate the fix. Check `write-ai-insights.py` for date-scoped writes. Run a full daemon cycle and confirm old entries don't persist.

---

### 2. Friday Chores — Claimed Closed, Actually Open

**Beads:** HEALTH-15, 16, 17, 18 (P4 chores)
**Codex overview says:** Closed (0 open in HEALTH)
**JSONL says:** All 4 are `status: "open"`

These were never actually executed. Codex's overview document states HEALTH has 0 open beads, but the raw data contradicts this. The chores (health data export, habit pruning, wins update, weekly digest) were likely auto-interpreted as "done" during planning without actual execution.

| Chore | JSONL Status | Actually Done? |
|-------|-------------|----------------|
| HEALTH-15: Export health data | 🔴 Open | ❓ No evidence |
| HEALTH-16: Prune habit streaks | 🔴 Open | ❓ No evidence |
| HEALTH-17: Update wins.md | 🟡 Partial | Codex may have updated wins.md |
| HEALTH-18: Weekly digest | 🔴 Open | ❓ No evidence |

**🎯 Action needed:** These should remain open. Run them properly on next Friday session.

---

### 3. WORK Beads Are Invisible

**Problem:** `bd list` from WORK directory returns nothing. `bd stats` shows 0 open. But the JSONL has 5 genuinely open tasks.

| Bead | Title | Priority |
|------|-------|----------|
| WORK-3 | Word cover letter generator | P2 |
| WORK-4 | Document job alerts in _JOB_ALERTS.md | P2 |
| WORK-5 | Interview prep: review role responsibilities | P2 |
| WORK-6 | Review job responsibilities + company film releases | P2 |
| WORK-pbv | Job search automation (scrapers, Readwise, export-memory) | P2 |

**Root cause:** WORK likely isn't registered in bd's routing configuration, so the CLI can't find the database. The beads exist in the JSONL but bd commands don't surface them.

**🎯 Action needed:** Register WORK in bd CLI routes. These are active job search tasks — they need to be visible.

---

### 4. TODO Beads — Significant CLI vs JSONL Gap

**bd CLI shows:** 3 open (TODO-7l2, TODO-7l2.8, TODO-7l2.9)
**JSONL shows:** 11 open, including:

| Bead | Title | Priority | In bd CLI? |
|------|-------|----------|-----------|
| TODO-7l2 | Personal Feedback System Phase 1 (epic) | P1 | ✅ |
| TODO-7l2.8 | Codex provider routing | P1 | ✅ |
| TODO-7l2.9 | Standalone app MVP | P1 | ✅ |
| TODO-7l2.5 | NUC migration runbook | P3 | ✅ (blocked) |
| TODO-ugu | Proactive fitness & mental health coach (epic) | P2 | ❌ |
| TODO-2ps | Fix weekly digest generation | P2 | ❌ |
| TODO-rni | Phase 2: HRV/sleep in AI guidance | P2 | ❌ |
| TODO-2ch | Phase 4: Therapy homework surfacing | P3 | ❌ |
| TODO-2 | Backfill Apple Notes historical summaries | P3 | ❌ |
| TODO-3 | Letterboxd/Plex integration | P3 | ❌ |
| TODO-3gw | Handoff template update | P2 | ❌ |
| TODO-d95 | App tracker Excel + daemon | P1 | ❌ |
| TODO-f8y | Fix Apple Notes MCP | P2 | ❌ |
| TODO-jaa | Akiflow/Todoist integration | P2 | ❌ |
| TODO-lxm | Opus system-wide efficiency audit | P3 | ❌ |

**Root cause:** The bd CLI database and JSONL are out of sync. The JSONL has items that were either created directly or refiled from other projects without being registered in the bd database.

**🎯 Action needed:** Reconcile bd database with JSONL. All 11 open items should be visible in `bd list`.

---

### 5. Anxiety Score — Pipeline Ready, No User Instructions

The anxiety reduction score system is fully instrumented:
- Daemon captures it
- Cache stores it at `ai_insights.by_date[date].anxiety_reduction_score`
- Weekly digest reports the average

But Jim hasn't been told how to feed data in. The trigger phrase is:

> **Add `anxiety reduction: X/10` to your diary entry** (Diarium updates field)

No code changes needed. Just needs communicating.

---

## 🟡 Decision Gates

These 4 items are blocked waiting for Jim's approval:

| # | Decision | Bead | Risk | Recommendation |
|---|----------|------|------|----------------|
| 1 | **Codex provider for AI insights** | TODO-7l2.8 | Low — feature-flagged, rollback to Anthropic as default | 🟢 Approve A/B test |
| 2 | **Standalone feedback app** | TODO-7l2.9 | Medium — new codebase, maintenance overhead | 🟡 Review roadmap first |
| 3 | **NUC migration** | TODO-7l2.5 | Low — deferred to March 17 | ⏸️ Leave deferred |
| 4 | **Anxiety score format** | N/A | Zero — no code changes | 🟢 Just start using it |

---

## 📋 Full Open Beads Summary (All Projects)

### 🏥 HEALTH — 4 Open

All Friday chores. Low priority but should be done this coming Friday.

| Bead | Title | Priority | Type |
|------|-------|----------|------|
| HEALTH-15 | Export and review health data | P4 | Chore |
| HEALTH-16 | Review and prune habit streaks | P4 | Chore |
| HEALTH-17 | Update wins.md | P4 | Chore |
| HEALTH-18 | Weekly insight digest | P4 | Chore |

### 💼 WORK — 5 Open (invisible to bd)

Active job search tasks. These matter.

| Bead | Title | Priority | Type |
|------|-------|----------|------|
| WORK-3 | Word cover letter generator | P2 | Task |
| WORK-4 | Document job alerts | P2 | Task |
| WORK-5 | Interview prep: role responsibilities | P2 | Task |
| WORK-6 | Review job responsibilities + company films | P2 | Task |
| WORK-pbv | Job search automation | P2 | Task |

### 📝 TODO — 11 Open (only 3 visible to bd)

Mix of system maintenance, fitness coaching epic, and deferred decisions.

| Bead | Title | Priority | Type | Status |
|------|-------|----------|------|--------|
| TODO-d95 | App tracker Excel + daemon | P1 | Task | Ready |
| TODO-7l2 | Personal Feedback System Phase 1 | P1 | Epic | Active |
| TODO-7l2.8 | Codex provider routing | P1 | Task | 🚧 Blocked (awaiting approval) |
| TODO-7l2.9 | Standalone app MVP | P1 | Task | 🚧 Blocked (awaiting approval) |
| TODO-ugu | Fitness & mental health coach | P2 | Epic | In Progress |
| TODO-2ps | Fix weekly digest generation | P2 | Task | Ready |
| TODO-rni | Phase 2: HRV/sleep in AI guidance | P2 | Task | Depends on TODO-7mf ✅ |
| TODO-3gw | Handoff template update | P2 | Task | Ready |
| TODO-f8y | Fix Apple Notes MCP | P2 | Task | Ready |
| TODO-jaa | Akiflow/Todoist integration | P2 | Task | Ready |
| TODO-2 | Backfill Apple Notes summaries | P3 | Task | Ready |
| TODO-3 | Letterboxd/Plex integration | P3 | Feature | Ready |
| TODO-lxm | Opus system-wide efficiency audit | P3 | Task | Ready |
| TODO-2ch | Phase 4: Therapy homework surfacing | P3 | Task | Depends on TODO-rni |
| TODO-7l2.5 | NUC migration runbook | P3 | Task | ⏸️ Deferred to March 17 |

**Total open across all projects: ~20 items**

---

## 🔧 Integrity Issues

### bd CLI vs JSONL Desync

This is the biggest systemic concern. The bd CLI is the primary interface for beads, but it's missing items:

- **WORK:** 5 items in JSONL, 0 in bd CLI (routing issue)
- **TODO:** 15 items in JSONL, 4 in bd CLI (database sync issue)
- **HEALTH:** 4 items in JSONL marked open, bd says 0 open (possible: bd reads the database, JSONL is stale export, or vice versa)

**Impact:** If bd is the source of truth, 16 tasks are invisible. If JSONL is the source of truth, bd is giving a dangerously incomplete view.

**🎯 Fix:** Determine which is authoritative (bd database or JSONL) and reconcile. Until then, trust JSONL — it has more data.

---

## 🎯 Next 3 Actions

1. **🔴 Validate the stale insights fix (HEALTH-yyc)** — This is a P1 bug that recurred. Run `write-ai-insights.py` through a full cycle, confirm date-scoped isolation works, check both daily and evening insight paths. Delegate to Opus.

2. **🔴 Fix bd CLI routing for WORK** — 5 job search tasks are invisible. Register WORK in bd routes so `bd list` surfaces them. Jim's job search is the most important active goal — these tasks cannot be hidden.

3. **🟡 Reconcile bd database with JSONL across all projects** — 16 items exist in JSONL but not in bd CLI. Either bulk-import them or identify why the sync broke. This undermines trust in the entire beads system.

---

*Generated 17 February 2026 by Claude Opus — Beads system audit for Jim*
*Source data: JSONL files (HEALTH, WORK, TODO), bd CLI output, Codex 5.3 overview document*
