# 📋 System Briefing — 17 February 2026

Generated: 17:15 GMT | Author: Claude Opus

---

## 🔁 Recurring Friday Beads

### Setup Status: ✅ Working Correctly

| Component | Status | Detail |
|-----------|--------|--------|
| Config file | ✅ Present | `~/.claude/config/recurring-beads.json` — 4 weekly HEALTH + 1 monthly WORK |
| Sync script | ✅ Solid | `~/.claude/scripts/sync-recurring-beads.py` — dedup logic, dry-run support |
| LaunchAgent | ✅ Loaded | `com.claude.sync-recurring-beads` — runs daily 08:05 + at login |
| Error log | ✅ Clean | No errors in `~/.claude/logs/sync-recurring-beads-error.log` |
| Last run | ✅ Correct | Output: `due=0, created=0` (today is Tuesday — nothing due) |

### How It Works

1. LaunchAgent fires at 08:05 every day (and at login)
2. Script checks: is today Friday? Is it the 1st of the month?
3. If yes → checks for existing open bead with same title
4. If yes → checks if same bead was already closed this week/month
5. Only creates if neither condition is true

### HEALTH-15/16/17/18 (Friday Chores)

These are **not one-offs**. They will be re-created next Friday automatically.

- All four were created on Friday 14 Feb
- All four were closed by Codex on Monday 17 Feb (with detailed evidence comments)
- The sync script's `same_period()` check uses ISO week numbers
- Since they were closed in W08 (this week), they won't be duplicated
- On Friday 20 Feb (W08 still), the script will see "already completed this period" and skip
- On Friday 27 Feb (W09), it will create fresh HEALTH-15/16/17/18 beads

### Verdict

🟢 **No gaps.** The recurring beads system is correctly set up and automated. The only minor note: today's log says `due=0` because it ran on a Tuesday. The real test will be Friday 20 Feb — if it skips (because W08 chores are done), and Friday 27 Feb — if it creates new ones. Worth checking the log on those days.

---

## 🤖 What Codex Has Done Since This Morning

### Git Commits Since 07:00

**Zero commits** across HEALTH, WORK, and TODO. Codex worked entirely within the beads system, scripts, and shared documents — no project-level code was committed to git.

### Documents Created Today (all in `claude-shared/`)

| Document | Purpose |
|----------|---------|
| `BEADS-AUDIT-2026-02-17.md` | Full audit of beads integrity across 3 projects |
| `BEADS-SYSTEM-OPERATING-GUIDE-2026-02-17.md` | How-to guide for the system post-maintenance |
| `STANDALONE-FEEDBACK-APP-ROADMAP-2026-02-17.md` | Tauri + Python standalone app plan |
| `CODEX-AI-INSIGHTS-SPIKE-2026-02-17.md` | Research: switching AI insights from Haiku to Codex |
| `CLAUDE-MD-DRIFT-REPORT-2026-02-17.md` | Cross-project CLAUDE.md consistency check |
| `COWORK-SCRIPTS-REVIEW-2026-02-17.md` | Script health check + `verify-sync.sh` modernised |
| `NUC-MIGRATION-PLAN-2026-02-17.md` | 3-phase NUC migration architecture |
| `GUARDRAILS-REVIEW-2026-02-17.md` | Weekly guardrails review (no changes needed) |
| `APPLE-NOTES-INTEGRATION-STATUS-2026-02-17.md` | AppleScript fallback confirmed working |
| `LETTERBOXD-PLEX-STATUS-2026-02-17.md` | EmBoxd Plex support still not shipped |
| `RECURRING-BEADS.md` | Recurring beads documentation |
| `weekly-digest-2026-W08.md` | Week 8 digest (partially filled) |

### Beads Closed Today

Codex closed **every open bead** across all three projects:

- **HEALTH:** 4 Friday chores (15, 16, 17, 18) — with evidence comments
- **WORK:** 7 items (cover letter gen, job alerts doc, interview prep, job automation)
- **TODO:** ~30 items including the entire `TODO-lxm` (dashboard audit) and `TODO-ugu` (fitness coach) epics

### Scripts Created/Modified

