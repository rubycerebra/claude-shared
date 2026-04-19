#!/usr/bin/env bash
# Claude Code PostToolUse hook
# Reads latest Claude Peak usage percentages and raises milestone alerts.
# Milestones are deduped per reset window so alerts fire once per threshold.
set -euo pipefail

# Consume hook stdin if present; this hook does not need payload details.
if [ ! -t 0 ]; then
  cat >/dev/null || true
fi

python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime

HOME = Path.home()
LOG_FILE = HOME / ".config" / "claude-peak" / "debug.log"
STATE_FILE = HOME / ".claude" / "cache" / "token-alert-state.json"
CFG_FILE = HOME / ".claude" / "config" / "token-alerts.json"

DEFAULT_CFG = {
    "enabled": True,
    "windows": ["seven_day", "five_hour"],
    "milestones": [20, 50, 75, 90, 100],
    "critical_threshold": 90,
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


def parse_latest_usage_payload(log_path: Path):
    if not log_path.exists():
        return None

    pattern = re.compile(r"Usage API HTTP 200:\s*(\{.*\})")
    try:
        lines = log_path.read_text(errors="ignore").splitlines()
    except Exception:
        return None

    for line in reversed(lines):
        m = pattern.search(line)
        if not m:
            continue
        raw = m.group(1)
        try:
            return json.loads(raw)
        except Exception:
            continue
    return None


def esc_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def human_reset(raw: str | None) -> str:
    if not raw:
        return "unknown"
    try:
        norm = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(norm)
        return dt.strftime("%a %d %b %H:%M")
    except Exception:
        return raw


def notify(title: str, message: str, critical: bool, dry_run: bool):
    if dry_run:
        print(f"[dry-run] {title}: {message} (critical={critical})")
        return

    title_e = esc_applescript(title)
    msg_e = esc_applescript(message)

    subprocess.run(
        ["osascript", "-e", f'display notification "{msg_e}" with title "{title_e}"'],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if critical:
        subprocess.run(
            ["osascript", "-e", f'display alert "{title_e}" message "{msg_e}" as critical'],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main():
    cfg = load_json(CFG_FILE, DEFAULT_CFG)
    if not cfg.get("enabled", True):
        return

    usage = parse_latest_usage_payload(LOG_FILE)
    if not isinstance(usage, dict):
        return

    state = load_json(STATE_FILE, {"windows": {}})
    if not isinstance(state, dict):
        state = {"windows": {}}
    win_state = state.setdefault("windows", {})

    try:
        milestones = sorted({int(x) for x in cfg.get("milestones", [20, 50, 75, 90, 100]) if isinstance(x, (int, float, str))})
    except Exception:
        milestones = [20, 50, 75, 90, 100]
    milestones = [m for m in milestones if 0 < m <= 100]
    if not milestones:
        milestones = [20, 50, 75, 90, 100]

    try:
        critical_threshold = int(cfg.get("critical_threshold", 90))
    except Exception:
        critical_threshold = 90

    configured_windows = cfg.get("windows", ["seven_day", "five_hour"])
    if not isinstance(configured_windows, list):
        configured_windows = ["seven_day", "five_hour"]

    dry_run = os.environ.get("TOKEN_ALERT_DRY_RUN", "0") == "1"

    for window in configured_windows:
        data = usage.get(window)
        if not isinstance(data, dict):
            continue

        util = data.get("utilization")
        if util is None:
            continue
        try:
            utilization = float(util)
        except Exception:
            continue

        reset_key = str(data.get("resets_at") or "none")

        window_state = win_state.setdefault(window, {"reset": reset_key, "fired": []})
        if not isinstance(window_state, dict):
            window_state = {"reset": reset_key, "fired": []}
            win_state[window] = window_state

        if window_state.get("reset") != reset_key:
            window_state["reset"] = reset_key
            window_state["fired"] = []

        fired = {int(x) for x in window_state.get("fired", []) if isinstance(x, (int, float, str)) and str(x).isdigit()}
        crossed = [m for m in milestones if utilization >= m and m not in fired]
        if not crossed:
            continue

        milestone = max(crossed)
        fired.add(milestone)
        window_state["fired"] = sorted(fired)

        label = "7-day" if window == "seven_day" else "5-hour"
        message = f"{label} usage reached {milestone}% (now {utilization:.1f}%). Reset: {human_reset(data.get('resets_at'))}."
        notify(
            title="Claude Token Milestone",
            message=message,
            critical=(milestone >= critical_threshold),
            dry_run=dry_run,
        )

    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
PY

exit 0
