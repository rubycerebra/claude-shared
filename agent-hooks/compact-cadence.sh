#!/usr/bin/env bash
# UserPromptSubmit hook — proactive /compact cadence based on substantive prompt count.
set -euo pipefail

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat || true)
fi

PAYLOAD="$INPUT" python3 - <<'PY'
import json
import os
import re
from pathlib import Path

HOME = Path.home()
CFG_FILE = HOME / ".claude" / "config" / "compact-cadence.json"
STATE_FILE = HOME / ".claude" / "cache" / "compact-cadence-state.json"
SESSION_ID = os.environ.get("CLAUDE_SESSION_ID", "default")

DEFAULT_CFG = {
    "enabled": True,
    "thresholds": [15, 20],
    "fresh_chat_threshold": 20,
    "minimum_words": 3,
}
ACK_WORDS = {
    "yes", "no", "ok", "okay", "sure", "thanks", "done", "cool", "great", "continue", "go"
}


def load_json(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return fallback


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def extract_prompt(payload: dict) -> str:
    prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
    if prompt:
        return prompt.strip()
    message = payload.get("message", {}) if isinstance(payload, dict) else {}
    parts = []
    for block in message.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return " ".join(parts).strip()


def is_substantive(prompt: str, minimum_words: int) -> bool:
    if not prompt or prompt.startswith("/"):
        return False
    words = prompt.split()
    if len(words) < minimum_words:
        return False
    if words[0].lower().rstrip(".,!?") in ACK_WORDS:
        return False
    return True


def emit_message(count: int, fresh_chat_threshold: int):
    if count >= fresh_chat_threshold:
        message = (
            f"COMPACT CADENCE: {count} substantive prompts in this session. "
            "If you are staying on the same workstream, run `/compact keep current goal, active files, latest verification state` now. "
            "If the next step is unrelated work, start fresh or use `/clear` before continuing."
        )
    else:
        message = (
            f"COMPACT CADENCE: {count} substantive prompts in this session. "
            "Run `/compact keep current goal, active files, latest verification state` before the thread gets more expensive."
        )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": message,
        }
    }))


def main():
    cfg = load_json(CFG_FILE, DEFAULT_CFG)
    if not cfg.get("enabled", True):
        return

    try:
        payload = json.loads(os.environ.get("PAYLOAD", "") or "{}")
    except Exception:
        return

    prompt = extract_prompt(payload)
    min_words = int(cfg.get("minimum_words", 3) or 3)
    if not is_substantive(prompt, min_words):
        return

    state = load_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}

    session_state = state.get(SESSION_ID, {"count": 0, "fired": []})
    if not isinstance(session_state, dict):
        session_state = {"count": 0, "fired": []}

    session_state["count"] = int(session_state.get("count", 0)) + 1
    fired = {int(x) for x in session_state.get("fired", []) if str(x).isdigit()}

    try:
        thresholds = sorted({int(x) for x in cfg.get("thresholds", [15, 20])})
    except Exception:
        thresholds = [15, 20]
    count = session_state["count"]
    fresh_chat_threshold = int(cfg.get("fresh_chat_threshold", max(thresholds) if thresholds else 20) or 20)

    if count in thresholds and count not in fired:
        fired.add(count)
        session_state["fired"] = sorted(fired)
        state[SESSION_ID] = session_state
        save_json(STATE_FILE, state)
        emit_message(count, fresh_chat_threshold)
        return

    session_state["fired"] = sorted(fired)
    state[SESSION_ID] = session_state
    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
PY

exit 0
