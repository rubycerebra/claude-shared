# Cross-Project Sync Verification

**Date:** 2026-01-13 17:45

All 3 Claude projects now have **identical** capabilities and data access.

## What's Synced

### ✅ All Projects Have:

1. **Pattern Support System**
   - Full CLAUDE.md with 6 neurological pattern protocols
   - Direct interrupt style
   - Time blindness protection
   - Object permanence support
   - Signal-to-noise detection
   - Completion anxiety management

2. **Helper Scripts** (`.helpers/`)
   - `mcp_poller.py` - Optimized Gmail (2d) + Apple Notes polling
   - `parse_diarium.py` - Morning + evening reflection parsing
   - `parse_alter.py` - Therapy transcript parsing
   - `parse_health.py` - Apple Health CSV parsing (needs fix Friday)
   - `parse_streaks.py` - Habit tracking
   - `file_watcher.py` - Auto-detect Diarium/Health exports
   - `auto-sync.sh` - Git branch syncing
   - `read_cache.py` - Unified cache access

3. **Auto-Sync Hooks** (`.claude/hooks/`)
   - `session-start.sh` - Runs on Claude Code startup
   - Fetches latest remote claude/* branches
   - Merges changes automatically

4. **Cache Infrastructure** (`.cache/`)
   - `aggregated.json` - All parsed data in one place
   - `gmail/job-responses.json` - Job application responses
   - `apple-notes/YYYY-MM-DD.json` - Today's note
   - `diarium/latest.json` - Latest Diarium entry
   - `health/weekly-YYYY-WW.json` - Apple Health weekly data
   - SQLite tracking for deduplication

5. **Shared Data Access**
   - `~/Documents/Claude Projects/claude-shared/wins.md`
   - `~/Documents/Claude Projects/claude-shared/what-works.md`
   - `~/Documents/Claude Projects/claude-shared/reality-check.md`
   - All journal entries, patterns, mental health insights

## Project-Specific Focus

While all projects have the **same data access**, they focus differently:

### 1. Mental Health Coach (`agitated-gauss`)
**Primary Focus:** Pattern detection, reality checks, therapy integration
- Uses reality-check.md actively
- Monitors Apple Health for anxiety signals
- Tracks therapy homework
- Interrupt spirals with evidence

### 2. Todo Life Management (`cranky-lamport`)
**Primary Focus:** Task extraction, time management, calendar integration
- Extracts todos from Diarium morning pages
- Google Calendar as primary source
- Time blindness warnings before suggesting tasks
- Formats todos for Akiflow (task/time/priority)

### 3. Life Assistant (`exciting-sutherland`)
**Primary Focus:** Job search progress, application tracking, daily check-ins
- Gmail job responses (interviews, offers, rejections)
- Application count vs weekly target (3-4/week)
- wins.md accomplishment tracking
- End-of-day reflections from Diarium

## How It Works

1. **Session Start:** Auto-sync hook pulls latest remote changes
2. **Data Pull:** MCP poller runs (Gmail 2d, Apple Note today, conditional #Therapy)
3. **File Watcher:** Monitors Google Drive for new Diarium/Health exports
4. **Parsing:** Helper scripts parse data → `.cache/aggregated.json`
5. **Access:** All projects read same cache + shared files
6. **Pattern Detection:** Any project can detect patterns and interrupt spirals

## Verification Commands

### Check Data Access
```bash
# From any project
python3 .helpers/read_cache.py
cat ~/Documents/Claude\ Projects/claude-shared/wins.md
```

### Check MCP Polling
```bash
# From any project
python3 .helpers/mcp_poller.py
cat .cache/aggregated.json
```

### Check File Watcher
```bash
# From any project
python3 .helpers/file_watcher.py --status
```

### Check Auto-Sync
```bash
# From any project
.helpers/auto-sync.sh
```

## Speed Optimizations

✅ Gmail: Only last 2 days (not 7)
✅ Apple Notes #Therapy: Only on therapy days
✅ MCP Polling: 2-3 queries (not 5+)
✅ File Watcher: Incremental processing (SQLite dedup)

## Git Commits

- **Mental Health Coach** (`agitated-gauss`): Already committed
- **Life Assistant** (`exciting-sutherland`): Commit `937bf3a`
- **Todo Management** (`cranky-lamport`): Commit `79734e5`

## Next Session

When you start any project:
1. Auto-sync will run automatically
2. Latest remote changes merged
3. Data already parsed and cached
4. Pattern protocols active
5. Shared files accessible

**Nothing to manually sync. It just works.**
