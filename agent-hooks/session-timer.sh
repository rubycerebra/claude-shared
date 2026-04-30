#!/usr/bin/env bash
# session-timer.sh — Escalating break enforcer for hyperfocus management (v2).
# PDA-aware redesign: observational tone, body prompts, no shaming, proportional cooldown.
#
# Stage 1 (30 min):    Banner notification — gentle checkpoint.
# Stage 2 (35-59 min): Check-in dialog: body prompt + free-text self-check + two buttons.
# Stage 3 (60-69 min): display alert as warning — 5-min timed break. 1 re-open on Escape.
# Stage 4 (70+ min):   display alert as critical — 10-15 min break, every 10 min. 1 re-open.
#
# Break cooldown is proportional to the break taken (not fixed at 5 min).
# In-chat context injection only at stage transitions, not every 5-min bracket.

# Use CLAUDE_SESSION_ID (set by Claude Code hooks) as stable session marker.
# PPID varies per tool call — never use it as a session key.
SESSION_MARKER="${CLAUDE_SESSION_ID:-fallback-$(date +%Y%m%d)}"
TIMER_FILE="/tmp/claude-session-start-${SESSION_MARKER}"
ALERT_FILE="/tmp/claude-session-alerted-${SESSION_MARKER}"
BREAK_FILE="/tmp/claude-session-break-${SESSION_MARKER}"
LASTFIRE_FILE="/tmp/claude-session-lastfire-${SESSION_MARKER}"
IDLE_FILE="/tmp/claude-session-idle-${SESSION_MARKER}"
LASTCTX_FILE="/tmp/claude-session-lastctx-${SESSION_MARKER}"

IDLE_THRESHOLD=900  # 15 minutes — gap longer than this counts as "away"

NOW=$(date +%s)

# ── First call: record session start ──────────────────────────────────────────
if [[ ! -f "$TIMER_FILE" ]]; then
    echo "$NOW" > "$TIMER_FILE"
    echo "" > "$ALERT_FILE"
    echo "$NOW" > "$LASTFIRE_FILE"
    echo "0" > "$IDLE_FILE"
    echo "0" > "$LASTCTX_FILE"
    osascript -e 'display notification "Session timer started. First check-in at 30 minutes." with title "Session Timer" sound name "Tink"' 2>/dev/null &
    # Clean up stale session files older than 24h (not belonging to current session)
    find /tmp -maxdepth 1 -name 'claude-session-*' -not -name "*-${SESSION_MARKER}" -mtime +1 -delete 2>/dev/null &
    exit 0
fi

# ── Idle detection: accumulate time spent away ────────────────────────────────
LAST_FIRE=$(cat "$LASTFIRE_FILE" 2>/dev/null || echo "$NOW")
GAP=$(( NOW - LAST_FIRE ))

IDLE_SECS=$(cat "$IDLE_FILE" 2>/dev/null || echo "0")
if (( GAP > IDLE_THRESHOLD )); then
    IDLE_SECS=$(( IDLE_SECS + GAP ))
    echo "$IDLE_SECS" > "$IDLE_FILE"
fi
echo "$NOW" > "$LASTFIRE_FILE"

# ── Compute effective elapsed (wall time minus idle time) ─────────────────────
START=$(cat "$TIMER_FILE")
WALL_ELAPSED=$(( (NOW - START) / 60 ))
IDLE_MINS=$(( IDLE_SECS / 60 ))
ELAPSED=$(( WALL_ELAPSED - IDLE_MINS ))
(( ELAPSED < 0 )) && ELAPSED=0

# ── Hard reset after 8 hours of active coding ────────────────────────────────
if (( ELAPSED > 480 )); then
    echo "$NOW" > "$TIMER_FILE"
    echo -n "" > "$ALERT_FILE"
    echo "$NOW" > "$LASTFIRE_FILE"
    echo "0" > "$IDLE_FILE"
    echo "0" > "$LASTCTX_FILE"
    rm -f "$BREAK_FILE"
    exit 0
fi

# ── Fast path: under 30 minutes, nothing to do ───────────────────────────────
if (( ELAPSED < 30 )); then
    exit 0
fi

# ── Stage detection ───────────────────────────────────────────────────────────
get_stage() {
    local mins=$1
    if (( mins < 35 )); then echo 1       # banner only
    elif (( mins < 60 )); then echo 2     # check-in dialog
    elif (( mins < 70 )); then echo 3     # 5-min timed break
    else echo 4                            # 10-15 min escalating break
    fi
}

STAGE=$(get_stage "$ELAPSED")

