# Codex Session Prompt — 2026-02-28

## Who You Are Working With

Jim Cherry, 39. Autistic, ADHD, anxiety. Work strategy: freelance-first (Chris, £27/hr from April). Job search fully disabled.

You have a large context window. Use it fully — load complete files, don't summarise prematurely.

British English throughout. Emojis for visual anchoring (ADHD accessibility). Short sentences.

---

## System Architecture (Read This First)

Jim's system is a personal life OS built on a macOS daemon + Claude CLI:

- **Daemon:** `~/.claude/daemon/data_collector.py` — runs hourly, collects all data, writes cache
- **Cache:** `~/.claude/cache/session-data.json` — single source of truth for ALL data
- **Session brief:** `~/.claude/cache/session-brief-HEALTH.md` — fast daily brief (~50 lines)
- **AI insights writer:** `~/.claude/scripts/write-ai-insights.py` — uses Haiku API
- **Dashboard:** `~/Documents/Claude Projects/claude-shared/generate-dashboard.py` → `dashboard.html`
- **Apple Notes sync:** `~/.claude/scripts/sync-journal-to-apple-notes.sh`
- **Journal:** `~/Documents/Claude Projects/claude-shared/journal/YYYY-MM-DD.md`
- **Beads (task tracking):** `.beads/` in each project — HEALTH, WORK, TODO
- **Auto-beads script:** `~/.claude/scripts/auto-beads.py`
- **Fitness log:** `~/Documents/Claude Projects/HEALTH/fitness-log.md`
- **Mental health:** `~/Documents/Claude Projects/claude-shared/mental-health-insights.md`
- **Patterns:** `~/Documents/Claude Projects/claude-shared/patterns.md`
- **Wins:** `~/Documents/Claude Projects/claude-shared/wins.md`
- **Diarium exports:** `~/My Drive (james.cherry01@gmail.com)/Diarium/Export/`
- **Therapy Spark summaries:** journal `## Therapy` sections (primary)
- **Therapy transcripts:** `~/Library/Application Support/Alter/Transcripts/` (fallback)
- **CV/Applications:** `~/Documents/CV/Applications/`

**Three projects:** HEALTH (therapy, fitness, mental health) | WORK (job search) | TODO (infrastructure, system tasks)

**If you get blocked** on any task: create a bead explaining the blocker, move on to the next task.

---

## Your Tasks (Work Through These In Order)

### TASK 1 — Log sleep/wake time patterns for 3 days to clarify 2am journaling habit
**Bead:** HEALTH-6tn | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-6tn --reason="Completed in Codex session"`

---

### TASK 2 — Review unmatched job-response emails
**Bead:** WORK-t5w | **Project:** WORK | **Priority:** P1 | **Type:** task 

Auto-created by application tracker sync: unmatched/manual-review job emails detected.
Please review and map to applications:
- 2026-02-26: $47.94 payment to Readwise, Inc. was unsuccessful again ("Readwise, Inc." <failed-payments+acct_1BvJKpKcTVUMAwem@stri)

**Success criteria:**
- Work is complete and validated
- Run: `bd close WORK-t5w --reason="Completed in Codex session"`

---

### TASK 3 — Redesign Tomorrow's Guidance section for actionable insights
**Bead:** TODO-y4c | **Project:** TODO | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-y4c --reason="Completed in Codex session"`

---

### TASK 4 — Extract and surface action points from morning pages in dashboard
**Bead:** TODO-953 | **Project:** TODO | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-953 --reason="Completed in Codex session"`

---

### TASK 5 — Set up Claude voice transcription workflow for morning pages
**Bead:** TODO-f47 | **Project:** TODO | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-f47 --reason="Completed in Codex session"`

---

### TASK 6 — Trace/review sequenced Codex pipeline implementation
**Bead:** TODO-hnf | **Project:** TODO | **Priority:** P2 | **Type:** task 

Claude follow-up: inspect new run-sequenced-codex.py, codex-sequenced-task.md, and run-quality-gate.sh for correctness and safety; confirm stage-gate behaviour and edge cases.

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-hnf --reason="Completed in Codex session"`

---


## Session Close Protocol (Do This At The End)

```bash
# 1. Close completed beads (add/remove IDs as appropriate)
bd close HEALTH-6tn WORK-t5w TODO-y4c TODO-953 TODO-f47 TODO-hnf

# 2. Sync all beads
bd sync

# 3. Git commit + push each project that changed
cd ~/Documents/Claude\ Projects/HEALTH && git add -A && git commit -m "Codex session: [what you did]" && git push
cd ~/Documents/Claude\ Projects/WORK && git add -A && git commit -m "Codex session: [what you did]" && git push
cd ~/Documents/Claude\ Projects/TODO && git add -A && git commit -m "Codex session: [what you did]" && git push

# 4. Regenerate dashboard
~/Documents/Claude\ Projects/claude-shared/trigger-dashboard.sh --no-open

# 5. Sync to Apple Notes
~/.claude/scripts/sync-journal-to-apple-notes.sh
```

---

*Generated automatically by `~/.claude/scripts/generate-codex-prompt.py`*
*2026-02-28 — 6 task(s) from ready beads*
