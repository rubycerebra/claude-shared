#!/bin/bash
# Trigger dashboard from Claude Code commands
# Usage:
#   trigger-dashboard.sh              # immediate, opens browser
#   trigger-dashboard.sh --delay      # wait 5s for data, opens browser
#   trigger-dashboard.sh --no-open    # immediate, no browser
#   trigger-dashboard.sh --delay --no-open  # wait + no browser
#   trigger-dashboard.sh --force      # bypass dedup check
#   trigger-dashboard.sh --cache-only # regenerate HTML from existing cache only (no daemon refresh)
#
# IMPORTANT: By default this script refreshes Diarium + journal data in cache
# before generating the dashboard. Use --cache-only to skip refresh/daemon
# triggers and regenerate purely from current cache state.

PYTHON="$HOME/.claude/daemon/venv/bin/python3"
DELAY=false
NO_OPEN=""
FORCE=false
CACHE_ONLY=false
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
        --cache-only)
            CACHE_ONLY=true
            ;;
    esac
done

if [[ "$DELAY" == "true" ]]; then
    echo "⏳ Waiting for daemon data..."
    sleep 5
fi

# Clear Readwise dedup markers on --force so re-sends work
if [[ "$FORCE" == "true" ]]; then
    rm -f "$HOME/.claude/cache/readwise-sent/"*dashboard* 2>/dev/null
    rm -f "$HOME/.claude/cache/readwise-sent/"*daily* 2>/dev/null
fi

# Dedup check: skip if cache hasn't changed since last generation
MARKER="$HOME/.claude/cache/last-dashboard-trigger"
CACHE="$HOME/.claude/cache/session-data.json"

if [[ "$FORCE" != "true" && -f "$MARKER" && -f "$CACHE" ]]; then
    SKIP=$($PYTHON -c "
import errno
import hashlib, json, sys, time
from datetime import datetime, timedelta

def _effective_today():
    now = datetime.now()
    if now.hour < 3:
        return (now - timedelta(days=1)).strftime('%Y-%m-%d')
    return now.strftime('%Y-%m-%d')

def _read_json_retry(path, retries=(0.0, 0.25, 0.75)):
    for idx, delay in enumerate(retries):
        try:
            if delay:
                time.sleep(delay)
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except OSError as exc:
            if exc.errno == errno.EDEADLK and idx < len(retries) - 1:
                continue
            raise

try:
    state = _read_json_retry('$MARKER')
    cache = _read_json_retry('$CACHE')
    cache_ts = cache.get('timestamp', '')
    pieces_fetched_at = ((cache.get('pieces_activity') or {}).get('fetched_at', '') if isinstance(cache.get('pieces_activity'), dict) else '')
    pieces_digest = ((cache.get('pieces_activity') or {}).get('digest', '') if isinstance(cache.get('pieces_activity'), dict) else '')
    pieces_digest_hash = hashlib.md5(str(pieces_digest).encode('utf-8')).hexdigest()[:12] if pieces_digest else ''
    if (
        state.get('date') == _effective_today()
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

if [[ "$CACHE_ONLY" != "true" ]]; then
    # Refresh Diarium + journal in cache before generating dashboard
    # This ensures the dashboard always shows today's diary data, even without /start-day
    # NOTE: Daemon is triggered AFTER this refresh so it sees today's Diarium when
    # regenerating day_state_summary (prevents "Continue the strongest work thread"
    # from referencing yesterday's activities).
    echo "🔄 Refreshing data..."
    $PYTHON -c "
import sys, json, subprocess, os, errno, shutil, time, random
import re
from pathlib import Path
from datetime import datetime, timedelta

cache_file = Path.home() / '.claude/cache/session-data.json'
if not cache_file.exists():
    print('  ⚠️  No cache file — skipping refresh')
    sys.exit(0)

def _read_text_retry(path, *, retries=(0.0, 0.25, 0.75), encoding='utf-8', errors='replace'):
    target = Path(path)
    for idx, delay in enumerate(retries):
        try:
            if delay:
                # small jitter helps when iCloud/FUSE locks are flapping
                time.sleep(delay + random.uniform(0, 0.1))
            return target.read_text(encoding=encoding, errors=errors)
        except OSError as exc:
            if exc.errno == errno.EDEADLK and idx < len(retries) - 1:
                continue
            raise

try:
    raw_cache = _read_text_retry(cache_file, retries=(0.0, 0.2, 0.6, 1.2))
except OSError as read_exc:
    if read_exc.errno == errno.EDEADLK:
        print('  ⚠️  Cache read locked (EDEADLK) — preserving last-known-good cache state')
        sys.exit(0)
    raise
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

def _atomic_write_json_preserve(path, payload, *, snapshot_path=None, label='file'):
    target = Path(path)
    tmp = Path(f'{target}.tmp')
    try:
        if snapshot_path and target.exists():
            snapshot = Path(snapshot_path)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, snapshot)
    except Exception as snap_exc:
        print(f'  ⚠️  Could not snapshot {target.name}: {snap_exc}')

    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, target)
        return True
    except OSError as write_exc:
        if write_exc.errno == errno.ENOSPC:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            print(f'  ⚠️  ENOSPC while writing {label}; preserving existing file')
            return False
        raise


