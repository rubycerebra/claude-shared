#!/usr/bin/env bash
# UserPromptSubmit — suggest maintenance mode when prompt looks like a fix/quick task
# Fires once per session max. Silent if maintenance mode is already on.

# Skip if maintenance mode already active
[ -f "$HOME/.claude/cache/.maintenance-mode" ] && exit 0

# Fire-once per session
SESSION_ID="${CLAUDE_SESSION_ID:-default}"
FIRED_FILE="/tmp/maint-suggest-${SESSION_ID:0:16}"
[ -f "$FIRED_FILE" ] && exit 0

INPUT=""
if [ ! -t 0 ]; then
    INPUT=$(cat || true)
fi

PAYLOAD="$INPUT" FIRED_FILE="$FIRED_FILE" python3 - <<'PY'
import json, os, sys, re

try:
    payload = json.loads(os.environ.get("PAYLOAD", "") or "{}")
except Exception:
    sys.exit(0)

prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
if not isinstance(prompt, str) or len(prompt.split()) < 3:
    sys.exit(0)

p = prompt.lower()

SIGNALS = r'\b(fix|bug|broken|quick|maintenance|not working|error|patch|tweak|tidy|small change|minor|one thing|just a)\b'
if not re.search(SIGNALS, p):
    sys.exit(0)

# Don't suggest if it's a big creative/feature request
ANTI = r'\b(build|create|new feature|design|implement|plan|architecture|refactor)\b'
if re.search(ANTI, p):
    sys.exit(0)

fired_file = os.environ.get("FIRED_FILE", "")
if fired_file:
    try:
        open(fired_file, "w").write("1")
    except Exception:
        pass

msg = "💡 Maintenance task detected — run `toggle-maintenance-mode.sh on` to reduce token overhead (~2k tokens/turn saved)."
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
PY

exit 0
