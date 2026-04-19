#!/usr/bin/env bash
set -euo pipefail

RESULT_FILE="$HOME/.claude/cache/last-audit-result.json"

python3 - <<'PY' "$RESULT_FILE"
import json, sys
from pathlib import Path
from datetime import datetime

result_path = Path(sys.argv[1])

if not result_path.exists():
    msg = "[AUDIT] No audit result found — run /audit to baseline."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    raise SystemExit(0)

try:
    data = json.loads(result_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

ts_raw = data.get("timestamp", "")
age_hours = None
if ts_raw:
    try:
        ts = datetime.fromisoformat(ts_raw)
        age_hours = (datetime.now() - ts).total_seconds() / 3600
    except Exception:
        pass

summary = data.get("summary", {})
fail_count = int(summary.get("fail", 0))
warn_count = int(summary.get("warn", 0))

msg = None
if age_hours is not None and age_hours > 24:
    msg = f"[AUDIT] Stale ({age_hours:.0f}h ago) — run /audit to refresh."
elif fail_count > 0:
    failing = [f"{c['category']}/{c['name']}" for c in data.get("checks", []) if c.get("status") == "fail"]
    label = ", ".join(failing[:3])
    if len(failing) > 3:
        label += f" +{len(failing) - 3} more"
    msg = f"[AUDIT] {fail_count} fail, {warn_count} warn — {label}"

if msg:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
PY

exit 0
