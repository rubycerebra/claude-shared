# Codex Session Prompt — 2026-02-18

## Who You Are Working With

Jim Cherry, 39. Autistic, ADHD, anxiety. Job searching (£35k+ remote WFH).

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

### TASK 1 — Fix income-log: Universal £180 paid 18 Feb, add Working Title £3870 due 25 Feb
**Bead:** HEALTH-7or | **Project:** HEALTH | **Priority:** P1 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-7or --reason="Completed in Codex session"`

---

### TASK 2 — Fix fitness-log: add full week schedule Mon-Sun (Wed=Workout B today, Fri=A, Sun=rest)
**Bead:** HEALTH-mle | **Project:** HEALTH | **Priority:** P1 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-mle --reason="Completed in Codex session"`

---

### TASK 3 — Address parser: create known-locations.json + extract location from Diarium, normalize Whinyates Road
**Bead:** HEALTH-uei | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-uei --reason="Completed in Codex session"`

---

### TASK 4 — Priming/mindfulness: map Streaks Priming habit to mindfulness category in daemon cache
**Bead:** HEALTH-hsx | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-hsx --reason="Completed in Codex session"`

---

### TASK 5 — Apple Notes idea dump: pinned note -> HEALTH inbox pipeline, clears+archives weekly
**Bead:** HEALTH-pp8 | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-pp8 --reason="Completed in Codex session"`

---

### TASK 6 — Starling Bank API -> income-log.json auto-reconciliation
**Bead:** HEALTH-6s1 | **Project:** HEALTH | **Priority:** P3 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-6s1 --reason="Completed in Codex session"`

---

### TASK 7 — Job strategy: tighten 3 CV variants (research, technical deliverables, digital collections) with quantified outcomes
**Bead:** WORK-chn | **Project:** WORK | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close WORK-chn --reason="Completed in Codex session"`

---

### TASK 8 — Follow up awaiting applications (Vertigo, SOAS, National Archives, BFI) and update tracker dates
**Bead:** WORK-vf3 | **Project:** WORK | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close WORK-vf3 --reason="Completed in Codex session"`

---

### TASK 9 — Apply to 3 high-fit roles this week (>=GBP35k, remote/hybrid viable, direct profile match)
**Bead:** WORK-kh5 | **Project:** WORK | **Priority:** P2 | **Type:** task 

**Success criteria:**
- Work is complete and validated
- Run: `bd close WORK-kh5 --reason="Completed in Codex session"`

---

### TASK 10 — Personal Feedback System Phase 1 (Dashboard Reactivity + Codex Spike + Standalone Plan)
**Bead:** TODO-7l2 | **Project:** TODO | **Priority:** P1 | **Type:** task 

Track implementation of dashboard update-reactivity, Beads UI workspace reliability, Codex migration research, standalone app roadmap planning, and refreshed operations documentation.

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-7l2 --reason="Completed in Codex session"`

---

### TASK 11 — ngrok/Cloudflare tunnel: expose API + dashboard to iPhone Safari, solves iCloud HTML preview issue
**Bead:** TODO-0mf | **Project:** TODO | **Priority:** P1 | **Type:** task 

ngrok or Cloudflare Tunnel: expose localhost:8765 (api-server) and dashboard.html to internet so Jim can access on iPhone Safari. Steps: 1) brew install ngrok + auth token OR cloudflared. 2) LaunchAgent plist to keep tunnel alive. 3) Update CORS in ~/.claude/scripts/api-server.py to allow tunnel domain. 4) Store tunnel URL in ~/.claude/config/tunnel-url.txt so dashboard and session-start know the public URL. 5) Update dashboard.html to load API calls via tunnel URL when accessed remotely. This also fixes iCloud HTML preview issue - Jim accesses via tunnel URL in Safari, not Files app.

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-0mf --reason="Completed in Codex session"`

---


## Session Close Protocol (Do This At The End)

```bash
# 1. Close completed beads (add/remove IDs as appropriate)
bd close HEALTH-7or HEALTH-mle HEALTH-uei HEALTH-hsx HEALTH-pp8 HEALTH-6s1 WORK-chn WORK-vf3 WORK-kh5 TODO-7l2 TODO-0mf

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
*2026-02-18 — 11 task(s) from ready beads*
