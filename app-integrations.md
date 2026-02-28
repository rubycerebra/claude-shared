# App Integrations for Mental Health Tracking

This document tracks how to access data from various mental health and habit tracking apps.

---

## Streaks (Habit Tracker)

**Status:** Integration needed

**Possible approaches:**
1. **Manual export** - Check app Settings → Export data
2. **iCloud sync** - Check if Streaks syncs to iCloud Drive
3. **Shortcuts** - Create Apple Shortcut to extract streak data

**What to track:**
- Daily habit completions
- Current streak lengths
- Patterns (what days/times habits are completed)
- Missed days and triggers

**Next steps:**
- Check Streaks app for export functionality
- Investigate if Streaks has an API or Shortcuts actions
- Consider manual daily logging if no automation available

---

## Finch (Mental Health Companion)

**Status:** Integration needed

**Possible approaches:**
1. **Manual export** - Check app Settings → Export data
2. **Screenshots** - If no export, use screenshots + OCR
3. **Manual logging** - Daily check-in notes

**What to track:**
- Mood check-ins
- Goals completed
- Reflections and journal entries
- Energy levels
- Self-care activities

**Next steps:**
- Check Finch app Settings for export functionality
- Check if Finch syncs to iCloud or has web interface
- Consider manual daily summary if no automation available

---

## Integration Priority

For ADHD/anxiety management, prioritise:
1. **Apple Health** (✅ MCP configured) - Sleep, HRV, mindful minutes
2. **Diarium** (✅ Parser exists) - Morning gratitude, evening Ta-Dah list
3. **Alter** (✅ Parser exists) - Therapy transcripts
4. **Apple Notes** (✅ MCP configured) - #Therapy notes, daily journal
5. **Streaks** (⏳ Pending) - Habit consistency
6. **Finch** (⏳ Pending) - Mood tracking

---

## Automation Ideas

### Apple Shortcuts Workflow
Create a daily shortcut that:
1. Pulls today's completed Streaks
2. Gets Finch mood rating
3. Exports to text file in `~/Documents/Claude Projects/claude-shared/daily-data/`
4. Runs automatically at 9pm each night

### Manual Logging Alternative
If automation isn't possible:
- Add `/log-habits` slash command
- Prompt for Streaks completion count and Finch mood
- Store in daily journal with timestamp
- Takes 30 seconds vs 5 minutes of manual export

---

**Last updated:** 2026-01-12
