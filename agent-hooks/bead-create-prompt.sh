#!/usr/bin/env bash
# PostToolUse hook (Bash) — fires when a bead is created via `bd create`
# Injects additionalContext telling Claude to run prompt-master-jim + save as bd note

INPUT=""
if [ ! -t 0 ]; then
    INPUT=$(cat || true)
fi

PAYLOAD="$INPUT" python3 - <<'PY'
import json, os, sys, re

payload_str = os.environ.get("PAYLOAD", "") or "{}"
try:
    payload = json.loads(payload_str)
except Exception:
    sys.exit(0)

# PostToolUse — check both tool_input (command) and tool_response (output)
tool_input = payload.get("tool_input", {}) if isinstance(payload, dict) else {}
tool_response = payload.get("tool_response", {}) if isinstance(payload, dict) else {}

command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
output = str(tool_response.get("output", "") or tool_response.get("stdout", "") or "")

# Only fire on bd create or bd in-progress / bd start commands
is_create = bool(re.search(r'\bbd create\b', command))
is_start = bool(re.search(r'\bbd (in-progress|start|begin)\b', command))

if not is_create and not is_start:
    sys.exit(0)

# Skip if bd create is being echo'd (test payload) or this hook script is in the command
if re.search(r"echo\s+['\"].*bd create", command, re.DOTALL) or 'bead-create-prompt' in command:
    sys.exit(0)

# Skip if the command output indicates failure
if re.search(r'(?i)^Error:', output.strip()):
    sys.exit(0)

# Extract bead ID — from output (bd create) or from command (bd in-progress HEALTH-xxx)
bead_id_match = re.search(r'(HEALTH|WORK|TODO)-[a-z0-9]{4,6}', output) or \
                re.search(r'(HEALTH|WORK|TODO)-[a-z0-9]{4,6}', command)
bead_id = bead_id_match.group(0) if bead_id_match else None

# Extract title from bd create command — quoted title only, or word-starting unquoted title
# Fallback must NOT match shell flags (--flag), redirects (2>&1), or pipes (|)
title_match = re.search(r"""bd create\s+['"](.+?)['"]""", command)
if not title_match:
    # Unquoted: must start with a letter/digit, no shell metacharacters
    m = re.search(r'bd create\s+([A-Za-z0-9][^|&;<>\n]*?)(?:\s+--|$)', command)
    if m and not m.group(1).strip().startswith('-'):
        title_match = m
title = title_match.group(1).strip() if title_match else ""

# Bail out if we can't identify a real bead title or ID
# (prevents misfiring on `bd create --help`, `bd create ... 2>&1 | head`, etc.)
if not title and not bead_id:
    sys.exit(0)

# Extra guard: if title looks like a shell flag or contains shell metacharacters, skip
if title and (title.startswith('-') or any(c in title for c in '|&;<>')):
    sys.exit(0)

ref = bead_id if bead_id else f'"{title}"'

if is_create:
    action = f"New bead {ref} just created."
    timing = "MANDATORY next step: before starting any implementation"
else:
    action = f"Bead {ref} set to in-progress — implementation about to start."
    timing = "MANDATORY before writing any code"

msg = (
    f"PROMPT-MASTER PROTOCOL: {action} "
    f"{timing}: use /prompt-master-jim to generate a Claude Code session prompt "
    f"for this bead, then save it: `bd note {ref} \"<prompt>\"`. "
    "The prompt must include: starting state, target state, steps, MUST/MUST NOT constraints, done-when condition. "
    "Skip only if a prompt note already exists on this bead."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
PY

exit 0
