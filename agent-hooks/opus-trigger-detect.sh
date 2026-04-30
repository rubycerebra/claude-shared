#!/usr/bin/env bash
# UserPromptSubmit hook — detects trigger words requiring Opus planning protocol

INPUT=""
if [ ! -t 0 ]; then
    INPUT=$(cat || true)
fi

# Fire-once per session using CLAUDE_SESSION_ID (stable across hook invocations)
# PPID changes each spawn so is useless for session dedup
SESSION_ID="${CLAUDE_SESSION_ID:-${PPID}}"
FIRED_FILE="/tmp/opus-fired-${SESSION_ID:0:16}"
[ -f "$FIRED_FILE" ] && exit 0

PAYLOAD="$INPUT" FIRED_FILE="$FIRED_FILE" python3 - <<'PY'
import json, os, sys, re

payload_str = os.environ.get("PAYLOAD", "") or "{}"
try:
    payload = json.loads(payload_str)
except Exception:
    sys.exit(0)

prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
if not isinstance(prompt, str):
    sys.exit(0)

TRIGGERS = r'\b(debug|fix|broken|error|not working|issue|bug|dashboard|daemon|script|cache|pipeline|automation)\b'
if not re.search(TRIGGERS, prompt.lower()):
    sys.exit(0)

fired_file = os.environ.get("FIRED_FILE", "")
if fired_file:
    try:
        with open(fired_file, 'w') as f:
            f.write("1")
    except Exception:
        pass

msg = "OPUS PROTOCOL: Trigger detected. Spawn Plan agent (model=opus) BEFORE code. Non-negotiable."
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
PY

exit 0
