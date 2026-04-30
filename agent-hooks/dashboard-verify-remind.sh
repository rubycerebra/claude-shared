#!/usr/bin/env bash
# PostToolUse: Edit|Write — remind about dashboard-verify or cross-project CLAUDE.md sync

INPUT=""
if [ ! -t 0 ]; then
    INPUT=$(cat 2>/dev/null || true)
fi

FILE=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except:
    print('')
" 2>/dev/null || true)

[ -z "$FILE" ] && exit 0

if [[ "$FILE" == *"CLAUDE.md"* ]]; then
    python3 -c "import json; print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':'You just edited a CLAUDE.md file. Check if this change needs mirroring to HEALTH, WORK, and TODO projects (cross-project sync rule).'}}))"
    exit 0
fi

for PATTERN in "api-server.py" "dashboard-app/src" "dashboard.html" "health-live" "session-data.json"; do
    if [[ "$FILE" == *"$PATTERN"* ]]; then
        python3 -c "import json; print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':'MANDATORY: You just edited a dashboard file. Run /dashboard-verify before declaring work complete. Never claim a dashboard fix without API data verification — query /v1/ui/app/today and quote the actual values. Do NOT take screenshots.'}}))"
        exit 0
    fi
done

exit 0
