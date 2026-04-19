#!/bin/bash
# PostToolUse hook — counts Edit/Write calls per session, nudges for /simplify after threshold
# Only counts Edit and Write tool uses (the ones that change code)

TOOL_NAME="${CLAUDE_TOOL_USE_NAME:-}"
STATE_FILE="$HOME/.claude/cache/simplify-nudge-state.json"

# Only count code-changing tools
case "$TOOL_NAME" in
    Edit|Write|NotebookEdit) ;;
    *) exit 0 ;;
esac

# Plan mode writes are not code — skip counting
INPUT=$(cat 2>/dev/null || true)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [[ "$FILE_PATH" == "$HOME/.claude/plans/"* ]]; then exit 0; fi

python3 -c "
import json, os, time

state_path = '$STATE_FILE'
threshold = 10
nudge_cooldown = 300  # seconds between nudges

state = {}
if os.path.exists(state_path):
    try:
        with open(state_path) as f:
            state = json.load(f)
    except: pass

# Reset if session changed (>30 min gap between edits)
now = time.time()
last_edit = state.get('last_edit', 0)
if now - last_edit > 1800:
    state = {'edit_count': 0, 'last_nudge': 0}

state['edit_count'] = state.get('edit_count', 0) + 1
state['last_edit'] = now

# Nudge at threshold, then every 10 edits after
count = state['edit_count']
last_nudge = state.get('last_nudge', 0)
should_nudge = (
    count >= threshold
    and count % threshold == 0
    and (now - last_nudge) > nudge_cooldown
)

if should_nudge:
    state['last_nudge'] = now
    msg = f'{count} edits this session — consider running /simplify before wrapping up.'
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": f"[NUDGE] {msg}"}}))

tmp = state_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(state, f)
os.replace(tmp, state_path)
" 2>/dev/null

exit 0
