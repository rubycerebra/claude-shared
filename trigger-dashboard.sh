#!/bin/bash
# Trigger dashboard from Claude Code commands
# Usage:
#   trigger-dashboard.sh              # immediate, opens browser
#   trigger-dashboard.sh --delay      # wait 5s for data, opens browser
#   trigger-dashboard.sh --no-open    # immediate, no browser
#   trigger-dashboard.sh --delay --no-open  # wait + no browser
#   trigger-dashboard.sh --force      # bypass dedup check
#
# IMPORTANT: This script refreshes Diarium + journal data in cache before
# generating the dashboard. No need to run /start-day first for fresh data.
# (AI analysis still requires /start-day — that's Claude's judgment work.)

DELAY=false
NO_OPEN=""
FORCE=false
STRICT_CHECK="${DASHBOARD_STRICT_CHECK:-0}"
LOG_FILE="$HOME/.claude/logs/trigger-dashboard.log"
mkdir -p "$(dirname "$LOG_FILE")"

for arg in "$@"; do
    case $arg in
        --delay)
            DELAY=true
            ;;
        --no-open)
            NO_OPEN="--no-open"
            ;;
        --force)
            FORCE=true
            ;;
    esac
done

if [[ "$DELAY" == "true" ]]; then
    echo "⏳ Waiting for daemon data..."
    sleep 5
fi

# Dedup check: skip if cache hasn't changed since last generation
MARKER="$HOME/.claude/cache/last-dashboard-trigger"
CACHE="$HOME/.claude/cache/session-data.json"

