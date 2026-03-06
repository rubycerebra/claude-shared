# 🆕 New Features Guide — 17 February 2026

*Written by Claude Sonnet. Updated throughout the day as Codex completed tasks.*
*Last updated: evening. ~12 min read.*

---

## 🔐 1. The Local API Server (Running Right Now)

**What it is:** A tiny web server running silently on your Mac at `http://localhost:8765`.

Instead of opening Terminal to run scripts, anything — a button, the dashboard, a future shortcut — can call this server and it'll do the action for you.

**It starts automatically every time you log in.** You don't need to do anything.

**It's now a unified server** — two separate API files were merged today into one. The full endpoint list:

| Action | Endpoint | What happens |
|--------|----------|-------------|
| Complete a loop | `POST /complete-loop` | Runs `close-loop.py` |
| Mark a todo done | `POST /complete-todo` | Runs `complete-todo.py` |
| Rate today's anxiety | `POST /rate-anxiety` | Saves 0–10 score to cache |
| Get today's data | `GET /v1/today` | Returns loops, todos, guidance, score |
| Get diary fields | `GET /v1/diary` | All Diarium fields for today |
| List beads | `GET /v1/beads?project=TODO` | Filtered bead list |
| Refresh cache | `POST /v1/refresh` | Triggers daemon update |

**The dashboard Quick Actions panel is live.** Complete loops, mark todos done, and rate your anxiety directly from the browser. No Terminal needed.

**Your token** (keep this private): `~/.claude/config/api-token.txt`

---

## 📊 2. The Anxiety Relief Score (0–10)

**What it measures:** Not how anxious you *are* — how much relief you got from your day.

- **0** = Nothing helped. Anxiety stayed or worsened.
- **5** = Neutral. Some relief, nothing dramatic.
- **10** = Real relief. You feel noticeably better than you started.

**How to submit it:** Use the slider in the Quick Actions panel on your dashboard. Or tell me at the end of any session — *"anxiety was a 7 today"* — and I'll submit it for you.

**Where you'll see it:**
- **Today's score** — shown on the dashboard alongside the slider ✅
- **Weekly average** — now displayed on the dashboard as a trend ✅
- **Friday digest** — your week's average included in the weekly review

**What it does over time:** Over months, the system will see correlations — weeks with yoga 3x score higher, weeks without routine score lower. The pipeline is fully instrumented. It just needs your input.

---

## 🗓️ 3. Friday Weekly Review — One Script, Not Four Tasks

**What it does:** Previously, Fridays had 4 separate chore beads. Now one script does all of it in a single pass. ✅ Validated and working.

**Script:** `~/.claude/scripts/friday-weekly-review.py`

**What it reads:**
- 7 days of journal entries
- All beads activity this week across 3 projects
- Fitness log for the week
- Streaks CSV
- Daemon cache (steps, HRV, sleep, exercise)
- Anxiety reduction scores you've submitted

**What it produces:**
- `weekly-digest-YYYY-WNN.md` in `claude-shared/`
- Emotional arc for the week
- Fitness numbers (actual, not vague)
- Habit streak health
- Wins summary with evidence
- Average anxiety score for the week
- Next week priorities

**Your 4 Friday chore beads still auto-create** — but they point to running this one script. The recurring bead system handles it automatically.

**Where you'll see it:** `claude-shared/weekly-digest-YYYY-WNN.md`. Claude will surface it at Monday session start.

---

## 🧠 4. Deep Journal Synthesis — Monthly, Not Daily

**What it is:** A monthly document that reads ALL your journal entries from the past month simultaneously — something Haiku physically can't do because it only sees one day at a time.

**February's synthesis:** Already at `claude-shared/deep-synthesis-2026-02.md` *(9KB — worth reading tonight)*

**What it contains:**
- Your full emotional arc for February — turning points, lows, highs
- Which patterns in `patterns.md` are confirmed by evidence (not assumed)
- Which therapy homework items appear in journals (and which are being avoided)
- Things recurring that weren't in your patterns file — now added
- Quotes from your own writing you should hear regularly
- Your best insights to yourself, captured

**How it fits into your day-to-day:**
- **Session brief** — a 3-line summary of the current month's synthesis now appears in your session brief at the start of every session ✅ Claude will see it automatically.
- **Spirals** — when you're catastrophising, Claude references it: *"your February synthesis shows this is a recurring pattern on high-stakes days, not a crisis"*
- **Monthly generation** — Codex produces a new one at the start of each month

---

## 💼 5. Job Search Strategy Document

**File:** `claude-shared/JOB-SEARCH-STRATEGY-2026-02-17.md`

Codex loaded your full CV, all applications, outcomes, and job alerts and produced a data-backed strategy.

