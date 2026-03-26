# Patterns

Cross-project patterns observed over time. Updated by weekly analysis pipeline + coaching sessions.

<!-- _last_updated: 2026-W10 | _auto_update: update-living-docs.py -->

---

## Current Patterns

### Application Anxiety → Breakthrough Pattern
- Fear blocks action until pressure builds
- Once started, momentum carries through
- Exhaustion follows breakthrough periods
- Need recovery time after pushing through
- **W10 update (2026-03-08):** Confirmed via Chris Milton email — deferred Wed, sent Fri under PDA demand conditions. Resulted in £27/hr freelance confirmed for April. Breakthrough was relational (emerged from meetings) not structured — worth tracking whether Jim can replicate with cold-application paths.

### Hyperfocus Distractions
- Autism-related: gets pulled into fixing things (3D printer, etc.)
- Creates time pressure and self-annoyance
- Pattern: distraction → stress → self-criticism → eventual completion

### Pacing Works
- Therapist's 3-4 applications/week sustainable
- Week 1 completed 4 applications (Rich Mix, BFI, Indigo, LSE)
- Body catches up after pushing - rest is essential

### Open Loops = Anxiety
- Cannot stop thinking about unfinished tasks
- Explicit parking with next steps reduces anxiety
- Needs clear "what happens next" for everything

### Recognition Deficit in Relationship (New: 2026-01-18)
- Feels contributions at home go unrecognised by Janna
- Triggers anger and "not enough" feeling
- Trap: Doing things for recognition = always feeling short-changed
- Reframe: Do things for their own sake, self-acknowledge accomplishments
- Note for therapy: Discuss with Samantha

### "Should" Language Awareness (From Therapy)
- "Should" creates pressure and self-criticism
- Replace with: "It would have been nice to..." or "I can learn from that"
- Not beating ourselves up = making it easier, not harder

### Motion-as-Safety Pattern (New: 2026-02-17)
- When anxiety rises, physical/practical doing ramps up quickly
- Can be adaptive (regulates body) or avoidant (delays priority task)
- Best use: short movement reset, then return to highest-priority task
- Evidence: 2026-02-09 "physical doing to avoid sitting with worry"

### Task Gravity vs Presence (New: 2026-02-17)
- Strong pull toward tidying/fixing when family presence is the stated goal
- Followed by guilt/remorse and repair attempts
- Requires explicit protected "presence blocks" on weekends
- Evidence: 2026-02-14 reflection on choosing tasks over being present

### Social Micro-Bravery Builds Confidence (New: 2026-02-17)
- Small social actions (saying hello, asking for help, shared spaces) repeatedly increase confidence
- Should be counted as genuine wins, not background noise
- Evidence: 2026-02-06 assertive and social wins at work

### System Work as Regulation (New: 2026-02-17)
- Maintenance work is both useful infrastructure and a controllability refuge under stress
- Needs a stop condition to prevent hyperfocus drift
- Evidence: multiple Feb entries naming hyperfocus and system-fixing pull

---


### PDA Demand Spiral (Named: 2026-03-08)
- Any task framed as obligation → autonomic threat response → avoidance → guilt → stronger demand frame → deeper avoidance
- Self-imposed demands ("I should do X") fire the same response as external pressure
- Avoidance disguises as genuine productivity (system building, tidying) — makes it hard to interrupt without shame
- Triggers: "need to", "should", "have to", quota framing, external accountability layers, countdown pressure
- Breaks: reframe as choice, low-demand entry, interest/curiosity angle, genuine full-demand drop (Coco walk)
- Healthy channelling: system design, building structures Jim chose himself — autonomy drive working correctly
- Evidence: motion-as-safety pattern, hyperfocus escalation when job apps pending, freeze states blocking all tasks
- **W10 update (2026-03-09):** First clean override — Chris email sent despite full demand frame active. Sequence: naming (Wed) → rest → action (Fri). Pattern shrank from ~3-day stall to 48h. One data point, not a trend — track next 2 instances.

## Quotes to Remember

> 'two done feels great to get some done, I was too scared to do so until now.' (2026-01-07)

> 'I struggle applying for jobs and seeing things through because I get overwhelmed easily.'

> 'I still seem to finishing the day feeling like I'm missing something. Why is that?' (2026-01-16)

> 'I've looked after both girls, played, made food, tidied everything I can imagine but it's generally not enough for my wife' (2026-01-18)