def _cache_path_write_healthy(path):
    probe = Path(path).parent / '.trigger-dashboard-write-probe.tmp'
    try:
        with open(probe, 'w', encoding='utf-8') as f:
            f.write('ok')
        probe.unlink(missing_ok=True)
        return True
    except OSError as probe_exc:
        if probe_exc.errno == errno.ENOSPC:
            print('  ⚠️  Cache path unhealthy (ENOSPC) — skipping destructive refresh')
            return False
        print(f'  ⚠️  Cache path probe failed: {probe_exc}')
        return False
    except Exception as probe_exc:
        print(f'  ⚠️  Cache path probe failed: {probe_exc}')
        return False


if not _cache_path_write_healthy(cache_file):
    sys.exit(0)

now = datetime.now()
effective_today = (now - timedelta(days=1)).strftime('%Y-%m-%d') if now.hour < 3 else now.strftime('%Y-%m-%d')
cache['diarium_fresh'] = False
cache['diarium_fresh_reason'] = 'No fresh Diarium export detected in this trigger run.'
cache.setdefault('diarium_source_date', '')
existing_diarium_cache = cache.get('diarium', {}) if isinstance(cache.get('diarium', {}), dict) else {}
existing_source_date = str(cache.get('diarium_source_date', '') or '').strip()
existing_diarium_is_today = bool(existing_diarium_cache and existing_source_date == effective_today)
snapshot_file = cache_file.with_name('session-data.last-good.json')
try:
    shutil.copy2(cache_file, snapshot_file)
except Exception as snapshot_exc:
    print(f'  ⚠️  Last-good snapshot skipped: {snapshot_exc}')

# ── Reset stale completed-todos.json at day boundary ──
_completed_f = Path.home() / '.claude/cache/completed-todos.json'
if _completed_f.exists():
    try:
        _ct = json.loads(_read_text_retry(_completed_f, retries=(0.0, 0.2, 0.6), encoding='utf-8', errors='replace'))
        if isinstance(_ct, dict) and str(_ct.get('date', '')).strip() != effective_today:
            _completed_reset = {
                'date': effective_today,
                'completed': [],
                'completed_texts': [],
                'completed_labels': [],
                'completed_at': {},
                'completed_source': {}
            }
            if _atomic_write_json_preserve(_completed_f, _completed_reset, label='completed-todos.json'):
                print(f'  ♻️  Reset completed-todos.json for {effective_today}')
    except Exception:
        pass

# Re-parse Diarium (find parser)
parser = None
for p in ['HEALTH', 'TODO', 'WORK']:
    candidate = Path.home() / 'Documents/Claude Projects' / p / '.helpers/parse_diarium.py'
    if candidate.exists():
        parser = candidate
        break