| Script | Status |
|--------|--------|
| `~/.claude/scripts/sync-recurring-beads.py` | ✅ New — recurring bead automation |
| `~/.claude/scripts/generate-cover-letter.py` | ✅ New — Word doc cover letters |
| `~/.claude/daemon/scrapers/readwise_scraper.py` | ✅ New — Readwise job scraper |
| `~/Documents/Claude Projects/claude-shared/verify-sync.sh` | ✅ Updated — modernised for 3-project model |

### Current Board State

| Project | Open | Notes |
|---------|------|-------|
| HEALTH | 0 | Clean. Next beads auto-created Friday |
| WORK | 0 | All job search tasks closed |
| TODO | 1 | `TODO-7l2` (epic) remains open — its children are done but it's the parent tracker |

### Audit Report Accuracy Note

⚠️ The `BEADS-AUDIT-2026-02-17.md` was written **mid-session** (before Codex finished). It claims 20 open items and bd CLI desync issues. **These are no longer true.** By the end of the Codex session, all items were closed and JSONL matches the SQLite database perfectly. The audit document is now a historical artefact, not current state.

---

## 💡 Codex Large-Context Opportunities

Codex can hold 200k+ tokens in a single pass. Here is what that unlocks for Jim's specific system.

### 1. 📔 Full Journal Synthesis (Cross-Session Memory)

**What:** Load all 50 journal entries (`claude-shared/journal/*.md`) + `mental-health-insights.md` (236 lines) + `patterns.md` (142 lines) + `what-works.txt` (154 lines) + `wins.md` (202 lines) in a single context window.

**Why Haiku can't:** Haiku processes one day at a time. It generates daily insights but never sees the full arc. Patterns that emerge over 4-8 weeks are invisible to it.

**What Codex could produce:**
- Monthly emotional trajectory report with turning points identified
- Cross-reference therapy homework against journal mood trends
- Detect seasonal/cyclical anxiety patterns across the full dataset
- Surface interventions that correlate with good days vs bad days (evidence-based, not anecdotal)

**Concrete output:** A monthly `deep-synthesis-YYYY-MM.md` that replaces the current weekly digests with something that actually connects the dots.

### 2. 🔧 Full Daemon + Dashboard Audit in One Pass

**What:** Load `data_collector.py` (7,301 lines) + `write-ai-insights.py` (1,055 lines) + `generate-dashboard.py` (2,679 lines) simultaneously.

**Why this matters:** These three files are tightly coupled but too large to fit in a single Sonnet/Opus session together. Every maintenance fix requires multiple sessions because the agent can't see the full picture.

**What Codex could do:**
- Identify dead code paths, duplicated logic, stale fallback branches
- Trace data flow from collection → insight generation → dashboard rendering end-to-end
- Propose a targeted refactor plan that Opus could then execute in fewer sessions
- Find the root cause of recurring bugs (like the stale insights bleed-through) by seeing both code paths at once

**Estimated savings:** 3-4 Opus sessions per daemon bug → 1 Codex analysis + 1 Opus implementation.

### 3. 💼 Job Search Pattern Analysis

**What:** Load all applications from `~/Documents/CV/Applications/`, all job alert sources, the `application-tracker.md`, interview feedback, and rejection history.

**What Codex could produce:**
- Success/failure correlation: which role types, company sizes, and application methods yield interviews?
- Cover letter effectiveness: compare letter variants against outcomes
- Gap analysis: what skills appear in successful applications that are missing from Jim's CV?
- Timing patterns: do applications sent on certain days/times get more responses?
- A data-backed strategy document: "apply to these types of roles, using this approach, on these days"

**Current state:** This analysis doesn't happen. Each application is ad hoc.

### 4. 🧠 Therapy Transcript Deep Integration

**What:** Load a full Alter therapy transcript (typically 3,000-8,000 words) alongside `mental-health-insights.md`, `what-works.txt`, `patterns.md`, and the past month of journal entries.