---

## What Works

1. **One thing at a time** - MIT focus reduces overwhelm
2. **Clear boundaries** - Knowing when to stop (kid care, rest)
3. **Naming patterns** - PDA spiral: naming it shortened stall from days to 48h (W10 evidence)
4. **Relational groundwork before asks** - Chris outcome emerged from meetings, not cold application
5. **Loop closing** - Explicit next steps for everything
6. **Personal tone in outreach** - Conversational, not corporate

---

## Technical Efficiency Patterns

### MCP Usage Rules (External Memory Aid)

**Jim's pattern:** ADHD = pattern amnesia during overwhelm. Needs explicit rules written down.

**Rule:** Use local/free methods first. MCP only when necessary.

**Apple Notes:**
- ❌ Don't use mcp__apple-notes__search_notes (slow, searches all notes)
- ✅ Use AppleScript with folder scope (fast, searches only "Claude" folder)

**Google Calendar:**
- ❌ Don't use MCP for today's events (daemon cache has this, free)
- ✅ Use daemon cache at ~/.claude/cache/session-data.json

**Gmail:**
- ❌ Don't use MCP for recent emails (daemon has last 2 days)
- ✅ Use daemon cache for job application updates

**General principle:**
1. Daemon cache first (free)
2. AppleScript/local scripts second (free)
3. MCP only for CREATE/UPDATE or complex operations

**See:** ~/Documents/Claude Projects/claude-shared/mcp-usage-rules.md for full reference

**Note:** Job search scope moved to WORK project `.plan/findings.md` (2026-01-29)

---

### Job Board Scraping System (2026-01-19)

**Location:** `~/.claude/daemon/job_scrapers.py` + `~/.claude/daemon/scrapers/`

**What it does:**
- Automatically scrapes BFI and Arts Council job boards every 5 minutes
- Filters for London/remote positions only
- Integrates into daemon cache at `~/.claude/cache/session-data.json`

**Key technical solutions:**
- Uses Playwright for JavaScript-rendered sites
- BFI requires iframe detection and search button click
- Duplicate filtering via vacancy ID tracking
- Must use venv Python (`sys.executable`) not system `python3`

**Job sources:**
- BFI: https://bfijobsandopportunities.bfi.org.uk/
- Arts Council: https://www.artscouncil.org.uk/jobs-and-careers/our-vacancies

**Files created:**
- `job_scrapers.py` - Coordinator module
- `scrapers/bfi_scraper.py` - BFI scraper (handles iframe + search button)
- `scrapers/arts_council_scraper.py` - Arts Council scraper
- `install_playwright.sh` - One-command installation
- `README_PLAYWRIGHT.md` - Full documentation

**Installation (if needed on new machine):**
```bash
~/.claude/daemon/install_playwright.sh
```

**Testing:**
```bash
cd ~/.claude/daemon
source venv/bin/activate
python3 job_scrapers.py
```

**Access scraped jobs:**
- Read `~/.claude/cache/session-data.json` → `job_boards` key
- Jobs appear in `/start-day`, `/check-day`, `/end-day` output
- Updated every 5 minutes by daemon

---

*Last updated: 2026-02-17*

---

<!-- weekly-update: 2026-W10 -->
## 2026-W10 — Pattern Verdicts

## 2. Pattern Verification

**Application Anxiety → Breakthrough Pattern:** **Confirmed.** The Chris email — carrying real weight as a concrete step toward income — was deferred on Wednesday evening (reasonably, given masking fatigue) and then sent on Friday. The deferral looked like avoidance in real time, and the demand frame was clearly active, but Jim pushed through it within 48 hours and received a positive response: £27/hr freelance, starting April. This is the pattern working as theorised — anxiety and avoidance precede the action, the action happens anyway, and the outcome is concretely positive. Notably, this breakthrough didn't emerge from a structured job-search process; it emerged from relational groundwork (Wednesday's meetings) followed by a single weighted email. The breakthrough was real, but it was also organic — worth tracking whether Jim can replicate this when the path is less relational and more cold-application.

**Hyperfocus Distractions:** **Confirmed.** The 3D printer Dyson trigger on Saturday is textbook: "I've spent quite a lot of time trying to fix the Dyson trigger… I've made a bit of a mess of the house because of it." Dashboard/system work consumed significant portions of Monday, Tuesday, Wednesday, and Sunday evenings. Jim himself names the mess and the pull: "stop finding new things to do and start tackling the things I need to do."