if parser:
    try:
        result = None
        parser_err = ''
        for timeout_s in (15, 30):
            try:
                attempt = subprocess.run(
                    ['python3', str(parser), '--json'],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s
                )
                result = attempt
                if attempt.returncode == 0:
                    break
                parser_err = (attempt.stderr or f'Parser exited {attempt.returncode}').strip().split('\\n')[0][:160]
            except subprocess.TimeoutExpired:
                parser_err = f'timed out after {timeout_s}s'
                result = None
                continue
            except Exception as parser_exc:
                parser_err = str(parser_exc)
                result = None
                break

        if result is None and parser_err:
            if existing_diarium_is_today:
                cache['diarium_fresh'] = True
                cache['diarium_source_date'] = existing_source_date
                cache['diarium_fresh_reason'] = f'Parser unavailable ({parser_err}); keeping last same-day Diarium cache.'
                print(f'  ⚠️  Diarium parser unavailable ({parser_err}) — keeping cached same-day data')
            else:
                cache['diarium_fresh'] = False
                cache['diarium_fresh_reason'] = f'Parser failed: {parser_err}'
                print(f'  ⚠️  Diarium parser failed (marked stale): {parser_err}')
        elif result and result.returncode == 0 and 'No Diarium entry found' not in result.stdout:
            data = json.loads(result.stdout)
            sections = data.get('sections', {})
            analysis = data.get('analysis_context', {})
            weather_raw = str(sections.get('weather', '') or '').strip()
            weather_clean = re.sub(r'^\\s*:\\s*', '', weather_raw).strip()
            location_raw = str(sections.get('location', '') or '').strip()
            location_clean = re.sub(r'^\\s*:\\s*', '', location_raw).strip()
            # Use _raw versions for proper list splitting (voice transcription cleanup collapses newlines)
            ta_dah_raw = sections.get('ta_dah_raw', sections.get('ta_dah', ''))
            ta_dah_list = [re.sub(r'^(?:\d+[.)]\s*|[-*\u2022\u2219\u2023]\s*)', '', item).strip() for item in re.split(r'\n+', ta_dah_raw) if item.strip()] if ta_dah_raw else []

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
            three_things_list = [re.sub(r'^(?:\d+[.)]\s*|[-*\u2022\u2219\u2023]\s*)', '', item).strip() for item in re.split(r'\n+', three_things_raw) if item.strip()] if three_things_raw else []

            # Preserve AI-cleaned fields: if existing diarium has _raw fields,
            # keep the cleaned text and _raw originals instead of overwriting
            existing_diarium = cache.get('diarium', {})
            if not isinstance(existing_diarium, dict):
                existing_diarium = {}

            def _strip_completion_hash_artifacts(raw):
                text = str(raw or '').strip()
                if not text:
                    return ''
                previous = None
                while text and text != previous:
                    previous = text
                    text = re.sub(r'\s*~~+\s*\[?\s*[0-9a-f]{6,16}\s*\]?\s*$', '', text, flags=re.IGNORECASE).strip()
                    text = re.sub(r'\s*\[\s*[0-9a-f]{6,16}\s*\]\s*$', '', text, flags=re.IGNORECASE).strip()
                    text = re.sub(r'(?:\s+[0-9a-f]{6,12})+\s*$', '', text, flags=re.IGNORECASE).strip()
                    text = re.sub(r'^\s*~~+\s*', '', text).strip()
                    text = re.sub(r'\s*~~+\s*$', '', text).strip()
                return re.sub(r'\s+', ' ', text).strip()

            def _norm_list_item(raw):
                text = _strip_completion_hash_artifacts(raw).lower()
                text = re.sub(r'\\s+', ' ', text)
                text = re.sub(r'\\b(?:the|a|an)\\b', ' ', text)
                text = re.sub(r'\\s+', ' ', text).strip()
                return re.sub(r'[^a-z0-9\\s]', '', text)

            def _merge_unique_list(primary, secondary):
                merged = []
                seen = set()
                for item in list(primary or []) + list(secondary or []):
                    text = _strip_completion_hash_artifacts(item)
                    if not text:
                        continue
                    key = _norm_list_item(text) or text.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(text)
                return merged

            def _normalise_section_status(raw_status, value):
                status = str(raw_status or '').strip().upper()
                if status in {'ABSENT', 'PRESENT_EMPTY', 'PRESENT_VALUE'}:
                    return status
                return 'PRESENT_VALUE' if str(value or '').strip() else 'ABSENT'

            new_diarium = {
                'status': 'success',
                'grateful': sections.get('grateful', 'Not specified'),
                'intent': sections.get('what_would_make_today_great', 'Not specified'),
                'ta_dah': ta_dah_list,
                'three_things': three_things_list,
                'tomorrow': sections.get('whats_tomorrow', ''),
                'tomorrow_raw': sections.get('whats_tomorrow_raw', ''),
                'images': data.get('images', []),
                'morning_pages': sections.get('morning_pages', ''),
                'daily_affirmation': sections.get('daily_affirmation', ''),
                'body_check': sections.get('body_check', ''),
                'letting_go': sections.get('letting_go', ''),
                'brave': sections.get('brave', ''),
                'updates': sections.get('updates', ''),
                'remember_tomorrow': sections.get('remember_tomorrow', ''),
                'remember_tomorrow_raw': sections.get('remember_tomorrow_raw', ''),
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

            tomorrow_status = _normalise_section_status(
                sections.get('whats_tomorrow_status'),
                sections.get('whats_tomorrow', ''),
            )
            remember_status = _normalise_section_status(
                sections.get('remember_tomorrow_status'),
                sections.get('remember_tomorrow', ''),
            )
            new_diarium['tomorrow_status'] = tomorrow_status
            new_diarium['remember_tomorrow_status'] = remember_status

            # Only carry forward tomorrow fields within the same effective day —
            # cross-day carry-forward produces stale "Tomorrow" text on the dashboard.
            _same_effective_day = bool(source_date and existing_source_date and source_date == existing_source_date)

            for field, status, raw_key, status_key, last_key, source_field in (
                ('tomorrow', tomorrow_status, 'tomorrow_raw', 'tomorrow_status', 'tomorrow_last_nonempty', 'whats_tomorrow'),
                ('remember_tomorrow', remember_status, 'remember_tomorrow_raw', 'remember_tomorrow_status', 'remember_tomorrow_last_nonempty', 'remember_tomorrow'),
            ):
                incoming = str(sections.get(source_field, '') or '').strip()
                existing_val = str(existing_diarium.get(field, '') or '').strip()
                existing_last = existing_diarium.get(last_key)
                if status == 'ABSENT' and existing_val and _same_effective_day:
                    new_diarium[field] = existing_diarium.get(field, '')
                    if raw_key in existing_diarium:
                        new_diarium[raw_key] = existing_diarium[raw_key]
                    new_diarium[status_key] = str(existing_diarium.get(status_key, 'PRESENT_VALUE') or 'PRESENT_VALUE')
                    if existing_last:
                        new_diarium[last_key] = existing_last
                elif status == 'ABSENT' and existing_val and not _same_effective_day:
                    new_diarium[field] = ''
                    new_diarium[status_key] = 'ABSENT'
                    if existing_last:
                        new_diarium[last_key] = existing_last
                elif status == 'PRESENT_EMPTY':
                    new_diarium[field] = ''
                    new_diarium.pop(raw_key, None)
                    new_diarium[status_key] = 'PRESENT_EMPTY'
                    if existing_last:
                        new_diarium[last_key] = existing_last
                else:
                    new_diarium[field] = incoming
                    new_diarium[status_key] = 'PRESENT_VALUE' if incoming else 'PRESENT_EMPTY'
                    if incoming:
                        new_diarium[last_key] = {
                            'value': incoming,
                            'source_date': source_date,
                            'source_file': data.get('source_file', ''),
                            'updated_at': datetime.now().isoformat(),
                        }
                    elif existing_last:
                        new_diarium[last_key] = existing_last

            # Pull ## Therapy from journal into diarium cache
            try:
                therapy_summary = ''
                journal_file = Path.home() / 'Documents/Claude Projects/claude-shared/journal' / f\"{effective_today}.md\"
                if journal_file.exists():
                    journal_text = _read_text_retry(journal_file, retries=(0.0, 0.25, 0.75), encoding='utf-8', errors='ignore')
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
                          'letting_go', 'daily_affirmation', 'updates', 'evening_reflections']:
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
            # IMPORTANT: do not merge cached ta_dah back into parser output.
            # Cached ta_dah can contain prior-day carryover from older runs, which
            # causes yesterday items to bleed into today's section. We keep parser
            # output for this refresh as source-of-truth, then append only explicit
            # same-day completions from completed-todos.json below.

            # Add today's completed todo labels as ta_dah fallback.
            completed_file = Path.home() / '.claude/cache/completed-todos.json'
            if completed_file.exists():
                try:
                    completed_payload = json.loads(_read_text_retry(completed_file, retries=(0.0, 0.2, 0.6), encoding='utf-8', errors='replace'))
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
        elif result and result.returncode == 0:
            cache['diarium_fresh'] = False
            cache['diarium_fresh_reason'] = f'No Diarium entry found for effective date {effective_today}.'
            print(f'  ⚠️  No Diarium entry found for {effective_today} (marked stale)')
        else:
            stderr = (result.stderr or parser_err or 'Parser failed').strip().split('\\n')[0][:160]
            if existing_diarium_is_today:
                cache['diarium_fresh'] = True
                cache['diarium_source_date'] = existing_source_date
                cache['diarium_fresh_reason'] = f'Parser unavailable ({stderr}); keeping last same-day Diarium cache.'
                print(f'  ⚠️  Diarium parser unavailable ({stderr}) — keeping cached same-day data')
            else:
                cache['diarium_fresh'] = False
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
today_file = journal_dir / f\"{effective_today}.md\"
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
if _atomic_write_json_preserve(
    cache_file,
    cache,
    snapshot_path=snapshot_file,
    label='session-data.json',
):
    print('  ✅ Cache updated')
