#!/usr/bin/env bash
set -euo pipefail

CACHE_FILE="$HOME/.claude/cache/session-data.json"

# Canonical write-path is daemon process_apple_notes_ideas_inbox().
# Hook is status-only to avoid split-brain processing at session start.
if [[ ! -f "$CACHE_FILE" ]]; then
  echo "[IDEAS] No cache yet (daemon has not produced session-data.json)"
  exit 0
fi

summary=$(python3 - <<'PY' "$CACHE_FILE"
import json, sys
from pathlib import Path

cache_path = Path(sys.argv[1])
try:
    data = json.loads(cache_path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)

ideas = data.get("apple_notes_ideas", {})
if not isinstance(ideas, dict) or not ideas:
    print("")
    raise SystemExit(0)

counts = ideas.get("counts", {}) if isinstance(ideas.get("counts", {}), dict) else {}
status = str(ideas.get("status", "?") or "?").strip()
new_items = int(counts.get("new_items", ideas.get("new_items_count", 0)) or 0)
created = int(counts.get("beads_created", 0) or 0)
failed = int(counts.get("beads_failed", 0) or 0)
retried = int(counts.get("retried", 0) or 0)
retry_queue = int(ideas.get("retry_queue_count", 0) or 0)
last_run = str(ideas.get("last_run", "") or "").strip()

parts = [f"status={status}", f"new={new_items}", f"created={created}", f"failed={failed}", f"retried={retried}", f"queue={retry_queue}"]
if last_run:
    parts.append(f"last_run={last_run}")
print(" • ".join(parts))

# Surface recent beads (created in last 24h)
recent_beads = ideas.get("recent_beads", [])
if isinstance(recent_beads, list) and recent_beads:
    for rb in recent_beads[:5]:
        bid = rb.get("bead_id", "?")
        raw_ts = rb.get("created_at", "")
        text = rb.get("text", "")[:60]
        time_label = raw_ts.split("T")[1][:5] if raw_ts and "T" in raw_ts else ""
        line = f"📌 Recent: {bid}"
        if time_label:
            line += f" ({time_label})"
        line += f" — {text}"
        print(line)
PY
)

if [[ -n "$summary" ]]; then
  first_line=$(echo "$summary" | head -1)
  echo "[IDEAS] $first_line"
  rest=$(echo "$summary" | tail -n +2)
  if [[ -n "$rest" ]]; then
    while IFS= read -r line; do
      echo "[IDEAS] $line"
    done <<< "$rest"
  fi
fi

exit 0