**What Codex could produce:**
- Extract homework from the transcript and cross-reference against existing homework tracker
- Identify themes the therapist keeps returning to (persistent patterns Jim may not notice)
- Generate a pre-session brief for Samantha: "Since last session, Jim has [journal evidence]. The homework on [X] shows [progress/regression]."
- Build a therapy arc narrative: what's been worked on, what's improving, what's stuck

**Why this is valuable:** Jim currently self-reports to therapy. Codex could provide an objective evidence layer.

### 5. 🔄 Batch CLAUDE.md Sync + Guardrails Alignment

**What:** Load all three project CLAUDE.md files (HEALTH, WORK, TODO) + `GUARDRAILS.md` (1,412 lines) + `MEMORY.md` files in one pass.

**What Codex could do:**
- Produce a single authoritative diff showing exactly which sections are out of sync
- Generate aligned versions of all three CLAUDE.md files in one output
- Identify contradictions between guardrails and project-specific rules
- Replace the current `sync-claude-md.py` script with a one-shot Codex task that's more thorough

**Current pain:** Drift detection runs but doesn't fix. Each alignment requires a manual session.

### 6. 📊 Weekly Review Automation (Friday One-Shot)

**What:** On Fridays, load the entire week's data in one pass: 7 journal entries + all beads activity + fitness log changes + Streaks CSV + daemon cache + AI insights history.

**What Codex could produce in one call:**
- Complete weekly digest with emotional arc (currently placeholder text)
- Fitness progress report with trend analysis
- Habit streak health assessment
- Wins summary with evidence
- Next-week priorities based on patterns

**Current state:** The weekly digest is generated piecemeal by 4 separate Friday chores. Codex could do it all in one pass with better cross-referencing.

### 7. 🏋️ Fitness Coaching Deep Analysis

**What:** Load `fitness-log.md` + Apple Health exports + AutoSleep data + HealthFit sheets + the past month of relevant journal entries mentioning exercise/anxiety/sleep.

**What Codex could produce:**
- Correlation analysis: does exercise on day N predict better sleep/mood on day N+1?
- Progressive overload tracking: are weights/reps actually increasing week over week?
- Recovery pattern detection: is Jim training when HRV suggests recovery is needed?
- A personalised weekly training recommendation based on all available biometric data

---

## 🏗️ Standalone App — Honest Assessment

### What It Is

A desktop application (macOS first) that gives Jim a dedicated UI for his daily feedback system. Instead of using Claude CLI for everything, he'd open an app that shows:

- **Today view:** morning diary, evening diary, updates, wins, current AI guidance
- **Guidance view:** AI tips sorted by type (pattern/win/signal/connection/todo)
- **Actions view:** complete open loops, mark todos done
- **Beads view:** filter and manage tasks across projects
- **Intervention score:** daily 0-10 anxiety reduction rating with trend chart

### Tech Stack

| Layer | Choice | Assessment |
|-------|--------|------------|
| Desktop shell | Tauri (Rust + WebView) | 🟡 Reasonable but adds Rust build complexity |
| Backend | Python API wrapping existing scripts | ✅ Good — reuses what exists |
| Data | Read from `session-data.json` cache | ✅ Good — no new data layer |
| Auth | Bearer token, LAN-only | ✅ Appropriate for personal use |

**Is Tauri the right call?** It's the modern choice for lightweight desktop apps, but it requires Rust toolchain knowledge for packaging and native features. **Electron would be simpler** (Jim's system is already JavaScript-adjacent via dashboard HTML). However, Tauri produces smaller binaries and better macOS integration.

**Alternative consideration:** A **local web app** (Flask/FastAPI serving the existing dashboard HTML with interactive features) would achieve 80% of the same value with 30% of the effort.

### Complexity Rating: 🔴 High