else:
    print('  ⚠️  Cache update skipped (preserved existing session-data.json)')
" 2>>"$LOG_FILE"

    # Now trigger daemon to re-fetch external sources (HealthFit, calendar, etc.)
    # Running AFTER Diarium refresh ensures daemon sees today's Diarium when
    # regenerating day_state_summary — fixes cross-day context in "work thread" insights.
    touch "$HOME/.claude/cache/trigger-refresh"
    sleep 8  # Give daemon time to fetch from GSheet + write cache
else
    echo "ℹ️ Cache-only mode: skipping refresh + daemon trigger"
fi

# Generate dashboard (pass through --no-open if specified)
$PYTHON ~/Documents/Claude\ Projects/claude-shared/generate-dashboard.py $NO_OPEN || { echo "Dashboard generation failed"; exit 1; }

# Section integrity checks (warn by default; fail when DASHBOARD_STRICT_CHECK=1)
$PYTHON - <<'PY' 2>>"$LOG_FILE"
import json
import errno
import random
import time
from pathlib import Path
import sys

cache_path = Path.home() / ".claude" / "cache" / "session-data.json"
dashboard_path = Path.home() / "Documents" / "Claude Projects" / "claude-shared" / "dashboard.html"

issues = []
cache = {}

def _read_text_retry(path, *, retries=(0.0, 0.25, 0.75), encoding="utf-8", errors="replace"):
    target = Path(path)
    for idx, delay in enumerate(retries):
        try:
            if delay:
                time.sleep(delay + random.uniform(0, 0.08))
            return target.read_text(encoding=encoding, errors=errors)
        except OSError as exc:
            if exc.errno == errno.EDEADLK and idx < len(retries) - 1:
                continue
            raise

