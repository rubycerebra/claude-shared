#!/usr/bin/env bash
# session-timer-gate.sh — PreToolUse enforcement gate for session timer.
# Denies tool execution at Stage 3+ unless a break has been genuinely acknowledged.
# PDA-aware: compassionate messages, no shaming. "suspend timer" always available.

PPID_MARKER="${PPID:-0}"
TIMER_FILE="/tmp/claude-session-start-${PPID_MARKER}"
BREAK_FILE="/tmp/claude-session-break-${PPID_MARKER}"
IDLE_FILE="/tmp/claude-session-idle-${PPID_MARKER}"
LASTFIRE_FILE="/tmp/claude-session-lastfire-${PPID_MARKER}"
PENDING_FILE="/tmp/claude-session-pending-${PPID_MARKER}"
ACK_FILE="/tmp/claude-session-ack-${PPID_MARKER}"

NOW=$(date +%s)
HOUR=$(date +%H)

# No timer file = no session tracking = allow
[[ ! -f "$TIMER_FILE" ]] && exit 0

# ── Work hours (9-17, all days): relaxed mode — no gate blocking ─────────────
# Dialogs and notifications still fire, but tool calls are never denied.
(( 10#$HOUR >= 9 && 10#$HOUR < 17 )) && exit 0

# ── Compute effective elapsed (same formula as session-timer.sh) ─────────────
START=$(cat "$TIMER_FILE")
IDLE_SECS=$(cat "$IDLE_FILE" 2>/dev/null || echo "0")
WALL_ELAPSED=$(( (NOW - START) / 60 ))
IDLE_MINS=$(( IDLE_SECS / 60 ))
ELAPSED=$(( WALL_ELAPSED - IDLE_MINS ))
(( ELAPSED < 0 )) && ELAPSED=0

# ── Stage detection (mirrors session-timer.sh) ──────────────────────────────
if (( ELAPSED < 35 )); then STAGE=1
elif (( ELAPSED < 60 )); then STAGE=2
elif (( ELAPSED < 70 )); then STAGE=3
else STAGE=4
fi

# Stages 1-2: no blocking
(( STAGE < 3 )) && exit 0

# ── Break cooldown: if active, allow ────────────────────────────────────────
if [[ -f "$BREAK_FILE" ]]; then
    read -r BREAK_END BREAK_DUR < "$BREAK_FILE"
    BREAK_DUR=${BREAK_DUR:-300}
    if (( NOW - BREAK_END < BREAK_DUR )); then
        exit 0  # In cooldown from a genuine break
    fi
fi

# ── Check acknowledgment file ───────────────────────────────────────────────
if [[ -f "$ACK_FILE" ]]; then
    ACK_TIME=$(cat "$ACK_FILE" 2>/dev/null || echo "0")
    ACK_AGE=$(( NOW - ACK_TIME ))
    if (( ACK_AGE < 1800 )); then
        exit 0  # Acknowledged within last 30 min
    else
        rm -f "$ACK_FILE"  # Stale, force re-acknowledgment
    fi
fi

# ── Check for stale pending file (AppleScript may have crashed) ─────────────
if [[ -f "$PENDING_FILE" ]]; then
    PENDING_TIME=$(cat "$PENDING_FILE" 2>/dev/null || echo "0")
    PENDING_AGE=$(( NOW - PENDING_TIME ))
    if (( PENDING_AGE > 1800 )); then
        rm -f "$PENDING_FILE"  # Stale pending, clean up and allow
        exit 0
    fi
fi

# ── DENY tool execution ────────────────────────────────────────────────────
# Build compassionate deny message based on stage and state
if [[ -f "$PENDING_FILE" ]]; then
    if (( STAGE == 3 )); then
        REASON="${ELAPSED} minutes active. A break dialog is open — tool calls are paused until it resolves. This is the system you set up, and it's doing its job. (Say 'suspend timer' to override.)"
    else
        REASON="${ELAPSED} minutes. Tool execution is paused while a break dialog is open. The work will still be here. (Say 'suspend timer' to override.)"
    fi
else
    # No pending file but no ack either — dialog was dismissed without completing
    if (( STAGE == 3 )); then
        REASON="${ELAPSED} minutes active. Break not yet taken — tool calls are paused. A new dialog will appear shortly. (Say 'suspend timer' to override.)"
    else
        REASON="${ELAPSED} minutes. The session timer has a break pending. Tool execution is paused. Step away for a few minutes — your body will thank you. (Say 'suspend timer' to override.)"
    fi
fi

# Output deny decision
python3 -c "
import json, sys
reason = sys.argv[1]
print(json.dumps({
    'decision': 'deny',
    'reason': reason
}))
" "$REASON"

exit 0
