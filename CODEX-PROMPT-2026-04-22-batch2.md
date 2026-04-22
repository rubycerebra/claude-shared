# Codex Session Prompt — 2026-04-22 (Batch 2)

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
- **Fitness log:** `~/Documents/Claude Projects/HEALTH/fitness-log.md`
- **Mental health:** `~/Documents/Claude Projects/claude-shared/mental-health-insights.md`
- **Patterns:** `~/Documents/Claude Projects/claude-shared/patterns.md`
- **Wins:** `~/Documents/Claude Projects/claude-shared/wins.md`
- **Diarium exports:** `~/My Drive (james.cherry01@gmail.com)/Diarium/Export/`
- **CV/Applications:** `~/Documents/CV/Applications/`
- **Settings:** `~/.claude/settings.json`
- **RTK:** `rtk` CLI — token-optimised proxy for git/bash commands

**Three projects:** HEALTH (therapy, fitness, mental health) | WORK (job search) | TODO (infrastructure, system tasks)

**If you get blocked** on any task: create a bead explaining the blocker, move on to the next task.

---

## Your Tasks (Work Through These In Order)

### TASK 1 — Weekly beads hygiene follow-up (2026-04-19)
**Bead:** TODO-uvx4 | **Project:** TODO | **Priority:** P2 | **Type:** task
**Labels:** automation, claude-maintenance, review, weekly

Weekly hygiene report found follow-up items.

- Duplicate groups: 0
- Stale open issues: 6
- Stale in-progress issues (>5d): 0
- Blocked issues: 0

Report: `/Users/jamescherry/Documents/Claude Projects/claude-shared/BEADS-HYGIENE-2026-04-19.md`

**What to do:**
1. Read the full hygiene report
2. For each stale open issue: review the bead, decide whether to close it (if done/obsolete), defer it, or add a comment noting why it remains open
3. Document what you did with each stale bead as a comment on TODO-uvx4
4. Close TODO-uvx4 when all 6 stale issues have been triaged

**Success criteria:**
- All 6 stale issues have been actioned (closed, deferred, or commented)
- Run: `bd close TODO-uvx4 --reason="Completed in Codex session — stale issues triaged"`

---

### TASK 2 — Close completed persona bead (HEALTH-syqv)
**Bead:** HEALTH-syqv | **Project:** HEALTH | **Priority:** P2 | **Type:** task

This bead tracks building the domain expert agent persona for Jim's theatrical/streaming/video work. Its notes read: *"Completed: WORK persona tree built, Mal brief, INDEX, terminology, workflow-patterns, contacts, qc-gotchas, platforms-specs, clients/atomic-film.md, clients/vertigo.md, bridge, /work Mal framing, optional /teach command, colleagues-extract.py, wrap-up integration. Static checks passed 2026-04-18."*

The bead was never closed. Work appears done.

**What to do:**
1. Verify the files listed in the notes exist:
   - `~/Documents/Claude Projects/WORK/.claude/persona/mal.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/INDEX.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/terminology.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/workflow-patterns.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/contacts.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/qc-gotchas.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/clients/atomic-film.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/clients/vertigo.md`
   - `~/Documents/Claude Projects/WORK/.claude/persona/bridge.md`
   - `~/.claude/scripts/colleagues-extract.py`
2. If all files exist: close the bead with a verification note
3. If any are missing: note exactly what's missing, create a follow-up bead, then close HEALTH-syqv as partially complete

**Never say "verified" unless you can quote the exact `ls` output confirming each file.**

**Success criteria:**
- Files checked, bead closed with verification note
- Run: `bd close HEALTH-syqv --reason="Files verified present — work was complete, bead unclosed"`

---

### TASK 3 — Bespoke skill: email drafting
**Bead:** HEALTH-7ge6 | **Project:** HEALTH | **Priority:** P3 | **Type:** task

Build a `/draft` skill wrapping Gmail MCP. Takes recipient + topic, drafts in Jim's voice (British English, direct, concise), presents for approval before sending. Gmail MCP auth already available.

