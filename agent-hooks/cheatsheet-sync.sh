#!/usr/bin/env bash
# cheatsheet-sync.sh — PostToolUse hook: syncs Claude cheatsheet Apple Note
# when a command file in ~/.claude/commands/ is written or edited.
set -euo pipefail

COMMANDS_DIR="$HOME/.claude/commands"

# PostToolUse passes tool input as JSON on stdin
INPUT=$(cat)

# Extract file_path from Write/Edit tool input
FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
# Write uses file_path; Edit uses file_path
print(d.get('file_path', ''))
" 2>/dev/null || true)

# Only proceed if the file is in the commands directory
if [[ -z "$FILE_PATH" ]] || [[ "$FILE_PATH" != "$COMMANDS_DIR"* ]]; then
    exit 0
fi

# Run sync in background so it doesn't block the hook
python3 "$HOME/.claude/scripts/sync-cheatsheet-note.py" --force \
    >> "$HOME/.claude/logs/cheatsheet-sync.log" 2>&1 &

exit 0
