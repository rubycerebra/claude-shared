#!/usr/bin/env bash
# UserPromptSubmit hook — suggest low-cost routing for routine tasks.
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
CFG_FILE = HOME / ".claude" / "config" / "model-effort-routing.json"

DEFAULT_CFG = {
    "enabled": True,
    "minimum_words": 3,
}
ROUTINE = re.compile(
    r"\b(reformat|format|tidy|clean up text|summari[sz]e|summary|extract|list|rewrite|proofread|grammar|spell|copyedit|convert|quick read|quick summary|scan this|read this|what does this say|simple note|turn this into)\b"
)
COMPLEX = re.compile(
    r"\b(debug|fix|broken|error|bug|not working|architecture|plan|refactor|migrate|pipeline|cache invalidation|investigate|distributed|multi-step|automation)\b"
)
ACK_WORDS = {"yes", "no", "ok", "okay", "sure", "thanks", "done", "continue"}


def load_json(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return fallback


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


def main():
    cfg = load_json(CFG_FILE, DEFAULT_CFG)
    if not cfg.get("enabled", True):
        return

    try:
        payload = json.loads(os.environ.get("PAYLOAD", "") or "{}")
    except Exception:
        return

    prompt = extract_prompt(payload)
    if not prompt or prompt.startswith("/"):
        return

    words = prompt.split()
    if len(words) < int(cfg.get("minimum_words", 3) or 3):
        return
    if words[0].lower().rstrip('.,!?') in ACK_WORDS:
        return

    lower = prompt.lower()
    if COMPLEX.search(lower):
        return
    if not ROUTINE.search(lower):
        return

    message = (
        "CHEAP TASK ROUTING: This looks routine. Prefer `/model haiku` + `/effort low` for reads, summaries, reformats, and other low-judgement work. "
        "Keep `sonnet` for normal implementation, and use `opus-plan` or high effort only for architecture or genuinely ambiguous debugging."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
PY

exit 0