**Pacing Works:** **Not evidenced.** No applications were attempted, so pacing couldn't be tested. The week's structure was reactive (meetings, sick child, hospital visit) rather than paced. The Chris email success came from a single push, not a paced sequence.

**Open Loops = Anxiety:** **Confirmed.** Thursday's Diarium: "Open loops really play on my mind — it's hard to stop them." The scam became a new open loop. The Chris email was another — and critically, closing that loop on Friday (sending the email) likely contributed to the slight anxiety reduction over the weekend (7→6→6). The bathroom project carried across multiple days. The ta-dah lists on Friday and Saturday are notably long — externalisation working overtime to manage the accumulation.

**Recognition Deficit in Relationship:** **Partially confirmed.** Friday's entry: "Instead of helping her, I took it personally… what can I do to help her? I'm trying, so why are you miserable?" The recognition hunger is visible — Jim is doing things and feeling unseen — though this instance resolved faster than previous ones.

**"Should" Language Awareness:** **Partially confirmed.** Friday: "that's not the right way to look at things. That's being a child, and I should be an adult about it." Ironic: the self-correction itself uses "should." The awareness is genuine but the language hasn't fully shifted.

**Motion-as-Safety Pattern:** **Confirmed.** Thursday: "I'm in the woods now… I'm using movement to get through it." Saturday: jumped straight into doing things upon waking. Movement as regulation is consistently deployed, but the line between regulation and avoidance remains blurred.

**Task Gravity vs Presence:** **Partially confirmed.** Saturday morning spent on Dyson trigger rather than family time. No explicit guilt logged this time, but the pattern is present. Sunday's ta-dah list is entirely task-oriented — no mention of family presence.

**Social Micro-Bravery Builds Confidence:** **Confirmed.** Wednesday's meetings represent significant social bravery, and the initial feeling was positive: "I actually think this might work out for me." The confidence was real, even if masking fatigue followed. The Friday email is a second act of social bravery in the same week — sending a rate-setting message to someone with power over a work opportunity. That Jim did this on the same day he caught his child ego state with Janna suggests Friday was a day of unusually high Adult-state functioning.

**System Work as Regulation:** **Confirmed.** Dashboard work on Monday, Tuesday, Wednesday, Sunday evenings. This is the week's dominant pattern — evening after evening consumed by system refinement. The stop condition is absent.