try:
    if cache_path.exists():
        cache = json.loads(_read_text_retry(cache_path, retries=(0.0, 0.2, 0.6), encoding="utf-8", errors="replace"))
except Exception as exc:
    issues.append(f"cache_read_failed:{exc}")

if not dashboard_path.exists():
    issues.append("dashboard_missing")
    html = ""
else:
    try:
        html = _read_text_retry(dashboard_path, retries=(0.0, 0.2, 0.6), encoding="utf-8", errors="replace")
    except Exception as exc:
        issues.append(f"dashboard_read_failed:{exc}")
        html = ""

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
$PYTHON -c "
import json
import errno
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path

def _effective_today():
    now = datetime.now()
    if now.hour < 3:
        return (now - timedelta(days=1)).strftime('%Y-%m-%d')
    return now.strftime('%Y-%m-%d')

def _read_json_retry(path, retries=(0.0, 0.25, 0.75)):
    for idx, delay in enumerate(retries):
        try:
            if delay:
                time.sleep(delay)
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except OSError as exc:
            if exc.errno == errno.EDEADLK and idx < len(retries) - 1:
                continue
            raise

cache_ts = ''
pieces_fetched_at = ''
pieces_digest_hash = ''
try:
    cache = _read_json_retry(Path.home() / '.claude/cache/session-data.json')
    cache_ts = cache.get('timestamp', '')
    if isinstance(cache.get('pieces_activity'), dict):
        pieces_fetched_at = cache.get('pieces_activity', {}).get('fetched_at', '')
        pieces_digest = str(cache.get('pieces_activity', {}).get('digest', '') or '')
        pieces_digest_hash = hashlib.md5(pieces_digest.encode('utf-8')).hexdigest()[:12] if pieces_digest else ''
except: pass
state = {
    'date': _effective_today(),
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
