# Data Sources Integration Guide

**Updated:** 2026-01-13
**Status:** ✅ Fully Automated

## Overview

All mental health and productivity data is automatically collected, parsed, and cached by the file watcher daemon running in the mental-health-coach project.

## Automated Data Flow

```
Data Source → File Watcher → Parser → JSON Cache → Commands
```

## Data Sources

### 1. Diarium (Journal)
- **Location:** `~/Library/CloudStorage/GoogleDrive-james.cherry01@gmail.com/My Drive/Diarium/Export/`
- **Format:** `.txt` files
- **Parser:** `.helpers/parse_diarium.py --json`
- **Cache:** `~/.claude-worktrees/mental-health-coach/agitated-gauss/.cache/diarium/YYYY-MM-DD.json`
- **Contains:**
  - Grateful for
  - What would make today great
  - Daily affirmation
  - Morning pages (full text)
  - Mental health keywords (anxiety, therapy, overwhelmed, etc.)
  - Extracted todos with time estimates and priority

### 2. Apple Notes
- **Access:** Via MCP (`mcp-apple-notes`)
- **Key folders:** Daily Notes, Therapy, Todo
- **Search:** Use keywords for recent entries only (avoid full scans)
- **Contains:** Therapy notes (#Therapy tag), journal entries, action items

### 3. Google Calendar
- **Access:** Node.js via googleapis OR MCP after restart
- **Primary calendar:** Tasks (`6b27a967e21edcbe20b3e3f9cce690e1ae67bf6d6d499eca4049ad771ed91cbe@group.calendar.google.com`)
- **Secondary:** Events (`james.cherry01@gmail.com`)
- **Helper scripts:** `/tmp/get_tasks.js`, `/tmp/get_events.js`

### 4. Alter Therapy Transcripts
- **Location:** `~/Library/Application Support/Alter/Transcripts/`
- **Parser:** `.helpers/parse_alter.py`
- **Cache:** `~/.claude-worktrees/mental-health-coach/agitated-gauss/.cache/alter/`
- **Contains:** Dialogue with Samantha Quinn (therapist)

### 5. Streaks App (Habit Tracking)
- **Location:** `~/Library/CloudStorage/GoogleDrive-james.cherry01@gmail.com/My Drive/Streaks Backup/`
- **Format:** CSV exports
- **Parser:** `.helpers/parse_streaks.py`
- **Cache:** `~/.claude-worktrees/mental-health-coach/agitated-gauss/.cache/habits/`
- **Reminder:** Manual export weekly

### 6. Apple Health
- **Location:** `~/Library/CloudStorage/GoogleDrive-james.cherry01@gmail.com/My Drive/Apple Health/`
- **Format:** XML exports
- **Parser:** `.helpers/parse_apple_health.py`
- **Cache:** `~/.claude-worktrees/mental-health-coach/agitated-gauss/.cache/health/`
- **Contains:** Sleep, HRV, steps, active energy, mindful minutes

### 7. Gmail (Therapy Summaries)
- **Access:** Via MCP (`@gongrzhe/server-gmail-autoauth-mcp`)
- **Search for:** Emails from Samantha Quinn
- **Contains:** Therapy session summaries, homework, techniques

## File Watcher Setup

**Location:** `~/.claude-worktrees/mental-health-coach/agitated-gauss/.helpers/file_watcher.py`

**Control:**
- Status: `.helpers/watcher-control.sh status`
- Logs: `.helpers/watcher-control.sh logs`
- Restart: `.helpers/watcher-control.sh restart`

**Launch Agent:** `~/Library/LaunchAgents/com.mentalhealth.watcher.plist`

## Cache Access

**Latest Diarium:**
```bash
cat ~/.claude-worktrees/mental-health-coach/agitated-gauss/.cache/diarium/latest.json
```

**Aggregated Summary:**
```bash
cat ~/.claude-worktrees/mental-health-coach/agitated-gauss/.cache/aggregated.json
```

## Command Integration Rules

### `/plan-day`
1. Read Diarium cache (grateful, intentions, mental state)
2. Fetch Tasks + Events calendars
3. Extract todos from Diarium
4. Check for therapy homework (Apple Notes search or cache)
5. Present MIT options based on context

### `/check-day`
1. Compare current progress vs. scheduled tasks
2. Check mental state from latest Diarium
3. Adjust recommendations based on energy/anxiety

### `/end-day`
1. Review completed vs. planned
2. Prompt for evening Diarium entry
3. Update journal with observations
4. Close all open loops

## Critical Rules

1. **Only check Apple Notes for TODAY and YESTERDAY** - full scans are too slow
2. **Always fetch Tasks calendar first** - it's the primary schedule
3. **Cache is source of truth** - don't re-parse files manually
4. **Watcher handles everything** - new files are processed within 2-5 seconds
5. **Restart Claude Code** - for Google Calendar MCP to load properly

## Shared Files Location

All cross-project data syncs to:
`~/Documents/Claude Projects/claude-shared/`

- `context-bridge.txt` - Current state
- `journal/` - Daily entries
- `patterns.md` - Observed patterns
- `mental-health-insights.md` - Therapy patterns
- `adhd-prompts.txt` - ADHD coaching

---

**Status:** Fully automated. Data flows from sources → cache → commands without manual steps.