# Stage-aware bracket: 5-min granularity for stages 1-3, 10-min for stage 4
if (( STAGE < 4 )); then
    BRACKET=$(( ((ELAPSED - 30) / 5) * 5 + 30 ))
else
    BRACKET=$(( ((ELAPSED - 70) / 10) * 10 + 70 ))
fi

# ── Break cooldown: proportional to break taken ───────────────────────────────
# Break file format: "timestamp duration_secs"
if [[ -f "$BREAK_FILE" ]]; then
    read -r BREAK_END BREAK_DUR < "$BREAK_FILE"
    BREAK_DUR=${BREAK_DUR:-300}
    if (( NOW - BREAK_END < BREAK_DUR )); then
        echo "$BRACKET" >> "$ALERT_FILE"
        exit 0
    fi
fi

# ── Already alerted this bracket? ────────────────────────────────────────────
if grep -qx "$BRACKET" "$ALERT_FILE" 2>/dev/null; then
    exit 0
fi

# Mark bracket as alerted before spawning (prevents double-fire on fast tool calls)
echo "$BRACKET" >> "$ALERT_FILE"

# ── Helper functions ──────────────────────────────────────────────────────────
get_message() {
    local mins=$1
    if (( mins < 35 )); then
        echo "30 minutes. Natural checkpoint."
    elif (( mins < 40 )); then
        echo "${mins} minutes active. The work is flowing — that's the hyperfocus talking."
    elif (( mins < 45 )); then
        echo "${mins} minutes. Your body has been still this whole time."
    elif (( mins < 50 )); then
        echo "${mins} minutes. The thing pulling you to stay is the fixation, not the deadline."
    elif (( mins < 55 )); then
        echo "${mins} minutes. Past-Jim set this up because present-Jim can't feel the time passing."
    elif (( mins < 60 )); then
        echo "${mins} minutes. This will still be here. Your back won't always feel fine."
    elif (( mins < 65 )); then
        echo "60 minutes. Break time — stand up, move, look at something far away."
    elif (( mins < 75 )); then
        echo "${mins} minutes. The fixation is strong today. That's data, not a failure."
    elif (( mins < 90 )); then
        echo "${mins} minutes. You set this boundary for a reason and you were right to."
    else
        echo "${mins} minutes. Long session. The work is patient. Your body is not."
    fi
}

get_sound() {
    local mins=$1
    if (( mins < 35 )); then echo "Tink"
    elif (( mins < 60 )); then echo "Basso"
    elif (( mins < 70 )); then echo "Sosumi"
    else echo "Funk"
    fi
}

get_break_duration() {
    local mins=$1
    if (( mins < 70 )); then echo 300     # 5 min
    elif (( mins < 90 )); then echo 600   # 10 min
    else echo 900                          # 15 min (capped)
    fi
}

# ── Compute values ────────────────────────────────────────────────────────────
MSG=$(get_message "$ELAPSED")
SOUND=$(get_sound "$ELAPSED")
BREAK_SECS=$(get_break_duration "$ELAPSED")
BREAK_MINS=$(( BREAK_SECS / 60 ))

# Rotating body prompts and check-in questions (index by bracket position)
BODY_PROMPTS=(
    "Stand up. Stretch your arms overhead. Sit back down."
    "Look away from the screen. Find the farthest point you can see."
    "Roll your shoulders back 5 times. Notice if they were hunched."
    "Put both feet flat on the floor. Uncurl if you are sitting on one leg."
    "Close your eyes for 10 seconds. Notice what your jaw is doing."
)
CHECKIN_PROMPTS=(
    "What are you working on right now?"
    "Is this the thing you sat down to do?"
    "How does your back feel?"
    "Are you still on the original task or did you drift?"
    "When did you last drink water?"
    "What would you do if you stopped now?"
    "Is this urgent or does it just feel urgent?"
)

if (( STAGE < 4 )); then
    PROMPT_INDEX=$(( (BRACKET - 35) / 5 ))
else
    PROMPT_INDEX=$(( (BRACKET - 70) / 10 ))
fi
BODY_PROMPT="${BODY_PROMPTS[$((PROMPT_INDEX % 5))]}"
CHECKIN_PROMPT="${CHECKIN_PROMPTS[$((PROMPT_INDEX % 7))]}"

# ── Stage 1: banner notification only ────────────────────────────────────────
if (( STAGE == 1 )); then
    osascript -e "display notification \"${MSG}\" with title \"Session Timer\" sound name \"Tink\"" 2>/dev/null &
fi

