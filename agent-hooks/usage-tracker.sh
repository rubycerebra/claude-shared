#!/bin/bash
# Claude Code PostToolUse hook — increments usage counter per active account
# Runs silently after every tool call. Writes to ~/.claude/accounts/usage-tracker.json

TRACKER="$HOME/.claude/accounts/usage-tracker.json"
ACTIVE_FILE="$HOME/.claude/accounts/active-account"
TODAY=$(date +%Y-%m-%d)

ACCOUNT=$(cat "$ACTIVE_FILE" 2>/dev/null || echo "unknown")

# Use python3 for atomic JSON update (jq may not be installed)
python3 -c "
import json, os, sys

tracker_path = '$TRACKER'
account = '$ACCOUNT'
today = '$TODAY'

# Load or create tracker
data = {}
if os.path.exists(tracker_path):
    try:
        with open(tracker_path, 'r') as f:
            data = json.load(f)
    except:
        data = {}

# Reset if date changed
if data.get('date') != today:
    data = {'date': today, 'accounts': {}}

# Increment
accts = data.setdefault('accounts', {})
accts[account] = accts.get(account, 0) + 1

# Write atomically
tmp = tracker_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f)
os.replace(tmp, tracker_path)
" 2>/dev/null

# Hook must exit 0 and not produce output that interferes
exit 0