if [[ "$FORCE" != "true" && -f "$MARKER" && -f "$CACHE" ]]; then
    SKIP=$(python3 -c "
import hashlib, json, sys
from datetime import date
try:
    with open('$MARKER') as f: state = json.load(f)
    with open('$CACHE') as f:
        cache = json.load(f)
    cache_ts = cache.get('timestamp', '')
    pieces_fetched_at = ((cache.get('pieces_activity') or {}).get('fetched_at', '') if isinstance(cache.get('pieces_activity'), dict) else '')
    pieces_digest = ((cache.get('pieces_activity') or {}).get('digest', '') if isinstance(cache.get('pieces_activity'), dict) else '')
    pieces_digest_hash = hashlib.md5(str(pieces_digest).encode('utf-8')).hexdigest()[:12] if pieces_digest else ''
    if (
        state.get('date') == str(date.today())
        and state.get('cache_timestamp') == cache_ts
        and state.get('pieces_fetched_at', '') == pieces_fetched_at
        and state.get('pieces_digest_hash', '') == pieces_digest_hash
    ):
        print('skip')
except: pass
" 2>>"$LOG_FILE")
    if [[ "$SKIP" == "skip" ]]; then
        echo "✅ Dashboard up to date (skipped)"
        exit 0
    fi
fi

# Refresh Diarium + journal in cache before generating dashboard
# This ensures the dashboard always shows today's diary data, even without /start-day
# NOTE: Daemon is triggered AFTER this refresh so it sees today's Diarium when
# regenerating day_state_summary (prevents "Continue the strongest work thread"
# from referencing yesterday's activities).
echo "🔄 Refreshing data..."
python3 -c "
import sys, json, subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta

cache_file = Path.home() / '.claude/cache/session-data.json'
if not cache_file.exists():
    print('  ⚠️  No cache file — skipping refresh')
    sys.exit(0)

with open(cache_file) as f:
    raw_cache = f.read()
try:
    cache = json.loads(raw_cache)
except json.JSONDecodeError:
    decoder = json.JSONDecoder()
    idx = 0
    recovered = None
    while idx < len(raw_cache):
        while idx < len(raw_cache) and raw_cache[idx].isspace():
            idx += 1
        if idx >= len(raw_cache):
            break
        try:
            obj, end = decoder.raw_decode(raw_cache, idx)
        except json.JSONDecodeError:
            break
        recovered = obj
        idx = end
    cache = recovered if isinstance(recovered, dict) else {}

now = datetime.now()
effective_today = (now - timedelta(days=1)).strftime('%Y-%m-%d') if now.hour < 3 else now.strftime('%Y-%m-%d')
cache['diarium_fresh'] = False
cache['diarium_fresh_reason'] = 'No fresh Diarium export detected in this trigger run.'
cache.setdefault('diarium_source_date', '')

# Re-parse Diarium (find parser)
parser = None
for p in ['HEALTH', 'TODO', 'WORK']:
    candidate = Path.home() / 'Documents/Claude Projects' / p / '.helpers/parse_diarium.py'
    if candidate.exists():
        parser = candidate
        break

if parser:
    try:
        result = subprocess.run(['python3', str(parser), '--json'], capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and 'No Diarium entry found' not in result.stdout:
            data = json.loads(result.stdout)
            sections = data.get('sections', {})
            analysis = data.get('analysis_context', {})
            weather_raw = str(sections.get('weather', '') or '').strip()
            weather_clean = re.sub(r'^\\s*:\\s*', '', weather_raw).strip()
            location_raw = str(sections.get('location', '') or '').strip()
            location_clean = re.sub(r'^\\s*:\\s*', '', location_raw).strip()
            # Use _raw versions for proper list splitting (voice transcription cleanup collapses newlines)
            ta_dah_raw = sections.get('ta_dah_raw', sections.get('ta_dah', ''))
            ta_dah_list = [item.strip() for item in ta_dah_raw.split('\n\n') if item.strip()] if ta_dah_raw else []

            def _extract_source_date(payload):
                explicit = str(payload.get('source_date', '') or '').strip()
                if re.match(r'^\d{4}-\d{2}-\d{2}$', explicit):
                    return explicit
                source_file = str(payload.get('source_file', '') or '').strip()
                m = re.search(r'(\d{4}-\d{2}-\d{2})', source_file)
                if m:
                    return m.group(1)
                source_files = payload.get('source_files', [])
                if isinstance(source_files, list):
                    for raw in source_files:
                        m2 = re.search(r'(\d{4}-\d{2}-\d{2})', str(raw or ''))
                        if m2:
                            return m2.group(1)
                return ''

            source_date = _extract_source_date(data) or str(cache.get('diarium_source_date', '') or '')
            fallback_raw = data.get('fallback_used', False)
            if isinstance(fallback_raw, bool):
                fallback_used = fallback_raw
            else:
                fallback_used = str(fallback_raw).strip().lower() in {'1', 'true', 'yes', 'y'}
            diarium_is_fresh = bool(source_date and source_date == effective_today and not fallback_used)

            three_things_raw = sections.get('three_things_raw', sections.get('three_things', ''))
            three_things_list = [item.strip() for item in three_things_raw.split('\n\n') if item.strip()] if three_things_raw else []

            # Preserve AI-cleaned fields: if existing diarium has _raw fields,
            # keep the cleaned text and _raw originals instead of overwriting
            existing_diarium = cache.get('diarium', {})
            if not isinstance(existing_diarium, dict):
                existing_diarium = {}

            def _norm_list_item(raw):
                text = re.sub(r'\\s+', ' ', str(raw or '').strip().lower())
                return re.sub(r'[^a-z0-9\\s]', '', text)

            def _merge_unique_list(primary, secondary):
                merged = []
                seen = set()
                for item in list(primary or []) + list(secondary or []):
                    text = str(item or '').strip()
                    if not text:
                        continue
                    key = _norm_list_item(text) or text.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(text)
                return merged

            new_diarium = {
                'status': 'success',
                'grateful': sections.get('grateful', 'Not specified'),
                'intent': sections.get('what_would_make_today_great', 'Not specified'),
                'ta_dah': ta_dah_list,
                'three_things': three_things_list,
                'tomorrow': sections.get('whats_tomorrow', ''),
                'images': data.get('images', []),
                'morning_pages': sections.get('morning_pages', ''),
                'daily_affirmation': sections.get('daily_affirmation', ''),
                'body_check': sections.get('body_check', ''),
                'letting_go': sections.get('letting_go', ''),
                'brave': sections.get('brave', ''),
                'updates': sections.get('updates', ''),
                'remember_tomorrow': sections.get('remember_tomorrow', ''),
                'evening_reflections': sections.get('evening_reflections', ''),
                'weather': weather_clean,
                'location': location_clean or sections.get('location', ''),
                'location_raw': location_raw,
                'locations_detected': sections.get('locations_detected', []),
                'analysis_context': analysis,
                'mood_tag': sections.get('mood_tag', ''),
                'diarium_rating': sections.get('diarium_rating', 0),
                'source_date': source_date,
                'fallback_used': fallback_used,
            }

            # Pull ## Therapy from journal into diarium cache
            try:
                therapy_summary = ''
                journal_file = Path.home() / 'Documents/Claude Projects/claude-shared/journal' / f\"{effective_today}.md\"
                if journal_file.exists():
                    journal_text = journal_file.read_text(encoding='utf-8', errors='ignore')
                    match = re.search(r'(?ms)^## Therapy\\s*\\n(.*?)(?=^##\\s+|\\Z)', journal_text)
                    if match:
                        block = match.group(1).strip()
                        lines = []
                        for raw in block.splitlines():
                            line = raw.strip()
                            if re.match(r'^\\*Captured:\\s+\\d{4}-\\d{2}-\\d{2}\\s+via\\s+[^*]+\\*$', line):
                                continue
                            lines.append(raw.rstrip())
                        therapy_summary = '\\n'.join(lines).strip()
                if therapy_summary:
                    new_diarium['therapy_summary'] = therapy_summary
            except Exception:
                pass

            # Restore _raw fields and AI-cleaned text from daemon cache
            for field in ['grateful', 'intent', 'morning_pages', 'brave', 'body_check',
                          'letting_go', 'daily_affirmation', 'tomorrow',
                          'updates', 'remember_tomorrow', 'evening_reflections']:
                raw_key = f'{field}_raw'
                if raw_key in existing_diarium:
                    new_diarium[field] = existing_diarium[field]
                    new_diarium[raw_key] = existing_diarium[raw_key]
            # Restore AI-cleaned list fields from daemon cache (keep three_things strict).
            for list_field in ['three_things']:
                raw_items_key = f'{list_field}_raw_items'
                if raw_items_key in existing_diarium:
                    # Daemon has AI-cleaned versions — use those instead of raw parser output
                    new_diarium[list_field] = existing_diarium[list_field]
                    new_diarium[raw_items_key] = existing_diarium[raw_items_key]
            # Preserve ta_dah wins merged by completion flows (and parser output).
            # Only merge if re-parsing the SAME day — cross-day merge causes yesterday's
            # ta-dah items to bleed into today's list.
            existing_source = existing_diarium.get('source_date', '') or str(cache.get('diarium_source_date', '') or '')
            if source_date and existing_source == source_date:
                existing_tadah = existing_diarium.get('ta_dah', [])
                if isinstance(existing_tadah, list):
                    new_diarium['ta_dah'] = _merge_unique_list(new_diarium.get('ta_dah', []), existing_tadah)
                if 'ta_dah_raw_items' in existing_diarium and isinstance(existing_diarium.get('ta_dah_raw_items'), list):
                    new_diarium['ta_dah_raw_items'] = _merge_unique_list(
                        existing_diarium.get('ta_dah_raw_items', []),
                        new_diarium.get('ta_dah_raw_items', []),
                    )
            # else: new day — start fresh with only today's parsed items (no cross-day bleed)

            # Add today's completed todo labels as ta_dah fallback.
            completed_file = Path.home() / '.claude/cache/completed-todos.json'
            if completed_file.exists():
                try:
                    completed_payload = json.loads(completed_file.read_text(encoding='utf-8', errors='replace'))
                    if (
                        isinstance(completed_payload, dict)
                        and str(completed_payload.get('date', '')).strip() == effective_today
                        and isinstance(completed_payload.get('completed_labels'), list)
                    ):
                        new_diarium['ta_dah'] = _merge_unique_list(
                            new_diarium.get('ta_dah', []),
                            completed_payload.get('completed_labels', []),
                        )
                except Exception:
                    pass
            # Preserve ALL daemon-enriched keys not already set by parser refresh.
            # This blanket merge replaces the old explicit list — future new daemon
            # fields are preserved automatically without needing manual sync here.
            for key in existing_diarium:
                if key not in new_diarium:
                    new_diarium[key] = existing_diarium[key]

            cache['diarium'] = new_diarium
            cache['diarium_images'] = data.get('images', [])
            cache['diarium_source_date'] = source_date
            cache['diarium_fresh'] = diarium_is_fresh
            if diarium_is_fresh:
                cache['diarium_fresh_reason'] = ''
            elif fallback_used:
                cache['diarium_fresh_reason'] = f'Fallback Diarium export from {source_date or "unknown"} reused; waiting for {effective_today}.'
            elif source_date:
                cache['diarium_fresh_reason'] = f'Latest Diarium export date is {source_date}; waiting for {effective_today}.'
            else:
                cache['diarium_fresh_reason'] = 'Diarium source date missing; waiting for fresh export.'
            print('  ✅ Diarium refreshed (AI-cleaned fields preserved)')
        elif result.returncode == 0:
            cache['diarium_fresh'] = False
            cache['diarium_fresh_reason'] = f'No Diarium entry found for effective date {effective_today}.'
            print(f'  ⚠️  No Diarium entry found for {effective_today} (marked stale)')
        else:
            cache['diarium_fresh'] = False
            stderr = (result.stderr or 'Parser failed').strip().split('\\n')[0][:160]
            cache['diarium_fresh_reason'] = f'Parser failed: {stderr}'
            print(f'  ⚠️  Diarium parser failed (marked stale): {stderr}')
    except Exception as e:
        cache['diarium_fresh'] = False
        cache['diarium_fresh_reason'] = f'Parser exception: {e}'
        print(f'  ⚠️  Diarium refresh failed: {e}')
else:
    cache['diarium_fresh'] = False
    cache['diarium_fresh_reason'] = 'No parser found.'

# Auto-create journal if missing
journal_dir = Path.home() / 'Documents/Claude Projects/claude-shared/journal'
today_file = journal_dir / f\"{datetime.now().strftime('%Y-%m-%d')}.md\"
if not today_file.exists():
    try:
        jm = Path.home() / '.claude/scripts/journal-manager.py'
        if jm.exists():
            subprocess.run(['python3', str(jm), 'create'], capture_output=True, timeout=10)
            print('  ✅ Journal created')
    except Exception:
        pass

# Refresh open loops using latest diary payload
try:
    import importlib.util
    dc_path = Path.home() / '.claude' / 'daemon' / 'data_collector.py'
    spec = importlib.util.spec_from_file_location('dc_mod', dc_path)
    dc_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc_mod)
    collector = dc_mod.DataCollector()
    cache['open_loops'] = collector.check_open_loops(
        diarium_data=cache.get('diarium', {}),
        effective_date=effective_today
    )
    print('  ✅ Open loops refreshed')
except Exception as e:
    print(f'  ⚠️  Open loops refresh failed: {e}')

# Update timestamp and write back
cache['timestamp'] = datetime.now().isoformat()
cache['time'] = datetime.now().strftime('%H:%M')
with open(cache_file, 'w') as f:
    json.dump(cache, f, indent=2)
print('  ✅ Cache updated')
" 2>>"$LOG_FILE"

# Now trigger daemon to re-fetch external sources (HealthFit, calendar, etc.)
# Running AFTER Diarium refresh ensures daemon sees today's Diarium when
# regenerating day_state_summary — fixes cross-day context in "work thread" insights.
touch "$HOME/.claude/cache/trigger-refresh"
sleep 8  # Give daemon time to fetch from GSheet + write cache

# Generate dashboard (pass through --no-open if specified)
python3 ~/Documents/Claude\ Projects/claude-shared/generate-dashboard.py $NO_OPEN || { echo "Dashboard generation failed"; exit 1; }

# Section integrity checks (warn by default; fail when DASHBOARD_STRICT_CHECK=1)
python3 - <<'PY' 2>>"$LOG_FILE"
import json
from pathlib import Path
import sys

cache_path = Path.home() / ".claude" / "cache" / "session-data.json"
dashboard_path = Path.home() / "Documents" / "Claude Projects" / "claude-shared" / "dashboard.html"

issues = []
cache = {}
try:
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8", errors="replace"))
except Exception as exc:
    issues.append(f"cache_read_failed:{exc}")

if not dashboard_path.exists():
    issues.append("dashboard_missing")
    html = ""
else:
    html = dashboard_path.read_text(encoding="utf-8", errors="replace")

for section_id in ("morning", "evening"):
    if f'id="{section_id}"' not in html:
        issues.append(f"missing_section:{section_id}")

if 'id="day"' not in html and 'data-focus="day' not in html:
    issues.append("missing_section:day_phase")

if "digest generating…" in html or "digest generating..." in html:
    issues.append("legacy_digest_generating_message_present")

pieces = cache.get("pieces_activity", {}) if isinstance(cache, dict) else {}
pieces_count = int(pieces.get("count", 0) or 0) if isinstance(pieces, dict) else 0
pieces_status = str(pieces.get("status", "")).strip().lower() if isinstance(pieces, dict) else ""
if pieces_status == "ok" and pieces_count > 0:
    if 'id="pieces"' not in html:
        issues.append("missing_pieces_section")
    if "🛠️ What you worked on today" not in html:
        issues.append("missing_evening_pieces_block")

if issues:
    print("⚠️ Dashboard integrity warnings: " + "; ".join(issues))
    sys.exit(2)
print("✅ Dashboard integrity checks passed")
PY
INTEGRITY_EXIT=$?
if [[ $INTEGRITY_EXIT -ne 0 ]]; then
    if [[ "$STRICT_CHECK" == "1" ]]; then
        echo "❌ Dashboard integrity check failed (strict mode)"
        exit 1
    fi
    echo "⚠️ Dashboard integrity warnings (non-strict mode); continuing"
fi

# Write state file
python3 -c "
import json
import hashlib
from datetime import date
from pathlib import Path
cache_ts = ''
pieces_fetched_at = ''
pieces_digest_hash = ''
try:
    with open(Path.home() / '.claude/cache/session-data.json') as f:
        cache = json.load(f)
        cache_ts = cache.get('timestamp', '')
        if isinstance(cache.get('pieces_activity'), dict):
            pieces_fetched_at = cache.get('pieces_activity', {}).get('fetched_at', '')
            pieces_digest = str(cache.get('pieces_activity', {}).get('digest', '') or '')
            pieces_digest_hash = hashlib.md5(pieces_digest.encode('utf-8')).hexdigest()[:12] if pieces_digest else ''
except: pass
state = {
    'date': str(date.today()),
    'cache_timestamp': cache_ts,
    'pieces_fetched_at': pieces_fetched_at,
    'pieces_digest_hash': pieces_digest_hash,
    'notes_synced': False
}
with open(Path.home() / '.claude/cache/last-dashboard-trigger', 'w') as f:
    json.dump(state, f)
" 2>>"$LOG_FILE"

if [[ -z "$NO_OPEN" ]]; then
    echo "✅ Dashboard opened in browser"
else
    echo "✅ Dashboard generated (no browser)"
fi