**Reasoning:**
- 6 API endpoints to implement
- Tauri requires Rust build toolchain + frontend framework (React/Svelte/Vue)
- Safe write policy needs careful implementation (existing scripts weren't designed to be called by an API)
- Error handling, auth, and state management across two languages (Python + Rust)
- Testing surface is large: API + frontend + script integration
- Ongoing maintenance: every daemon/script change could break the API contract

### Time Estimate

| Milestone | Description | Sessions | What Jim Gets |
|-----------|-------------|----------|---------------|
| M1 | API skeleton + auth + read endpoints | 3-4 | Can `curl` today's data from localhost |
| M2 | Tauri shell with Today + Guidance screens | 4-6 | A window that shows what the dashboard shows |
| M3 | Safe write endpoints (complete loops/todos) | 2-3 | Can close items from the app |
| M4 | Intervention score capture + trends | 2-3 | Daily rating with weekly chart |
| M5 | Beads panel with label filtering | 2-3 | Browse/filter beads without CLI |
| M6 | Hardening, logging, packaging | 2-3 | Stable `.app` bundle |
| **Total** | | **15-22 sessions** | Full standalone app |

Each "session" = roughly 1 Opus/Codex interaction of moderate length.

### What Jim Gets at Each Milestone

- **After M1:** Nothing visible. API-only. Useful for testing but not daily use.
- **After M2:** A read-only window. Equivalent to opening `dashboard.html` but slightly nicer. **Marginal gain over status quo.**
- **After M3:** First real value. Can close loops and todos without opening terminal. **This is the minimum viable product.**
- **After M4:** Anxiety tracking becomes frictionless. **Worth it if Jim commits to daily ratings.**
- **After M5:** Full task management without CLI. **Nice-to-have but `bd` already works.**
- **After M6:** Polished experience. **Only matters if Jim uses M1-M5 daily.**

### Recommendation

🟡 **Don't start it yet.** Here's why:

1. **The dashboard already exists.** `dashboard.html` renders in any browser and updates automatically. The app would be a fancier version of something that already works.

2. **The write features are the only new value.** Closing loops and rating anxiety from a GUI instead of CLI. That's a lot of engineering for two buttons.

3. **Maintenance cost is real.** Every daemon change, every script refactor, every cache schema update would need corresponding API updates. Jim's system changes frequently.

4. **Simpler path exists:** Add a "Quick Actions" section to the existing `dashboard.html` with JavaScript buttons that call the completion scripts via a tiny local server. This gets the write functionality (M3 value) in 2-3 sessions, not 15-22.

### The Faster Path

| Step | Effort | Result |
|------|--------|--------|
| Add FastAPI micro-server (3 endpoints) | 1-2 sessions | `POST /complete-loop`, `POST /complete-todo`, `POST /rate-anxiety` |
| Add buttons to `dashboard.html` | 1 session | Click-to-complete from the browser |
| Add intervention rating widget | 1 session | 0-10 slider in the dashboard |
| **Total** | **3-4 sessions** | 80% of standalone app value at 20% of the cost |

---

## 🎯 Recommended Next Actions

### 1. 🟢 Verify Friday Beads on 27 Feb (Low Effort)

Check `~/.claude/logs/sync-recurring-beads.log` on Friday 27 Feb. Confirm 4 new HEALTH beads were created for W09. This proves the recurring system works end-to-end across a week boundary.

### 2. 🟢 Start Using Anxiety Scores (Zero Effort)

The pipeline is ready. Just add `anxiety reduction: X/10` to Diarium diary entries. The daemon will pick it up, cache it, and the weekly digest will report averages. No code changes needed.

### 3. 🟡 Build the FastAPI Micro-Server Instead of Standalone App (Medium Effort)

3-4 sessions to get interactive buttons in the existing dashboard. Skip Tauri entirely. Get 80% of the standalone app's value at 20% of the build cost.

### 4. 🟡 Schedule a Codex Deep Synthesis Session (Medium Effort)

Load all 50 journal entries + therapy context + mental health files in one Codex pass. Produce a `deep-synthesis-2026-02.md` that surfaces patterns Haiku can't see. This is the highest-value use of Codex's large context window.

### 5. 🟡 Run Codex Daemon Audit (Medium Effort)

Load `data_collector.py` (7,301 lines) + `write-ai-insights.py` + `generate-dashboard.py` in one Codex pass. Get a comprehensive refactor plan that Opus can execute in fewer sessions. This would reduce the ongoing maintenance burden.

---

*End of briefing. All source data verified against live system state as of 17:15 GMT, 17 February 2026.*
