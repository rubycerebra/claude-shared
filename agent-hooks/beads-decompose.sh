#!/usr/bin/env bash
# UserPromptSubmit hook — detects multi-part / meandering prompts
# and reminds agent to decompose into beads for tracking.
set -euo pipefail

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat || true)
fi

# Fast-path: skip short prompts entirely (saves Python startup)
PROMPT_LEN=$(echo "$INPUT" | jq -r '.prompt // ""' 2>/dev/null | wc -c | tr -d ' ')
if [ "$PROMPT_LEN" -lt 80 ]; then exit 0; fi

PAYLOAD="$INPUT" python3 - <<'PY'
import json
import os
import time
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "cache" / "beads-decompose-state.json"
COOLDOWN = 180  # seconds

def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {"last_nudge": 0, "msg_count": 0}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)

def is_multipart(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    questions = text.count("?")
    signals = sum(1 for word in [
        "also", "another thing", "and then", "plus", "oh and",
        "separately", "on a different note", "while you're at it",
        "one more", "btw", "by the way", "second", "third",
        "next", "finally", "as well", "too",
    ] if word in text.lower())
    sentences = text.count(".") + text.count("!") + text.count("?")
    if len(paragraphs) >= 3:
        return True
    if signals >= 2:
        return True
    if questions >= 2 and len(text) > 200:
        return True
    if sentences >= 5 and len(text) > 300:
        return True
    return False

def main():
    try:
        payload = json.loads(os.environ.get("PAYLOAD", "") or "{}")
    except Exception:
        return
    prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
    if not isinstance(prompt, str):
        return
    state = load_state()
    now = time.time()
    state["msg_count"] = state.get("msg_count", 0) + 1
    if not is_multipart(prompt):
        save_state(state)
        return
    last_nudge = state.get("last_nudge", 0)
    if now - last_nudge < COOLDOWN:
        save_state(state)
        return
    state["last_nudge"] = now
    save_state(state)
    msg = "[BEADS] Multi-part prompt detected. Decompose into separate beads (bd create) before starting work."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))

if __name__ == "__main__":
    main()
PY

exit 0
