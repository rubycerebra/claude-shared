#!/usr/bin/env bash
# session-lifecycle.sh — dispatch SessionStart/Stop/title tracking lifecycle hooks.
set -euo pipefail

ACTION="${1:-}"
DB="$HOME/.claude/sessions/sessions.db"
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%Y-%m-%dT%H:%M:%S)

PROJECT_HEALTH="$HOME/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-HEALTH"
PROJECT_WORK="$HOME/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-WORK"
PROJECT_TODO="$HOME/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-TODO"
PROJECT_DAEMON="$HOME/.claude/projects/-Users-jamescherry--claude-daemon"
PROJECT_SCRIPTS="$HOME/.claude/projects/-Users-jamescherry--claude-scripts"
PROJECT_DIRS=("$PROJECT_HEALTH" "$PROJECT_WORK" "$PROJECT_TODO" "$PROJECT_DAEMON" "$PROJECT_SCRIPTS")

read_stdin_payload() {
  if [[ ! -t 0 ]]; then
    cat
  fi
}

json_session_id() {
  local payload="$1"
  [[ -z "$payload" ]] && return 0
  printf '%s' "$payload" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || true
}

marker_file() {
  local uuid="$1"
  printf '/tmp/session-titled-%s' "$uuid"
}

clear_title_marker() {
  local uuid="$1"
  [[ -n "$uuid" ]] && rm -f "$(marker_file "$uuid")"
}

mark_titled() {
  local uuid="$1"
  [[ -n "$uuid" ]] && touch "$(marker_file "$uuid")"
}

is_titled() {
  local uuid="$1"
  [[ -n "$uuid" && -f "$(marker_file "$uuid")" ]]
}

detect_project() {
  case "${PWD:-}" in
    */HEALTH*|*/Health*) echo "HEALTH" ;;
    */WORK*) echo "WORK" ;;
    */TODO*) echo "TODO" ;;
    */.claude/daemon*) echo "daemon" ;;
    */.claude/scripts*) echo "scripts" ;;
    *) echo "unknown" ;;
  esac
}

project_jsonl_dir() {
  case "$1" in
    HEALTH) echo "$PROJECT_HEALTH" ;;
    WORK) echo "$PROJECT_WORK" ;;
    TODO) echo "$PROJECT_TODO" ;;
    daemon) echo "$PROJECT_DAEMON" ;;
    scripts) echo "$PROJECT_SCRIPTS" ;;
    *) echo "$PROJECT_HEALTH" ;;
  esac
}

