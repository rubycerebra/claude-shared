#!/usr/bin/env bash
# timer-suspend-detect.sh — Auto-suspend session timer when user says it's ok
# Detects phrases like "suspend timer", "disable timer", "timer off", "focus mode"

PROMPT=$(jq -r '.prompt // ""' 2>/dev/null)

if echo "$PROMPT" | grep -qiE '(suspend.timer|disable.timer|timer.off|pause.timer|focus.mode|skip.breaks?|no.breaks?|timer.ok|ok.*timer|it.?s ok|its ok)'; then
    bash /Users/jamescherry/.claude/scripts/timer-suspend.sh 4 2>/dev/null
    python3 -c "
import json, sys
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': '[TIMER] Session timer suspended for 4 hours at your request.'}}))
"
fi

exit 0
