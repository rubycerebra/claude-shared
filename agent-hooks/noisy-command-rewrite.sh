#!/usr/bin/env bash
# PreToolUse hook — rewrite noisy commands through compact-command-output.py
set -euo pipefail

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat || true)
fi

PAYLOAD="$INPUT" python3 - <<'PY'
import json
import os
import re
import shlex

try:
    payload = json.loads(os.environ.get("PAYLOAD", "") or "{}")
except Exception:
    raise SystemExit(0)

command = payload.get("tool_input", {}).get("command", "")
if not isinstance(command, str) or not command.strip():
    raise SystemExit(0)
if "compact-command-output.py" in command:
    raise SystemExit(0)

patterns = [
    r"(^|\s)python3\s+-m\s+pytest\b",
    r"(^|\s)pytest\b",
    r"(^|\s)npm\s+test\b",
    r"(^|\s)npm\s+run\s+(lint|build|test)\b",
    r"(^|\s)git\s+log\b",
    r"(^|\s)git\s+diff\b",
    r"(^|\s)cargo\s+test\b",
]
if not any(re.search(pattern, command) for pattern in patterns):
    raise SystemExit(0)

wrapper = os.path.join(os.path.expanduser("~"), ".claude", "scripts", "compact-command-output.py")
rewritten = f"python3 {shlex.quote(wrapper)} -- {command}"
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "Noisy command routed through compact output wrapper",
        "updatedInput": {
            "command": rewritten,
        },
    }
}))
PY

exit 0
