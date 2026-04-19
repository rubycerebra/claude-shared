#!/usr/bin/env bash
# UserPromptSubmit hook — detects unstructured/multi-part requests and triggers auto-reformat

INPUT=""
if [ ! -t 0 ]; then
    INPUT=$(cat || true)
fi

COOLDOWN_FILE="/tmp/prompt-reformat-${PPID}.last"
NOW=$(date +%s)

if [ -f "$COOLDOWN_FILE" ]; then
    LAST=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
    ELAPSED=$(( NOW - LAST ))
    # 3-minute cooldown — don't fire twice in quick succession
    [ "$ELAPSED" -lt 180 ] && exit 0
fi

PAYLOAD="$INPUT" COOLDOWN_FILE="$COOLDOWN_FILE" NOW="$NOW" python3 - <<'PY'
import json, os, sys, re

payload_str = os.environ.get("PAYLOAD", "") or "{}"
try:
    payload = json.loads(payload_str)
except Exception:
    sys.exit(0)

prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
if not isinstance(prompt, str) or not prompt.strip():
    sys.exit(0)

# Skip slash commands — they're deliberate, not brain dumps
if prompt.strip().startswith("/"):
    sys.exit(0)

words = prompt.split()
word_count = len(words)

# Absolute floor — nothing under 10 words is a brain dump
if word_count < 10:
    sys.exit(0)

# Strong uncertainty signals — fire regardless of word count
UNCERTAINTY = r'\b(not sure|not entirely sure|i was wondering|hard to explain|rough idea|brain dump|not really sure|unclear how|kind of want|sort of want|i think i want|something like|not certain)\b'

# Pivot words that signal multi-part requests — require ≥20 words (filter common "also" in short messages)
PIVOTS = r'\b(oh and|by the way|btw|another thing|one more|and also|and maybe|could also|plus also)\b'

# Sequential task language
MULTI_TASK = r'\b(first[,\s]|second[,\s]|third[,\s]|then also|after that also|and then also)\b'

has_uncertainty = bool(re.search(UNCERTAINTY, prompt.lower()))
has_pivots = bool(re.search(PIVOTS, prompt.lower())) and word_count >= 20
has_multi_task = bool(re.search(MULTI_TASK, prompt.lower()))

trigger = has_uncertainty or has_pivots or has_multi_task

if not trigger:
    sys.exit(0)

# Write cooldown
cooldown_file = os.environ.get("COOLDOWN_FILE", "")
now_str = os.environ.get("NOW", "")
if cooldown_file and now_str:
    try:
        with open(cooldown_file, 'w') as f:
            f.write(now_str)
    except Exception:
        pass

msg = (
    "REFORMAT PROTOCOL ACTIVATED: This message appears multi-part or unstructured. "
    "MANDATORY before acting: "
    "(1) Parse into Context / Goal / Tasks / Constraints / Questions. "
    "(2) Present the reformatted version clearly. "
    "(3) Ask: 'Does this capture everything correctly? Ready for me to proceed?' "
    "(4) Wait for confirmation — do NOT execute until Jim confirms. "
    "Use /prompt-master-jim if Jim wants an optimised prompt output instead of task execution."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
PY

exit 0
