# Patterns

Cross-project patterns observed over time. Updated automatically by coaching sessions.

---

## Current Patterns

### Application Anxiety → Breakthrough Pattern
- Fear blocks action until pressure builds
- Once started, momentum carries through
- Exhaustion follows breakthrough periods
- Need recovery time after pushing through

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

## Quotes to Remember

> 'two done feels great to get some done, I was too scared to do so until now.' (2026-01-07)

> 'I struggle applying for jobs and seeing things through because I get overwhelmed easily.'

> 'I still seem to finishing the day feeling like I'm missing something. Why is that?' (2026-01-16)

> 'I've looked after both girls, played, made food, tidied everything I can imagine but it's generally not enough for my wife' (2026-01-18)

---

## What Works

1. **One thing at a time** - MIT focus reduces overwhelm
2. **Clear boundaries** - Knowing when to stop (kid care, rest)
3. **Therapist pacing** - 3-4 per week is sustainable
4. **Personal tone in applications** - Conversational, not corporate
5. **Loop closing** - Explicit next steps for everything

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