# ── Stage 2: check-in dialog — body prompt + free-text + two buttons ─────────
# Work hours (9-17): 2-word minimum, relaxed. Outside: 3-word minimum.
# Escape silently exits (next bracket fires in 5 min).
WORK_HOUR=$(date +%H)
STAGE2_MIN_WORDS=3
(( 10#$WORK_HOUR >= 9 && 10#$WORK_HOUR < 17 )) && STAGE2_MIN_WORDS=2

if (( STAGE == 2 )); then
    osascript <<APPLESCRIPT &
        do shell script "afplay /System/Library/Sounds/${SOUND}.aiff > /dev/null 2>&1 &"

        set breakFile to "${BREAK_FILE}"
        set msg to "${MSG}"
        set bodyPrompt to "${BODY_PROMPT}"
        set checkinQ to "${CHECKIN_PROMPT}"
        set minWords to ${STAGE2_MIN_WORDS}
        set fullMsg to msg & return & return & bodyPrompt & return & return & checkinQ

        repeat
            try
                set response to display dialog fullMsg ¬
                    default answer "" ¬
                    buttons {"Take a break", "Continue session"} ¬
                    default button "Continue session" ¬
                    with title "Session Check-in" ¬
                    with icon caution

                if button returned of response is "Take a break" then
                    set nowTS to do shell script "date +%s"
                    do shell script "echo '" & nowTS & " 300' > " & quoted form of breakFile
                    display notification "Enjoy the break." with title "Session Timer" sound name "Glass"
                    exit repeat
                else
                    set answer to text returned of response
                    if answer is "" then
                        display dialog "One real word about how you feel — this check-in is for you." ¬
                            buttons {"OK"} default button 1 giving up after 5 ¬
                            with title "Session Check-in"
                        -- loop continues
                    else if (count of words of answer) < minWords then
                        if minWords > 2 then
                            display dialog "A bit more — just finish the thought. Three words minimum." ¬
                                buttons {"OK"} default button 1 giving up after 5 ¬
                                with title "Session Check-in"
                        else
                            display dialog "Two words minimum — just finish the thought." ¬
                                buttons {"OK"} default button 1 giving up after 5 ¬
                                with title "Session Check-in"
                        end if
                        -- loop continues
                    else
                        exit repeat
                    end if
                end if
            on error number -128
                -- Escape pressed: exit silently, next bracket fires in 5 min
                exit repeat
            end try
        end repeat
APPLESCRIPT
fi

# ── Stage 3: 5-min timed break — display alert as warning, 1 re-open ─────────
if (( STAGE == 3 )); then
    PENDING_FILE="/tmp/claude-session-pending-${SESSION_MARKER}"
    ACK_FILE="/tmp/claude-session-ack-${SESSION_MARKER}"
    echo "$NOW" > "$PENDING_FILE"
    osascript <<APPLESCRIPT &
        do shell script "afplay /System/Library/Sounds/${SOUND}.aiff > /dev/null 2>&1 &"

        set breakFile to "${BREAK_FILE}"
        set pendingFile to "${PENDING_FILE}"
        set ackFile to "${ACK_FILE}"
        set breakMins to ${BREAK_MINS}
        set breakSecs to ${BREAK_SECS}
        set attemptsLeft to 2

        repeat while attemptsLeft > 0
            try
                display alert "Break Time" ¬
                    message "60 minutes active. Stand up, move around. This closes automatically in " & breakMins & " minutes." ¬
                    as warning ¬
                    buttons {"Taking a break (" & breakMins & " min)"} ¬
                    default button 1 ¬
                    giving up after breakSecs

                -- Genuine break: write break file, ack file, remove pending
                set nowTS to do shell script "date +%s"
                do shell script "echo '" & nowTS & " " & breakSecs & "' > " & quoted form of breakFile
                do shell script "echo '" & nowTS & "' > " & quoted form of ackFile
                do shell script "rm -f " & quoted form of pendingFile
                exit repeat
            on error number -128
                -- Escape pressed: do NOT write break/ack files. Gate keeps denying.
                set attemptsLeft to attemptsLeft - 1
                if attemptsLeft > 0 then
                    do shell script "afplay /System/Library/Sounds/Sosumi.aiff > /dev/null 2>&1 &"
                    display alert "Break dismissed." ¬
                        message "Tool calls remain paused until break is taken. This will reappear shortly." ¬
                        as informational ¬
                        buttons {"OK"} giving up after 5
                else
                    -- Both escapes used. Spawn persistent background reminders.
                    do shell script "bash -c 'for i in 1 2 3 4 5; do sleep 60; osascript -e \"display notification \\\"Break still pending. Take a stretch.\\\" with title \\\"Session Timer\\\" sound name \\\"Tink\\\"\" 2>/dev/null; done' &"
                end if
            end try
        end repeat
APPLESCRIPT
fi

# ── Stage 4: escalating break — display alert as critical, 1 re-open ─────────
if (( STAGE == 4 )); then
    PENDING_FILE="/tmp/claude-session-pending-${SESSION_MARKER}"
    ACK_FILE="/tmp/claude-session-ack-${SESSION_MARKER}"
    echo "$NOW" > "$PENDING_FILE"
    osascript <<APPLESCRIPT &
        do shell script "afplay /System/Library/Sounds/${SOUND}.aiff > /dev/null 2>&1 &"

        set breakFile to "${BREAK_FILE}"
        set pendingFile to "${PENDING_FILE}"
        set ackFile to "${ACK_FILE}"
        set breakMins to ${BREAK_MINS}
        set breakSecs to ${BREAK_SECS}
        set msg to "${MSG}"
        set attemptsLeft to 2

        repeat while attemptsLeft > 0
            try
                display alert "Extended Break" ¬
                    message msg & " " & breakMins & "-minute break. This closes automatically." ¬
                    as critical ¬
                    buttons {"Taking a break (" & breakMins & " min)"} ¬
                    default button 1 ¬
                    giving up after breakSecs

                -- Genuine break: write break file, ack file, remove pending
                set nowTS to do shell script "date +%s"
                do shell script "echo '" & nowTS & " " & breakSecs & "' > " & quoted form of breakFile
                do shell script "echo '" & nowTS & "' > " & quoted form of ackFile
                do shell script "rm -f " & quoted form of pendingFile
                exit repeat
            on error number -128
                -- Escape pressed: do NOT write break/ack files. Gate keeps denying.
                set attemptsLeft to attemptsLeft - 1
                if attemptsLeft > 0 then
                    do shell script "afplay /System/Library/Sounds/Funk.aiff > /dev/null 2>&1 &"
                    display alert "Break dismissed." ¬
                        message "Tool calls remain paused until break is taken. This will reappear shortly." ¬
                        as informational ¬
                        buttons {"OK"} giving up after 5
                else
                    -- Both escapes used. Spawn persistent background reminders.
                    do shell script "bash -c 'for i in 1 2 3 4 5; do sleep 60; osascript -e \"display notification \\\"Break still pending. Take a stretch.\\\" with title \\\"Session Timer\\\" sound name \\\"Tink\\\"\" 2>/dev/null; done' &"
                end if
            end try
        end repeat
APPLESCRIPT
fi

# ── In-chat context injection ─────────────────────────────────────────────────
LAST_CTX=$(cat "$LASTCTX_FILE" 2>/dev/null || echo "0")
SHOULD_INJECT=0

# Stage boundary triggers
if (( ELAPSED >= 30 && LAST_CTX < 30 )); then SHOULD_INJECT=1; fi
if (( ELAPSED >= 60 && LAST_CTX < 60 )); then SHOULD_INJECT=1; fi
if (( ELAPSED >= 70 && LAST_CTX < 70 )); then SHOULD_INJECT=1; fi

# Stage 3+: inject every bracket (every 5-10 min), not just at transitions
if (( STAGE >= 3 && LAST_CTX != ELAPSED )); then SHOULD_INJECT=1; fi

# Stages 1-2: every 30 min after first injection
if (( STAGE < 3 && LAST_CTX > 0 && ELAPSED - LAST_CTX >= 30 )); then SHOULD_INJECT=1; fi

if (( SHOULD_INJECT )); then
    echo "$ELAPSED" > "$LASTCTX_FILE"
    if (( STAGE >= 3 )); then
        CTX_MSG="[SESSION TIMER — BREAK PENDING] Jim has been working for ${ELAPSED}m (${WALL_ELAPSED}m wall / ${IDLE_MINS}m idle). A break dialog is active and tool calls may be paused. If Jim asks to continue working, acknowledge the timer factually — no guilt, just note it: \"I notice the session timer is at ${ELAPSED} minutes. I'm here when you're ready.\""
    else
        CTX_MSG="[SESSION TIMER] ${MSG} (${ELAPSED}m active / ${WALL_ELAPSED}m wall / ${IDLE_MINS}m idle)"
    fi
    python3 -c "import json,sys; msg=sys.argv[1]; print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':msg}}))" \
        "$CTX_MSG"
fi

exit 0
