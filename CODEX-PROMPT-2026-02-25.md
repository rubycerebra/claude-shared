# Codex Session Prompt — 2026-02-25

## Who You Are Working With

Jim Cherry, 39. Autistic, ADHD, anxiety. Work strategy: selective jobs (remote £35k+ or local/hybrid £40k+) plus equal-priority freelance opportunities.

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

### TASK 1 — Weekly beads hygiene follow-up (2026-02-24)
**Bead:** TODO-k6a | **Project:** TODO | **Priority:** P2 | **Type:** task 

Weekly hygiene report found follow-up items.

- Duplicate groups: 0
- Stale open issues: 0
- Stale in-progress issues (>5d): 1
- Blocked issues: 2

Report: /Users/jamescherry/Documents/Claude Projects/claude-shared/BEADS-HYGIENE-2026-02-24.md

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-k6a --reason="Completed in Codex session"`

---

### TASK 2 — 💼
**Bead:** TODO-xcj | **Project:** TODO | **Priority:** P2 | **Type:** task 

Captured automatically from Apple Notes '💡 Ideas for Claude' on 2026-02-25T18:26:13.

Source text:
💼

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-xcj --reason="Completed in Codex session"`

---

### TASK 3 — 🧠
**Bead:** TODO-rtq | **Project:** TODO | **Priority:** P2 | **Type:** task 

Captured automatically from Apple Notes '💡 Ideas for Claude' on 2026-02-25T18:26:13.

Source text:
🧠

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-rtq --reason="Completed in Codex session"`

---

### TASK 4 — 💼
**Bead:** TODO-qez | **Project:** TODO | **Priority:** P2 | **Type:** task 

Captured automatically from Apple Notes '💡 Ideas for Claude' on 2026-02-25T18:26:14.

Source text:
💼

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-qez --reason="Completed in Codex session"`

---

### TASK 5 — 🧠
**Bead:** TODO-4lr | **Project:** TODO | **Priority:** P2 | **Type:** task 

Captured automatically from Apple Notes '💡 Ideas for Claude' on 2026-02-25T18:26:14.

Source text:
🧠

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-4lr --reason="Completed in Codex session"`

---


## Session Close Protocol (Do This At The End)

```bash
# 1. Close completed beads (add/remove IDs as appropriate)
bd close TODO-k6a TODO-xcj TODO-rtq TODO-qez TODO-4lr

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
*2026-02-25 — 5 task(s) from ready beads*
