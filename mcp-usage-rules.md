# MCP Usage Rules

**CRITICAL: Use local/free methods first. MCP only when necessary.**

---

## Rule: Avoid MCP When Free Alternatives Exist

**Why:** MCP calls cost tokens. Local scripts are free and often faster.

**Jim's reminder:** "I'm asking you to refrain from using MCP if there is a free, faster way locally that doesn't cost tokens. Only use MCP for editing, deeper insights."

---

## Apple Notes: Use AppleScript, Not MCP

**❌ DON'T:**
```
mcp__apple-notes__search_notes  # Slow - searches ALL notes
mcp__apple-notes__list_notes    # Slow - lists ALL notes
```

**✅ DO:**
```bash
# Fast - folder-specific AppleScript
osascript <<'EOF'
tell application "Notes"
    set claudeFolder to folder "Claude"
    repeat with aNote in notes of claudeFolder
        if name of aNote contains "Search Term" then
            # Found it!
        end if
    end repeat
end tell
EOF
```

**When to use MCP for Apple Notes:**
- Creating new notes (mcp__apple-notes__create_note)
- Complex updates requiring structure parsing
- Initial folder setup

**When NOT to use MCP:**
- Searching for notes (use AppleScript with folder scope)
- Reading note content (use AppleScript)
- Simple updates (use AppleScript)

---

## Google Calendar: Daemon Cache, Not MCP

**❌ DON'T:**
```
mcp__google-calendar__list-events  # Costs tokens, daemon already has this
```

**✅ DO:**
```python
# Read from daemon cache (free)
import json
cache = json.load(open('~/.claude/cache/session-data.json'))
events = cache['calendar']['events']
```

**When to use MCP for Calendar:**
- Creating events (mcp__google-calendar__create-event)
- Updating events (mcp__google-calendar__update-event)
- Complex queries not in cache

**When NOT to use MCP:**
- Reading today's events (daemon has this)
- Checking free/busy (daemon has this)

---

## Gmail: Daemon Cache for Recent, MCP for Actions

**❌ DON'T:**
```
mcp__gmail__search_emails for recent emails  # Daemon has last 2 days
```

**✅ DO:**
```python
# Read from daemon cache (free) for last 2 days
cache['gmail']['recent']  # Job application updates
```

**When to use MCP for Gmail:**
- Sending emails
- Complex searches beyond last 2 days
- Modifying labels
- Creating filters

**When NOT to use MCP:**
- Checking recent job application emails (daemon has this)

---

## File Operations: Always Use Local Tools

**❌ DON'T:** Look for MCP file tools

**✅ DO:**
```bash
# Read, Write, Edit, Glob, Grep - always use these
Read file_path
Write file_path content
Edit file_path old new
Glob pattern
Grep pattern
```

---

## General Principle

**Ask yourself:**
1. Is this data already in daemon cache? → Use cache (free)
2. Can AppleScript do this? → Use AppleScript (free)
3. Can local Python/Bash do this? → Use local (free)
4. Do I need to CREATE/UPDATE something? → Consider MCP
5. Do I need deep insight requiring AI? → Consider MCP

**MCP is for:**
- Creating/updating external data (calendar events, notes, emails)
- Complex operations requiring structured API access
- Actions that local scripts can't handle

**MCP is NOT for:**
- Reading data (use cache or local scripts)
- Searching (use local scripts with folder/scope limits)
- Anything the daemon already provides

---

## Memory Update

**Pattern recognized:** Jim has ADHD - reminders about efficiency are important because:
- Executive function challenges = forgetting best practices
- Pattern amnesia during overwhelm = reverting to inefficient methods
- Need explicit rules written down = external memory aid

**Action:** This file serves as external memory. Reference it when making decisions about MCP vs local tools.