newest_jsonl_uuid() {
  local dir="$1"
  local jsonl=""
  jsonl=$(ls -t "$dir"/*.jsonl 2>/dev/null | head -1 || true)
  [[ -n "$jsonl" ]] && basename "$jsonl" .jsonl
}

find_jsonl() {
  local uuid="$1"
  local dir
  for dir in "${PROJECT_DIRS[@]}"; do
    if [[ -f "$dir/$uuid.jsonl" ]]; then
      echo "$dir/$uuid.jsonl"
      return 0
    fi
  done
  return 1
}

sql_escape() {
  local q="''"
  printf '%s' "${1//\'/$q}"
}

ensure_db() {
  mkdir -p "$(dirname "$DB")"
  sqlite3 "$DB" "
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY, label TEXT NOT NULL, ai_title TEXT,
      path TEXT NOT NULL, project TEXT NOT NULL, created TEXT NOT NULL,
      started_at TEXT, ended_at TEXT, duration_m INTEGER,
      source TEXT DEFAULT 'auto', first_msg TEXT, tags TEXT, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created);
  "
  sqlite3 "$DB" "ALTER TABLE sessions ADD COLUMN decisions TEXT;" >/dev/null 2>&1 || true
}

extract_first_user_message() {
  local jsonl="$1"
  python3 -c "
import json, re, sys
path = sys.argv[1]
limit = int(sys.argv[2])
try:
    fh = open(path, encoding='utf-8')
except OSError:
    raise SystemExit(0)
with fh:
    for i, line in enumerate(fh):
        if i >= limit: break
        try:
            d = json.loads(line.strip())
            if d.get('type') != 'user': continue
            msg = d.get('message', {})
            content = msg.get('content', '')
            if isinstance(content, list):
                text = ' '.join(c.get('text','') for c in content if isinstance(c,dict) and c.get('type')=='text').strip()
            elif isinstance(content, str):
                text = content.strip()
            else:
                continue
            if '<system-reminder>' in text or len(text) < 5: continue
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\\s+', ' ', text).strip()
            print(text)
            break
        except Exception:
            continue
" "$jsonl" "${2:-30}" 2>/dev/null
}

extract_ai_title() {
  local jsonl="$1"
  python3 -c "
import json, sys
path = sys.argv[1]
try:
    fh = open(path, encoding='utf-8')
except OSError:
    raise SystemExit(0)
with fh:
    for i, line in enumerate(fh):
        if i >= 20: break
        try:
            d = json.loads(line.strip())
            if d.get('type') == 'ai-title':
                print(d.get('aiTitle', ''))
                break
        except Exception:
            pass
" "$jsonl" 2>/dev/null
}

start_session() {
  local payload uuid project proj_dir jsonl_path
  payload=$(read_stdin_payload)
  uuid=$(json_session_id "$payload")
  project=$(detect_project)
  proj_dir=$(project_jsonl_dir "$project")
  if [[ -z "$uuid" ]]; then
    uuid=$(newest_jsonl_uuid "$proj_dir")
  fi
  [[ -z "$uuid" ]] && exit 0
  jsonl_path="$proj_dir/$uuid.jsonl"
  ensure_db
  sqlite3 "$DB" "
    INSERT OR IGNORE INTO sessions (id, label, path, project, created, started_at, source, updated_at)
    VALUES ('$(sql_escape "$uuid")', '$TODAY session', '$(sql_escape "$jsonl_path")', '$(sql_escape "$project")', '$TODAY', '$NOW', 'auto', '$NOW');
  "
  clear_title_marker "$uuid"
  echo "[SESSION] Tracked: ${uuid:0:8}… ($project)"
}

title_session() {
  local payload uuid jsonl title safe_title first_msg safe_first
  payload=$(read_stdin_payload)
  uuid=$(json_session_id "$payload")
  [[ -z "$uuid" ]] && exit 0
  is_titled "$uuid" && exit 0
  jsonl=$(find_jsonl "$uuid" || true)
  [[ -z "$jsonl" || ! -f "$DB" ]] && exit 0
  title=$(extract_ai_title "$jsonl")
  if [[ -n "$title" ]]; then
    safe_title=$(sql_escape "$title")
    sqlite3 "$DB" "
      UPDATE sessions SET label='$safe_title', ai_title='$safe_title', updated_at='$NOW'
      WHERE id='$(sql_escape "$uuid")' AND label LIKE '%-__-__ session';
    "
    first_msg=$(extract_first_user_message "$jsonl" 30 | head -c 200)
    if [[ -n "$first_msg" ]]; then
      safe_first=$(sql_escape "$first_msg")
      sqlite3 "$DB" "UPDATE sessions SET first_msg='$safe_first' WHERE id='$(sql_escape "$uuid")';"
    fi
    mark_titled "$uuid"
  fi
}

close_session() {
  local payload uuid label jsonl fallback safe_fallback started_at decisions commits repo log safe_decisions
  payload=$(read_stdin_payload)
  uuid=$(json_session_id "$payload")
  [[ -z "$uuid" || ! -f "$DB" ]] && exit 0

  sqlite3 "$DB" "
    UPDATE sessions
    SET ended_at='$NOW',
        duration_m = CAST((julianday('$NOW') - julianday(COALESCE(started_at, '$NOW'))) * 1440 AS INTEGER),
        updated_at='$NOW'
    WHERE id='$(sql_escape "$uuid")';
  "

  label=$(sqlite3 "$DB" "SELECT label FROM sessions WHERE id='$(sql_escape "$uuid")';" || true)
  if [[ "$label" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ session$ ]]; then
    jsonl=$(find_jsonl "$uuid" || true)
    if [[ -n "$jsonl" ]]; then
      fallback=$(extract_first_user_message "$jsonl" 30 | python3 -c "import sys; t=sys.stdin.read().strip(); label=t[:60].rstrip(' ,.!?') + ('…' if len(t)>60 else ''); print(label.replace(chr(39), chr(39)*2))" 2>/dev/null || true)
      if [[ -n "$fallback" ]]; then
        safe_fallback=$(sql_escape "$fallback")
        sqlite3 "$DB" "UPDATE sessions SET label='$safe_fallback', updated_at='$NOW' WHERE id='$(sql_escape "$uuid")';"
      fi
    fi
  fi

  started_at=$(sqlite3 "$DB" "SELECT COALESCE(started_at, ended_at) FROM sessions WHERE id='$(sql_escape "$uuid")';" | tr ' ' 'T')
  decisions=""
  if [[ -n "$started_at" ]]; then
    commits=""
    for repo in \
      "$HOME/Documents/Claude Projects/HEALTH" \
      "$HOME/Documents/Claude Projects/WORK" \
      "$HOME/Documents/Claude Projects/TODO" \
      "$HOME/.claude" \
      "$HOME/Documents/Health/dashboard-app"; do
      [[ -d "$repo/.git" ]] || continue
      log=$(git -C "$repo" log --since="$started_at" --oneline --no-merges 2>/dev/null | head -5 || true)
      [[ -n "$log" ]] && commits+="$log"$'\n'
    done
    if [[ -n "$commits" ]]; then
      decisions=$(printf '%s' "$commits" | sed 's/^[a-f0-9]* //' | awk 'NF' | sort -u | head -8 | awk '{print "- " $0}')
    fi
  fi
  if [[ -n "$decisions" ]]; then
    safe_decisions=$(sql_escape "$decisions")
    sqlite3 "$DB" "UPDATE sessions SET decisions='$safe_decisions', updated_at='$NOW' WHERE id='$(sql_escape "$uuid")';"
  fi

  clear_title_marker "$uuid"

  # Sync this session to QMD summaries (background — must not block session close)
  SYNC_SCRIPT="$HOME/.claude/scripts/sync-sessions-to-qmd.py"
  if [[ -f "$SYNC_SCRIPT" ]]; then
    python3 "$SYNC_SCRIPT" >> "$HOME/.claude/logs/session-sync.log" 2>&1 &
  fi
}

case "$ACTION" in
  start) start_session ;;
  close) close_session ;;
  title) title_session ;;
  *) echo "Usage: $0 {start|close|title}" >&2; exit 64 ;;
esac

exit 0
