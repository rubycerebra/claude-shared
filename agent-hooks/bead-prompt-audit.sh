#!/usr/bin/env bash
# SessionStart hook — scans in-progress beads and flags any missing session prompts
# Silent if all in-progress beads already have prompt notes
# SAFETY: all bd calls run with 3s kill-timeout to prevent dolt hangs
# PERF: all 3 project bd list calls run in parallel (was sequential, up to 9s worst-case)

HEALTH_BEADS="/Users/jamescherry/Documents/Claude Projects/HEALTH/.beads"
WORK_BEADS="/Users/jamescherry/Documents/Claude Projects/WORK/.beads"
TODO_BEADS="/Users/jamescherry/Documents/Claude Projects/TODO/.beads"

NL=$'\n'

# Run bd list for one project dir in background, append in-progress IDs to shared file
list_project() {
    local bdir="$1"
    local out="$2"
    [[ -d "$bdir" ]] || return
    local tmp
    tmp=$(mktemp /tmp/bead-audit-XXXXXX)
    env BEADS_DIR="$bdir" bd list > "$tmp" 2>/dev/null &
    local pid=$!
    ( sleep 3 && kill "$pid" 2>/dev/null ) &
    local wdog=$!
    wait "$pid" 2>/dev/null
    kill "$wdog" 2>/dev/null
    wait "$wdog" 2>/dev/null
    grep "◐" "$tmp" | grep -o '[A-Z]*-[a-z0-9]*' >> "$out" 2>/dev/null || true
    rm -f "$tmp"
}

IP_FILE=$(mktemp /tmp/bead-audit-ip-XXXXXX)
TMPOUT=$(mktemp /tmp/bead-audit-show-XXXXXX)
trap 'rm -f "$IP_FILE" "$TMPOUT"' EXIT

# Ensure dolt servers are running before bd calls
for bdir in "$HEALTH_BEADS" "$WORK_BEADS" "$TODO_BEADS"; do
  port_file="$bdir/dolt-server.port"
  [[ -f "$port_file" ]] || continue
  lsof -iTCP:"$(cat "$port_file")" -sTCP:LISTEN >/dev/null 2>&1 && continue
  proj_dir=$(dirname "$bdir")
  ( cd "$proj_dir" && env BEADS_DIR="$bdir" bd dolt start --quiet 2>/dev/null ) &
done
wait

# All 3 project lists in parallel — max wait ~3s instead of ~9s
list_project "$HEALTH_BEADS" "$IP_FILE" &
list_project "$WORK_BEADS"  "$IP_FILE" &
list_project "$TODO_BEADS"  "$IP_FILE" &
wait

IN_PROGRESS=$(sort -u "$IP_FILE" | grep -v '^$' || true)
[[ -z "$IN_PROGRESS" ]] && exit 0

MISSING=""
for BEAD_ID in $IN_PROGRESS; do
    PREFIX=$(echo "$BEAD_ID" | cut -d'-' -f1)
    case "$PREFIX" in
        HEALTH) BDIR="$HEALTH_BEADS" ;;
        WORK)   BDIR="$WORK_BEADS" ;;
        TODO)   BDIR="$TODO_BEADS" ;;
        *)      continue ;;
    esac
    env BEADS_DIR="$BDIR" bd show "$BEAD_ID" > "$TMPOUT" 2>/dev/null &
    local_pid=$!
    ( sleep 3 && kill "$local_pid" 2>/dev/null ) &
    wdog=$!
    wait "$local_pid" 2>/dev/null
    kill "$wdog" 2>/dev/null
    wait "$wdog" 2>/dev/null
    if ! grep -qi 'starting state\|target state\|must not\|prompt-master\|done when' "$TMPOUT"; then
        MISSING="$MISSING $BEAD_ID"
    fi
done

MISSING=$(printf '%s' "$MISSING" | tr ' ' "$NL" | grep -v '^$')

# Prefix purity check — detect cross-project contamination
CONTAMINATION=""
for proj_info in "WORK:$WORK_BEADS" "HEALTH:$HEALTH_BEADS" "TODO:$TODO_BEADS"; do
  prefix="${proj_info%%:*}"
  bdir="${proj_info##*:}"
  jsonl="$bdir/issues.jsonl"
  [[ -f "$jsonl" ]] || continue
  bad=$(python3 -c "
import json, sys
bad = []
try:
    for ln in open('$jsonl'):
        ln = ln.strip()
        if not ln: continue
        o = json.loads(ln)
        if o.get('_type') == 'memory': continue
        id_ = o.get('id', '')
        if id_ and not id_.startswith('${prefix}-'):
            bad.append(id_)
except Exception as e:
    pass
print(' '.join(bad))
" 2>/dev/null)
  [[ -n "$bad" ]] && CONTAMINATION="$CONTAMINATION ${prefix}:[${bad}]"
done

if [[ -n "$CONTAMINATION" ]]; then
  python3 -c "
import json
msg = 'BEADS CONTAMINATION: Wrong-prefix issues detected:$CONTAMINATION — run bd delete on the foreign IDs from the correct project dir.'
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': msg}}))"
  exit 0
fi

[[ -z "$MISSING" ]] && exit 0

MISSING_LIST=$(printf '%s' "$MISSING" | tr "$NL" ' ' | sed 's/ $//')

python3 -c "
import json
msg = 'PROMPT-MASTER AUDIT: In-progress beads without session prompt: $MISSING_LIST. Run /prompt-master-jim before implementing.'
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': msg}}))"

exit 0
