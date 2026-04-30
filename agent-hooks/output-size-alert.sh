#!/bin/bash
# PostToolUse hook — monitors Bash output size, nudges for RTK when output is large
# Thresholds: 15K chars (nudge), 30K chars (warning), 200K cumulative (budget alert)

TOOL_NAME="${CLAUDE_TOOL_USE_NAME:-}"

# Only process Bash tool output
case "$TOOL_NAME" in
    Bash) ;;
    *) exit 0 ;;
esac

INPUT=$(cat 2>/dev/null || true)
[ -z "$INPUT" ] && exit 0

STATE_FILE="/tmp/output-budget-${PPID}.json"

# Write input to temp file to avoid shell escaping issues with large JSON
TMPINPUT=$(mktemp /tmp/hook-input-XXXXXX.json)
printf '%s' "$INPUT" > "$TMPINPUT"

python3 -c '
import json, os, sys, time

state_path = sys.argv[1]
input_path = sys.argv[2]

try:
    with open(input_path) as f:
        data = json.load(f)
except Exception:
    sys.exit(0)
finally:
    try:
        os.unlink(input_path)
    except Exception:
        pass

resp = data.get("tool_response", data.get("tool_result", {}))
if isinstance(resp, str):
    output_text = resp
elif isinstance(resp, dict):
    output_text = resp.get("stdout", "") or resp.get("output", "") or resp.get("content", "")
    stderr = resp.get("stderr", "")
    if stderr:
        output_text = (output_text or "") + stderr
else:
    sys.exit(0)

if not output_text:
    sys.exit(0)

char_count = len(output_text)

state = {}
if os.path.exists(state_path):
    try:
        with open(state_path) as f:
            state = json.load(f)
    except Exception:
        pass

now = time.time()
last_ts = state.get("last_timestamp", 0)
if now - last_ts > 1800:
    state = {"cumulative_chars": 0, "last_alert_cumulative": 0, "command_count": 0}

state["cumulative_chars"] = state.get("cumulative_chars", 0) + char_count
state["command_count"] = state.get("command_count", 0) + 1
state["last_timestamp"] = now

cumulative = state["cumulative_chars"]
last_alert_cum = state.get("last_alert_cumulative", 0)

alerts = []

if char_count > 30000:
    tokens_est = char_count // 4
    alerts.append(
        "\U0001f6a8 CRITICAL: {:,} chars of tool output (~{:,} tokens). "
        "This is budget-harmful. Use RTK filtered commands.".format(char_count, tokens_est)
    )
elif char_count > 15000:
    tokens_est = char_count // 4
    alerts.append(
        "\u26a0\ufe0f Large output consumed ({:,} chars, ~{:,} tokens). "
        "Consider RTK equivalents: `rtk read`, `rtk grep`, `rtk test`, `rtk err`.".format(char_count, tokens_est)
    )

if cumulative > 200000 and (cumulative - last_alert_cum) > 100000:
    total_k = cumulative // 1000
    alerts.append(
        "\U0001f6a8 SESSION OUTPUT BUDGET: {}K chars consumed by Bash output this session. "
        "Consider shorter commands.".format(total_k)
    )
    state["last_alert_cumulative"] = cumulative

try:
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, state_path)
except Exception:
    pass

if alerts:
    msg = " | ".join(alerts)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg
        }
    }
    print(json.dumps(result))
' "$STATE_FILE" "$TMPINPUT" 2>/dev/null

exit 0