**PDA Demand Spiral:** **Confirmed — formally named this week (8 March) — and meaningfully overcome in one critical instance.** The spiral was visibly active: the Chris email was deferred on Wednesday, and all the conditions for indefinite avoidance were present (masking fatigue, Thursday's crisis stack, weekend hyperfocus objects). But Jim sent it on Friday — mid-week, under load, without a structured plan forcing his hand. This is important: the PDA spiral was not absent, it was *overridden*. The avoidance of job applications more broadly, and the weekend's absorption into practical tasks and system work, confirm the spiral continued operating on other fronts. The pattern is real and named; what's new is evidence that Jim can move through it on a high-stakes, real-world task when the relational context supports action.

---

## Therapy Techniques in Use

Techniques introduced by Samantha and actively being practised. Auto-updated from session transcripts.

### One Thing Now
- **Source:** Samantha — session 2026-03-12
- **What it is:** When multiple tasks are active or future anxieties compound, stop and identify the single thing to do *right now*. Close everything else. The overwhelm comes from holding all threads simultaneously — this cuts it down to one.
- **Jim's context:** ADHD hyperfocus means Jim often has "10 things on the go." This technique directly counters the paralysis that comes from the gap between what's started and what's finished.
- **W11 (2026-03-12):** Introduced this session. Todoist task created for same-day practice.

### Language Reframing (should/need → could/want to)
- **Source:** Samantha — ongoing, reinforced 2026-03-12
- **What it is:** Replace demand language ("should", "need to", "have to", "must") with autonomous language ("could", "want to", "I'd like to"). PDA demand avoidance is triggered by the framing of obligation, not the task itself.
- **Jim's context:** "Should" re-fires the avoidance loop involuntarily. Reframing is not just semantics — it changes the nervous system response.
- **W11 (2026-03-12):** Partially confirmed active in journals but ironic self-correction still uses "should." Awareness is present, full shift ongoing.

### Lower Goal Thresholds
- **Source:** Samantha — session 2026-03-12
- **What it is:** Set achievable targets deliberately below what feels "right" (e.g. 15 min yoga instead of 30) to build a felt sense of accomplishment. The brain needs to register completion, not effort.
- **Jim's context:** Jim consistently overestimates what he can achieve in a session (ADHD time blindness + effort/output mismatch). Lower thresholds counteract perfectionism-driven avoidance.
- **W11 (2026-03-12):** Newly introduced. Paired with doubling time estimates strategy.

### Consequences Journaling
- **Source:** Samantha — session 2026-03-12
- **What it is:** Before acting on an impulse or hyperfocus pull, write down the consequences: "if I do X now, what happens?" Slows the automatic dive into activity and engages Adult ego state decision-making.
- **Jim's context:** Hyperfocus episodes (e.g. staying up late on computer, bypassing bedtime with Janna) happen without conscious evaluation of cost. This technique inserts a pause.
- **W11 (2026-03-12):** Newly introduced. Todoist task created as reminder to practise.

### Time Blocking
- **Source:** Samantha — session 2026-03-19
- **What it is:** A scheduling technique where specific time periods are designated for particular activities, with a hard stop before a predetermined event (in this case, school pick-up). This helps James enforce boundaries on his coding hyperfocus by using an external constraint that cannot be negotiated away.
- **W12 (2026-03-19):** Auto-added from session transcript.

### Parking
- **Source:** Samantha — session 2026-03-19
- **What it is:** A task management technique where activities are temporarily suspended for short intervals, starting with one minute and gradually increasing duration. This helps James retrain his brain to tolerate stopping and build tolerance for disengaging from compulsive behaviors.
- **W12 (2026-03-19):** Auto-added from session transcript.

### Pomodoro Technique
- **Source:** Samantha — session 2026-03-19
- **What it is:** A time-management method that breaks work into focused intervals (typically 25 minutes) with scheduled short breaks between them. This helps James create structured work sessions with enforced stopping points to prevent hyperfocus-driven sleep deprivation.
- **W12 (2026-03-19):** Auto-added from session transcript.

### Parking Tasks
- **Source:** Samantha — session 2026-03-19
- **What it is:** A technique where one intentionally pauses or 'parks' a task for short intervals starting at one minute, then gradually increasing duration to build tolerance for stopping and stepping away. This helps James retrain his brain to tolerate breaks from compulsive coding by slowly desensitizing his nervous system to task interruption.
- **W12 (2026-03-19):** Auto-added from session transcript.

### PACT
- **Source:** Samantha — session 2026-03-19
- **W13 (2026-03-19):** Auto-added from session transcript.

### PACT
- **Source:** Samantha — session 2026-03-19
- **W13 (2026-03-19):** Auto-added from session transcript.

### Time Blocking
- **Source:** Samantha — session 2026-03-19
- **What it is:** Scheduling specific time blocks for activities with a hard stop point, ensuring other priorities aren't neglected. For James, this prevents compulsive coding from extending past school pickup by creating an external forced stopping point that interrupts the hyperfocus cycle.
- **W13 (2026-03-19):** Auto-added from session transcript.

### Pomodoro Technique
- **Source:** Samantha — session 2026-03-19
- **What it is:** A time management method that breaks work into focused intervals (typically 25 minutes) followed by short breaks, incorporating movement and rest. This helps James interrupt his coding hyperfocus with enforced physical breaks, preventing sleep deprivation and managing anxious energy.
- **W13 (2026-03-19):** Auto-added from session transcript.

### Parking
- **Source:** Samantha — session 2026-03-19
- **What it is:** Setting aside tasks or urges for brief, gradually increasing intervals (starting at one minute) to build tolerance for disengagement. This retrains James's brain to tolerate stopping compulsive activities by slowly expanding his capacity to pause and step away.
- **W13 (2026-03-19):** Auto-added from session transcript.

### Parking tasks
- **Source:** Samantha — session 2026-03-19
- **What it is:** A technique where tasks are temporarily set aside for short intervals (starting with one minute, gradually increasing duration) to build tolerance for stopping. It retrains James's nervous system to accept breaks and reduces anxiety associated with task interruption.
- **W13 (2026-03-19):** Auto-added from session transcript.

---