**Notes:**
Check `~/.claude/cache/session-brief-HEALTH.md` and `~/.claude/NOW.md` before starting.

## Context
- Bead: HEALTH-7ge6 (P3, open)
- Goal: Create a `/draft` skill at `~/.claude/commands/draft.md`
- Gmail MCP auth available: `mcp__claude_ai_Gmail__authenticate`
- Skill pattern reference: `~/.claude/commands/cheapest.md` (search-and-report shape)
- No existing email skill in `~/.claude/commands/`

## Goal
Build a `/draft [recipient] [topic]` skill that authenticates Gmail MCP, drafts a message in Jim's voice (British English, direct, concise), and presents it for approval before sending.

## Tasks
1. Read `~/.claude/commands/cheapest.md` for skill structure, then check the Gmail MCP tool schema
2. Write `~/.claude/commands/draft.md` — frontmatter, argument parsing for recipient + topic, Gmail auth, draft generation, approval gate before send
3. Test: `/draft` with no args shows usage; `/draft test@example.com check in about project` produces a reviewable draft
4. Close HEALTH-7ge6

## Constraints
- MUST include approval gate — never auto-send
- MUST write in Jim's voice: British English, direct, no filler, 3-5 sentences unless explicitly longer
- MUST follow skill frontmatter: `name:` and `description:` required
- MUST NOT hardcode email addresses or credentials
- Never say 'verified' or 'confirmed' unless you can quote the exact output
- Done when: `/draft recipient topic` produces a reviewable draft with a send/discard choice

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-7ge6 --reason="Completed in Codex session"`

---

### TASK 4 — Work log mobile/web sync stale — diagnose pipeline
**Bead:** TODO-lepz | **Project:** TODO | **Priority:** P4 | **Type:** task
**Triage route:** auto_codex | **Suggested workdir:** HEALTH

Mobile work log data isn't syncing to web dashboard and appears stale. Previous dispatch was blocked — run fresh diagnostic.

## Diagnostic workflow
1. Run `/stale-check` (or equivalent) — check `~/.claude/cache/health-live.json` age, session-data cache freshness, API freshness fields
2. Run `/iron-out` if diary sections, sleep, or fitness data are missing or stale
3. Check the dashboard React app at port 8765 — is work log data appearing?
4. Trace the data path: where does work log data originate? Check `~/.claude/cache/session-data.json` for work log fields
5. Identify the exact breakpoint: daemon collection → cache write → API read → dashboard display
6. Fix any gap found, or document the root cause as a bead comment if it needs deeper work

## Constraints
- Use lumen (`mcp__lumen__semantic_search`) for code search, not grep
- Never claim "verified" without quoting exact output
- If blocked, document the specific blocker and move on

**Success criteria:**
- Root cause identified and either fixed or documented
- Run: `bd close TODO-lepz --reason="Completed in Codex session — [root cause summary]"`

---


## Session Close Protocol (Do This At The End)

```bash
# 1. Close completed beads (remove any you didn't finish)
bd close TODO-uvx4 HEALTH-syqv HEALTH-7ge6 TODO-lepz

# 2. Export beads to JSONL
cd ~/Documents/Claude\ Projects/HEALTH && bd export -o .beads/issues.jsonl
cd ~/Documents/Claude\ Projects/TODO && bd export -o .beads/issues.jsonl

# 3. Git commit + push each project that changed
cd ~/Documents/Claude\ Projects/HEALTH && git add -A && git commit -m "Codex session batch2: [what you did]" && git push
cd ~/Documents/Claude\ Projects/WORK && git add -A && git commit -m "Codex session batch2: [what you did]" && git push
cd ~/Documents/Claude\ Projects/TODO && git add -A && git commit -m "Codex session batch2: [what you did]" && git push

# 4. Regenerate dashboard
~/Documents/Claude\ Projects/claude-shared/trigger-dashboard.sh --no-open --cache-only

# 5. Sync to Apple Notes
~/.claude/scripts/sync-journal-to-apple-notes.sh
```

---

*Batch 2 — curated manually from ready pool*
*2026-04-22 — P2 hygiene + persona close + P3 skill + P4 diagnostic*