**Three new WORK beads from the analysis — these are your next actions:**
- **[WORK-kh5](http://localhost:3000/#/issues?issue=WORK-kh5)** — Apply to 3 high-fit roles this week (≥£35k, remote/hybrid, direct profile match)
- **[WORK-vf3](http://localhost:3000/#/issues?issue=WORK-vf3)** — Follow up: Vertigo, SOAS, National Archives, BFI — update tracker dates
- **[WORK-chn](http://localhost:3000/#/issues?issue=WORK-chn)** — Tighten 3 CV variants with quantified outcomes

Read the strategy doc tonight. Those 3 beads are your job search week.

---

## 🧘 6. Therapy Brief — Now Automatic

**What it does:** Generates a 1-page brief for Samantha before each therapy session. Evidence-based, not self-report.

**It now triggers automatically.** ✅ When your calendar has a therapy event (anything matching "therapy", "Samantha", "counselling"), the daemon detects it and generates the brief at session start. You'll see it in your morning readout.

**What it reads:**
- Past month of journal entries
- `mental-health-insights.md` (current homework, patterns, techniques)
- `patterns.md`

**What it produces:**
- What happened since last session (journal evidence)
- Homework progress (what appears in journals, what doesn't)
- Current emotional patterns

**Output:** `HEALTH/therapy-brief-YYYY-MM-DD.md` — one per session day.

**Manual run:** `python3 ~/.claude/scripts/generate-therapy-brief.py`

---

## 📋 7. After Therapy — Spark Capture ✅ BUILT

**What it does:** After each Samantha session, captures your Spark AI summary directly into the day's journal under `## Therapy`. No Claude session needed.

**How to use it:**
1. Open Spark app → copy your session summary
2. Run: `~/.claude/scripts/spark-therapy.sh`
3. Done — summary written to `journal/YYYY-MM-DD.md` under `## Therapy`

**Notes:**
- Reads from clipboard automatically — just copy, run, done
- If you have the text in a file or want to pass it directly: `python3 ~/.claude/scripts/capture-therapy-spark.py --date 2026-02-17 "your summary here"`
- Wrong day? Pass the date: `~/.claude/scripts/spark-therapy.sh 2026-02-16`
- If `## Therapy` already exists in the journal, it replaces it cleanly (no duplicates)

**Automation level:** Manual trigger. You run it after therapy. No daemon can know when Spark is ready — this one is intentionally yours to run.

**Alter fallback:** If Spark isn't available, tell Claude the summary during the session — it'll write it for you.

---

## 🏋️ 8. Fitness Coaching Analysis

**File:** `HEALTH/docs/analysis/fitness-analysis-2026-02.md`

Codex produced a coaching report from your fitness log, Apple Health data, and journal entries.

**What it covers:**
- Progressive overload tracking (are your lifts actually going up?)
- Exercise vs. mood correlation
- Sleep-exercise relationship
- A/B split assessment
- Next 4 weeks progression targets — specific numbers

**Where you'll see it:** Read the file. Claude references it when coaching your morning workouts.

**Going forward:** New fitness analysis generated monthly as part of Friday one-shot review.

---

## 🧭 9. Neuro Command Centre — One Place for Everything

**What it is:** A plain-language command entrypoint that replaces knowing long script paths.

**Quick reference doc:** `~/Documents/Claude Projects/claude-shared/NEURO-QUICK-COMMANDS.md`

### The commands

| Command | What it does | Automation level |
|---------|-------------|-----------------|
| `neuro-ops.sh status` | Daemon ✅/❌, API ✅/❌, cache age, open bead counts, next best action | **Manual** — run when you want a snapshot |
| `neuro-ops.sh refresh` | Calls `/v1/refresh` → daemon reruns → regenerates dashboard | **Manual** — when dashboard looks stale |
| `neuro-ops.sh open day` | Regenerates + opens dashboard in day focus mode | **Manual** — your shortcut to the dashboard |
| `neuro-ops.sh open morning` | Morning focus mode | **Manual** |
| `neuro-ops.sh open evening` | Evening focus mode | **Manual** |
| `neuro-ops.sh open day --low-stim` | Low-stimulation visual mode (less colour) | **Manual** |
| `morning-start.sh` | Runs: status → refresh → open morning. All three in one go | **Manual trigger, automated sequence** |
| `morning-start.sh --low-stim` | Same but with low-stim dashboard | **Manual trigger** |

### Optional aliases (add once, use forever)
Add these to `~/.zshrc`:
```bash
alias nops='~/.claude/scripts/neuro-ops.sh'
alias nstatus='~/.claude/scripts/neuro-ops.sh status'
alias nrefresh='~/.claude/scripts/neuro-ops.sh refresh'
alias nmorning='~/.claude/scripts/neuro-ops.sh open morning'
alias nday='~/.claude/scripts/neuro-ops.sh open day'
alias nevening='~/.claude/scripts/neuro-ops.sh open evening'
```
Then: `source ~/.zshrc` once. After that `nmorning` opens your dashboard.

### Manual close (only if an item is missing)

The dashboard Quick Actions panel has buttons to close loops and mark todos done. This is the **manual escape hatch** — only use it when an item didn't auto-close.

**Normal path (preferred):**
- Tell Claude "done", "sorted", "that's done" → Claude runs `close-loop.py` automatically

**Manual close (use when that didn't happen):**
- Open dashboard → Quick Actions → press the ✓ button next to the loop/todo
- This calls the API directly: `POST /complete-loop` or `POST /complete-todo`
- Use this for items you completed offline, without telling Claude

The label "only if an item is missing" means: if you expect to see a loop in the list but it's not there, you can add and close it from the dashboard without starting a Claude session.

---

## 🔧 11. Daemon Refactor Plan

**File:** `claude-shared/DAEMON-REFACTOR-PLAN-2026-02-17.md`

Codex loaded all 11,000+ lines of your three core system files simultaneously and produced:
- Dead code to remove
- Duplicated logic to consolidate
- Root cause of stale insights bug (now fixed ✅)
- Prioritised implementation order for future Opus maintenance

**You don't need to do anything.** It's a map for future system sessions — means fixes take fewer sessions because the diagnosis is already done.

---

## 📋 12. CLAUDE.md Sync

All 3 project CLAUDE.md files now aligned. Removed duplicate Model Selection blocks, fixed stale file paths, updated MEMORY.md files. Claude across all projects now follows consistent rules. ✅

---

## 🗺️ How Everything Fits Into Your Day

```
MORNING
  └── start-day shows: journal insights, calendar, fitness coaching
  └── If therapy today → brief auto-generated and shown
  └── Monthly synthesis summary in session brief (always available)

DURING DAY
  └── Dashboard: complete loops/todos with one click
  └── No Terminal needed for routine actions

EVENING
  └── Rate anxiety 0-10 via dashboard slider
  └── Today's score + weekly average shown on dashboard
  └── Diarium entry feeds tomorrow's insights

AFTER THERAPY
  └── ✅ Copy Spark summary → run spark-therapy.sh → written to journal ## Therapy
  └── Fallback: tell Claude, it writes it for you

FRIDAY
  └── friday-weekly-review.py runs automatically
  └── Weekly digest: emotional arc, fitness, habits, anxiety average, priorities

MONTHLY (start of month)
  └── Codex: deep synthesis of all journal entries
  └── deep-synthesis-YYYY-MM.md generated
  └── patterns.md updated
  └── 3-line summary in every session brief going forward
```

---

## ⏳ Remaining Open Beads (For Your Awareness)

These are tracked — Codex or Claude will pick them up. You don't need to action them:

| Bead | What | Priority |
|------|------|----------|
| [HEALTH-wod](http://localhost:3000/#/issues?issue=HEALTH-wod) | ~~Spark → journal ## Therapy capture~~ ✅ Done | — |
| [TODO-4a7](http://localhost:3000/#/issues?issue=TODO-4a7) | ~~API server merge~~ ✅ Done | — |
| [TODO-kes](http://localhost:3000/#/issues?issue=TODO-kes) | ~~Validate Friday review script~~ ✅ Done | — |
| [TODO-ncy](http://localhost:3000/#/issues?issue=TODO-ncy) | ~~Anxiety score on dashboard~~ ✅ Done | — |
| [HEALTH-5up](http://localhost:3000/#/issues?issue=HEALTH-5up) | ~~Deep synthesis in session brief~~ ✅ Done | — |
| [HEALTH-bx3](http://localhost:3000/#/issues?issue=HEALTH-bx3) | ~~Therapy brief auto-trigger~~ ✅ Done | — |
| [TODO-nf6](http://localhost:3000/#/issues?issue=TODO-nf6) | Dashboard Refresh button (uses /v1/refresh) | P3 |

**Your only active job search beads:**
- [WORK-kh5](http://localhost:3000/#/issues?issue=WORK-kh5) — Apply to 3 roles this week
- [WORK-vf3](http://localhost:3000/#/issues?issue=WORK-vf3) — Follow up pending applications
- [WORK-chn](http://localhost:3000/#/issues?issue=WORK-chn) — Tighten CV variants

---

*All output files from today's Codex session:*
- `~/Documents/Claude Projects/claude-shared/` — job strategy, journal synthesis, refactor plan
- `~/Documents/Claude Projects/HEALTH/` — fitness analysis, therapy brief
- `~/.claude/scripts/` — api-server.py (unified), friday-weekly-review.py, generate-therapy-brief.py

*Last updated: 17 February 2026 — night (Spark capture ✅, neuro-ops ✅, manual close explained)*
