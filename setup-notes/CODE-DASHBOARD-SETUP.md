# Dashboard Trigger Setup for Claude Code

> Legacy note: this document describes the old HTML dashboard trigger flow. The primary dashboard is now the API app at `http://127.0.0.1:8765/app`.

Copy this prompt to your Code session to set up dashboard triggers.

---

## Prompt to paste into Code:

```
I have a visual dashboard app at `/app` that reads from the API/cache. I only want to use the old HTML trigger flow when explicitly regenerating the deprecated snapshot.

**Files already created:**
- `~/Documents/Health/dashboard-app/` - React dashboard app source
- `~/.claude/scripts/api-server.py` - serves the dashboard at `/app`
- `~/Documents/Claude Projects/claude-shared/trigger-dashboard.sh` - deprecated legacy HTML snapshot generator

**What I need:**

1. **Add to `/end-day` command:**
   After the session closes, run:
   ```bash
   ~/Documents/Claude\ Projects/claude-shared/trigger-dashboard.sh
   ```
   This opens my visual daily summary in the browser.

2. **Add to `/check-day` command:**
   Same trigger - opens dashboard to see current progress visually.

3. **Add to `/start-day` command:**
   After the daemon has pulled fresh data (wait ~5 seconds for cache to update), run the trigger.
   Maybe add a `sleep 5` before calling the script to ensure fresh data.

**The flow:**
- Code pulls data → daemons update context files
- Trigger script runs → reads context files → generates HTML → opens browser
- I see a beautiful visual dashboard with charts, habit streaks, calendar, etc.

Please update the relevant slash commands to include these triggers. The script already handles everything - just needs to be called at the right time.
```

---

## What the triggers do:

| Command | When dashboard opens |
|---------|---------------------|
| `/start-day` | After 5s delay (data needs to load first) |
| `/check-day` | Immediately (data already loaded) |
| `/end-day` | At session close (final summary) |

---

## Manual trigger (Raycast):

The `open-dashboard.sh` script is ready for Raycast:
```bash
cp ~/Documents/Claude\ Projects/claude-shared/open-dashboard.sh ~/path/to/raycast/scripts/
```

Then search "Open Daily Dashboard" in Raycast anytime.
