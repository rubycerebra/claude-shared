#!/usr/bin/env bash
# Claude Code PreToolUse:Bash hook
# Detects explicit task switches (bd update ... --status=in_progress)
# and prompts a context clear to reduce stale-context carryover.
set -euo pipefail

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat || true)
fi

PAYLOAD="$INPUT" python3 - <<'PY'
import json
import os
import re
import subprocess
import time
from pathlib import Path

HOME = Path.home()
CFG_FILE = HOME / ".claude" / "config" / "task-clear.json"
STATE_FILE = HOME / ".claude" / "cache" / "task-clear-state.json"

DEFAULT_CFG = {
    "enabled": True,
    "notify_on_switch": True,
    "auto_type_clear": False,
    "emit_context_hint": True,
    "cooldown_seconds": 45,
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


def esc_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str):
    title_e = esc_applescript(title)
    msg_e = esc_applescript(message)
    subprocess.run(
        ["osascript", "-e", f'display notification "{msg_e}" with title "{title_e}"'],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def type_clear_command():
    script = '''
    tell application "System Events"
      keystroke "/clear"
      key code 36
    end tell
    '''
    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def extract_task_id(command: str):
    m = re.search(r"\bbd\s+update\s+([A-Z]+-[a-z0-9.]+)\b[^\n]*--status(?:=|\s+)in_progress\b", command)
    if m:
        return m.group(1)

    if re.search(r"\bbd\s+update\b[^\n]*--status(?:=|\s+)in_progress\b", command):
        ids = re.findall(r"\b[A-Z]+-[a-z0-9.]+\b", command)
        if ids:
            return ids[0]

    return None


def emit_context_hint(previous_task: str, next_task: str):
    previous = previous_task or "(no previous claimed task)"
    message = (
        f"TASK SWITCH DETECTED: {previous} → {next_task}. "
        "If this is unrelated work, run `/clear` before the next prompt so stale context does not carry over. "
        "If it is the same workstream, continue without re-stating context that is already in history."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
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

    command = payload.get("tool_input", {}).get("command") if isinstance(payload, dict) else None
    if not isinstance(command, str) or not command.strip():
        return

    task_id = extract_task_id(command)
    if not task_id:
        return

    state = load_json(
        STATE_FILE,
        {"last_task_id": "", "last_notified_at": 0, "last_notified_task_id": ""},
    )
    if not isinstance(state, dict):
        state = {"last_task_id": "", "last_notified_at": 0, "last_notified_task_id": ""}

    last_task = str(state.get("last_task_id") or "")
    now = int(time.time())
    try:
        cooldown = int(cfg.get("cooldown_seconds", 45))
    except Exception:
        cooldown = 45

    switched = task_id != last_task
    if switched and cfg.get("notify_on_switch", True):
        last_notified = int(state.get("last_notified_at", 0) or 0)
        last_notified_task_id = str(state.get("last_notified_task_id") or "")
        if task_id != last_notified_task_id or now - last_notified >= max(cooldown, 0):
            notify(
                "Task switched",
                f"Now on {task_id}. Run /clear before continuing to avoid stale context.",
            )
            state["last_notified_at"] = now
            state["last_notified_task_id"] = task_id

            if cfg.get("auto_type_clear", False):
                type_clear_command()

    state["last_task_id"] = task_id
    state["last_command"] = command
    save_json(STATE_FILE, state)

    if switched and cfg.get("emit_context_hint", True):
        emit_context_hint(last_task, task_id)


if __name__ == "__main__":
    main()
PY

exit 0
