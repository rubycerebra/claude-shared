#!/usr/bin/env bash
# circuit-breaker — PreToolUse hook that blocks wasteful tool patterns.
# Tracks per-session tool usage and blocks:
#   1. Same file read 2+ times -> deny
#   2. 5+ consecutive reads without writes -> warn
#   3. Same bash command attempted 3+ times -> deny
#
# State: /tmp/circuit-breaker-<session-hash>.json
# Session hash: composite of PPID + start-time + cmdline + SSE port + PWD
# so sibling Claude sessions in the same workspace get distinct state files.

# Fail gracefully — never block tool execution on hook failure
trap 'exit 0' ERR

if ! command -v python3 &>/dev/null; then
  exit 0
fi

TOOL_NAME="${CLAUDE_TOOL_USE_NAME:-}"
if [ -z "$TOOL_NAME" ]; then
  exit 0
fi

# Opportunistic cleanup: remove state files older than 1 day
find /tmp -maxdepth 1 -name 'circuit-breaker-*.json' -mtime +1 -delete 2>/dev/null || true

# Build a composite session key that distinguishes sibling Claude sessions
# sharing the same PPID and PWD (e.g. two windows in same VSCode workspace).
# Each Claude binary has a distinct PID; they also listen on distinct SSE ports.
_PPID_LSTART=$(ps -o lstart= -p "$PPID" 2>/dev/null | tr -s ' ')
_PPID_CMD=$(ps -o command= -p "$PPID" 2>/dev/null)
_PPID_ENV=$(ps eww -p "$PPID" 2>/dev/null \
  | grep -oE 'CLAUDE_CODE_SSE_PORT=[0-9]+|CLAUDE_CODE_ENTRYPOINT=[^ ]+|TERM_SESSION_ID=[^ ]+' \
  | sort | tr '\n' '|')
_SESSION_RAW="${PPID}|${_PPID_LSTART}|${_PPID_CMD}|${_PPID_ENV}|${PWD}"
_SESSION_KEY=$(printf '%s' "$_SESSION_RAW" | shasum -a 256 2>/dev/null | cut -c1-16)
# Fallback if shasum unavailable
_SESSION_KEY="${_SESSION_KEY:-${PPID}_fallback}"
STATE_FILE="/tmp/circuit-breaker-${_SESSION_KEY}.json"

# Pass tool name and state file path as argv; read hook input from stdin in Python
# with a SIGALRM timeout so a hung stdin never blocks tool execution.
python3 -c "
import json, os, signal, sys

def main():
    tool_name = sys.argv[1]
    state_file = sys.argv[2]

    # --- timeout-guarded stdin read ---
    raw_input = ''
    def _timeout(_sig, _frm):
        sys.exit(0)
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(3)
    try:
        raw_input = sys.stdin.buffer.read().decode('utf-8', errors='replace')
    finally:
        signal.alarm(0)

    try:
        input_data = json.loads(raw_input)
        tool_input = input_data.get('tool_input', {})
    except (json.JSONDecodeError, TypeError):
        return

    state = {'file_reads': {}, 'consecutive_reads': 0, 'bash_retries': {}}
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    state.setdefault('file_reads', {})
    state.setdefault('consecutive_reads', 0)
    state.setdefault('bash_retries', {})

    decision = None

    if tool_name in ('Read', 'Grep', 'Glob'):
        path = None
        if tool_name == 'Read':
            path = tool_input.get('file_path')
        elif tool_name in ('Grep', 'Glob'):
            path = tool_input.get('path')

        if path:
            count = state['file_reads'].get(path, 0) + 1
            state['file_reads'][path] = count
            if count >= 2:
                decision = {
                    'type': 'deny',
                    'reason': 'You already read ' + path + ' ' + str(count - 1) + ' time(s) this session. Use the content you already have.'
                }

        state['consecutive_reads'] = state['consecutive_reads'] + 1

        if decision is None and state['consecutive_reads'] >= 5:
            decision = {
                'type': 'warn',
                'message': 'You have done ' + str(state['consecutive_reads']) + ' reads without writing anything. Are you stuck? (a) make the edit, (b) ask the user for clarification, (c) move on.'
            }

    elif tool_name == 'Bash':
        command = tool_input.get('command', '')
        sig = command[:80]

        if sig:
            count = state['bash_retries'].get(sig, 0) + 1
            state['bash_retries'][sig] = count
            if count >= 3:
                decision = {
                    'type': 'deny',
                    'reason': 'This command was attempted ' + str(count - 1) + ' times. The approach is not working. Try a different strategy.'
                }

        state['consecutive_reads'] = state['consecutive_reads'] + 1

        if decision is None and state['consecutive_reads'] >= 5:
            decision = {
                'type': 'warn',
                'message': 'You have done ' + str(state['consecutive_reads']) + ' reads/commands without writing anything. Are you stuck? (a) make the edit, (b) ask the user for clarification, (c) move on.'
            }

    elif tool_name in ('Edit', 'Write'):
        state['consecutive_reads'] = 0

    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
    except OSError:
        pass

    if decision is None:
        return

    if decision['type'] == 'deny':
        output = {
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': decision['reason']
            }
        }
        print(json.dumps(output))
    elif decision['type'] == 'warn':
        output = {
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'additionalContext': decision['message']
            }
        }
        print(json.dumps(output))

try:
    main()
except Exception:
    pass
" "$TOOL_NAME" "$STATE_FILE"
