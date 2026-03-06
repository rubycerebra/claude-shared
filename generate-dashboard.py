#!/usr/bin/env python3
"""
Generate Jim's Daily Dashboard as a standalone HTML file.
Reads DIRECTLY from daemon cache (session-data.json) for fresh data.

Colour palette: Dark mode with pastel mint green + pink (autism-friendly).
Layout: Action Items (with close controls + open loops) → Mood → Morning entries → Morning Insights → Evening entries → Evening Insights → Calendar/Ta-Dah → Jobs → Habits

Usage:
    python3 generate-dashboard.py
    # Opens dashboard in default browser

Called by Raycast shortcut or Code commands.
"""

import html
import json
import os
import re
import socket
import sys
import webbrowser
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen

# Import shared synthesis logic (used by both Apple Notes + Raycast HTML dashboard)
sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))
from shared.insights import synthesise_top_insights
from shared.cache_dates import get_effective_date, get_ai_day, normalize_ai_cache_for_date
from shared.workout_logic import (
    is_streaks_export_today,
    is_healthfit_export_today,
    extract_healthfit_sleep_hours,
    derive_workout_progression,
    workout_progression_view,
)
from dashboard_action_items import (
    FUTURE_KEYWORDS,
    collect_akiflow_today_items,
    compact_task_text,
    infer_target_date_from_text,
    is_actionable_task,
    is_future_facing_task,
    load_dashboard_action_state,
    load_action_item_defer_rows as _load_action_item_defer_rows,
    load_action_item_defer_targets as _load_action_item_defer_targets,
    load_active_action_item_state_rows as _load_active_action_item_state_rows,
    load_completed_todo_state,
    save_action_item_state as _save_action_item_state,
    task_completion_hash,
    task_completion_hash_legacy,
    task_match_key,
    task_matches_completed_text,
    tasks_equivalent,
)
from dashboard_daily_report import (
    DAILY_REPORT_FILE,
    build_daily_report_context,
    compose_today_fallback as compose_daily_report_today_fallback,
    compose_tomorrow_fallback as compose_daily_report_tomorrow_fallback,
    parse_journal as parse_daily_report_journal,
    parse_saved_report_html,
    report_is_evening_ready,
)
from dashboard_film_recommendations import build_watch_recommendations
from dashboard_freshness_ideas import (
    build_backend_status_pills_html,
    build_section_freshness_html,
    build_today_section_freshness_registry,
    build_important_thing_warning_html,
    build_freshness_watch_html,
    build_ideas_status_html,
    build_stale_notice_html,
    build_system_status_html,
    compute_cache_freshness,
    compute_diarium_freshness,
    compute_diarium_pickup_freshness,
    compute_freshness_overview,
    compute_mood_freshness,
    narrative_contradiction_reason,
    resolve_ai_path_status,
)
from dashboard_state_vector import build_daily_state_vector, build_state_vector_html
from dashboard_static_css import build_dashboard_utility_css
from dashboard_day_narrative import (
    collect_day_narrative_lines,
    compose_day_narrative,
    split_day_narrative_paragraphs,
)
from dashboard_value_helpers import (
    coerce_choice,
    coerce_optional_int,
    end_day_status_text,
    input_num_text,
)


# Paths
DAEMON_CACHE = Path.home() / ".claude" / "cache" / "session-data.json"
SHARED_DIR = Path.home() / "Documents" / "Claude Projects" / "claude-shared"
WINS_FILE = SHARED_DIR / "wins.md"
JOURNAL_DIR = SHARED_DIR / "journal"  # Used only for hyperlinks, not for reading raw text
OUTPUT_FILE = SHARED_DIR / "dashboard.html"
COMPLETED_TODOS_FILE = Path.home() / ".claude" / "cache" / "completed-todos.json"

DASHBOARD_DUMP_MARKER_PATTERNS = (
    r"^\s*(?:📊\s*)?Dashboard\s*[-—:|]",
    r"^\s*🗓️?\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s*$",
    r"^\s*🌅\s*Morning\b",
    r"^\s*🌙\s*Evening\b",
    r"^\s*💡\s*Today[’']s Guidance\b",
    r"^\s*✅\s*Completed today\b",
)


def _iso_to_ts(raw):
    try:
        return datetime.fromisoformat(str(raw).strip()).timestamp()
    except Exception:
        return 0.0


def _clock_hhmm(raw):
    try:
        stamp = datetime.fromisoformat(str(raw).strip())
    except Exception:
        return ""
    return stamp.strftime("%H:%M")


def _parse_ymd(raw):
    try:
        return datetime.strptime(str(raw or "").strip(), "%Y-%m-%d")
    except Exception:
        return None


def _latest_diarium_source_iso(cache, effective_date):
    """Best-effort timestamp for the latest Diarium source text for the effective day."""
    if not isinstance(cache, dict):
        return ""
    candidates = []
    pickup = cache.get("diarium_pickup_status", {}) if isinstance(cache.get("diarium_pickup_status", {}), dict) else {}
    latest_file = str(pickup.get("latest_file", "") or "").strip()
    latest_file_mtime = str(pickup.get("latest_file_mtime", "") or "").strip()
    if latest_file_mtime:
        candidates.append(latest_file_mtime)
    if latest_file:
        try:
            fp = Path(latest_file)
            if fp.exists():
                candidates.append(datetime.fromtimestamp(fp.stat().st_mtime).isoformat(timespec="seconds"))
        except Exception:
            pass
    diarium = cache.get("diarium", {}) if isinstance(cache.get("diarium", {}), dict) else {}
    source_date = str(diarium.get("source_date", "") or "").strip()
    source_file = str(diarium.get("source_file", "") or "").strip()
    if source_file and (not source_date or source_date == effective_date):
        try:
            sf = Path(source_file)
            if sf.exists():
                candidates.append(datetime.fromtimestamp(sf.stat().st_mtime).isoformat(timespec="seconds"))
        except Exception:
            pass
    best = ""
    best_ts = 0.0
    for raw in candidates:
        ts = _iso_to_ts(raw)
        if ts and ts > best_ts:
            best = str(raw).strip()
            best_ts = ts
    return best


def _latest_ai_generated_iso(ai_day):
    if not isinstance(ai_day, dict):
        return ""
    candidates = []
    narrative_meta = ai_day.get("narrative_meta", {}) if isinstance(ai_day.get("narrative_meta", {}), dict) else {}
    for key in ("source_max_ts", "generated_at", "source_generated_at", "updated_at"):
        value = str(narrative_meta.get(key, "") or "").strip()
        if value:
            candidates.append(value)
    for key in ("daily_guidance", "tomorrow_guidance", "tomorrow_suggestions"):
        payload = ai_day.get(key, {})
        if isinstance(payload, dict):
            value = str(payload.get("generated_at", "") or "").strip()
            if value:
                candidates.append(value)
    best = ""
    best_ts = 0.0
    for raw in candidates:
        ts = _iso_to_ts(raw)
        if ts and ts > best_ts:
            best = str(raw).strip()
            best_ts = ts
    return best


def _apply_diarium_alignment_guard(ai_cache, cache, effective_date, tolerance_seconds=120):
    """
    Mark stale alignment when AI output predates latest Diarium source text.
    Non-destructive: preserves action items/insights and surfaces freshness metadata.
    """
    if not isinstance(ai_cache, dict):
        return ai_cache, {"active": False, "reason": "no_ai_cache"}
    ai_day = get_ai_day(ai_cache, effective_date)
    if not isinstance(ai_day, dict):
        return ai_cache, {"active": False, "reason": "no_ai_day"}
    if str(ai_day.get("status", "")).strip().lower() != "success":
        return ai_cache, {"active": False, "reason": "ai_day_not_success"}

    diarium_iso = _latest_diarium_source_iso(cache, effective_date)
    ai_iso = _latest_ai_generated_iso(ai_day)
    diarium_ts = _iso_to_ts(diarium_iso)
    ai_ts = _iso_to_ts(ai_iso)
    if not diarium_ts or not ai_ts:
        return ai_cache, {"active": False, "reason": "missing_timestamps", "diarium_iso": diarium_iso, "ai_iso": ai_iso}
    if ai_ts + float(tolerance_seconds) >= diarium_ts:
        return ai_cache, {"active": False, "reason": "aligned", "diarium_iso": diarium_iso, "ai_iso": ai_iso}

    guarded_day = dict(ai_day)
    last_known_good_at = str(guarded_day.get("last_known_good_at", "") or ai_iso).strip() or ai_iso
    guarded_day["stale_reason"] = "ai_predates_diarium_source_text"
    guarded_day["last_known_good_at"] = last_known_good_at
    narrative_meta = guarded_day.get("narrative_meta", {}) if isinstance(guarded_day.get("narrative_meta", {}), dict) else {}
    narrative_meta = dict(narrative_meta)
    narrative_meta["freshness_state"] = "stale_diarium_lag"
    narrative_meta["stale_reason"] = "ai_predates_diarium_source_text"
    narrative_meta["ai_generated_at"] = ai_iso
    narrative_meta["diarium_source_mtime"] = diarium_iso
    narrative_meta["last_known_good_at"] = last_known_good_at
    guarded_day["narrative_meta"] = narrative_meta

    guarded_cache = dict(ai_cache)
    by_date = dict(guarded_cache.get("by_date", {})) if isinstance(guarded_cache.get("by_date", {}), dict) else {}
    by_date[effective_date] = guarded_day
    guarded_cache["by_date"] = by_date
    guarded_cache["date"] = effective_date
    guarded_cache["status"] = guarded_day.get("status", "success")
    guarded_cache["latest_summary"] = guarded_day.get("latest_summary", "")
    guarded_cache["latest_patterns"] = guarded_day.get("latest_patterns", "")
    guarded_cache["entries"] = guarded_day.get("entries", [])
    guarded_cache["all_insights"] = guarded_day.get("all_insights", [])
    guarded_cache["genuine_todos"] = guarded_day.get("genuine_todos", [])

    return guarded_cache, {
        "active": True,
        "reason": "ai_predates_diarium_source_text",
        "diarium_iso": diarium_iso,
        "ai_iso": ai_iso,
    }


def _dashboard_dump_start_index(raw_text):
    raw = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return None

    earliest = None
    for pattern in DASHBOARD_DUMP_MARKER_PATTERNS:
        match = re.search(pattern, raw, flags=re.IGNORECASE | re.MULTILINE)
        if match and (earliest is None or match.start() < earliest):
            earliest = match.start()

    if earliest is None:
        return None

    suffix = raw[earliest:].strip()
    heading_hits = sum(
        1
        for pattern in DASHBOARD_DUMP_MARKER_PATTERNS
        if re.search(pattern, suffix, flags=re.IGNORECASE | re.MULTILINE)
    )
    suffix_lower = suffix.lower()
    strong_signals = sum(
        1
        for token in (
            "dashboard",
            "morning insights",
            "today's guidance",
            "todays guidance",
            "what you did today",
            "mood + anxiety",
        )
        if token in suffix_lower
    )
    looks_like_dump = heading_hits >= 2 or strong_signals >= 2 or len(suffix) >= 600
    return earliest if looks_like_dump else None


def _strip_dashboard_dump_suffix(raw_text):
    raw = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return "", False
    dump_start = _dashboard_dump_start_index(raw)
    if dump_start is None:
        return raw, False
    return raw[:dump_start].rstrip(), True


def _dedupe_insights_for_display(insights):
    """Deduplicate insights for dashboard display by topic phrase.

    Groups insights that share the same semantic topic (the phrase before
    em-dash/colon) and keeps only one representative per topic per type.
    Limits to max 3 per type (pattern/win/signal/connection).
    """
    if not insights:
        return insights

    def _topic_key(text):
        """Extract normalized topic words from the leading phrase."""
        topic = re.split(r'[—:\.\!\?]', text)[0].strip().lower()
        topic = re.sub(r'[^\w\s]', '', topic)
        stop = {'the', 'a', 'an', 'in', 'to', 'for', 'of', 'and', 'or', 'but',
                'is', 'are', 'was', 'were', 'jim', 'jims', 'that', 'this', 'with',
                'from', 'on', 'at', 'by', 'his', 'her', 'through', 'about', 'its', 'vs'}
        return frozenset(w for w in topic.split() if w not in stop and len(w) > 2)

    # Group by (type, topic_key) — merge overlapping topic keys
    groups = {}  # key: (type, topic_frozenset) -> list of items
    for item in insights:
        text = item.get("text", "").strip()
        itype = item.get("type", "other")
        if not text or itype == "todo":
            continue
        key = _topic_key(text)
        if not key:
            continue

        # Find existing group with overlapping topic key
        merged = False
        for (gtype, gkey) in list(groups.keys()):
            if gtype == itype and len(key) > 0 and len(gkey) > 0:
                overlap = len(key & gkey) / max(len(key | gkey), 1)
                if overlap >= 0.3:
                    groups[(gtype, gkey)].append(item)
                    merged = True
                    break
        if not merged:
            groups[(itype, key)] = [item]

    # From each group, keep the shortest item
    unique_non_todos = []
    type_counts = {}
    for (itype, _), group in groups.items():
        if type_counts.get(itype, 0) >= 3:
            continue  # Max 3 per type
        group.sort(key=lambda x: len(x.get("text", "")))
        unique_non_todos.append(group[0])
        type_counts[itype] = type_counts.get(itype, 0) + 1

    # Re-add todos unchanged
    todos = [i for i in insights if i.get("type") == "todo"]
    return unique_non_todos + todos


def _anxiety_week_points(ai_insights, effective_today, days=7):
    """Return last-N daily anxiety scores and weekly average."""
    try:
        base = datetime.strptime(effective_today, "%Y-%m-%d")
    except Exception:
        return [], None

    points = []
    for offset in range(days - 1, -1, -1):
        day_key = (base - timedelta(days=offset)).strftime("%Y-%m-%d")
        day = get_ai_day(ai_insights, day_key)
        raw_score = day.get("anxiety_reduction_score") if isinstance(day, dict) else None
        if isinstance(raw_score, (int, float)):
            score = float(raw_score)
        else:
            score = None
        points.append((day_key, score))

    numeric = [score for _, score in points if isinstance(score, (int, float))]
    avg = round(sum(numeric) / len(numeric), 1) if numeric else None
    return points, avg


def _anxiety_sparkline(points):
    """Render a compact 7-day sparkline from 0-10 scores."""
    levels = "▁▂▃▄▅▆▇█"
    bars = []
    for _, score in points:
        if score is None:
            bars.append("·")
            continue
        clamped = max(0.0, min(10.0, float(score)))
        idx = int(round((clamped / 10.0) * (len(levels) - 1)))
        bars.append(levels[idx])
    return "".join(bars)


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _is_updates_verification_noise_text(text):
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not lowered:
        return False
    if any(
        token in lowered
        for token in (
            "verification note",
            "updates section sync",
            "codex verification",
            "test scratch pad entry",
        )
    ):
        return True
    if re.search(r"\btest[-_ ]?(?:item|entry|stub|dummy|does)\b", lowered):
        return True
    return False


def _clean_evening_reflections_text(raw_text):
    text = str(raw_text or "").strip()
    if not text:
        return ""

    # If parser leaked the full evening template blob, keep only the
    # "Evening Reflections" section body.
    heading_match = re.search(
        r"(?is)##\s*evening reflections?\s*(.*?)(?=(?:\n|\s)##\s*[A-Za-z]|\Z)",
        text,
    )
    if heading_match:
        extracted = str(heading_match.group(1) or "").strip()
        if extracted:
            text = extracted
    else:
        fallback_match = re.search(
            r"(?is)(?:^|\n)\s*(?:#+\s*)?evening reflections?\s*:?\s*(.*)$",
            text,
        )
        if fallback_match:
            extracted = str(fallback_match.group(1) or "").strip()
            if extracted:
                text = extracted

    bleed_prefixes = (
        "## three things",
        "## ta-dah",
        "## ta dah",
        "## where was i brave",
        "## what's tomorrow",
        "## what’s tomorrow",
        "## what do i need to remember",
        "## remember tomorrow",
    )
    if any(marker in text.lower() for marker in bleed_prefixes):
        lines = []
        for raw_line in text.splitlines():
            line = str(raw_line or "").strip()
            ll = line.lower()
            if any(ll.startswith(prefix) for prefix in bleed_prefixes):
                continue
            lines.append(raw_line)
        text = "\n".join(lines).strip()

    text = re.sub(r"^\s*Tracker\s*:.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^\s*Rating\s*:.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _normalise_updates_line_key(text):
    raw = re.sub(r"\s+", " ", str(text or "").strip().lower())
    raw = re.sub(r"[^a-z0-9\s]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _updates_overlap_ratio(a, b):
    aset = _token_set(a)
    bset = _token_set(b)
    if not aset or not bset:
        return 0.0
    return len(aset & bset) / max(1, min(len(aset), len(bset)))


def _dedupe_updates_lines(lines, max_items=8):
    deduped = []
    for raw_line in lines:
        line = re.sub(r"\s+", " ", str(raw_line or "").strip())
        if len(line) < 4:
            continue
        if _is_updates_verification_noise_text(line):
            continue
        line_key = _normalise_updates_line_key(line)
        if not line_key:
            continue

        merged = False
        for idx, existing in enumerate(deduped):
            existing_key = _normalise_updates_line_key(existing)
            if not existing_key:
                continue
            overlap = _updates_overlap_ratio(line, existing)
            if line_key == existing_key or overlap >= 0.68:
                # Keep the fresher line if it's similarly rich, otherwise keep richer text.
                if len(line) >= int(len(existing) * 0.85):
                    deduped[idx] = line
                merged = True
                break

        if not merged:
            deduped.append(line)

        if len(deduped) > max_items:
            deduped = deduped[-max_items:]
    return deduped


def _strip_updates_metadata(text):
    """Remove Weather/Location metadata lines from Updates display."""
    if not text:
        return ""

    weather_block_pattern = re.compile(
        r'^\s*(?:\W+)?weather\s*:.*(?:sunrise|sunset|location)\b.*$',
        re.IGNORECASE,
    )
    location_coord_pattern = re.compile(
        r'^\s*(?:\W+)?location\s*:\s*[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+\s*\.?\s*$',
        re.IGNORECASE,
    )
    sunrise_sunset_pattern = re.compile(
        r'^\s*(?:\W+)?(?:sunrise|sunset)\s*:\s*\d{1,2}:\d{2}\b.*$',
        re.IGNORECASE,
    )

    kept_lines = []
    for raw_line in re.split(r'\n+', str(text)):
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        is_weather_block = bool(weather_block_pattern.match(line))
        is_location_line = bool(location_coord_pattern.match(line))
        is_sun_line = bool(sunrise_sunset_pattern.match(line))
        looks_metadata_combo = (
            "weather" in lower
            and ("sunrise" in lower or "sunset" in lower or "location" in lower)
            and bool(re.search(r'[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+', line))
        )

        if is_weather_block or is_location_line or is_sun_line or looks_metadata_combo:
            continue

        # Filter transcription assistant artefacts that leak from diary assistant responses
        _TRANSCRIPTION_LEAK = (
            "here's the full formatted version",
            "here is the full formatted version",
            "ready to paste into diarium",
            "your evening entry is complete",
            "here is the formatted version",
            "formatted version, ready to paste",
            "paste into diarium",
            "full formatted version",
        )
        if any(phrase in lower for phrase in _TRANSCRIPTION_LEAK):
            continue

        if _is_updates_verification_noise_text(line):
            continue

        kept_lines.append(line)

    deduped_lines = _dedupe_updates_lines(kept_lines, max_items=8)
    cleaned = "\n".join(deduped_lines).strip()
    cleaned, _ = _strip_dashboard_dump_suffix(cleaned)
    return cleaned


def _is_effectively_empty_updates_text(text):
    """Treat punctuation-only/placeholder updates values as empty."""
    raw = str(text or "").strip()
    if not raw:
        return True
    lowered = raw.lower()
    if lowered in {"-", "--", "---", "—", "—-", "n/a", "na", "none", "nil", "null"}:
        return True
    token_stripped = re.sub(r"[\s\-\—\–\•\·\.\,\:\;\|\_\/]+", "", lowered)
    return token_stripped == ""


def _is_stale_diarium_fallback_line(text):
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return "diarium is stale" in lowered and "live activity context" in lowered


def _is_tracker_metadata_leak_text(text):
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not lowered:
        return False
    if "tracker says" in lowered and "mood" in lowered:
        return True
    leak_patterns = (
        r"\bmood marker is\b",
        r"\btracker:\s*mood\b",
        r"\bmorning mood(?:\s*tag)?\s*:",
        r"\bevening mood(?:\s*tag)?\s*:",
        r"\bmood(?:\s*tag)?\s*:\s*(ready|ok|calm|anxious|tired|stressed|good|bad|sad|happy)\b",
        r"\brating:\s*[★*]",
    )
    return any(re.search(pattern, lowered) for pattern in leak_patterns)


def _time_to_minutes_hhmm(value):
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(value or ""))
    if not match:
        return None
    try:
        hh = int(match.group(1))
        mm = int(match.group(2))
    except Exception:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh * 60 + mm


def _sanitize_mood_entries_for_today(entries, now_dt=None, *, allow_diarium_source=True):
    """Drop malformed/future mood entries and return a stable, sorted list."""
    if not isinstance(entries, list):
        return []
    now_dt = now_dt or datetime.now()
    now_minutes = now_dt.hour * 60 + now_dt.minute
    cleaned = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        time_minutes = _time_to_minutes_hhmm(item.get("time", ""))
        source = str(item.get("source", "")).strip().lower()
        if (not allow_diarium_source) and source == "diarium":
            continue
        # Filter obviously future auto-injected diarium placeholders only.
        # Keep manual entries even if timestamp/timezone skew makes them look ahead.
        if time_minutes is not None and time_minutes > now_minutes and source == "diarium":
            continue
        cleaned.append(item)

    def _sort_key(item):
        mins = _time_to_minutes_hhmm(item.get("time", ""))
        if mins is None:
            mins = 24 * 60 + 1
        logged_at = str(item.get("logged_at", "")).strip()
        return (mins, logged_at)

    cleaned.sort(key=_sort_key)
    return cleaned[-8:]


def _token_set(text):
    raw = str(text or "").lower()
    words = re.findall(r"[a-z0-9']+", raw)
    stop = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
        "is", "it", "this", "that", "be", "as", "at", "by", "i", "im", "i'm",
        "we", "you", "my", "our", "your", "will", "should", "can", "again",
    }
    return {w for w in words if len(w) > 2 and w not in stop}


def _parrot_overlap(candidate, sources):
    cset = _token_set(candidate)
    if not cset:
        return 0.0
    best = 0.0
    for src in sources:
        sset = _token_set(src)
        if not sset:
            continue
        overlap = len(cset & sset) / max(len(cset), 1)
        if overlap > best:
            best = overlap
    return best


def _looks_work_guidance_text(text):
    lowered = str(text or "").lower()
    tokens = _token_set(lowered)
    if "job hunt" in lowered or "cover letter" in lowered:
        return True
    work_tokens = {
        "job", "jobs", "apply", "application", "applications", "cv", "resume",
        "interview", "linkedin", "recruiter", "career", "employment", "employer",
        "role", "roles", "salary", "remote", "hybrid",
    }
    if tokens & work_tokens:
        return True
    if "work" in tokens and "workout" not in lowered:
        return True
    return False


def _build_tomorrow_reframe_lines(jim_tomorrow, jim_remember, weekend_mode=False):
    seed = f"{str(jim_tomorrow or '').strip()} {str(jim_remember or '').strip()}".strip().lower()
    lines = []

    if any(k in seed for k in ("family", "mum", "kids", "girls")):
        lines.append({
            "emoji": "👨‍👩‍👧",
            "text": "Front-load family time, then protect a short decompression block so recovery still happens.",
        })
    if any(k in seed for k in ("decompress", "relax", "rest", "calm", "recharge", "relief")):
        lines.append({
            "emoji": "🧘",
            "text": "Schedule decompression as a fixed slot (10–20 min) instead of waiting for 'free time'.",
        })
    if any(k in seed for k in ("grateful", "gratefulness", "relieved", "pressure", "ok")):
        lines.append({
            "emoji": "💚",
            "text": "Hold both truths: relief and gratitude can coexist—name both, then choose one grounding action.",
        })

    if not lines:
        if weekend_mode:
            lines = [
                {"emoji": "🌿", "text": "Weekend mode: prioritise recovery and connection over output."},
                {"emoji": "🧠", "text": "Do one regulation anchor early (mindfulness, walk, or food) to steady the day."},
                {"emoji": "🌙", "text": "Keep tomorrow simple: one must-do, then protected decompression time."},
            ]
        else:
            lines = [
                {"emoji": "🎯", "text": "Set one must-do and one nice-to-have to avoid overload tomorrow."},
                {"emoji": "🧠", "text": "Do one regulation anchor early (mindfulness, walk, or food) before reactive tasks."},
                {"emoji": "🌙", "text": "Leave a short evening close note to reduce rumination at night."},
            ]

    return lines[:4]


def _normalise_tomorrow_action_text(text):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n-•")
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(and|then|after that|afterwards|also)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" ,.;")
    if not cleaned:
        return ""
    if len(cleaned) > 140:
        cleaned = cleaned[:137].rstrip() + "..."
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned[0].upper() + cleaned[1:]


def _extract_tomorrow_action_chunks(jim_tomorrow, jim_remember):
    combined = [str(jim_tomorrow or "").strip(), str(jim_remember or "").strip()]
    chunks = []
    for source in combined:
        if not source:
            continue
        parts = re.split(r"(?:\n+|[•]+|;\s*|,\s*then\s+|\bafter that\b|\bthen\b)", source, flags=re.IGNORECASE)
        for part in parts:
            cleaned = _normalise_tomorrow_action_text(part)
            if not cleaned:
                continue
            token_count = len(_token_set(cleaned))
            if token_count < 3:
                continue
            if any(_parrot_overlap(cleaned, [existing]) >= 0.82 for existing in chunks):
                continue
            chunks.append(cleaned)
    return chunks


def _build_tomorrow_action_lines(jim_tomorrow, jim_remember, weekend_mode=False):
    chunks = _extract_tomorrow_action_chunks(jim_tomorrow, jim_remember)
    lines = []
    step_labels = ["First block", "Next block", "Later block"]
    emojis = ["🎯", "⏱️", "🧩"]

    for idx, chunk in enumerate(chunks[:3]):
        slot = step_labels[min(idx, len(step_labels) - 1)]
        emoji = emojis[min(idx, len(emojis) - 1)]
        lines.append({
            "emoji": emoji,
            "text": f"{slot}: {chunk}",
        })

    remember_clean = _normalise_tomorrow_action_text(jim_remember)
    if remember_clean:
        boundary_text = f"Boundary reminder: {remember_clean}"
        if _parrot_overlap(boundary_text, [item.get("text", "") for item in lines]) < 0.72:
            lines.append({
                "emoji": "🛡️",
                "text": boundary_text,
            })

    if not lines:
        lines = _build_tomorrow_reframe_lines(jim_tomorrow, jim_remember, weekend_mode=weekend_mode)
    return lines[:4]


def _pearson(xs, ys):
    if not xs or not ys or len(xs) != len(ys) or len(xs) < 3:
        return None
    n = len(xs)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den_x = sum((x - x_mean) ** 2 for x in xs) ** 0.5
    den_y = sum((y - y_mean) ** 2 for y in ys) ** 0.5
    den = den_x * den_y
    if den == 0:
        return None
    return round(num / den, 2)


def _build_metric_map(cache):
    healthfit = cache.get("healthfit", {}) if isinstance(cache.get("healthfit", {}), dict) else {}
    apple_health = cache.get("apple_health", {}) if isinstance(cache.get("apple_health", {}), dict) else {}
    metric_map = {}

    if healthfit.get("status") == "success" and isinstance(healthfit.get("daily_metrics"), list):
        for item in healthfit.get("daily_metrics", []):
            date_raw = str(item.get("date", "")).strip()
            try:
                date_key = datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                continue
            metric_map[date_key] = {
                "steps": _to_float(item.get("steps")),
                "exercise": _to_float(item.get("exercise_minutes")),
                "sleep": _to_float(item.get("sleep_hours")),
            }
    elif apple_health.get("status") == "success" and isinstance(apple_health.get("daily_metrics"), list):
        for item in apple_health.get("daily_metrics", []):
            date_key = str(item.get("date", "")).strip()
            if not date_key:
                continue
            metric_map[date_key] = {
                "steps": _to_float(item.get("steps")),
                "exercise": _to_float(item.get("exercise_minutes")),
                "sleep": _to_float(item.get("sleep_hours")),
            }
    return metric_map


def _compute_anxiety_correlation(cache, ai_insights, effective_today, days=14):
    try:
        base = datetime.strptime(effective_today, "%Y-%m-%d")
    except Exception:
        return {"status": "none"}

    metric_map = _build_metric_map(cache)
    points = []
    for offset in range(days - 1, -1, -1):
        day_key = (base - timedelta(days=offset)).strftime("%Y-%m-%d")
        day_data = get_ai_day(ai_insights, day_key)
        raw_score = day_data.get("anxiety_reduction_score") if isinstance(day_data, dict) else None
        score = _to_float(raw_score)
        if score is None:
            continue
        metrics = metric_map.get(day_key, {})
        if not metrics:
            continue
        points.append({
            "date": day_key,
            "score": score,
            "steps": metrics.get("steps"),
            "exercise": metrics.get("exercise"),
            "sleep": metrics.get("sleep"),
        })

    if len(points) < 3:
        return {"status": "none", "count": len(points)}

    def paired(metric_name):
        xs, ys = [], []
        for p in points:
            m = p.get(metric_name)
            if m is None:
                continue
            xs.append(float(p["score"]))
            ys.append(float(m))
        return xs, ys

    score_steps, steps_vals = paired("steps")
    score_ex, ex_vals = paired("exercise")
    score_sleep, sleep_vals = paired("sleep")

    step_corr = _pearson(score_steps, steps_vals)
    ex_corr = _pearson(score_ex, ex_vals)
    sleep_corr = _pearson(score_sleep, sleep_vals)

    high_days = [p for p in points if p["score"] >= 7]
    low_days = [p for p in points if p["score"] <= 4]

    def avg(items, key):
        values = [float(i[key]) for i in items if i.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    return {
        "status": "ok",
        "count": len(points),
        "step_corr": step_corr,
        "exercise_corr": ex_corr,
        "sleep_corr": sleep_corr,
        "high_avg_steps": avg(high_days, "steps"),
        "high_avg_exercise": avg(high_days, "exercise"),
        "low_avg_steps": avg(low_days, "steps"),
        "low_avg_exercise": avg(low_days, "exercise"),
    }


def _looks_like_weekly_digest_summary(text):
    """Detect weekly digest/session rollup text not suitable for 'How Today Felt'."""
    if not text:
        return False
    lowered = str(text).strip().lower()
    if lowered.startswith("weekly digest"):
        return True
    return "# week in review" in lowered or "week in review" in lowered


def _pick_primary_summary_for_how_felt(ai_day):
    """Select the best emotional summary for 'How Today Felt' card.

    Priority:
    1. Today's evening summaries (evening/daemon_evening)
    2. Most-recent daytime summary (updates/check-in/therapy/morning)
    3. Non-digest latest_summary fallback

    Explicitly avoids weekly digest/session rollup summaries.
    """
    if not isinstance(ai_day, dict):
        return ""

    entries = ai_day.get("entries", [])
    if not isinstance(entries, list):
        entries = []

    evening_sources = {"evening", "daemon_evening"}
    daytime_sources = {"updates", "check_in", "therapy", "morning"}

    # Evening remains highest-priority when available.
    for entry in reversed(entries):
        if not isinstance(entry, dict) or entry.get("source") not in evening_sources:
            continue
        summary = str(entry.get("emotional_summary", "")).strip()
        if summary and not _looks_like_weekly_digest_summary(summary):
            return summary

    # Otherwise choose the freshest daytime summary so new morning/check-in text
    # can replace older updates-only summaries.
    def _entry_epoch(entry):
        raw = str(entry.get("generated_at") or entry.get("timestamp") or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    daytime_candidates = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get("source") not in daytime_sources:
            continue
        summary = str(entry.get("emotional_summary", "")).strip()
        if not summary or _looks_like_weekly_digest_summary(summary):
            continue
        daytime_candidates.append((_entry_epoch(entry), idx, summary))

    if daytime_candidates:
        daytime_candidates.sort(key=lambda item: (item[0] is not None, item[0] or float("-inf"), item[1]))
        return daytime_candidates[-1][2]

    latest_summary = str(ai_day.get("latest_summary", "")).strip()
    if latest_summary and not _looks_like_weekly_digest_summary(latest_summary):
        return latest_summary

    return ""


def _clean_pieces_text(raw_text):
    """Normalise Pieces markdown/text into compact readable sentence text."""
    if not raw_text:
        return ""
    text = str(raw_text)
    # Strip fenced code blocks and markdown headings/bullets.
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate_sentence_safe(raw_text, max_len=3000):
    """Trim text safely, preferring sentence boundaries over hard clipping."""
    text = re.sub(r"\s+", " ", str(raw_text or "")).strip()
    if not text or len(text) <= max_len:
        return text
    cut_candidates = [
        text.rfind(". ", 0, max_len),
        text.rfind("! ", 0, max_len),
        text.rfind("? ", 0, max_len),
    ]
    cut = max(cut_candidates)
    if cut >= int(max_len * 0.6):
        return text[: cut + 1].strip()
    return text[:max_len].rstrip(" ,;:-") + "…"


def _render_pieces_timeline_html(summaries, details_class=""):
    """Render all same-day Pieces sessions in a collapsed timeline."""
    if not isinstance(summaries, list):
        return ""

    rows = []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        created = str(summary.get("created", "")).strip()
        time_label = created[11:16] if len(created) >= 16 else "--:--"
        name_raw = str(summary.get("name", "Activity")).strip() or "Activity"
        name_safe = html.escape(name_raw)
        rows.append(
            f'<div class="flex gap-2 text-xs mb-1">'
            f'<span style="color:#6b7280;min-width:2.8rem">{time_label}</span>'
            f'<span style="color:#9ca3af;word-break:break-word;" title="{name_safe}">{name_safe}</span>'
            f'</div>'
        )

    if not rows:
        return ""

    details_attr = f' class="{details_class}"' if details_class else ""
    return (
        f'<details{details_attr}>'
        f'<summary class="text-xs cursor-pointer" style="color:#6b7280">Sessions ({len(rows)})</summary>'
        f'<div class="mt-2">{"".join(rows)}</div>'
        f'</details>'
    )


def _build_pieces_shared_parts(pieces_payload, digest_text, digest_source, body_color="#d1d5db", muted_color="#9ca3af", details_class=""):
    """Build shared Pieces digest/wins/timeline HTML parts used across cards."""
    parts = []
    payload = pieces_payload if isinstance(pieces_payload, dict) else {}
    count = int(payload.get("count", 0) or 0)
    wins = payload.get("unplanned_wins", []) if isinstance(payload.get("unplanned_wins", []), list) else []
    summaries = payload.get("summaries", []) if isinstance(payload.get("summaries", []), list) else []

    if digest_text:
        # Condense to 2 sentences max for the summary line
        sentences = re.split(r'(?<=[.!?])\s+', digest_text.strip())
        short_summary = " ".join(sentences[:2])
        if len(sentences) > 2:
            short_summary += "…"
        parts.append(
            f'<p class="text-sm mb-2" style="color:{body_color};line-height:1.5;">{html.escape(short_summary)}</p>'
        )
    elif count > 0:
        parts.append(
            f'<p class="text-sm mb-2" style="color:{muted_color}">{count} sessions captured — showing session timeline while digest catches up.</p>'
        )

    if wins:
        win_items = "".join(
            f'<p class="text-xs mb-1" style="color:#6ee7b7">🏆 {html.escape(str(w))}</p>'
            for w in wins[:3]
        )
        parts.append(
            f'<div class="rounded p-2 mb-3" style="background:rgba(6,95,70,0.08);border:1px solid rgba(110,231,183,0.2);">{win_items}</div>'
        )

    timeline_html = _render_pieces_timeline_html(summaries, details_class=details_class)
    if timeline_html:
        parts.append(timeline_html)

    return parts


def _derive_pieces_digest(pieces_payload, max_chars=3000):
    """Return best-available Pieces digest text + source label.

    Priority:
    1) pieces_activity.digest
    2) composed fallback from session descriptions/names (deduped)
    3) morning_brief.summary_md fallback
    """
    if not isinstance(pieces_payload, dict):
        return "", ""

    digest = _truncate_sentence_safe(_clean_pieces_text(pieces_payload.get("digest", "")), max_len=max_chars)
    if digest:
        return digest, "digest"

    summaries = pieces_payload.get("summaries", [])
    fallback_bits = []
    seen = set()
    if isinstance(summaries, list):
        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            name = _clean_pieces_text(summary.get("name", ""))
            description = _clean_pieces_text(summary.get("description", ""))
            snippet = description or name
            if description and name and name.lower() not in description.lower():
                snippet = f"{name}: {description}"
            snippet = _truncate_sentence_safe(snippet, max_len=240)
            if not snippet:
                continue
            key = re.sub(r"[^a-z0-9]+", " ", snippet.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            fallback_bits.append(snippet)

    if fallback_bits:
        if len(fallback_bits) == 1:
            merged = fallback_bits[0]
        else:
            sentences = []
            for bit in fallback_bits:
                s = bit.rstrip()
                if s and s[-1] not in ".!?":
                    s += "."
                sentences.append(s)
            merged = f"Worked across {len(fallback_bits)} sessions today. " + " ".join(sentences)
        return _truncate_sentence_safe(merged, max_len=max_chars), "summary_fallback"

    morning_brief = pieces_payload.get("morning_brief", {})
    if isinstance(morning_brief, dict):
        mb_text = _clean_pieces_text(morning_brief.get("summary_md", ""))
        if mb_text:
            return _truncate_sentence_safe(mb_text, max_len=max_chars), "morning_brief_fallback"

    return "", ""


def load_daemon_cache():
    """Load the daemon cache directly - this is always the freshest data"""
    if DAEMON_CACHE.exists():
        try:
            with open(DAEMON_CACHE, 'r') as f:
                data = json.load(f)
                return data
        except Exception as e:
            print(f"Error loading cache: {e}")
    return {}


def _runtime_daemon_running():
    """Best-effort daemon process check for status strip."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "data_collector.py"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return result.returncode == 0
    except Exception:
        return False


def _runtime_api_health():
    """Best-effort API health check for status strip."""
    req = Request("http://127.0.0.1:8765/health", method="GET")
    for timeout_s in (6, 10):
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            continue
    return False


def _runtime_cache_age_minutes(path):
    if not path.exists():
        return None
    try:
        return int((datetime.now().timestamp() - path.stat().st_mtime) / 60)
    except Exception:
        return None


def _count_open_issues_from_jsonl(project_path):
    """Fast local open-count fallback that avoids bd timeout issues."""
    issues_file = project_path / ".beads" / "issues.jsonl"
    if not issues_file.exists():
        return None
    latest = {}
    try:
        with open(issues_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    issue = json.loads(line)
                except Exception:
                    continue
                issue_id = str(issue.get("id", "")).strip()
                if not issue_id:
                    continue
                latest[issue_id] = issue
        return sum(1 for issue in latest.values() if str(issue.get("status", "")).lower() == "open")
    except Exception:
        return None


def _read_open_issues_from_jsonl(project_path, limit=160):
    """Fast local open-issue reader used by optional backlog card (no bd call needed)."""
    issues_file = project_path / ".beads" / "issues.jsonl"
    if not issues_file.exists():
        return []
    latest = {}
    try:
        with open(issues_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    issue = json.loads(line)
                except Exception:
                    continue
                issue_id = str(issue.get("id", "")).strip()
                if not issue_id:
                    continue
                latest[issue_id] = issue
    except Exception:
        return []

    def _priority_val(issue):
        raw = issue.get("priority")
        try:
            p = int(raw)
            return p if p > 0 else 99
        except Exception:
            return 99

    def _updated_key(issue):
        for key in ("updated_at", "updated", "created_at", "created"):
            raw = str(issue.get(key, "")).strip()
            if raw:
                return raw
        return ""

    open_items = [
        issue for issue in latest.values()
        if str(issue.get("status", "")).lower() == "open"
    ]
    open_items.sort(key=lambda issue: (_priority_val(issue), _updated_key(issue)), reverse=False)
    return open_items[: max(1, int(limit))]


def _runtime_open_bead_counts():
    counts = {}
    base = Path.home() / "Documents" / "Claude Projects"
    for project in ("HEALTH", "WORK", "TODO"):
        project_path = base / project
        if not project_path.exists():
            counts[project] = None
            continue
        # Prefer JSONL count first for responsiveness.
        quick = _count_open_issues_from_jsonl(project_path)
        if isinstance(quick, int):
            counts[project] = quick
            continue
        try:
            result = subprocess.run(
                ["bd", "count", "--status", "open"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=6,
            )
            if result.returncode != 0:
                counts[project] = None
                continue
            counts[project] = int((result.stdout or "").strip())
        except Exception:
            counts[project] = None
    return counts


def _runtime_remote_access():
    payload = {
        "tailscale_url": "",
        "tailscale_state": "unknown",
        "cloudflare_url": "",
        "cloudflare_state": "missing",
        "cloudflare_age_minutes": None,
    }

    tunnel_file = Path.home() / ".claude" / "config" / "tunnel-url.txt"
    if tunnel_file.exists():
        cf_url = tunnel_file.read_text().strip()
        if cf_url.startswith("https://"):
            payload["cloudflare_url"] = cf_url
            try:
                age = int((datetime.now().timestamp() - tunnel_file.stat().st_mtime) / 60)
            except Exception:
                age = None
            payload["cloudflare_age_minutes"] = age
            if isinstance(age, int):
                payload["cloudflare_state"] = "fresh" if age <= 45 else "stale"
            else:
                payload["cloudflare_state"] = "unknown"

    try:
        serve = subprocess.run(
            ["tailscale", "serve", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if serve.returncode == 0 and serve.stdout.strip():
            parsed = json.loads(serve.stdout)
            web = parsed.get("Web", {}) if isinstance(parsed, dict) else {}
            if isinstance(web, dict) and web:
                first_key = next(iter(web.keys()))
                host = str(first_key).split(":", 1)[0].strip().rstrip(".")
                if host:
                    payload["tailscale_url"] = f"https://{host}"
                    payload["tailscale_state"] = "serve"
    except Exception:
        pass

    if not payload["tailscale_url"]:
        try:
            status = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if status.returncode == 0 and status.stdout.strip():
                parsed = json.loads(status.stdout)
                self_info = parsed.get("Self", {}) if isinstance(parsed, dict) else {}
                host = str(self_info.get("DNSName", "")).strip().rstrip(".")
                if host:
                    payload["tailscale_url"] = f"https://{host}"
                    payload["tailscale_state"] = "tailnet"
        except Exception:
            pass

    return payload


def get_diarium_images(date_str):
    """Get Diarium images from cache directory"""
    image_cache = Path.home() / ".claude" / "cache" / "diarium-images"
    images = []

    if image_cache.exists():
        for img_file in image_cache.glob(f"{date_str}_image*.jpg"):
            images.append({
                'filename': img_file.name,
                'path': str(img_file),
                'url': f"file://{img_file}"
            })
        for img_file in image_cache.glob(f"{date_str}_image*.png"):
            images.append({
                'filename': img_file.name,
                'path': str(img_file),
                'url': f"file://{img_file}"
            })

    return images


def get_todays_workout():
    """Determine today's scheduled workout from fitness-log.md.

    Reads the Fitness Schedule section, matches today's date against listed days.
    Returns dict with keys: type ('weights'|'yoga'|'rest'), emoji, title, detail, done.
    """
    fitness_log = Path.home() / "Documents" / "Claude Projects" / "HEALTH" / "fitness-log.md"
    if not fitness_log.exists():
        return {"type": "rest", "emoji": "😌", "title": "Rest day", "detail": "", "done": False}

    try:
        content = fitness_log.read_text()
    except Exception:
        return {"type": "rest", "emoji": "😌", "title": "Rest day", "detail": "", "done": False}

    # Use effective date (3am rollover) so this matches checklist/anxiety/mindfulness day logic.
    # This avoids midnight mismatch where schedule flips before the rest of the dashboard resets.
    effective_day = get_effective_date()
    try:
        day_dt = datetime.strptime(effective_day, "%Y-%m-%d")
    except Exception:
        day_dt = datetime.now()

    month_short = day_dt.strftime("%b")
    day_num = day_dt.day
    today_label = f"{day_dt.strftime('%a')} {day_dt.day} {day_dt.strftime('%b')}"  # e.g. "Mon 16 Feb"
    schedule_date_pattern = re.compile(
        rf"^\s*-\s*[A-Za-z]{{3,9}}\s+0?{day_num}\s+{re.escape(month_short)}\s*:",
        re.IGNORECASE,
    )

    # Check if today is in the fitness schedule section
    workout_type = None  # "workout_a", "workout_b", "yoga", or None
    in_schedule = False
    schedule_line = ""
    for line in content.split("\n"):
        line_lower = line.lower().strip()
        if "fitness schedule" in line_lower or "this week" in line_lower:
            in_schedule = True
        # Only match schedule entries for the exact effective day (avoid "9 Feb" matching "19 Feb").
        if in_schedule and schedule_date_pattern.search(line):
            schedule_line = line_lower
            if "workout a" in line_lower:
                workout_type = "workout_a"
            elif "workout b" in line_lower:
                workout_type = "workout_b"
            elif "yoga" in line_lower:
                workout_type = "yoga"
            break

    # Check if workout is already done
    # 1) Schedule line itself contains ✅
    done = "✅" in schedule_line if schedule_line else False
    # 2) Fall back to explicit Progress Notes match for the same day + same workout label.
    if not done and workout_type:
        workout_label = ""
        if workout_type == "workout_a":
            workout_label = "Workout A"
        elif workout_type == "workout_b":
            workout_label = "Workout B"
        elif workout_type == "yoga":
            workout_label = "Yoga"

        if workout_label:
            progress_pattern = re.compile(
                rf'^\s*\*\*{re.escape(today_label)}:\*\*\s*{re.escape(workout_label)}\s+completed.*✅\s*$',
                re.IGNORECASE,
            )
            for line in content.split("\n"):
                if progress_pattern.match(line):
                    done = True
                    break

    # Extract current programme details for weights days
    weight_amt = ""
    sets_reps = ""
    for line in content.split("\n"):
        if line.startswith("**Weight:**"):
            weight_amt = line.split("**Weight:**")[1].strip().split("(")[0].strip()
        if line.startswith("**Sets × Reps:**"):
            sets_reps = line.split("**Sets × Reps:**")[1].strip().split("(")[0].strip()

    if workout_type == "workout_a":
        detail = f"{weight_amt}, {sets_reps}" if weight_amt and sets_reps else ""
        exercises = [
            {"name": "Goblet Squat", "muscles": "quads, glutes"},
            {"name": "Dumbbell Rows", "muscles": "back, biceps"},
            {"name": "Floor Press", "muscles": "chest, triceps"},
            {"name": "Romanian Deadlift", "muscles": "hamstrings, glutes"},
            {"name": "Standing Calf Raises", "sets_reps": "3×12-15"},
            {"name": "Bent-Knee Calf Raises", "sets_reps": "3×12"},
        ]
        return {"type": "weights", "emoji": "💪", "title": "Workout A", "detail": detail,
                "exercises": exercises, "done": done}
    elif workout_type == "workout_b":
        detail = f"{weight_amt}, {sets_reps}" if weight_amt and sets_reps else ""
        exercises = [
            {"name": "Lunges", "muscles": "quads, glutes"},
            {"name": "Shoulder Press", "muscles": "shoulders, triceps"},
            {"name": "Curls", "muscles": "biceps"},
            {"name": "Plank", "muscles": "core", "sets_reps": "2×30-60s"},
            {"name": "Standing Calf Raises", "sets_reps": "3×12-15"},
            {"name": "Bent-Knee Calf Raises", "sets_reps": "3×12"},
        ]
        return {"type": "weights", "emoji": "💪", "title": "Workout B", "detail": detail,
                "exercises": exercises, "done": done}
    elif workout_type == "yoga":
        exercises = [
            {"name": "Downward Dog", "muscles": "heel-down focus"},
            {"name": "Low Lunge", "muscles": "heel-down focus"},
            {"name": "Forward Fold", "muscles": "heel-down focus"},
            {"name": "Calf stretches", "muscles": "calves"},
        ]
        return {"type": "yoga", "emoji": "🧘", "title": "Yoga", "detail": "",
                "exercises": exercises, "done": done}
    else:
        return {"type": "rest", "emoji": "😌", "title": "Rest day",
                "detail": "Daily calf stretch (3 mins) still applies", "exercises": [], "done": False}


def _parse_tadah_from_journal(date_str):
    """Extract ta-dah items from a journal file by date. Returns list of strings."""
    journal_file = JOURNAL_DIR / f"{date_str}.md"
    if not journal_file.exists():
        return []
    try:
        content = journal_file.read_text()
        # Find ta-dah section (case-insensitive, various formats)
        match = re.search(r'(?i)(?:ta.?dah|accomplishment).*?\n((?:[-*].*\n)*)', content)
        if not match:
            return []
        items = []
        for line in match.group(1).strip().split('\n'):
            line = line.strip().lstrip('-*').strip()
            if not line or len(line) <= 2:
                continue
            # Skip workout detail lines (numbered exercises, reps, weights)
            if re.match(r'^\d+\.?\s*\*?\*?[A-Z]', line):
                continue
            if re.match(r'^\d+\s*(lbs?|kg|reps?|sets?)$', line, re.IGNORECASE):
                continue
            # Strip inline markdown headers from ta-dah items (e.g. "Weights! ### Workout B")
            line = re.sub(r'\s*###?\s*.*$', '', line).strip()
            if line:
                items.append(line)
        return items
    except Exception:
        return []


def _parse_updates_from_journal(date_str):
    """Extract user-entered updates from journal ## Notes section."""
    journal_file = JOURNAL_DIR / f"{date_str}.md"
    if not journal_file.exists():
        return ""
    try:
        content = journal_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'(?ms)^## Notes\s*\n(.*?)(?=^##\s+|\Z)', content)
        if not match:
            return ""
        raw_block = match.group(1)
        lines = []
        for raw in raw_block.splitlines():
            line = str(raw).strip()
            if not line:
                continue
            if re.match(r'^\*\[\d{1,2}:\d{2}\s+via dashboard\]\*$', line, re.IGNORECASE):
                continue
            lines.append(line)
        deduped_lines = _dedupe_updates_lines(lines, max_items=8)
        if not deduped_lines:
            return ""
        # Keep recent lines only to avoid stale bloat from long-running notes files.
        return "\n".join(deduped_lines[-8:])
    except Exception:
        return ""


def _tadah_items_overlap(candidate, existing_texts, threshold=0.5):
    """Return True if candidate overlaps significantly with any existing text (word-overlap dedup)."""
    def _sig_words(s):
        return set(w for w in re.findall(r'\b[a-z]{3,}\b', s.lower()))
    cand_words = _sig_words(candidate)
    if not cand_words:
        return False
    for existing in existing_texts:
        ex_words = _sig_words(existing)
        if not ex_words:
            continue
        overlap = len(cand_words & ex_words)
        ratio = overlap / min(len(cand_words), len(ex_words))
        if ratio >= threshold:
            return True
    return False


def _strip_completion_hash_artifacts(text):
    value = str(text or "").strip()
    if not value:
        return ""
    previous = None
    while value and value != previous:
        previous = value
        value = re.sub(r'\s*~~+\s*\[?\s*[0-9a-f]{6,16}\s*\]?\s*$', '', value, flags=re.IGNORECASE).strip()
        value = re.sub(r'\s*\[\s*[0-9a-f]{6,16}\s*\]\s*$', '', value, flags=re.IGNORECASE).strip()
        value = re.sub(r'(?:\s+[0-9a-f]{6,12})+\s*$', '', value, flags=re.IGNORECASE).strip()
        value = re.sub(r'^\s*~~+\s*', '', value).strip()
        value = re.sub(r'\s*~~+\s*$', '', value).strip()
    return re.sub(r'\s+', ' ', value).strip()


def _tadah_score_key(text):
    raw = _strip_completion_hash_artifacts(text).lower()
    raw = re.sub(r'\b(?:the|a|an)\b', ' ', raw)
    raw = re.sub(r'\s+', ' ', raw).strip()
    return re.sub(r'[^a-z0-9\s]', '', raw).strip()


def _score_tadah_items(items):
    """Score ta-dah items deterministically (no model calls, no token usage)."""
    if not items:
        return items

    high_signal = (
        "fixed", "solved", "finished", "completed", "shipped", "launched",
        "therapy", "interview", "workout", "weights", "yoga", "family", "girls",
    )
    medium_signal = (
        "updated", "improved", "set up", "organised", "organized",
        "scheduled", "cleaned", "walked", "wrote", "built",
    )
    low_signal = (
        "checked", "quick", "small", "tiny", "sorted", "tidied",
    )

    def _score_item(item):
        existing = item.get("score")
        if isinstance(existing, (int, float)):
            return max(1, min(5, int(round(existing))))
        text = str(item.get("text", "")).strip().lower()
        source = str(item.get("source", "diary")).strip().lower()
        score = 3
        if any(k in text for k in high_signal):
            score += 2
        elif any(k in text for k in medium_signal):
            score += 1
        if any(k in text for k in low_signal):
            score -= 1
        if len(text.split()) <= 3:
            score -= 1
        if source == "pieces":
            score = max(score, 3)
        return max(1, min(5, score))

    scored = [{**item, "score": _score_item(item)} for item in items]
    scored.sort(key=lambda x: (-x.get("score", 3), x["text"]))

    return scored


def get_tadah():
    """Get ta-dah list merged from diary (Diarium) and Pieces unplanned wins.
    Items tagged with source for colour-coded display. Capped at 20 significant items.
    Strict daily reset; yesterday shown separately."""
    today = get_effective_date()
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    today_items = []  # List of dicts: {text, source}
    yesterday_tadah = []

    if DAEMON_CACHE.exists():
        try:
            with open(DAEMON_CACHE) as f:
                cache = json.load(f)
            source_date = str(cache.get("diarium_source_date", "")).strip()
            if source_date == today:
                # Diary ta-dahs first — user-written, highest priority
                diarium_cache = cache.get("diarium", {}) if isinstance(cache.get("diarium", {}), dict) else {}
                cache_tadah = diarium_cache.get("ta_dah", [])
                scored_rows = diarium_cache.get("ta_dah_scored_items", [])
                score_lookup = {}
                if isinstance(scored_rows, list):
                    for row in scored_rows:
                        if not isinstance(row, dict):
                            continue
                        key = _tadah_score_key(row.get("text", ""))
                        if not key:
                            continue
                        try:
                            value = int(round(float(row.get("score", 3))))
                        except Exception:
                            value = 3
                        score_lookup[key] = max(1, min(5, value))
                if cache_tadah and isinstance(cache_tadah, list):
                    for item in cache_tadah:
                        text = _strip_completion_hash_artifacts(item)
                        if text and text.lower() not in ("list", ""):
                            row = {"text": text, "source": "diary"}
                            score_key = _tadah_score_key(text)
                            if score_key in score_lookup:
                                row["score"] = score_lookup[score_key]
                            today_items.append(row)

                # Pieces unplanned wins — de-duped against diary items
                pieces = cache.get("pieces_activity", {})
                if pieces.get("status") == "ok":
                    diary_texts = [i["text"] for i in today_items]
                    for win in pieces.get("unplanned_wins", []):
                        win = _strip_completion_hash_artifacts(win)
                        if win and not _tadah_items_overlap(win, diary_texts):
                            today_items.append({"text": win, "source": "pieces"})
        except Exception:
            pass

    # De-duplicate wording/hash variants ("the", hash suffixes, etc.) before caps/scoring.
    deduped_today_items = []
    seen_today_keys = set()
    for row in today_items:
        if not isinstance(row, dict):
            continue
        key = _tadah_score_key(row.get("text", ""))
        if not key or key in seen_today_keys:
            continue
        seen_today_keys.add(key)
        deduped_today_items.append(row)
    today_items = deduped_today_items

    # Reserve up to 5 slots for Pieces items so diary count never crowds them out
    diary_items = [i for i in today_items if i["source"] == "diary"][:17]
    pieces_items = [i for i in today_items if i["source"] == "pieces"][:5]
    today_items = diary_items + pieces_items
    # Score by significance via Claude Haiku (subscription, cached per day)
    today_items = _score_tadah_items(today_items)

    # Yesterday remains explicit context only (never merged into today's list)
    try:
        yesterday_tadah = _parse_tadah_from_journal(yesterday)
    except Exception:
        yesterday_tadah = []

    return {
        "categories": {},
        "flat": [i["text"] for i in today_items],
        "items_with_source": today_items,
        "yesterday": yesterday_tadah,
    }


def parse_wins(content):
    """Parse wins.md - extract most recent accomplishments only (last 3 days)."""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    cutoff = today - timedelta(days=3)

    weeks = re.split(r'^## (Week \d+.*?)$', content, flags=re.MULTILINE)
    if len(weeks) < 3:
        return []
    last_content = weeks[-1]

    skip_prefixes = [
        '- Evidence:', '- Status:', '- Note:', '- Reason:', '- Decision:',
        '- Reflection:', '- Contract:', '- Salary negotiation',
    ]

    wins = []
    current_date = None
    lines = last_content.split('\n')

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue

        # Parse date context from **DayName MonDD: style headers
        date_match = re.match(r'\*\*\w+ (\w+ \d+):', line)
        if date_match:
            try:
                current_date = datetime.strptime(
                    f"{date_match.group(1)} {today.year}", "%b %d %Y"
                ).date()
            except ValueError:
                current_date = None
            continue

        # Parse [YYYY-MM-DD] prefix from Pieces entries
        bracket = re.match(r'[-•]\s*\[(\d{4}-\d{2}-\d{2})\]', line)
        if bracket:
            try:
                current_date = datetime.strptime(bracket.group(1), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Skip lines older than cutoff
        if current_date and current_date < cutoff:
            continue

        # Skip unwanted patterns
        if line.startswith('###') or line.startswith('**Target') or line.startswith('**Actual'):
            continue
        if any(line.startswith(p) for p in skip_prefixes):
            continue
        if '❌' in line:
            continue

        # Accept win lines
        clean = None
        if '🎉' in line or '✅' in line:
            clean = re.sub(r'^\d+\.\s*', '', line).strip('- ').replace('**', '')
        elif line.startswith('- ') and len(line) > 10:
            clean = line.lstrip('- ').strip().replace('**', '')

        if clean:
            # Strip [date] prefix and Pieces attribution
            clean = re.sub(r'^\[\d{4}-\d{2}-\d{2}\]\s*', '', clean).strip()
            clean = re.sub(r'\s*\(via Pieces\)\s*$', '', clean).strip()
            if 5 < len(clean) < 120:
                wins.append(clean)

        if len(wins) >= 4:
            break

    # Deduplicate
    seen = set()
    deduped = []
    for w in wins:
        key = re.sub(r'[^a-z0-9]', '', w.lower())[:60]
        if key not in seen:
            seen.add(key)
            deduped.append(w)

    return deduped[:4]


def generate_html(data):
    """Generate the dashboard HTML with pastel mint/pink colour palette"""

    # === Pastel colour tokens ===
    # Mint: #a7f3d0 (light), #6ee7b7 (mid), #34d399 (bright), #065f46 (dark bg)
    # Pink: #fbcfe8 (light), #f9a8d4 (mid), #f472b6 (bright), #831843 (dark bg)
    # Lavender: #c4b5fd (accent), #8b5cf6 (bright)
    # Warm: #fde68a (amber light), #fbbf24 (amber)

    def _pick_content_emoji(text):
        """Pick a contextual emoji for ANY content item (action items, gratitude, calendar, etc.).
        More general than _pick_insight_emoji -- covers tasks, events, feelings, and daily life."""
        t = text.lower()
        _content_rules = [
            # Communication / people
            (["email", "e-mail", "inbox", "reply", "respond"], "📧"),
            (["call ", "phone", "ring ", "dial"], "📞"),
            (["message", "text ", "whatsapp", "signal", "telegram", "chat"], "💬"),
            (["meeting", "zoom", "teams", "standup", "sync", "1:1", "one-on-one"], "🤝"),
            (["friend", "mate", "adam", "social", "catch up", "hang out"], "👥"),
            (["family", "mum", "dad", "parent", "brother", "sister", "nephew", "niece", "girls", "daughters", "nice time with"], "👨‍👩‍👧"),
            (["partner", "date ", "dating", "relationship"], "💕"),
            # Work / career / productivity
            (["interview", "interviewing"], "🎤"),
            (["apply", "application", "submit", "cv ", "resume", "cover letter"], "📝"),
            (["job ", "career", "employ", "hire", "recruit", "linkedin"], "💼"),
            (["deadline", "due ", "urgent", "asap", "on time", "got up"], "⏰"),
            (["plan", "schedule", "organis", "organiz", "priorit"], "📋"),
            (["code", "script", "debug", "deploy", "build", "develop", "program"], "💻"),
            (["write", "draft", "blog", "article", "content"], "✍️"),
            (["research", "investigate", "look into", "find out"], "🔍"),
            # Shopping / errands
            (["shop", "buy ", "purchase", "order", "amazon", "supermarket", "grocer", "tesco", "sainsbury"], "🛒"),
            (["pick up", "collect", "deliver", "parcel", "package", "post "], "📦"),
            (["bank", "transfer", "pay ", "payment", "invoice", "bill", "direct debit"], "💳"),
            # Creative / leisure (check before health so "calming music" → 🎵 not 🧘‍♂️)
            (["music", "listen", "spotify", "album", "song", "playlist"], "🎵"),
            (["film", "movie", "cinema", "watch", "netflix", "tv ", "series"], "🎬"),
            (["read", "book", "kindle", "chapter", "novel"], "📚"),
            (["photo", "camera", "picture", "image"], "📸"),
            (["art", "draw", "paint", "sketch", "creat"], "🎨"),
            (["game", "play", "gaming", "xbox", "playstation", "switch", "steam"], "🎮"),
            # Health / fitness / body
            (["gym", "workout", "weights", "lift", "press", "squat", "deadlift"], "🏋️"),
            (["yoga", "stretch", "pilates", "flexibility"], "🧘"),
            (["walk", "walking", "steps", "hike"], "🚶"),
            (["run ", "running", "jog", "cardio"], "🏃"),
            (["exercise", "active", "movement", "physical"], "💪"),
            (["swim", "pool", "lane"], "🏊"),
            (["meditat", "mindful", "breathe", "breathing", "calm"], "🧘‍♂️"),
            (["sleep", "rest", "nap", "bed ", "insomnia", "tired", "fatigue"], "😴"),
            (["pain", "ache", "sore", "tight", "tension", "stiff"], "🤕"),
            (["doctor", "gp ", "appointment", "dentist", "optician"], "🏥"),
            (["therapy", "therapist", "counsell", "session"], "🛋️"),
            (["medic", "prescription", "tablet", "pill"], "💊"),
            (["food", "eat", "meal", "cook", "recipe", "lunch", "dinner", "breakfast", "burrito", "made food"], "🍽️"),
            (["water", "hydrat", "drink"], "💧"),
            # Mental / emotional
            (["anxi", "worry", "stress", "overwhelm", "panic"], "🌊"),
            (["mood", "emotion", "feeling"], "🎭"),
            (["brain", "cognit", "focus", "attention", "adhd", "executive function"], "🧠"),
            (["grateful", "gratitude", "thankful", "appreciat", "blessed"], "🙏"),
            (["proud", "accomplish", "achieve", "celebrate", "win ", "won ", "persever"], "🏆"),
            (["brave", "courage", "risk", "challeng", "difficult", "hard "], "🦁"),
            (["safe", "secure", "comfort", "warm", "cosy", "cozy"], "🏡"),
            (["happy", "joy", "delight", "glad", "excit"], "😊"),
            (["love", "loved", "loving", "kind", "compassion"], "❤️"),
            (["hope", "optimis", "looking forward", "excited about"], "🌟"),
            (["peace", "serene", "tranquil", "still", "quiet"], "🕊️"),
            (["energy", "motiv", "drive", "fuel", "recharg"], "⚡"),
            # Household / home
            (["tidy", "tidied", "clean", "hoover", "vacuum", "dust", "organise", "organize"], "🧹"),
            (["laundry", "wash", "iron", "clothes"], "👕"),
            (["dishes", "kitchen", "cook"], "🍳"),
            (["garden", "plant", "water", "mow"], "🌱"),
            (["fix", "repair", "diy", "tool"], "🔧"),
            # Travel / commute
            (["travel", "trip", "flight", "train", "bus ", "tube", "commute", "drive"], "🚗"),
            (["airport", "station", "terminal"], "✈️"),
            # Learning / growth
            (["learn", "study", "course", "tutorial", "class", "lecture"], "📖"),
            (["idea", "insight", "realis", "discover"], "💡"),
            (["goal", "target", "milestone", "aim"], "🎯"),
            (["progress", "improv", "growth", "forward", "momentum"], "📈"),
            (["habit", "routine", "streak", "consistent"], "📊"),
            # Tech / admin
            (["update", "upgrade", "install", "download", "software", "app "], "📲"),
            (["password", "login", "account", "security"], "🔐"),
            (["backup", "sync", "cloud", "storage"], "☁️"),
            (["config", "setting", "preference", "setup"], "⚙️"),
            (["daemon", "dashboard", "claude", "script", "cache", "system"], "🤖"),
            # Money
            (["money", "financ", "budget", "saving", "income", "cost", "invest"], "💰"),
            # Weather / time / nature
            (["morning", "sunrise", "dawn", "wake"], "🌅"),
            (["evening", "sunset", "night", "dusk"], "🌙"),
            (["sun", "sunny", "bright", "warm"], "☀️"),
            (["rain", "storm", "weather", "cold", "wind"], "🌧️"),
            (["nature", "outside", "park", "tree", "forest", "beach", "sea", "ocean"], "🌿"),
            # Places / venues
            (["museum", "gallery", "exhibit", "tate"], "🏛️"),
            # Emotional repair / remorse
            (["remorse", "guilt", "sorry", "apologi", "forgave"], "💙"),
            (["baby", "toddler", "child", "infant"], "👶"),
        ]
        for keywords, emoji in _content_rules:
            if any(kw in t for kw in keywords):
                return emoji
        return "▸"  # clean default for unmatched items

    # Calendar HTML - grouped by time blocks with emoji
    calendar_html = ""
    calendar_events = data.get("calendar", [])[:12]  # Show more events with grouping

    # Group events by time blocks
    time_blocks = {
        '🌅 Morning (6am-12pm)': [],
        '☀️ Afternoon (12pm-5pm)': [],
        '🌆 Evening (5pm-9pm)': [],
        '🌙 Night (9pm-6am)': []
    }

    for item in calendar_events:
        time_str = item.get("time", "")
        # Determine time block based on hour
        try:
            # Parse time (format: "HH:MM" or "HH:MM am/pm")
            time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
            if time_match:
                hour = int(time_match.group(1))
                # Convert to 24h if needed
                if 'pm' in time_str.lower() and hour != 12:
                    hour += 12
                elif 'am' in time_str.lower() and hour == 12:
                    hour = 0

                if 6 <= hour < 12:
                    time_blocks['🌅 Morning (6am-12pm)'].append(item)
                elif 12 <= hour < 17:
                    time_blocks['☀️ Afternoon (12pm-5pm)'].append(item)
                elif 17 <= hour < 21:
                    time_blocks['🌆 Evening (5pm-9pm)'].append(item)
                else:
                    time_blocks['🌙 Night (9pm-6am)'].append(item)
            else:
                # All-day event or unparseable - add to morning
                time_blocks['🌅 Morning (6am-12pm)'].append(item)
        except Exception:
            time_blocks['🌅 Morning (6am-12pm)'].append(item)

    # Render grouped events
    for block_name, events in time_blocks.items():
        if events:
            calendar_html += f'<div class="mb-3"><p class="text-xs font-semibold mb-2" style="color: #9ca3af">{html.escape(block_name)}</p>'
            for item in events:
                event_text = str(item.get("event", ""))
                time_text = str(item.get("time", ""))
                is_akiflow = item.get("type") == "task"
                if is_akiflow:
                    event_emoji = "📌"
                    text_color = "#fbbf24"
                else:
                    event_emoji = _pick_content_emoji(event_text)
                    text_color = "#e5e7eb"
                calendar_html += f'''
        <div class="flex items-center gap-2 text-sm ml-2">
            <span class="w-14 font-mono text-xs" style="color: #9ca3af">{html.escape(time_text)}</span>
            <span style="font-size: 0.9rem;">{event_emoji}</span>
            <span style="color: {text_color}">{html.escape(event_text)}</span>
        </div>'''
            calendar_html += '</div>'

    # Scheduling nudge: if no Akiflow tasks (Tasks calendar) are in today's calendar
    _cal_has_akiflow = any(e.get("type") == "task" for e in data.get("calendar", []))
    if not _cal_has_akiflow:
        calendar_html += '<p class="text-xs mt-3 pt-3" style="border-top: 1px solid rgba(249,168,212,0.12); color: #9ca3af">⏰ Nothing scheduled yet — consider time-blocking in Akiflow.</p>'

    # Ta-Dah HTML — categorised with emoji headers, merged with recent wins as badges
    tadah_data = data.get("tadah", {})
    if isinstance(tadah_data, list):
        # Legacy flat list format
        tadah_flat = tadah_data
        tadah_categories = {}
    else:
        tadah_flat = tadah_data.get("flat", [])
        tadah_categories = tadah_data.get("categories", {})

    # Strip Diarium bullet artifacts (∙, •, ·, tabs) and filter sentinel "list" item
    _BULLET_STRIP = re.compile(r'^[\u2219\u2022\u00b7\u2022\-\*\t\s]+')
    def _clean_tadah_text(t):
        return _strip_completion_hash_artifacts(_BULLET_STRIP.sub("", str(t)).strip())
    tadah_flat = [_clean_tadah_text(t) for t in tadah_flat
                  if str(t).strip().lower() not in ("list", "")]
    yesterday_tadah = [_clean_tadah_text(t) for t in (tadah_data.get("yesterday", []) if isinstance(tadah_data, dict) else [])
                       if _clean_tadah_text(t) and str(t).strip().lower() not in ("list", "")]

    wins = data.get("wins", [])
    tadah_html = ""
    _category_order = ["family", "emotional_growth", "self_care", "admin", "social", "work", "creative", "household", "uncategorised"]
    _category_labels = {
        "family": "👨‍👩‍👧 Family & Connection",
        "emotional_growth": "🌱 Emotional Growth",
        "self_care": "🧘 Self-Care & Regulation",
        "admin": "📋 Admin",
        "social": "💬 Social",
        "work": "💼 Work",
        "creative": "🎬 Creative",
        "household": "🏠 Routine & Household",
        "uncategorised": "✅ Other"
    }
    _category_colors = {
        "family": "#f9a8d4",           # soft pink (warm)
        "emotional_growth": "#fbbf24", # warm amber (growth/achievement)
        "self_care": "#7dd3fc",        # soft cyan (calming)
        "admin": "#fdba74",            # soft orange (attention)
        "social": "#e9d5ff",           # soft lilac (social)
        "work": "#93c5fd",             # soft blue (professional)
        "creative": "#c4b5fd",         # soft purple (imagination)
        "household": "#86efac",        # soft green (home)
        "uncategorised": "#d1d5db"     # soft gray (neutral)
    }

    # Fallback helpers (overridden by richer categoriser in flat-list branch below).
    def _get_sort_key(item_text):
        return (999, str(item_text).lower())

    def _get_category(item_text):
        return "uncategorised"

    if tadah_categories:
        # Categorised display
        for cat_name, items in tadah_categories.items():
            tadah_html += f'<div class="mb-2"><p class="text-xs font-semibold mb-1" style="color: #9ca3af">{html.escape(str(cat_name))}</p>'
            for item in items:
                tadah_html += f'<div class="flex items-start gap-2 text-sm ml-2"><span style="color: #6ee7b7">•</span><span style="color: #d1d5db">{html.escape(str(item))}</span></div>'
            tadah_html += '</div>'
    else:
        # Flat list with inline category emojis from ta_dah_categorised
        _ta_dah_cat_data = data.get("taDahCategorised", {}) if "data" in dir() else {}
        _theme_emojis = {
            "work": "💼", "self_care": "🧘", "household": "🏠",
            "family": "👨‍👩‍👧", "creative": "🎬", "social": "💬",
            "health": "💪", "admin": "📋", "learning": "📚",
            "emotional_growth": "🌱",
        }
        # Simple keyword-to-theme mapping for inline categorisation
        # Order matters: more specific themes checked first to avoid false matches
        # Mental health/self-care/social keywords expanded for neurodivergent wins
        from collections import OrderedDict
        _kw_themes = OrderedDict([
            ("emotional_growth", [
                # Perseverance, accountability, vulnerability
                "persever", "remorse", "guilt", "accountab", "apologi", "sorry",
                "forgave", "bounced back", "pushed through", "kept going", "didn't give up",
                "honest", "vulnerab", "brave", "proud", "overcame", "faced",
                "admitted", "owned", "reflected", "grew", "growth",
            ]),
            ("family", [
                "family", "wife", "daughter", "kids", "janna", "girls", "mum", "my dad",
                "museum", "park", "outing", "day out", "trip", "nice time with",
            ]),
            ("admin", ["organis", "schedule", "email", "sort", "fix", "improv", "claude", "dashboard", "api", "parsing", "invest", "ensure"]),
            ("social", [
                "friend", "spoke", "adam", "call ", "chat", "message",
                # Expanded social wins
                "messaged", "replied", "reached out", "spoke to", "texted", "called",
            ]),
            ("creative", ["film", "cinema", "photo", "write", "creative", "music"]),
            ("self_care", [
                # Physical self-care
                "yoga", "walk", "weight", "exercise", "meditat", "breakfast", "healthy", "ate ", "food", "steps", "coco", "diary", "journal", "look",
                # Basic self-care wins (neurodivergent — these matter enormously)
                "bed", "teeth", "shower", "dressed", "medication", "meds",
                # Routine wins
                "got up on time", "woke up", "early", "routine",
                # Mental health / emotional regulation
                "regulated", "calm", "breathed", "managed", "coped", "despite", "anxiety",
                "didn't snap", "got through", "hard day", "difficult", "overwhelmed", "asked for help",
            ]),
            ("household", [
                "clean", "tidy", "tidied", "laundry", "dishes", "hoover", "cook", "household",
                "window", "extractor", "sweep", "mop", "iron", "vacuum", "dusting", "bins", "wash",
                # Cooking specifics
                "burrito", "dinner", "lunch", "meal", "made food",
            ]),
            ("work", ["went to work", "at work", "job", "apply", "application", "interview", "career", "sony", "bfi", "working title", "office"]),
        ])
        def _categorise_item(item_text):
            lower = item_text.lower()
            # Detect cleaning tasks to prevent false self_care matches (e.g. "cleaned bathroom" matching "bath")
            is_cleaning = any(kw in lower for kw in ['clean', 'tidy', 'wash', 'hoover', 'vacuum', 'sweep', 'mop', 'dust', 'iron'])
            for theme, keywords in _kw_themes.items():
                # Skip self_care for cleaning tasks — same guard as daemon
                if theme == 'self_care' and is_cleaning:
                    continue
                for kw in keywords:
                    if kw in lower:
                        return _theme_emojis.get(theme, "•")
            # Short ta-dahs (<8 words) with no keyword match → uncategorised, not self_care
            # The daemon doesn't default unknowns to self_care, so neither should the dashboard
            return "✅"

        # Build source/score lookup: cleaned item text → source and score
        _items_with_source = tadah_data.get("items_with_source", []) if isinstance(tadah_data, dict) else []
        _source_lookup = {}
        _score_lookup = {}
        for _itm in _items_with_source:
            _cleaned_key = _BULLET_STRIP.sub("", str(_itm.get("text", ""))).strip()
            _source_lookup[_cleaned_key] = _itm.get("source", "diary")
            _score_lookup[_cleaned_key] = _itm.get("score")
        _has_scores = any(v is not None for v in _score_lookup.values())

        # Category helpers (used for inline emoji on each item)
        _emoji_to_category = {v: k for k, v in _theme_emojis.items()}
        _emoji_to_category["✅"] = "uncategorised"

        def _get_sort_key(item_text):
            emoji = _categorise_item(item_text)
            category = _emoji_to_category.get(emoji, "uncategorised")
            order = _category_order.index(category) if category in _category_order else 999
            return (order, item_text.lower())

        def _get_category(item_text):
            emoji = _categorise_item(item_text)
            return _emoji_to_category.get(emoji, "uncategorised")

        def _render_tadah_item(item_text, category, source="diary", score=None):
            color = _category_colors.get(category, "#d1d5db")
            content_emoji = _pick_content_emoji(item_text)
            source_badge = ""
            if source == "pieces":
                source_badge = '<span style="margin-left: 6px; padding: 1px 6px; background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.35); border-radius: 9999px; color: #fbbf24; font-size: 0.65rem; vertical-align: middle; white-space: nowrap;">⚡ Pieces</span>'
            # ★ prefix on high-significance items (score 4+)
            star_prefix = '<span style="color: #fbbf24; margin-right: 4px; font-size: 0.85em;">★</span>' if (score is not None and score >= 4) else ""
            return (f'<div class="flex items-start gap-2 text-sm" style="margin-left: 4px;">'
                    f'<span style="color: {color}; font-size: 1.2em; line-height: 1;">●</span>'
                    f'<span style="color: #d1d5db; line-height: 1.4;">{star_prefix}{html.escape(str(item_text))} {content_emoji}{source_badge}</span>'
                    f'</div>')

        # Sort: by category first, then by significance (score desc) within each category
        def _get_sort_key_with_score(item_text):
            emoji = _categorise_item(item_text)
            category = _emoji_to_category.get(emoji, "uncategorised")
            cat_order = _category_order.index(category) if category in _category_order else 999
            score = _score_lookup.get(item_text) or 0
            return (cat_order, -score, item_text.lower())

        tadah_sorted = sorted(tadah_flat, key=_get_sort_key_with_score)
        _VISIBLE_TADAH = 15  # show up to 15 before collapsing

        def _render_tadah_list(items):
            out = ""
            last_cat = None
            for i, item in enumerate(items):
                current_category = _get_category(item)
                item_score = _score_lookup.get(item)
                if current_category != last_cat:
                    out += (f'<div style="color: #6ee7b7; font-size: 0.85rem; font-weight: 700; '
                            f'margin-top: {12 if i > 0 else 0}px; margin-bottom: 6px; '
                            f'text-transform: uppercase; letter-spacing: 0.08em;">'
                            f'{_category_labels.get(current_category, "Other")}</div>')
                    last_cat = current_category
                out += _render_tadah_item(item, current_category, _source_lookup.get(item, "diary"), item_score)
            return out

        tadah_html += _render_tadah_list(tadah_sorted[:_VISIBLE_TADAH])

        if len(tadah_sorted) > _VISIBLE_TADAH:
            extra_html = _render_tadah_list(tadah_sorted[_VISIBLE_TADAH:])
            tadah_html += (f'<details class="mt-2"><summary style="color: #6ee7b7; font-size: 0.75rem; cursor: pointer;">'
                           f'+{len(tadah_sorted) - _VISIBLE_TADAH} more</summary>'
                           f'<div class="mt-1 space-y-1">{extra_html}</div></details>')

    # Append recent wins as mint badges
    if wins:
        wins_badges = ""
        for w in wins:
            win_emoji = _pick_content_emoji(w)
            wins_badges += f'<span class="optional-pill" style="background: rgba(6,95,70,0.4); border: 1px solid rgba(110,231,183,0.3); border-radius: 9999px; padding: 2px 10px; color: #a7f3d0; font-size: 0.75rem;">{win_emoji} {html.escape(str(w))}</span>'
        tadah_html += f'<div class="flex flex-wrap gap-1 mt-3 pt-2" style="border-top: 1px solid #374151">{wins_badges}</div>'

    # Yesterday's ta-dahs — always separate from today's list for clear differentiation
    # Uses same categorization as today's ta-dahs (helpers defined in else block above)
    yesterday_tadah_html = ""
    if yesterday_tadah:
        try:
            yesterday_label_date = (
                datetime.strptime(get_effective_date(), "%Y-%m-%d") - timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except Exception:
            yesterday_label_date = "yesterday"
        yesterday_sorted = sorted(yesterday_tadah[:10], key=_get_sort_key)
        yesterday_items = ""
        last_cat = None
        for i, item in enumerate(yesterday_sorted):
            current_cat = _get_category(item)
            if current_cat != last_cat:
                yesterday_items += f'<div style="color: #6b7280; font-size: 0.85rem; font-weight: 700; margin-top: {10 if i > 0 else 0}px; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.08em;">{_category_labels.get(current_cat, "Other")}</div>'
                last_cat = current_cat
            color = _category_colors.get(current_cat, "#9ca3af")
            yesterday_items += f'<div class="flex items-start gap-2 text-sm" style="margin-left: 4px;"><span style="color: {color}; opacity: 0.6; font-size: 1.2em; line-height: 1;">●</span><span style="color: #9ca3af; line-height: 1.4;">{html.escape(str(item))}</span></div>'
        yesterday_tadah_html = f'''
        <div class="mt-3 pt-3" style="border-top: 1px solid #374151">
            <details>
                <summary class="text-xs font-semibold cursor-pointer" style="color: #9ca3af">📋 Yesterday&apos;s Ta-Dahs ({html.escape(yesterday_label_date)}) • {len(yesterday_sorted)}</summary>
                <div class="mt-2">
                    {yesterday_items}
                </div>
            </details>
        </div>'''

    # Habits HTML — pastel progress bars with at-risk warnings
    habits_html = ""
    for h in data.get("habits", [])[:6]:
        rate = h.get("rate", 0)
        color = "#6ee7b7" if rate >= 80 else "#fbbf24" if rate >= 50 else "#f9a8d4"
        # Add warning flag for habits < 60% (at risk)
        warning_flag = '<span style="color: #fbbf24; font-size: 0.9rem; margin-right: 4px;">⚠️</span>' if rate < 60 else ''
        habit_emoji = _pick_content_emoji(h.get("name", ""))
        habits_html += f'''
        <div class="flex items-center gap-2 mb-2">
            {warning_flag}<span class="w-28 text-sm" style="color: #d1d5db">{habit_emoji} {h.get("name", "")}</span>
            <div class="flex-1 h-2 rounded-full overflow-hidden" style="background: #1f2937">
                <div class="h-full rounded-full" style="width:{rate}%;background:{color}"></div>
            </div>
            <span class="w-10 text-xs text-right" style="color: #9ca3af">{rate:.0f}%</span>
        </div>'''

    # Jobs HTML
    jobs_html = ""
    for job in data.get("topJobs", [])[:3]:
        score = job.get("score", 0)
        badge_bg = "rgba(6,95,70,0.4)" if score >= 18 else "rgba(120,53,15,0.4)"
        badge_color = "#a7f3d0" if score >= 18 else "#fde68a"
        job_emoji = _pick_content_emoji(job.get("title", ""))
        jobs_html += f'''
        <div class="flex justify-between items-center text-sm mb-1">
            <span style="color: #d1d5db" class="truncate flex-1">{job_emoji} {job.get("title", "")}</span>
            <span class="ml-2 px-2 py-0.5 rounded text-xs" style="background:{badge_bg};color:{badge_color}">{score}</span>
        </div>'''

    # === Workout Guide (always visible) ===
    workout_html = ""
    workout = get_todays_workout()
    workout_progression = data.get("workoutProgression", {}) if isinstance(data.get("workoutProgression"), dict) else {}
    workout_progression_ui = workout_progression_view(workout_progression)
    workout_progression_detail_html = (
        f'<p id="qa-workout-progression-detail" class="text-xs mt-1" style="color: #6b7280">{html.escape(workout_progression_ui["detail"])}</p>'
        if workout_progression_ui["detail"] else ""
    )

    def _build_workout_exercise_list(exercises):
        if not exercises or not isinstance(exercises, list):
            return ""
        items_html = ""
        for ex in exercises:
            label = ex.get("name", "")
            note = ex.get("sets_reps") or ex.get("muscles", "")
            items_html += f'<li style="color: #d1d5db; margin-bottom: 2px;">{label} — <span style="color: #9ca3af">{note}</span></li>\n'
        return f'<ul style="margin: 6px 0 0 0; padding-left: 18px; list-style: disc;">{items_html}</ul>'

    exercise_list_html = _build_workout_exercise_list(workout.get("exercises"))
    detail_badge = f'<span class="text-sm ml-2" style="color: #9ca3af">({workout["detail"]})</span>' if workout.get("detail") else ""
    workout_toggle_html = ""
    if workout.get("type") in {"weights", "yoga"}:
        checked_attr = "checked" if workout.get("done") else ""
        workout_meta_text = f"✅ {workout['title']} logged for today" if workout.get("done") else f"⬜ {workout['title']} not logged yet"
        workout_meta_color = "#6ee7b7" if workout.get("done") else "#9ca3af"
        workout_toggle_html = f'''
        <div class="mt-3 pt-3" style="border-top: 1px solid rgba(110,231,183,0.15);">
            <label class="flex items-center gap-3 cursor-pointer">
                <input id="qa-workout-check" type="checkbox" {checked_attr} data-workout="{html.escape(workout["title"], quote=True)}" onchange="qaToggleWorkout(this)" class="h-4 w-4">
                <span class="text-sm" style="color: #e5e7eb">Log today&apos;s {workout["title"]}</span>
            </label>
            <p id="qa-workout-meta" class="text-xs mt-2" style="color: {workout_meta_color}">{workout_meta_text}</p>
        </div>'''

    if workout["done"]:
        workout_html = f'''
    <div class="card rounded-xl p-4 mb-4" style="background: rgba(6,95,70,0.15); border: 1px solid rgba(110,231,183,0.2);">
        <div class="flex items-center gap-3">
            <span class="text-2xl">✅</span>
            <div>
                <span class="text-base font-semibold" style="color: #6ee7b7">Workout Guide: {workout["title"]} — done</span>
                {detail_badge}
            </div>
        </div>
        <p id="qa-workout-progression-meta" class="text-xs mt-2" style="color: {workout_progression_ui["color"]}">{html.escape(workout_progression_ui["label"])}</p>
        {workout_progression_detail_html}
        {exercise_list_html}
        {workout_toggle_html}
    </div>'''
    elif workout["type"] == "rest":
        workout_html = f'''
    <div class="card rounded-xl p-4 mb-4 flex items-center gap-3" style="background: rgba(55,65,81,0.3); border: 1px solid rgba(107,114,128,0.2);">
        <span class="text-2xl">{workout["emoji"]}</span>
        <div>
            <span class="text-base font-semibold" style="color: #d1d5db">Workout Guide: {workout["title"]}</span>
            <p id="qa-workout-progression-meta" class="text-xs mt-1" style="color: {workout_progression_ui["color"]}">{html.escape(workout_progression_ui["label"])}</p>
            {workout_progression_detail_html}
            {f'<p class="text-xs mt-1" style="color: #9ca3af">{workout["detail"]}</p>' if workout.get("detail") else ""}
        </div>
    </div>'''
    else:
        window_note = "Tonight option: still valid to run this session if energy allows." if datetime.now().hour >= 14 else "Plan this into today’s schedule."
        workout_html = f'''
    <div class="card rounded-xl p-4 mb-4" style="background: rgba(6,95,70,0.15); border: 1px solid rgba(110,231,183,0.2);">
        <div class="flex items-center gap-3">
            <span class="text-2xl">{workout["emoji"]}</span>
            <div>
                <span class="text-base font-semibold" style="color: #6ee7b7">Workout Guide: {workout["title"]}</span>
                {detail_badge}
                <p class="text-xs mt-1" style="color: #9ca3af">{window_note}</p>
            </div>
        </div>
        <p id="qa-workout-progression-meta" class="text-xs mt-2" style="color: {workout_progression_ui["color"]}">{html.escape(workout_progression_ui["label"])}</p>
        {workout_progression_detail_html}
        {exercise_list_html}
        {workout_toggle_html}
    </div>'''

    # === Film Section (Letterboxd) ===
    film_html = ""
    film_data = data.get("film_data", {}) if isinstance(data.get("film_data"), dict) else {}
    if film_data.get("status") == "success" and not (film_data.get("stale") and film_data.get("export_age_days", 0) > 180):
        import html as _html
        def _format_lb_rating(raw_rating):
            if raw_rating in (None, ""):
                return ""
            try:
                rating_num = float(raw_rating)
                if rating_num <= 0:
                    return ""
                return f"★{rating_num:g}"
            except Exception:
                rating_text = str(raw_rating).strip()
                return f"★{rating_text}" if rating_text else ""

        wl_count = film_data.get("counts", {}).get("watchlist") or film_data.get("full_watchlist_count", 0)
        recent_watched = film_data.get("recent_watched", [])[:5]
        recent_watchlist = film_data.get("recent_watchlist", [])[:5]
        fetched_at = film_data.get("fetched_at", "")[:10] if film_data.get("fetched_at") else "unknown"
        lb_username = film_data.get("username", "jcherry01")
        film_recs = build_watch_recommendations(film_data, data)
        film_profile = film_recs.get("profile", {}) if isinstance(film_recs.get("profile", {}), dict) else {}
        film_primary = film_recs.get("primary", {}) if isinstance(film_recs.get("primary", {}), dict) else {}
        film_alternates = film_recs.get("alternates", []) if isinstance(film_recs.get("alternates", []), list) else []
        recent_watch_note = str(film_recs.get("recent_watch_note", "")).strip()

        # Recently watched
        watched_items_html = ""
        for item in recent_watched:
            title = _html.escape(str(item.get("title", "")))
            year = _html.escape(str(item.get("year", "")))
            date = _html.escape(str(item.get("date", "")))
            rating_label = _format_lb_rating(item.get("rating"))
            rating_html = f'<span class="text-xs" style="color:#fbbf24">{_html.escape(rating_label)}</span>' if rating_label else ""
            date_html = f'<span class="text-xs" style="color:#4b5563">{date}</span>' if date else ""
            meta_html = f'<span class="ml-auto flex items-center gap-2">{rating_html}{date_html}</span>' if (rating_html or date_html) else ""
            watched_items_html += f'<div class="flex items-center gap-2 mb-1"><span style="color:#c4b5fd">🎬</span><span class="text-sm" style="color:#e5e7eb">{title} <span style="color:#6b7280">({year})</span></span>{meta_html}</div>'

        # Watchlist recently added
        watchlist_items_html = ""
        for item in recent_watchlist:
            title = _html.escape(str(item.get("title", "")))
            year = _html.escape(str(item.get("year", "")))
            url = item.get("url", "")
            link = f'<a href="{_html.escape(url)}" style="color:#f9a8d4;text-decoration:none">{title}</a>' if url else title
            watchlist_items_html += f'<div class="flex items-center gap-2 mb-1"><span style="color:#f9a8d4">📋</span><span class="text-sm" style="color:#e5e7eb">{link} <span style="color:#6b7280">({year})</span></span></div>'

        watched_summary = f"{len(recent_watched)} diary entries" if recent_watched else "No recent diary"
        wl_str = f"{wl_count:,}" if isinstance(wl_count, int) else str(wl_count or "?")
        latest_item = recent_watched[0] if recent_watched else {}
        latest_title = str(latest_item.get("title", "")).strip()
        latest_rating_label = _format_lb_rating(latest_item.get("rating"))
        latest_summary_html = ""
        if latest_title:
            latest_title_html = _html.escape(latest_title)
            latest_rating_html = f' <span style="color:#fbbf24">{_html.escape(latest_rating_label)}</span>' if latest_rating_label else ""
            latest_summary_html = f" · Latest: {latest_title_html}{latest_rating_html}"

        primary_pick_summary_html = ""
        primary_pick_html = ""
        primary_title = str(film_primary.get("title", "")).strip()
        if primary_title:
            primary_year = str(film_primary.get("year", "")).strip()
            primary_url = str(film_primary.get("url", "")).strip()
            primary_reason = str(film_primary.get("reason", "")).strip()
            primary_link = (
                f'<a href="{_html.escape(primary_url)}" style="color:#f9a8d4;text-decoration:none">{_html.escape(primary_title)}</a>'
                if primary_url else _html.escape(primary_title)
            )
            primary_pick_summary_html = f" · Tonight: {_html.escape(primary_title)}"
            profile_headline = str(film_profile.get("headline", "")).strip()
            profile_reason = str(film_profile.get("reason_text", "")).strip()
            profile_reason_html = (
                f'<p class="text-xs mt-1" style="color:#9ca3af">{_html.escape(profile_reason)}</p>'
                if profile_reason else ""
            )
            alternate_rows_html = ""
            for alt in film_alternates[:2]:
                alt_title = str(alt.get("title", "")).strip()
                if not alt_title:
                    continue
                alt_year = str(alt.get("year", "")).strip()
                alt_url = str(alt.get("url", "")).strip()
                alt_reason = str(alt.get("reason", "")).strip()
                alt_link = (
                    f'<a href="{_html.escape(alt_url)}" style="color:#cbd5e1;text-decoration:none">{_html.escape(alt_title)}</a>'
                    if alt_url else _html.escape(alt_title)
                )
                alt_reason_html = (
                    f'<span class="text-xs" style="color:#94a3b8">{_html.escape(alt_reason)}</span>'
                    if alt_reason else ""
                )
                alternate_rows_html += (
                    f'<div class="flex items-start gap-2 mb-1">'
                    f'<span style="color:#cbd5e1">•</span>'
                    f'<div class="min-w-0"><p class="text-sm" style="color:#cbd5e1">{alt_link} '
                    f'<span style="color:#6b7280">({ _html.escape(alt_year) })</span></p>{alt_reason_html}</div>'
                    f'</div>'
                )
            alternates_html = ""
            if alternate_rows_html:
                alternates_html = (
                    '<div class="mt-3">'
                    '<p class="text-xs font-semibold mb-2" style="color:#cbd5e1">Back-up picks</p>'
                    f'{alternate_rows_html}'
                    '</div>'
                )
            primary_pick_html = f'''
            <div class="rounded-lg px-3 py-2.5 mb-3" style="background:rgba(88,28,135,0.18);border:1px solid rgba(196,181,253,0.28)">
              <p class="text-xs font-semibold mb-1" style="color:#f9a8d4">🍿 Tonight&apos;s watch</p>
              <p class="text-sm font-semibold" style="color:#f3e8ff">{primary_link} <span style="color:#94a3b8">({_html.escape(primary_year)})</span></p>
              <p class="text-sm mt-1" style="color:#e5e7eb">{_html.escape(profile_headline)}</p>
              {profile_reason_html}
              {(f'<p class="text-xs mt-2" style="color:#cbd5e1">{_html.escape(primary_reason)}</p>') if primary_reason else ''}
              {alternates_html}
            </div>
            '''

        watched_note_html = (
            f'<p class="text-xs mb-2" style="color:#9ca3af">{_html.escape(recent_watch_note)}</p>'
            if recent_watch_note else ""
        )
        watched_block = (
            f'<div class="mt-3"><p class="text-xs font-semibold mb-2" style="color:#c4b5fd">Recently watched</p>'
            f'{watched_note_html}{watched_items_html}</div>'
        ) if watched_items_html else ""
        wl_block = (
            '<details class="mt-3 rounded-lg px-3 py-2" '
            'style="background:rgba(15,23,42,0.36);border:1px solid rgba(249,168,212,0.18)">'
            '<summary class="text-xs font-semibold cursor-pointer" style="color:#f9a8d4">'
            f'📋 Watchlist adds ({len(recent_watchlist)})</summary>'
            f'<div class="mt-2">{watchlist_items_html}</div>'
            '</details>'
        ) if watchlist_items_html else ""

        film_html = f'''<details class="card rounded-xl p-5 mb-4" style="background:rgba(88,28,135,0.12);border:1px solid rgba(196,181,253,0.18)">
  <summary class="cursor-pointer flex items-center gap-2">
    <span class="text-lg font-semibold" style="color:#c4b5fd">🎬 Film</span>
    <span class="text-sm ml-2" style="color:#9ca3af">{watched_summary} · {wl_str} watchlist{latest_summary_html}{primary_pick_summary_html}</span>
  </summary>
  <div class="mt-3">
    {primary_pick_html}
    {watched_block}
    {wl_block}
    <p class="text-xs mt-3" style="color:#4b5563"><a href="https://letterboxd.com/{_html.escape(lb_username)}/" style="color:#6b7280">@{_html.escape(lb_username)}</a> · synced {fetched_at}</p>
  </div>
</details>'''

    # === Action Items Section — categorised by quick_win / maintenance / standard ===
    # Matches embed-dashboard-in-notes.py action items section
    ai_insights = data.get("aiInsights", {})
    ai_today = get_ai_day(ai_insights, get_effective_date())
    weekly_digest_for_actions = data.get("weeklyDigest", {}) if isinstance(data.get("weeklyDigest"), dict) else {}
    weekly_report_due = bool(weekly_digest_for_actions.get("needs_generation"))
    action_items_list_html = '<p class="text-sm" style="color: #9ca3af">No action items right now.</p>'
    display_action_items = []
    one_thing_candidates = []

    # Date-gate: only show action items from today's data
    _effective_today = get_effective_date()
    _ai_is_today = ai_today.get("status") == "success"
    _completed_hashes_today, _completed_text_keys_today, _completed_labels_today = load_completed_todo_state(
        COMPLETED_TODOS_FILE,
        _effective_today,
    )

    # Collect action items from multiple sources (only if data is from today)
    diarium_data = data.get("diariumTodos", []) if data.get("diariumDataDate") == _effective_today else []
    notes_todos = data.get("appleNotesTodos", []) if isinstance(data.get("appleNotesTodos", []), list) else []
    diarium_tadah = data.get("diariumTaDah", []) if data.get("diariumDataDate") == _effective_today else []
    ai_todos = ai_today.get("genuine_todos", []) if _ai_is_today else []

    # --- Akiflow today tasks (non-routine, for action items injection) ---
    _akiflow_today_items = collect_akiflow_today_items(data.get("akiflow_tasks", {}))

    # --- Schedule analysis extraction (feasibility_map populated after _task_match_key) ---
    _sa = data.get("schedule_analysis", {})
    _sa_today = isinstance(_sa, dict) and _sa.get("date") == _effective_today
    _burnout_risk = _sa.get("burnout_risk", "") if _sa_today else ""
    _schedule_density = _sa.get("schedule_density", "") if _sa_today else ""
    _schedule_insight = _sa.get("schedule_insight", "") if _sa_today else ""
    _feasibility_map = {}  # populated after _task_match_key is defined below

    _task_match_key = task_match_key
    _task_completion_hash = task_completion_hash
    _task_completion_hash_legacy = task_completion_hash_legacy
    _tasks_equivalent = tasks_equivalent
    _is_actionable_task = is_actionable_task
    _compact_task_text = compact_task_text
    _future_keywords = FUTURE_KEYWORDS
    _is_future_facing_task = is_future_facing_task

    _deferred_task_targets = _load_action_item_defer_targets(_effective_today)
    _deferred_task_rows = _load_action_item_defer_rows(_effective_today)
    _persisted_action_rows = _load_active_action_item_state_rows(_effective_today)

    # Pending task guard: tasks still in genuine_todos are never "done" even if a stale
    # hash exists in completed-todos.json (daemon false-positive injection defence).
    _pending_task_keys = {
        _task_match_key(t.get("text", "") if isinstance(t, dict) else str(t))
        for t in ai_todos
        if (t.get("text", "") if isinstance(t, dict) else str(t)).strip()
    }
    # Also add article-stripped variants so minor wording differences still match
    _article_words = {"the", "a", "an"}
    _pending_task_keys |= {
        " ".join(w for w in k.split() if w not in _article_words)
        for k in _pending_task_keys
    }

    # Populate feasibility map now that _task_match_key is defined
    if _sa_today:
        for _fi in _sa.get("feasibility_per_item", []):
            _fk = _task_match_key(_fi.get("task", ""))
            if _fk:
                _feasibility_map[_fk] = _fi.get("feasibility", "ok")

    # Pieces likely-completed cross-reference (normalised for fuzzy matching)
    _pieces_observed_keys = set()
    _pieces_d_ac = data.get("pieces_activity", {})
    if isinstance(_pieces_d_ac, dict) and _pieces_d_ac.get("status") == "ok":
        for _pc_item in _pieces_d_ac.get("likely_completed", []):
            _pck = _task_match_key(str(_pc_item))
            if _pck:
                _pieces_observed_keys.add(_pck)

    def _task_matches_completed_text(raw_text):
        return task_matches_completed_text(raw_text, _completed_text_keys_today)

    def _is_task_completed_today(raw_text):
        if not _completed_hashes_today and not _completed_text_keys_today:
            return False
        h = _task_completion_hash(raw_text)
        h_legacy = _task_completion_hash_legacy(raw_text)
        return (
            h in _completed_hashes_today
            or h_legacy in _completed_hashes_today
            or _task_matches_completed_text(raw_text)
        )

    all_action_items = []
    action_item_index = {}

    def _future_target_is_explicit(task_text, target_date="", defer_target_date="", due_today_override=False):
        future_target = str(target_date or "").strip()
        defer_target = str(defer_target_date or "").strip()
        if bool(due_today_override):
            return False
        if not future_target or future_target <= _effective_today:
            return False
        if defer_target and defer_target > _effective_today:
            return True
        return bool(_is_future_facing_task(task_text))

    def _append_action_item(
        task,
        priority="Medium",
        time_est="30m",
        source="daemon",
        category="standard",
        force_done=False,
        due_today_override=False,
        target_date="",
    ):
        task_text = str(task or "").strip().rstrip("~").strip()
        if not task_text:
            return
        if source != "akiflow" and not _is_actionable_task(task_text):
            return
        task_key = _task_match_key(task_text)
        if not task_key:
            return
        defer_target_date = str(_deferred_task_targets.get(task_key, "") or "").strip()
        if not defer_target_date and _deferred_task_rows:
            for _defer_row in _deferred_task_rows:
                _row_text = str((_defer_row or {}).get("text", "")).strip()
                _row_target = str((_defer_row or {}).get("target_date", "")).strip()
                if not _row_text or not _row_target:
                    continue
                if _tasks_equivalent(task_text, _row_text):
                    if not defer_target_date or _row_target > defer_target_date:
                        defer_target_date = _row_target
        inferred_target_date = infer_target_date_from_text(task_text, _effective_today)
        effective_target_date = (
            str(target_date or "").strip()
            or defer_target_date
            or inferred_target_date
        )
        if effective_target_date and effective_target_date > _effective_today:
            if not _future_target_is_explicit(
                task_text,
                effective_target_date,
                defer_target_date,
                due_today_override=due_today_override,
            ):
                effective_target_date = ""
        # Never mark future-facing items as done — they're reminders, not completions.
        # Also never mark items still in genuine_todos (pending) as done — guards against
        # daemon false-positive injection writing stale hashes.
        _is_future_item = _is_future_facing_task(task_text) and not bool(due_today_override)
        _is_pending = task_key in _pending_task_keys
        done_today = (force_done or _is_task_completed_today(task_text)) and not _is_future_item and not _is_pending
        existing_idx = action_item_index.get(task_key)
        if existing_idx is None:
            for idx, existing_item in enumerate(all_action_items):
                if _tasks_equivalent(task_text, existing_item.get("task", "")):
                    existing_idx = idx
                    break
        if existing_idx is not None:
            existing_item = all_action_items[existing_idx]
            action_item_index[task_key] = existing_idx
            # Keep best metadata and preserve completion state if any source marks done.
            if len(task_text) > len(str(existing_item.get("task", ""))):
                existing_item["task"] = task_text
            existing_item["done"] = bool(existing_item.get("done")) or done_today
            if not existing_item.get("time") and time_est:
                existing_item["time"] = time_est
            existing_item["due_today_override"] = bool(existing_item.get("due_today_override")) or bool(due_today_override)
            existing_target_date = str(existing_item.get("target_date", "")).strip()
            if existing_target_date and not _future_target_is_explicit(
                existing_item.get("task", task_text),
                existing_target_date,
                existing_item.get("defer_target_date", ""),
                due_today_override=bool(existing_item.get("due_today_override")),
            ):
                existing_item["target_date"] = ""
                existing_target_date = ""
            candidate_target = ""
            if defer_target_date:
                existing_item["defer_target_date"] = defer_target_date
                candidate_target = defer_target_date
            elif effective_target_date:
                candidate_target = effective_target_date
            if candidate_target and (not existing_target_date or candidate_target > existing_target_date):
                existing_item["target_date"] = candidate_target
            if inferred_target_date and not str(existing_item.get("inferred_target_date", "")).strip():
                existing_item["inferred_target_date"] = inferred_target_date
            return
        action_item_index[task_key] = len(all_action_items)
        all_action_items.append({
            "task": task_text,
            "priority": priority,
            "time": time_est,
            "source": source,
            "category": category,
            "done": done_today,
            "due_today_override": bool(due_today_override),
            "target_date": effective_target_date,
            "inferred_target_date": inferred_target_date,
            "defer_target_date": defer_target_date,
        })

    for todo in (diarium_data or []):
        task = (todo.get("task", "") or todo.get("text", "")) if isinstance(todo, dict) else str(todo)
        priority = todo.get("priority", "Medium") if isinstance(todo, dict) else "Medium"
        time_est = todo.get("time", "30m") if isinstance(todo, dict) else "30m"
        category = todo.get("category", "standard") if isinstance(todo, dict) else "standard"
        _append_action_item(task, priority=priority, time_est=time_est, source="daemon", category=category)

    # Daily Apple Note ✅ To-Dos (manual edits should flow into dashboard action items)
    for note_todo in (notes_todos or []):
        text = str(note_todo or "").strip()
        if not text:
            continue
        _append_action_item(text, priority="Medium", time_est="15m", source="apple_notes", category="standard")

    # Completed tasks that were promoted into ta_dah should remain visible as done rows.
    for done_item in (diarium_tadah or []):
        done_text = str(done_item or "").strip()
        if not done_text or done_text.lower() in ("list", ""):
            continue
        if len(done_text.split()) < 2:
            continue  # single-word fragment — skip
        # Never mark future-facing tasks as done — they're reminders, not completions
        if any(kw in done_text.lower() for kw in _future_keywords):
            continue
        # Ta-dah items are definitionally completions — force_done=True.
        # _is_pending guard inside _append_action_item still blocks false positives.
        _append_action_item(done_text, priority="Medium", time_est="", source="ta_dah", category="maintenance", force_done=True)

    # Fallback: if ta_dah sync lags, still render completed labels from completion cache.
    # Normalised pending texts for fuzzy-match guard (catches "schedule on calendar" vs "schedule on the calendar")
    _ai_pending_texts = [
        (t.get("text", "") if isinstance(t, dict) else str(t)).strip()
        for t in (ai_todos or [])
        if (t.get("text", "") if isinstance(t, dict) else str(t)).strip()
    ]
    for done_label in (_completed_labels_today or []):
        done_text = str(done_label or "").strip().rstrip("~").strip()
        if not done_text:
            continue
        if any(kw in done_text.lower() for kw in _future_keywords):
            continue
        # Skip labels that are still in the pending genuine_todos — daemon false-positive guard
        if any(_tasks_equivalent(done_text, pt) for pt in _ai_pending_texts):
            continue
        _append_action_item(done_text, priority="Medium", time_est="", source="completed", category="maintenance", force_done=True)

    # Akiflow time-blocked tasks (non-routine) -> action items (core source)
    for _ak in _akiflow_today_items:
        _append_action_item(
            _ak["summary"],
            priority="High",
            time_est=_ak["time_est"],
            source="akiflow",
            category="standard",
        )

    core_sources_present = any(
        str(item.get("source", "")).strip().lower() in {"daemon", "apple_notes", "akiflow"}
        for item in all_action_items
        if isinstance(item, dict)
    )

    try:
        _effective_today_dt = datetime.strptime(_effective_today, "%Y-%m-%d")
    except Exception:
        _effective_today_dt = None
    if not core_sources_present:
        for todo in (ai_todos or []):
            text = todo.get("text", "") if isinstance(todo, dict) else str(todo)
            category = todo.get("category", "standard") if isinstance(todo, dict) else "standard"
            target_date = str(todo.get("rollover_target_date", "")).strip() if isinstance(todo, dict) else ""
            due_today_override = False
            try:
                target_dt = datetime.strptime(target_date, "%Y-%m-%d") if target_date else None
            except Exception:
                target_dt = None
            if _effective_today_dt and target_dt and target_dt <= _effective_today_dt:
                due_today_override = True
            _append_action_item(
                text,
                priority="Medium",
                time_est="15m",
                source="ai",
                category=category,
                due_today_override=due_today_override,
                target_date=target_date,
            )
    else:
        # Keep future-facing AI todos visible even when core feeds are present.
        # Core feeds can omit these rollover reminders (e.g. glasses post office task).
        for todo in (ai_todos or []):
            text = todo.get("text", "") if isinstance(todo, dict) else str(todo)
            if not str(text or "").strip():
                continue
            category = todo.get("category", "standard") if isinstance(todo, dict) else "standard"
            target_date = str(todo.get("rollover_target_date", "")).strip() if isinstance(todo, dict) else ""
            try:
                target_dt = datetime.strptime(target_date, "%Y-%m-%d") if target_date else None
            except Exception:
                target_dt = None
            due_today_override = bool(_effective_today_dt and target_dt and target_dt <= _effective_today_dt)
            should_keep = (
                due_today_override
                or _is_future_facing_task(text)
                or (_effective_today_dt and target_dt and target_dt > _effective_today_dt)
            )
            if not should_keep:
                continue
            _append_action_item(
                text,
                priority="Medium",
                time_est="15m",
                source="ai_future",
                category=category,
                due_today_override=due_today_override,
                target_date=target_date,
            )

    if weekly_report_due:
        _append_action_item(
            "Generate weekly report and review it on the dashboard weekly section.",
            priority="Medium",
            time_est="10m",
            source="system",
            category="maintenance",
        )

    # Also pull todo-type from all_insights that aren't already captured (date-gated)
    if _ai_is_today and not core_sources_present:
        existing_texts = set(a["task"].lower() for a in all_action_items)
        for item in ai_today.get("all_insights", []):
            candidate_text = str(item.get("text", "") or "")
            if (
                item.get("type") == "todo"
                and candidate_text.lower() not in existing_texts
                and _is_actionable_task(candidate_text)
            ):
                category = item.get("category", "standard")
                _append_action_item(candidate_text, priority="Medium", time_est="15m", source="ai", category=category)

    # Keep deferred items visible even when their original source feed no longer carries them.
    for deferred in (_deferred_task_rows or []):
        deferred_text = str(deferred.get("text", "")).strip()
        deferred_target = str(deferred.get("target_date", "")).strip()
        if not deferred_text or not deferred_target:
            continue
        due_today_override = False
        try:
            deferred_target_dt = datetime.strptime(deferred_target, "%Y-%m-%d")
        except Exception:
            deferred_target_dt = None
        if _effective_today_dt and deferred_target_dt and deferred_target_dt <= _effective_today_dt:
            due_today_override = True
        _append_action_item(
            deferred_text,
            priority="Medium",
            time_est="15m",
            source="deferred",
            category="standard",
            due_today_override=due_today_override,
            target_date=deferred_target,
        )

    # State-backed carry-forward: keep unresolved action items visible across transient source gaps.
    for persisted in (_persisted_action_rows or {}).values():
        persisted_text = str(persisted.get("text", "")).strip()
        if not persisted_text:
            continue
        if _is_task_completed_today(persisted_text):
            continue
        persisted_target = str(persisted.get("target_date", "")).strip()
        due_today_override = False
        try:
            persisted_target_dt = datetime.strptime(persisted_target, "%Y-%m-%d") if persisted_target else None
        except Exception:
            persisted_target_dt = None
        if _effective_today_dt and persisted_target_dt and persisted_target_dt <= _effective_today_dt:
            due_today_override = True
        _append_action_item(
            persisted_text,
            priority="Medium",
            time_est=str(persisted.get("time", "15m")).strip() or "15m",
            source="persisted",
            category=str(persisted.get("category", "standard")).strip() or "standard",
            due_today_override=due_today_override,
            target_date=persisted_target,
        )

    if all_action_items:
        _category_rank = {"quick_win": 0, "standard": 1, "maintenance": 2, "system": 3}
        _source_rank = {
            "akiflow": 0,
            "daemon": 1,
            "ai": 2,
            "ai_future": 2,
            "apple_notes": 3,
            "deferred": 4,
            "persisted": 4,
            "completed": 5,
            "ta_dah": 5,
            "system": 6,
        }
        _urgency_keywords = ("urgent", "asap", "today", "now", "before", "by ")

        def _due_bucket(item):
            if bool(item.get("due_today_override")):
                return 0
            target_date = str(item.get("target_date", "")).strip()
            if target_date:
                if target_date <= _effective_today:
                    return 0
                return 2
            return 1

        def _urgency_score(item):
            task_lower = str(item.get("task", "")).strip().lower()
            score = 0
            if any(tok in task_lower for tok in _urgency_keywords):
                score += 2
            if str(item.get("priority", "")).strip().lower() in {"high", "p0", "p1", "1", "0"}:
                score += 2
            if str(item.get("category", "")).strip().lower() == "quick_win":
                score += 1
            return score

        all_action_items.sort(
            key=lambda item: (
                bool(item.get("done")),
                _due_bucket(item),
                _source_rank.get(str(item.get("source", "")).strip().lower(), 9),
                _category_rank.get(str(item.get("category", "standard")).strip().lower(), 1),
                -_urgency_score(item),
                _task_match_key(item.get("task", "")),
            )
        )
        # Group by category: quick_win, maintenance, standard, system (claude)
        quick_items = []
        maintenance_items = []
        standard_items = []
        system_items = []
        completed_items = []
        tomorrow_queue_items = []
        system_keywords = ["daemon", "dashboard", "claude", "script", "config", "cache", "verify"]

        current_hour_for_filter = datetime.now().hour
        for item in all_action_items:
            # Skip items with empty task text
            if not item.get("task", "").strip():
                continue
            # Skip "set tomorrow's plans" before 18:00 — Jim sets these in the evening
            if current_hour_for_filter < 18 and "tomorrow" in item.get("task", "").lower() and "plan" in item.get("task", "").lower():
                continue
            defer_target_date = str(item.get("defer_target_date", "") or "").strip()
            target_date = str(item.get("target_date", "") or "").strip()
            force_tomorrow_queue = bool(
                (defer_target_date and defer_target_date > _effective_today)
                or (target_date and target_date > _effective_today)
            )
            due_today_flag = bool(item.get("due_today_override"))
            if target_date and target_date > _effective_today:
                due_today_flag = False
            if (_is_future_facing_task(item.get("task", "")) or force_tomorrow_queue) and not due_today_flag:
                tomorrow_queue_items.append(item)
                continue
            display_action_items.append(item)
            if item.get("done"):
                completed_items.append(item)
                continue
            task_lower = item["task"].lower()
            cat = item.get("category", "standard")
            if any(kw in task_lower for kw in system_keywords):
                system_items.append(item)
            elif cat == "quick_win":
                quick_items.append(item)
            elif cat == "maintenance":
                maintenance_items.append(item)
            else:
                standard_items.append(item)

        one_thing_candidates = [
            str(item.get("task", "")).strip()
            for item in (quick_items + standard_items)
            if isinstance(item, dict) and not bool(item.get("done")) and str(item.get("task", "")).strip()
        ]

        def _render_action_item_row(item):
            task = str(item.get("task", "")).strip()
            if not task:
                return ""
            task_hash = _task_completion_hash(task)
            task_emoji = _pick_content_emoji(task)
            compact_task = _compact_task_text(task, max_len=150)
            time_text = str(item.get("time", "")).strip()
            is_done = bool(item.get("done"))
            time_html = ""
            if time_text:
                time_html = f'''
                        <p class="text-xs mt-1 flex items-center gap-1">
                            <span class="rounded px-1.5 py-0.5" style="background: rgba(148,163,184,0.18); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.24);">{html.escape(time_text)}</span>'''
                # Feasibility badge
                _fk2 = _task_match_key(task)
                _fval = _feasibility_map.get(_fk2, "")
                if _fval:
                    _feas_styles = {
                        "ok":         {"bg": "rgba(6,95,70,0.28)",   "color": "#6ee7b7", "label": "🟢 ok"},
                        "tight":      {"bg": "rgba(120,53,15,0.28)", "color": "#fde68a", "label": "🟡 tight"},
                        "overloaded": {"bg": "rgba(153,27,27,0.28)", "color": "#fca5a5", "label": "🔴 overloaded"},
                    }
                    _fs = _feas_styles.get(_fval, {})
                    if _fs:
                        time_html += (
                            f'<span class="rounded px-1.5 py-0.5" '
                            f'style="background:{_fs["bg"]};color:{_fs["color"]};font-size:0.65rem;">'
                            f'{_fs["label"]}</span>'
                        )
                time_html += '''
                        </p>
                '''
            # Pieces observed badge (cross-reference from workstream activity)
            _task_key_lower = _task_match_key(task)
            _pieces_observed = bool(_pieces_observed_keys) and any(
                (_task_key_lower in pk or pk in _task_key_lower)
                for pk in _pieces_observed_keys
                if len(pk) > 5
            )
            if _pieces_observed and time_html:
                time_html = time_html.rstrip()
                time_html = time_html.rstrip("</p>").rstrip() + (
                    '<span class="rounded px-1.5 py-0.5" '
                    'style="background:rgba(88,28,135,0.22);color:#c4b5fd;font-size:0.65rem;">🧩 observed</span>'
                    "</p>\n"
                )
            elif _pieces_observed:
                time_html = (
                    '<p class="text-xs mt-1 flex items-center gap-1">'
                    '<span class="rounded px-1.5 py-0.5" '
                    'style="background:rgba(88,28,135,0.22);color:#c4b5fd;font-size:0.65rem;">🧩 observed</span>'
                    "</p>"
                )

            if is_done:
                row_style = "background: rgba(15,23,42,0.46); border: 1px solid rgba(148,163,184,0.2); opacity: 0.72;"
                text_style = "color: #cbd5e1; line-height: 1.45; text-decoration: line-through; text-decoration-thickness: 1.5px; text-decoration-color: rgba(148,163,184,0.82);"
                button_html = '<button disabled class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(30,64,175,0.26); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">☑ Done</button>'
            else:
                row_style = "background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.24);"
                text_style = "color: #f3f4f6; line-height: 1.45;"
                button_html = f'''
                <div class="flex flex-col gap-1">
                    <button onclick="qaCompleteTodoFromButton(this)" data-text="{html.escape(task, quote=True)}" data-task-hash="{html.escape(task_hash, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(131,24,67,0.35); color: #fbcfe8; border: 1px solid rgba(249,168,212,0.35);">☐ Done</button>
                    <button onclick="qaDeferTodoFromButton(this)" data-text="{html.escape(task, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(30,58,138,0.35); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">⏭️ Defer</button>
                </div>'''
            return f'''
                <div class="rounded-lg px-3 py-2.5 mb-2 flex items-start gap-2" data-qa-row="todo" data-task-hash="{html.escape(task_hash, quote=True)}" style="{row_style}">
                    <span style="font-size: 1rem; line-height: 1.35;">{task_emoji}</span>
                    <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium" title="{html.escape(task, quote=True)}" style="{text_style}">{html.escape(compact_task)}</p>
                        {time_html}
                    </div>
                    {button_html}
                </div>'''

        items_html = ""
        primary_items = quick_items[:3] + standard_items[:5]
        one_thing_seed = ""
        if one_thing_candidates:
            one_thing_seed = str(one_thing_candidates[0] or "").strip()
        elif primary_items:
            first_primary = primary_items[0]
            if isinstance(first_primary, dict):
                one_thing_seed = str(first_primary.get("task", "")).strip()
            else:
                one_thing_seed = str(first_primary or "").strip()
        if one_thing_seed:
            one_thing_key = task_match_key(one_thing_seed)
            filtered_primary_items = []
            for section_item in primary_items:
                section_task = str(section_item.get("task", "")).strip() if isinstance(section_item, dict) else str(section_item or "").strip()
                section_key = task_match_key(section_task)
                if section_task and (
                    (one_thing_key and section_key == one_thing_key)
                    or tasks_equivalent(section_task, one_thing_seed)
                ):
                    continue
                filtered_primary_items.append(section_item)
            primary_items = filtered_primary_items
        support_items = maintenance_items[:4] + system_items[:3]
        grouped_sections = [
            ("🎯 Do Next", "#f9a8d4", primary_items),
            ("🧰 Keep Running", "#fde68a", support_items),
            ("✅ Done Today", "#93c5fd", completed_items[:8]),
        ]
        for label, color, section_items in grouped_sections:
            if not section_items:
                continue
            items_html += f'<p class="text-xs font-semibold mb-2 mt-3" style="color: {color}">{label}</p>'
            for section_item in section_items:
                items_html += _render_action_item_row(section_item)

        if tomorrow_queue_items:
            tomorrow_rows_html = "".join(_render_action_item_row(item) for item in tomorrow_queue_items[:8])
            tomorrow_extra = ""
            if len(tomorrow_queue_items) > 8:
                tomorrow_extra = (
                    f'<p class="text-xs mt-2" style="color:#6b7280">'
                    f'+{len(tomorrow_queue_items) - 8} more future item(s)</p>'
                )
            items_html += f'''
            <details data-qa-tomorrow-queue="1" class="mt-4 rounded-lg px-3 py-2" style="background: rgba(30,41,59,0.38); border: 1px solid rgba(129,140,248,0.24);">
                <summary class="text-xs font-semibold cursor-pointer" style="color:#c4b5fd">🗓️ Tomorrow queue ({len(tomorrow_queue_items)})</summary>
                <p class="text-xs mt-2 mb-2" style="color:#9ca3af">Hidden from today’s action list. Expands into action items on its target day.</p>
                {tomorrow_rows_html}
                {tomorrow_extra}
            </details>
            '''

        if items_html:
            action_items_list_html = items_html

    _save_action_item_state(
        _effective_today,
        all_action_items,
        today_items=display_action_items,
        future_items=tomorrow_queue_items if 'tomorrow_queue_items' in locals() else [],
        completed_items=completed_items if 'completed_items' in locals() else [],
    )

    # === Insights Section — SPLIT into Morning Insights + Evening Insights ===
    # Each follows its respective entries card for narrative flow:
    # Morning entries → Morning Insights, Evening entries → Evening Insights
    type_icons = {
        "pattern": "🔁", "win": "🏆", "signal": "⚡",
        "todo": "⚡", "connection": "🔗", "affirmation": "💚",
    }

    # Fixed display order for insight types: patterns → wins → signals → connections
    _insight_type_order = ["pattern", "win", "signal", "connection"]

    def _pick_insight_emoji(text):
        """Pick a relevant emoji for an insight based on its content keywords."""
        t = text.lower()
        # Check keyword groups from most specific to least
        _emoji_rules = [
            # Physical / health
            (["exercise", "gym", "workout", "walk", "run ", "running", "physical", "body", "weight", "fitness", "movement"], "💪"),
            (["sleep", "rest", "tired", "fatigue", "nap", "bed", "insomnia", "woke"], "😴"),
            (["food", "eat", "meal", "cook", "diet", "nutrition", "hunger", "lunch", "dinner", "breakfast"], "🍽️"),
            (["medic", "health", "pain", "symptom", "doctor", "therap"], "🏥"),
            # Mental / cognitive
            (["brain", "cognit", "think", "mental", "focus", "attention", "adhd", "autism", "executive function", "memory"], "🧠"),
            (["anxi", "worry", "stress", "overwhelm", "panic", "nervous"], "🌊"),
            (["mood", "emotion", "feeling", "depress", "sad ", "happy", "joy"], "🎭"),
            (["therapy", "therapist", "session", "homework"], "🛋️"),
            # Goals / productivity
            (["goal", "target", "aim", "milestone", "accomplish", "achieve"], "🎯"),
            (["habit", "routine", "consistent", "streak", "daily practice"], "📊"),
            (["progress", "improv", "growth", "develop", "forward", "momentum"], "📈"),
            (["deadline", "urgent", "time", "schedule", "clock", "late", "early", "morning", "evening"], "⏰"),
            (["plan", "strateg", "organis", "organiz", "priorit", "system"], "🗺️"),
            # Social / relationships
            (["friend", "social", "people", "relationship", "connect", "family", "partner", "date "], "🤝"),
            (["boundar", "protect", "say no", "limit", "space", "alone"], "🛡️"),
            (["support", "help", "communit", "team", "together"], "🫂"),
            # Energy / motivation
            (["energy", "motiv", "drive", "fuel", "recharge", "burnout", "exhaust"], "⚡"),
            (["win ", "won ", "success", "proud", "celebrate", "victory", "nailed"], "🏆"),
            (["brave", "courage", "risk", "challeng", "difficult", "hard "], "🦁"),
            # Ideas / learning
            (["idea", "insight", "realis", "realiz", "discover", "learn", "understand", "click"], "💡"),
            (["pattern", "repeat", "cycle", "trend", "recur", "notice"], "🔁"),
            (["creat", "build", "make", "project", "ship", "launch", "code", "develop"], "🔨"),
            # Work / career
            (["job", "career", "work", "employ", "interview", "application", "resume", "hire"], "💼"),
            (["money", "financ", "budget", "saving", "income", "cost", "pay "], "💰"),
            # Self / identity
            (["self", "identity", "value", "worth", "authentic", "true to"], "🌱"),
            (["gratit", "thankf", "appreciat", "grateful"], "🙏"),
        ]
        for keywords, emoji in _emoji_rules:
            if any(kw in t for kw in keywords):
                return emoji
        return "💡"  # default fallback

    def _render_entry_items(entry_insights, skip_todos=True):
        """Render insight items grouped by type with headers in fixed order:
        Patterns → Wins → Signals → Connections (then any remaining types)."""
        # Group by type
        grouped = {}
        for item in entry_insights:
            if skip_todos and item.get("type") == "todo":
                continue
            text = str(item.get("text", "")).strip()
            if _is_stale_missing_reflection_signal(text):
                continue
            if _is_stale_structured_gap_signal(text):
                continue
            if _is_tracker_metadata_leak_text(text):
                continue
            itype = item.get("type", "other")
            if itype not in grouped:
                grouped[itype] = []
            grouped[itype].append(item)

        # Category labels and colors
        category_config = {
            "pattern": {"label": "Patterns", "color": "#c4b5fd", "bg": "rgba(196,181,253,0.08)"},
            "signal": {"label": "Signals", "color": "#fbbf24", "bg": "rgba(251,191,36,0.08)"},
            "win": {"label": "Wins", "color": "#6ee7b7", "bg": "rgba(110,231,183,0.08)"},
            "connection": {"label": "Connections", "color": "#f9a8d4", "bg": "rgba(249,168,212,0.08)"},
        }

        # Render in fixed order: patterns → wins → signals → connections, then any extras
        ordered_types = [t for t in _insight_type_order if t in grouped]
        remaining = [t for t in grouped if t not in _insight_type_order]
        ordered_types.extend(remaining)

        html = ""
        for itype in ordered_types:
            items = grouped[itype]
            config = category_config.get(itype, {"label": itype.replace('_', ' ').title(), "color": "#d1d5db", "bg": "rgba(209,213,219,0.08)"})
            icon = type_icons.get(itype, "💡")

            html += f'''
            <div class="mb-5 rounded-lg p-4" style="background: {config['bg']}; border-left: 3px solid {config['color']}">
                <p class="text-xs font-bold mb-3 uppercase tracking-wider" style="color: {config['color']}; letter-spacing: 0.08em;">{icon} {config['label']}</p>'''

            for idx, item in enumerate(items):
                text = item.get("text", "")
                # Break long insights into lead sentence + supporting detail
                sentences = re.split(r'(?<=[.!?])\s+', text)
                emoji = _pick_insight_emoji(text)
                wrapper_attrs = ' class="mt-3 pt-3" style="border-top: 1px solid rgba(75,85,99,0.15);"' if idx > 0 else ""
                if len(sentences) > 1 and len(text) > 120:
                    lead = sentences[0]
                    rest = ' '.join(sentences[1:])
                    html += f'''
                <div{wrapper_attrs}>
                    <p class="text-base font-medium mb-1" style="color: #f3f4f6; line-height: 1.7;">{emoji} {lead}</p>
                    <p class="text-sm ml-6" style="color: #9ca3af; line-height: 1.6;">{rest}</p>
                </div>'''
                else:
                    html += f'''
                <div{wrapper_attrs}>
                    <p class="text-base" style="color: #e5e7eb; line-height: 1.7;">{emoji} {text}</p>
                </div>'''

            html += '''
            </div>'''

        return html

    # Build SEPARATE morning and evening insights HTML
    morning_insights_html = ""
    updates_insights_html = ""
    evening_insights_html = ""
    insights_fallback_html = ""  # For daemon/keyword fallback when no AI insights
    today = get_effective_date()
    ai_today = get_ai_day(ai_insights, today)
    entries = ai_today.get("entries", []) if ai_today.get("status") == "success" else []
    if not bool(data.get("diariumFresh", True)):
        # Keep dashboard-authored updates insights even when Diarium export is stale.
        entries = [e for e in entries if str(e.get("source", "")).strip().lower() == "updates"]
    anxiety_today_raw = ai_today.get("anxiety_reduction_score") if isinstance(ai_today, dict) else None
    try:
        anxiety_today_value = float(anxiety_today_raw)
    except Exception:
        anxiety_today_value = None
    workout_signals_for_stale = data.get("workoutChecklistSignals", {}) if isinstance(data.get("workoutChecklistSignals"), dict) else {}
    anxiety_saved_signal = bool(workout_signals_for_stale.get("anxiety_saved_today"))
    has_anxiety_logged_today = anxiety_today_value is not None or anxiety_saved_signal
    important_thing_present = bool(str(data.get("importantThing", "")).strip())
    important_thing_missing_flag = bool(data.get("importantThingMissing", False))
    evening_payload_for_stale = data.get("evening", {}) if isinstance(data.get("evening"), dict) else {}
    evening_mood_present = bool(str(evening_payload_for_stale.get("mood_tag", "")).strip())
    evening_reflection_fields_present = any(
        bool(str(evening_payload_for_stale.get(field, "")).strip())
        for field in ("brave", "tomorrow", "updates", "remember_tomorrow", "evening_reflections")
    )

    def _is_stale_missing_reflection_signal(text: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not lowered:
            return False
        mentions_missing = "missing" in lowered
        mentions_evening = "evening reflection" in lowered
        mentions_anxiety = "anxiety reduction score" in lowered
        if not (mentions_missing and mentions_evening and mentions_anxiety):
            return False
        # Suppress stale synthesis once anxiety has actually been logged.
        return has_anxiety_logged_today

    def _is_stale_structured_gap_signal(text: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not lowered:
            return False
        if important_thing_present and not important_thing_missing_flag:
            if "important thing" in lowered and any(tok in lowered for tok in ("missing", "not extracted", "not captured", "add one priority")):
                return True
        if evening_mood_present:
            if "evening mood" in lowered and any(tok in lowered for tok in ("missing", "slot", "not set", "blank")):
                return True
        if evening_reflection_fields_present:
            if any(tok in lowered for tok in ("evening reflection", "reflection fields", "brave", "remember for tomorrow", "what's tomorrow", "whats tomorrow", "updates")):
                if any(tok in lowered for tok in ("blank", "missing", "mostly blank", "unset", "not set", "execution-heavy", "reflection-light")):
                    return True
        return False

    def _is_stale_diarium_guidance_text(text: str) -> bool:
        return _is_stale_diarium_fallback_line(text) or _is_stale_structured_gap_signal(text)

    if entries:
        # Entries are already today-scoped; only split by source
        morning_entries = [e for e in entries if e.get("source") == "morning"]
        evening_payload = data.get("evening", {}) if isinstance(data.get("evening"), dict) else {}
        cleaned_updates_text = _strip_updates_metadata(evening_payload.get("updates", ""))
        has_real_updates_text = not _is_effectively_empty_updates_text(cleaned_updates_text)
        updates_entries = [e for e in entries if e.get("source") == "updates"] if has_real_updates_text else []
        evening_entries = [e for e in entries if e.get("source") == "evening"]
        # Fallback: daemon_evening (heuristic) when no API-based evening insights exist
        if not evening_entries:
            evening_entries = [e for e in entries if e.get("source") == "daemon_evening"]

        # Synthesised insights — split by source
        daily_guidance = ai_today.get("daily_guidance")
        if bool(data.get("diariumFresh", True)) and isinstance(daily_guidance, dict):
            guidance_lines = daily_guidance.get("lines", []) if isinstance(daily_guidance.get("lines", []), list) else []
            if guidance_lines:
                filtered_lines = [
                    item for item in guidance_lines
                    if not _is_stale_diarium_guidance_text(str(item.get("text", "")) if isinstance(item, dict) else str(item))
                ]
                if filtered_lines != guidance_lines:
                    daily_guidance = dict(daily_guidance)
                    daily_guidance["lines"] = filtered_lines

        # Morning synthesis (morning data only)
        # Guard: if daily_guidance was generated after 20:00 (or before 03:00), it was
        # produced from full-day content during an evening re-run and should NOT be
        # shown as "Morning Insights" — fall through to heuristic synthesis instead.
        morning_daily_guidance = daily_guidance
        if isinstance(daily_guidance, dict):
            _gen_at = daily_guidance.get("generated_at", "")
            if _gen_at:
                try:
                    from datetime import datetime as _dt
                    _gen_hour = _dt.fromisoformat(_gen_at).hour
                    if _gen_hour >= 20 or _gen_hour < 3:
                        morning_daily_guidance = None
                except Exception:
                    pass

        morning_synthesis = synthesise_top_insights(
            morning_entries, [],  # No evening data for morning synthesis
            data.get("engagementHints", []),
            data.get("mentalHealthFlags", []),
            {"status": "found", "items": data.get("openLoopItems", [])} if data.get("openLoopItems") else {},
            data.get("aiInsights", {}).get("therapy_homework", []),
            max_length=500,
            daily_guidance=morning_daily_guidance
        )
        morning_synthesis = [
            line for line in morning_synthesis
            if not _is_stale_missing_reflection_signal(line)
            and not _is_stale_structured_gap_signal(line)
            and not _is_tracker_metadata_leak_text(line)
        ]

        # Evening synthesis (evening data only)
        evening_synthesis = synthesise_top_insights(
            [], evening_entries,  # No morning data for evening synthesis
            [],  # No engagement hints for evening (already shown in morning)
            [],  # No keywords for evening
            {},  # No open loops for evening
            [],  # No therapy homework for evening
            max_length=500,
            daily_guidance=None  # Daily guidance goes with morning
        )
        evening_synthesis = [
            line for line in evening_synthesis
            if not _is_stale_missing_reflection_signal(line)
            and not _is_stale_structured_gap_signal(line)
            and not _is_tracker_metadata_leak_text(line)
        ]

        # Build Morning Insights card
        morning_sections = ""
        if morning_synthesis:
            synthesis_items_html = ""
            for idx, sl in enumerate(morning_synthesis):
                # Break long synthesis paragraphs into scannable chunks
                emoji = _pick_insight_emoji(sl)
                sentences = re.split(r'(?<=[.!?])\s+', sl)
                if len(sentences) > 2 and len(sl) > 150:
                    lead = sentences[0]
                    rest = ' '.join(sentences[1:])
                    divider_attrs = ' class="mb-4 pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);"' if idx > 0 else ' class="mb-4"'
                    synthesis_items_html += f'''
                        <div{divider_attrs}>
                            <p class="text-base font-medium leading-relaxed" style="color: #f3f4f6; line-height: 1.8;">{emoji} {lead}</p>
                            <p class="text-sm mt-2 ml-6 leading-relaxed" style="color: #b0b5bd; line-height: 1.7;">{rest}</p>
                        </div>'''
                else:
                    divider_attrs = ' class="mb-4 pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);"' if idx > 0 else ' class="mb-4"'
                    synthesis_items_html += f'''
                        <div{divider_attrs}>
                            <p class="text-base leading-relaxed" style="color: #e5e7eb; line-height: 1.8;">{emoji} {sl}</p>
                        </div>'''
            morning_sections += f'''
            <div class="mb-4 pb-3" style="border-bottom: 1px solid rgba(196,181,253,0.1);">
                {synthesis_items_html}
            </div>'''

        if morning_entries:
            # Consolidate all morning insights into one block to avoid duplicate headers
            all_morning_insights = []
            for entry in morning_entries:
                for insight in entry.get("insights", []):
                    if not isinstance(insight, dict):
                        continue
                    insight_text = str(insight.get("text", "")).strip()
                    if not insight_text:
                        continue
                    if _is_stale_missing_reflection_signal(insight_text):
                        continue
                    if _is_stale_structured_gap_signal(insight_text):
                        continue
                    if _is_tracker_metadata_leak_text(insight_text):
                        continue
                    all_morning_insights.append(insight)
            # Deduplicate by topic phrase: "Anxiety management..." variations → one representative
            if len(all_morning_insights) > 10:
                all_morning_insights = _dedupe_insights_for_display(all_morning_insights)
            if all_morning_insights:
                morning_sections += f'''
            <div class="mb-4">
                {_render_entry_items(all_morning_insights, skip_todos=True)}
            </div>'''

        if morning_sections:
            morning_insights_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: linear-gradient(135deg, rgba(88,28,135,0.15), rgba(6,95,70,0.1)); border: 1px solid rgba(196,181,253,0.15);">
                <details>
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #a7f3d0">🌅 Morning Insights</summary>
                    <div class="mt-3">
                        {morning_sections}
                    </div>
                </details>
            </div>'''

        # Build Update Insights card (from source=updates)
        updates_sections = ""
        if updates_entries:
            update_summaries = []
            all_updates_insights = []
            for entry in updates_entries:
                summary = entry.get("emotional_summary", "").strip()
                if (
                    summary
                    and not _is_stale_missing_reflection_signal(summary)
                    and not _is_stale_structured_gap_signal(summary)
                    and not _is_tracker_metadata_leak_text(summary)
                    and not _is_updates_verification_noise_text(summary)
                ):
                    update_summaries.append(summary)
                for insight in entry.get("insights", []):
                    if not isinstance(insight, dict):
                        continue
                    insight_text = str(insight.get("text", "")).strip()
                    if not insight_text:
                        continue
                    if _is_stale_missing_reflection_signal(insight_text):
                        continue
                    if _is_stale_structured_gap_signal(insight_text):
                        continue
                    if _is_tracker_metadata_leak_text(insight_text):
                        continue
                    if _is_updates_verification_noise_text(insight_text):
                        continue
                    all_updates_insights.append(insight)

            if update_summaries:
                update_summaries = _dedupe_updates_lines(update_summaries, max_items=3)
                summary_items = ""
                for idx, summary in enumerate(update_summaries[:2]):
                    emoji = _pick_insight_emoji(summary)
                    summary_items += f'''
                        <div class="mb-3{'  pt-3" style="border-top: 1px solid rgba(147,197,253,0.12);' if idx > 0 else '"'}>
                            <p class="text-base leading-relaxed" style="color: #e5e7eb; line-height: 1.7;">{emoji} {summary}</p>
                        </div>'''
                updates_sections += f'''
                <div class="mb-4 pb-3" style="border-bottom: 1px solid rgba(147,197,253,0.16);">
                    {summary_items}
                </div>'''

            if len(all_updates_insights) > 10:
                all_updates_insights = _dedupe_insights_for_display(all_updates_insights)
            if all_updates_insights:
                updates_sections += f'''
                <div class="mb-2">
                    {_render_entry_items(all_updates_insights, skip_todos=True)}
                </div>'''
            elif has_real_updates_text:
                fallback_lines = collect_day_narrative_lines([cleaned_updates_text], max_items=4, split_sentences=True)
                fallback_lines = [line for line in fallback_lines if not _is_updates_verification_noise_text(line)]
                fallback_items = []
                for line in fallback_lines:
                    lowered_line = line.lower()
                    item_type = "connection"
                    if any(token in lowered_line for token in ("good", "went well", "fit", "win", "worked")):
                        item_type = "win"
                    elif any(token in lowered_line for token in ("self-conscious", "masking", "anxious", "exhausted", "tired", "overload")):
                        item_type = "signal"
                    elif any(token in lowered_line for token in ("next action", "need to", "email", "tomorrow", "follow up", "follow-up")):
                        item_type = "signal"
                    fallback_items.append({
                        "type": item_type,
                        "text": _truncate_sentence_safe(line, max_len=190),
                    })
                if fallback_items:
                    updates_sections += f'''
                <div class="mb-2">
                    {_render_entry_items(fallback_items, skip_todos=True)}
                </div>'''

        if updates_sections:
            updates_insights_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: linear-gradient(135deg, rgba(30,64,175,0.18), rgba(6,95,70,0.08)); border: 1px solid rgba(147,197,253,0.2);">
                <details>
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #93c5fd">📝 Update Insights</summary>
                    <div class="mt-3">
                        {updates_sections}
                    </div>
                </details>
            </div>'''

        # Build Evening Insights card
        evening_sections = ""
        if evening_synthesis:
            synthesis_items_html = ""
            for idx, sl in enumerate(evening_synthesis):
                # Break long synthesis paragraphs into scannable chunks
                emoji = _pick_insight_emoji(sl)
                sentences = re.split(r'(?<=[.!?])\s+', sl)
                if len(sentences) > 2 and len(sl) > 150:
                    lead = sentences[0]
                    rest = ' '.join(sentences[1:])
                    divider_attrs = ' class="mb-4 pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);"' if idx > 0 else ' class="mb-4"'
                    synthesis_items_html += f'''
                        <div{divider_attrs}>
                            <p class="text-base font-medium leading-relaxed" style="color: #f3f4f6; line-height: 1.8;">{emoji} {lead}</p>
                            <p class="text-sm mt-2 ml-6 leading-relaxed" style="color: #b0b5bd; line-height: 1.7;">{rest}</p>
                        </div>'''
                else:
                    divider_attrs = ' class="mb-4 pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);"' if idx > 0 else ' class="mb-4"'
                    synthesis_items_html += f'''
                        <div{divider_attrs}>
                            <p class="text-base leading-relaxed" style="color: #e5e7eb; line-height: 1.8;">{emoji} {sl}</p>
                        </div>'''
            evening_sections += f'''
            <div class="mb-4 pb-3" style="border-bottom: 1px solid rgba(196,181,253,0.1);">
                {synthesis_items_html}
            </div>'''

        if evening_entries:
            # Consolidate all evening insights into one block to avoid duplicate headers
            all_evening_insights = []
            for entry in evening_entries:
                for insight in entry.get("insights", []):
                    if not isinstance(insight, dict):
                        continue
                    insight_text = str(insight.get("text", "")).strip()
                    if not insight_text:
                        continue
                    if _is_stale_missing_reflection_signal(insight_text):
                        continue
                    if _is_stale_structured_gap_signal(insight_text):
                        continue
                    if _is_tracker_metadata_leak_text(insight_text):
                        continue
                    all_evening_insights.append(insight)
            # Deduplicate by topic phrase
            if len(all_evening_insights) > 10:
                all_evening_insights = _dedupe_insights_for_display(all_evening_insights)
            if all_evening_insights:
                evening_sections += f'''
            <div class="mb-4">
                {_render_entry_items(all_evening_insights, skip_todos=True)}
            </div>'''

        if evening_sections:
            evening_insights_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: linear-gradient(135deg, rgba(88,28,135,0.15), rgba(6,95,70,0.1)); border: 1px solid rgba(196,181,253,0.15);">
                <details>
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #c4b5fd">🌙 Evening Insights</summary>
                    <div class="mt-3">
                        {evening_sections}
                    </div>
                </details>
            </div>'''

    # === Therapy Notes (HEALTH project only) ===
    # Therapy homework is extracted by AI insights — no raw journal parsing
    therapy_notes_html = ""
    therapy_homework = data.get("aiInsights", {}).get("therapy_homework", [])
    if therapy_homework:
        therapy_rows = []
        for bullet in therapy_homework[:5]:
            hw_text = bullet.get("text", "") if isinstance(bullet, dict) else str(bullet)
            if hw_text:
                therapy_emoji = _pick_content_emoji(hw_text)
                therapy_rows.append(f'<div class="flex items-start gap-2 mb-2"><span style="color: #c4b5fd">{therapy_emoji}</span><span class="text-sm" style="color: #e5e7eb">{hw_text}</span></div>')

        if therapy_rows:
            bullets_html = "".join(therapy_rows)
            therapy_notes_html = f'''
            <div class="card mb-4">
                <details>
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #c4b5fd">🧠 Therapy Homework ({len(therapy_rows)})</summary>
                    <div class="mt-3">
                        {bullets_html}
                    </div>
                </details>
            </div>'''

    if not morning_insights_html and not updates_insights_html and not evening_insights_html:
        # Daemon/keyword fallback when no AI insights — show as general guidance after action items
        insights_items = []
        engagement_hints = data.get("engagementHints", [])
        if engagement_hints:
            daemon_icons = {
                "application_gap": "📝", "therapy_today": "🧠",
                "open_loops": "🔄", "fitness": "💪",
                "habit_risk": "⚠️", "pattern_detected": "📊",
            }
            for hint in engagement_hints[:3]:
                icon = daemon_icons.get(hint.get("type", ""), "💡")
                insights_items.append((icon, hint.get("message", ""), hint.get("suggested_question", "")))

        mh_flags = data.get("mentalHealthFlags", [])
        if mh_flags and len(insights_items) < 3:
            for flag in mh_flags[:1]:
                if isinstance(flag, str) and len(flag) > 20:
                    clean = ' '.join(flag.split())
                    insights_items.append(("🧠", f'"{clean}"', "From morning pages"))

        if insights_items:
            items_html = ""
            for icon, text, subtext in insights_items[:6]:
                sub = f'<p class="text-xs mt-0.5 italic" style="color: rgba(167,243,208,0.5)">{subtext}</p>' if subtext else ""
                items_html += f'''
                <div class="mb-3 last:mb-0">
                    <div class="flex items-start gap-2">
                        <span class="text-lg">{icon}</span>
                        <div>
                            <p class="text-sm" style="color: #e5e7eb">{text}</p>
                            {sub}
                        </div>
                    </div>
                </div>'''
            insights_fallback_html = f'''
                <div class="card rounded-xl p-5 mb-4" style="background: linear-gradient(135deg, rgba(88,28,135,0.15), rgba(6,95,70,0.1)); border: 1px solid rgba(196,181,253,0.15);">
                    <h3 class="text-lg font-semibold mb-3" style="color: #c4b5fd">💡 Today's Guidance</h3>
                    {items_html}
                </div>'''

    # === Mood Trend (5-day) — date-gated ===
    mood_html = ""
    diarium_analysis = data.get("diariumAnalysis", {})
    _mood_ai_today = get_ai_day(data.get("aiInsights", {}), get_effective_date())
    tone = diarium_analysis.get("emotional_tone", "") if _mood_ai_today.get("status") == "success" else ""
    tone_emojis = {
        "anxious": "😰", "low_energy": "😔", "positive": "😊",
        "frustrated": "😤", "neutral": "😐", "calm": "🧘",
    }
    if tone:
        emoji = tone_emojis.get(tone, "🤔")
        tone_label = tone.replace('_', ' ').title()
        # mood merged into context_bar_html header pill — no standalone card needed

    # === Overwhelm Support (specific regulation techniques) ===
    support_html = ""
    support_triggers = set()
    if tone in {"anxious", "frustrated", "low_energy"}:
        support_triggers.add(tone)
    _support_ai_today = get_ai_day(data.get("aiInsights", {}), get_effective_date())
    if _support_ai_today.get("status") == "success":
        for entry in _support_ai_today.get("entries", []):
            for item in entry.get("insights", []):
                if item.get("type") != "signal":
                    continue
                text = str(item.get("text", "")).lower()
                if any(k in text for k in ("anxious", "anxiety", "overwhelm", "panic", "worry", "stress")):
                    support_triggers.add("anxiety")
                if any(k in text for k in ("focus", "executive", "stuck", "avoid", "freeze")):
                    support_triggers.add("focus")

    if support_triggers:
        techniques = [
            "Physiological sigh x3 (two short inhales, one long exhale) then 60s pause.",
            "2-minute body reset: shoulders down, unclench jaw, long exhale longer than inhale.",
            "5-4-3-2-1 grounding scan to pull attention out of spirals.",
            "10-minute starter sprint: one tiny step only, then reassess.",
            "Externalise load: write 3 worries, choose 1 controllable next action.",
        ]
        if "low_energy" in support_triggers:
            techniques[3] = "5-minute starter sprint only, then short walk/water before deciding next step."
        technique_html = "".join(
            f'<li class="text-sm mb-1" style="color: #dbeafe; line-height: 1.5;">{html.escape(item)}</li>'
            for item in techniques[:4]
        )
        support_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(30,64,175,0.14); border: 1px solid rgba(147,197,253,0.2);">
                <h3 class="text-lg font-semibold mb-2" style="color: #93c5fd">🧠 Overwhelm Support</h3>
                <p class="text-xs mb-2" style="color: #94a3b8">Trigger signals detected: {", ".join(sorted(support_triggers))}</p>
                <ul style="margin: 0; padding-left: 1rem;">{technique_html}</ul>
            </div>'''

    intervention_html = ""
    selector = _support_ai_today.get("intervention_selector", {}) if isinstance(_support_ai_today, dict) else {}
    if isinstance(selector, dict):
        best_now = selector.get("best_now", {}) if isinstance(selector.get("best_now", {}), dict) else {}
        technique = str(best_now.get("technique", "")).strip()
        steps = best_now.get("steps", []) if isinstance(best_now.get("steps", []), list) else []
        if technique:
            predicted = best_now.get("predicted_relief")
            confidence = str(best_now.get("confidence", "medium")).strip().lower()
            why = str(best_now.get("why", "")).strip()
            path_used = str(selector.get("path", "")).strip().lower()

            if isinstance(predicted, (int, float)):
                relief_text = f"{float(predicted):.1f} / 10"
                relief_tone = "#6ee7b7" if float(predicted) >= 7 else "#fbbf24" if float(predicted) >= 5 else "#fca5a5"
            else:
                relief_text = "n/a"
                relief_tone = "#9ca3af"

            confidence_map = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence"}
            confidence_text = confidence_map.get(confidence, "Medium confidence")
            source_text = "AI selected" if path_used.startswith("ai") else "Heuristic fallback"

            steps_html = ""
            for step in steps[:3]:
                step_text = str(step).strip()
                if not step_text:
                    continue
                steps_html += f'<li class="text-sm mb-1" style="color: #e2e8f0; line-height: 1.45;">{html.escape(step_text)}</li>'

            intervention_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(2,132,199,0.14); border: 1px solid rgba(125,211,252,0.24);">
                <div class="flex items-start justify-between gap-3 mb-2">
                    <h3 class="text-lg font-semibold" style="color: #bae6fd">🎯 Best Intervention Now</h3>
                    <span class="text-xs rounded px-2 py-1" style="border: 1px solid rgba(148,163,184,0.32); color: #cbd5e1;">{source_text}</span>
                </div>
                <div class="flex flex-wrap gap-2 mb-2">
                    <span class="optional-pill text-xs rounded px-2 py-1" style="border: 1px solid rgba(125,211,252,0.34); color: #dbeafe; background: rgba(15,23,42,0.5);">{html.escape(technique)}</span>
                    <span class="optional-pill text-xs rounded px-2 py-1" style="border: 1px solid rgba(148,163,184,0.34); color: {relief_tone}; background: rgba(15,23,42,0.5);">Predicted relief: {relief_text}</span>
                    <span class="optional-pill text-xs rounded px-2 py-1" style="border: 1px solid rgba(148,163,184,0.34); color: #cbd5e1; background: rgba(15,23,42,0.5);">{confidence_text}</span>
                </div>
                {f'<p class="text-sm mb-2" style="color: #e2e8f0; line-height: 1.5;">{html.escape(why)}</p>' if why else ''}
                {f'<ul style="margin: 0; padding-left: 1rem;">{steps_html}</ul>' if steps_html else ''}
            </div>'''

    # Detect WT day (for jobs section collapse)
    is_wt_day = any(
        "WT" in e.get("calendar", "") or "WT" in e.get("summary", "")
        for e in data.get("calendar_raw", [])
    )

    # Open loops data (rendered in the top Action Points card)
    open_loop_items = data.get("openLoopItems", [])
    if not isinstance(open_loop_items, list):
        open_loop_items = []
    deduped_loop_items = []
    seen_loop_items = set()
    for raw_loop in open_loop_items:
        text = str(raw_loop).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen_loop_items:
            continue
        seen_loop_items.add(key)
        deduped_loop_items.append(text)
    open_loop_items = deduped_loop_items
    open_loops = len(open_loop_items)

    # === Fitness Tracking (HealthFit workouts, calendar scheduled, yoga goals) ===
    # Matches embed-dashboard-in-notes.py lines 419-500
    workout_checklist = data.get("workoutChecklist", {}) if isinstance(data.get("workoutChecklist"), dict) else {}
    workout_checklist_post = workout_checklist.get("post_workout", {}) if isinstance(workout_checklist.get("post_workout"), dict) else {}
    workout_checklist_signals = data.get("workoutChecklistSignals", {}) if isinstance(data.get("workoutChecklistSignals"), dict) else {}
    shortcut_endpoint = str(data.get("workoutShortcutEndpoint", "")).strip() or "http://127.0.0.1:8765/v1/workout/log"

    wc_recovery = str(workout_checklist.get("recovery_gate", "unknown")).strip().lower()
    if wc_recovery not in {"pass", "fail", "unknown"}:
        wc_recovery = "unknown"
    wc_calf_checked = "checked" if bool(workout_checklist.get("calf_done")) else ""
    wc_rpe_value = input_num_text(workout_checklist_post.get("rpe"), 1, 10)
    wc_pain_value = input_num_text(workout_checklist_post.get("pain"), 0, 10)
    wc_energy_value = input_num_text(workout_checklist_post.get("energy_after"), 1, 10)
    wc_feedback = workout_checklist.get("session_feedback", {}) if isinstance(workout_checklist.get("session_feedback"), dict) else {}
    wc_duration_value = input_num_text(wc_feedback.get("duration_minutes"), 5, 240)
    wc_intensity_value = coerce_choice(wc_feedback.get("intensity"), {"easy", "moderate", "hard"}, empty_value="")
    wc_session_type_value = coerce_choice(wc_feedback.get("session_type"), {"somatic", "yin", "flow", "mobility", "restorative", "other"}, empty_value="")
    wc_body_feel_value = coerce_choice(wc_feedback.get("body_feel"), {"relaxed", "neutral", "tight", "sore", "energised", "fatigued"}, empty_value="")
    wc_note_value = str(wc_feedback.get("session_note", "")).strip()
    wc_yoga_anxiety_source = wc_feedback.get("anxiety_reduction_score")
    if wc_yoga_anxiety_source in {None, ""}:
        wc_yoga_anxiety_source = get_ai_day(data.get("aiInsights", {}) if isinstance(data.get("aiInsights", {}), dict) else {}, get_effective_date()).get("anxiety_reduction_score")
    wc_yoga_anxiety_value = input_num_text(wc_yoga_anxiety_source, 0, 10)
    wc_workout_type = str(workout.get("type", "")).strip().lower() if isinstance(workout, dict) else ""

    recovery_signal = str(workout_checklist_signals.get("recovery_signal", "unknown")).strip().lower()
    if recovery_signal == "pass":
        recovery_signal_badge = "🟢 Auto gate suggests PASS"
    elif recovery_signal == "fail":
        recovery_signal_badge = "🟠 Auto gate suggests FAIL"
    elif recovery_signal == "caution":
        recovery_signal_badge = "🟡 Auto gate borderline"
    else:
        recovery_signal_badge = "⚪ Auto gate unavailable"
    recovery_signal_detail = str(workout_checklist_signals.get("recovery_signal_detail", "No HRV/sleep gate signal yet.")).strip()

    hf_fresh_checked = "checked" if bool(workout_checklist_signals.get("healthfit_export_today")) else ""
    streaks_fresh_checked = "checked" if bool(workout_checklist_signals.get("streaks_export_today")) else ""
    anxiety_saved_checked = "checked" if bool(workout_checklist_signals.get("anxiety_saved_today")) else ""
    reflection_saved_checked = "checked" if bool(workout_checklist_signals.get("reflection_saved_today")) else ""
    is_evening_close_window = datetime.now().hour >= 18
    streaks_close_check_html = ""
    evening_close_checks_html = ""
    if is_evening_close_window:
        streaks_close_check_html = f'''
                        <label class="flex items-center gap-2 text-xs mb-1" style="color: #cbd5e1"><input id="qa-wc-sig-streaks" type="checkbox" disabled {streaks_fresh_checked} class="h-3 w-3">Streaks export done today</label>
        '''
        evening_close_checks_html = f'''
                        <label class="flex items-center gap-2 text-xs mb-1" style="color: #cbd5e1"><input id="qa-wc-sig-anxiety" type="checkbox" disabled {anxiety_saved_checked} class="h-3 w-3">Anxiety score saved</label>
                        <label class="flex items-center gap-2 text-xs mb-1" style="color: #cbd5e1"><input id="qa-wc-sig-reflection" type="checkbox" disabled {reflection_saved_checked} class="h-3 w-3">Evening reflection saved</label>
        '''
    else:
        streaks_close_check_html = '''
                        <p class="text-xs" style="color: #94a3b8">⏳ Streaks + evening close checks unlock after 18:00.</p>
        '''
    wc_progression = data.get("workoutProgression", {}) if isinstance(data.get("workoutProgression"), dict) else {}
    wc_progression_view = workout_progression_view(wc_progression)
    wc_weights_progression = data.get("workoutProgressionWeights", {}) if isinstance(data.get("workoutProgressionWeights"), dict) else {}
    wc_weights_progression_view = workout_progression_view(wc_weights_progression)
    wc_weights_progression_html = ""
    if wc_workout_type != "weights":
        wc_weights_progression_html = f'''
                    <div class="rounded px-3 py-2 mb-2" style="background: rgba(15,23,42,0.45); border: 1px solid rgba(148,163,184,0.18);">
                        <p class="text-xs font-semibold mb-1" style="color: #93c5fd">🏋️ Weights progression snapshot</p>
                        <p id="qa-wc-weights-progression-meta" class="text-xs" style="color: {wc_weights_progression_view["color"]}">{html.escape(wc_weights_progression_view["label"])}</p>
                        {f'<p id="qa-wc-weights-progression-detail" class="text-xs mt-1" style="color: #9ca3af">{html.escape(wc_weights_progression_view["detail"])}</p>' if wc_weights_progression_view["detail"] else '<p id="qa-wc-weights-progression-detail" class="text-xs mt-1" style="color: #9ca3af"></p>'}
                    </div>
        '''

    workout_checklist_html = f'''
            <details id="qa-workout-checklist" class="mt-3 pt-2" style="border-top: 1px solid rgba(110,231,183,0.1);">
                <summary class="text-xs font-semibold cursor-pointer" style="color: #9ca3af">🧾 Workout checklist</summary>
                <div class="mt-3">
                    <div class="rounded px-3 py-3 mb-2" style="background: rgba(15,23,42,0.5); border: 1px solid rgba(110,231,183,0.18);">
                        <div class="flex flex-wrap items-center gap-2 mb-2">
                            <label for="qa-wc-recovery" class="text-xs font-semibold" style="color: #a7f3d0">Recovery gate before weights</label>
                            <select id="qa-wc-recovery" class="rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(110,231,183,0.25); color: #e5e7eb;">
                                <option value="unknown" {'selected' if wc_recovery == 'unknown' else ''}>Unknown</option>
                                <option value="pass" {'selected' if wc_recovery == 'pass' else ''}>Pass</option>
                                <option value="fail" {'selected' if wc_recovery == 'fail' else ''}>Fail</option>
                            </select>
                        </div>
                        <p id="qa-wc-recovery-signal" class="text-xs" style="color: #9ca3af">{recovery_signal_badge} • {html.escape(recovery_signal_detail)}</p>
                    </div>

                    <label class="flex items-center gap-2 text-sm mb-3 cursor-pointer">
                        <input id="qa-wc-calf" type="checkbox" {wc_calf_checked} class="h-4 w-4">
                        <span style="color: #e5e7eb">Calf work done (standing + bent-knee raises)</span>
                    </label>

                    <div class="rounded px-3 py-3 mb-3" style="background: rgba(15,23,42,0.5); border: 1px solid rgba(148,163,184,0.2);">
                        <p class="text-xs font-semibold mb-2" style="color: #cbd5e1">Post-workout log (weights progression)</p>
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <label class="text-xs" style="color: #9ca3af">RPE (1-10)
                                <input id="qa-wc-rpe" type="number" min="1" max="10" value="{wc_rpe_value}" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(148,163,184,0.25); color: #e5e7eb;">
                            </label>
                            <label class="text-xs" style="color: #9ca3af">Pain (0-10)
                                <input id="qa-wc-pain" type="number" min="0" max="10" value="{wc_pain_value}" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(148,163,184,0.25); color: #e5e7eb;">
                            </label>
                            <label class="text-xs" style="color: #9ca3af">Energy after (1-10)
                                <input id="qa-wc-energy" type="number" min="1" max="10" value="{wc_energy_value}" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(148,163,184,0.25); color: #e5e7eb;">
                            </label>
                        </div>
                    </div>

                    <div id="qa-wc-yoga-feedback-wrap" class="rounded px-3 py-3 mb-3" style="display: {'block' if wc_workout_type == 'yoga' else 'none'}; background: rgba(30,64,175,0.14); border: 1px solid rgba(147,197,253,0.24);">
                        <p class="text-xs font-semibold mb-2" style="color: #bfdbfe">🧘 Yoga feedback (for progression)</p>
                        <p class="text-xs mb-2" style="color: #9ca3af">To personalise progression, fill: duration, intensity, type, anxiety, body feel.</p>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mb-2">
                            <label class="text-xs" style="color: #9ca3af">Duration (minutes)
                                <input id="qa-wc-duration" type="number" min="5" max="240" value="{wc_duration_value}" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.26); color: #e5e7eb;">
                            </label>
                            <label class="text-xs" style="color: #9ca3af">Intensity
                                <select id="qa-wc-intensity" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.26); color: #e5e7eb;">
                                    <option value="" {'selected' if not wc_intensity_value else ''}>Select…</option>
                                    <option value="easy" {'selected' if wc_intensity_value == 'easy' else ''}>Easy</option>
                                    <option value="moderate" {'selected' if wc_intensity_value == 'moderate' else ''}>Moderate</option>
                                    <option value="hard" {'selected' if wc_intensity_value == 'hard' else ''}>Hard</option>
                                </select>
                            </label>
                            <label class="text-xs" style="color: #9ca3af">Type
                                <select id="qa-wc-session-type" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.26); color: #e5e7eb;">
                                    <option value="" {'selected' if not wc_session_type_value else ''}>Select…</option>
                                    <option value="somatic" {'selected' if wc_session_type_value == 'somatic' else ''}>Somatic</option>
                                    <option value="yin" {'selected' if wc_session_type_value == 'yin' else ''}>Yin</option>
                                    <option value="flow" {'selected' if wc_session_type_value == 'flow' else ''}>Flow</option>
                                    <option value="mobility" {'selected' if wc_session_type_value == 'mobility' else ''}>Mobility</option>
                                    <option value="restorative" {'selected' if wc_session_type_value == 'restorative' else ''}>Restorative</option>
                                    <option value="other" {'selected' if wc_session_type_value == 'other' else ''}>Other</option>
                                </select>
                            </label>
                            <label class="text-xs" style="color: #9ca3af">Body feel after
                                <select id="qa-wc-body-feel" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.26); color: #e5e7eb;">
                                    <option value="" {'selected' if not wc_body_feel_value else ''}>Select…</option>
                                    <option value="relaxed" {'selected' if wc_body_feel_value == 'relaxed' else ''}>Relaxed</option>
                                    <option value="neutral" {'selected' if wc_body_feel_value == 'neutral' else ''}>Neutral</option>
                                    <option value="tight" {'selected' if wc_body_feel_value == 'tight' else ''}>Tight</option>
                                    <option value="sore" {'selected' if wc_body_feel_value == 'sore' else ''}>Sore</option>
                                    <option value="energised" {'selected' if wc_body_feel_value == 'energised' else ''}>Energised</option>
                                    <option value="fatigued" {'selected' if wc_body_feel_value == 'fatigued' else ''}>Fatigued</option>
                                </select>
                            </label>
                            <label class="text-xs" style="color: #9ca3af">Anxiety relief (0-10)
                                <input id="qa-wc-anxiety" type="number" min="0" max="10" step="1" value="{wc_yoga_anxiety_value}" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.26); color: #e5e7eb;">
                            </label>
                        </div>
                        <label class="text-xs block" style="color: #9ca3af">Optional note
                            <textarea id="qa-wc-note" rows="2" maxlength="280" class="mt-1 w-full rounded px-2 py-1 text-xs" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.26); color: #e5e7eb;">{html.escape(wc_note_value)}</textarea>
                        </label>
                    </div>

                    <div class="rounded px-3 py-2 mb-2" style="background: rgba(15,23,42,0.45); border: 1px solid rgba(148,163,184,0.18);">
                        <p class="text-xs font-semibold mb-1" style="color: #94a3b8">Close checks</p>
                        <label class="flex items-center gap-2 text-xs mb-1" style="color: #cbd5e1"><input id="qa-wc-sig-healthfit" type="checkbox" disabled {hf_fresh_checked} class="h-3 w-3">HealthFit export done today</label>
                        {streaks_close_check_html}
                        {evening_close_checks_html}
                    </div>

                    <div class="rounded px-3 py-2 mb-2" style="background: rgba(6,95,70,0.14); border: 1px solid rgba(110,231,183,0.2);">
                        <p class="text-xs font-semibold mb-1" style="color: #6ee7b7">Auto-adjust progression rule</p>
                        <p id="qa-wc-progression-meta" class="text-xs" style="color: {wc_progression_view["color"]}">{html.escape(wc_progression_view["label"])}</p>
                        {f'<p id="qa-wc-progression-detail" class="text-xs mt-1" style="color: #9ca3af">{html.escape(wc_progression_view["detail"])}</p>' if wc_progression_view["detail"] else '<p id="qa-wc-progression-detail" class="text-xs mt-1" style="color: #9ca3af"></p>'}
                    </div>
                    {wc_weights_progression_html}

                    <details class="mt-2">
                        <summary class="text-xs font-semibold cursor-pointer" style="color: #93c5fd">📱 Shortcut hybrid setup (Health + dashboard sync)</summary>
                        <div class="mt-2 rounded px-3 py-2 text-xs" style="background: rgba(30,64,175,0.16); border: 1px solid rgba(147,197,253,0.2); color: #dbeafe;">
                            <p class="mb-1">1) In iOS Shortcuts, add <span style="color:#bfdbfe;">Log Workout</span> (Traditional Strength Training).</p>
                            <p class="mb-1">2) Add <span style="color:#bfdbfe;">Format Date</span> with <code>yyyy-MM-dd</code>.</p>
                            <p class="mb-1">3) Add <span style="color:#bfdbfe;">Get Contents of URL</span> POST to:</p>
                            <p class="mb-1"><code style="word-break: break-all;">{html.escape(shortcut_endpoint)}</code></p>
                            <p class="mb-1">4) JSON body: <code>{{"done":true,"workout":"Workout A","date":"Formatted Date","source":"shortcuts"}}</code></p>
                            <p>5) Header: <code>Authorization: Bearer &lt;api-token&gt;</code> (token in <code>~/.claude/config/api-token.txt</code>).</p>
                        </div>
                    </details>

                    <div class="mt-3 flex items-center gap-2">
                        <button id="qa-wc-save-btn" onclick="qaSaveWorkoutChecklist(this)" class="rounded px-3 py-1.5 text-xs font-semibold" style="background: rgba(6,95,70,0.35); color: #6ee7b7; border: 1px solid rgba(110,231,183,0.35);">Save checklist</button>
                        <span id="qa-wc-status" class="text-xs" style="color: #9ca3af">Not saved yet.</span>
                    </div>
                </div>
            </details>'''

    fitness_html = ""
    hf_workouts = data.get("healthfitWorkouts", [])
    if hf_workouts:
        today_str = datetime.now().strftime("%d/%m/%Y")

        def parse_duration_mins(dur_str):
            if not dur_str:
                return 0
            try:
                parts = dur_str.replace("h:", ":").replace("m:", ":").replace("s", "").split(":")
                hours = int(parts[0]) if len(parts) > 0 else 0
                mins = int(parts[1]) if len(parts) > 1 else 0
                return hours * 60 + mins
            except (ValueError, IndexError):
                return 0

        # Recent workouts (last 7 days)
        recent = []
        for w in hf_workouts:
            try:
                w_date = datetime.strptime(w.get("date", ""), "%d/%m/%Y")
                if (datetime.now() - w_date).days <= 7:
                    recent.append(w)
            except (ValueError, TypeError):
                pass

        # Today's completed workouts
        today_workouts = [w for w in recent if w.get("date") == today_str]

        # Yoga tracking (20m baseline minimum, progression-based)
        yoga_sessions = [w for w in recent if "yoga" in w.get("type", "").lower()]
        yoga_durations = [parse_duration_mins(y.get("duration", "")) for y in yoga_sessions]

        fitness_items_html = ""
        fitness_deep_html = ""

        # Scheduled today (from calendar)
        cal_fitness = []
        for ev in data.get("calendar_raw", []):
            summary_lower = ev.get("summary", "").lower()
            if any(kw in summary_lower for kw in ["weights", "yoga", "walk", "gym", "exercise", "run"]):
                cal_fitness.append(ev.get("summary", ""))

        if cal_fitness:
            fitness_items_html += f'''
            <div class="flex items-start gap-2 mb-2">
                <span style="color: #9ca3af">📋</span>
                <span class="text-sm" style="color: #d1d5db">Scheduled: {', '.join(cal_fitness)}</span>
            </div>'''

        # Completed today — check HealthFit data first, then fall back to fitness-log.md
        if today_workouts:
            for tw in today_workouts:
                dur = parse_duration_mins(tw.get("duration", ""))
                fitness_items_html += f'''
            <div class="flex items-start gap-2 mb-2">
                <span style="color: #6ee7b7">✅</span>
                <span class="text-sm" style="color: #e5e7eb">{tw.get('type', '?')} — {dur}m</span>
            </div>'''
        else:
            # Fall back to fitness-log.md (manual logging for home weights/yoga)
            _fl_workout = get_todays_workout()
            if _fl_workout.get("done"):
                fitness_items_html += f'''
            <div class="flex items-start gap-2 mb-2">
                <span style="color: #6ee7b7">✅</span>
                <span class="text-sm" style="color: #e5e7eb">{_fl_workout["title"]} — logged in fitness-log.md</span>
            </div>'''
            else:
                fitness_items_html += '''
            <div class="flex items-start gap-2 mb-2">
                <span style="color: #6b7280">⬜</span>
                <span class="text-sm" style="color: #6b7280">No workout recorded yet today</span>
            </div>'''

        # 7-day progression
        if recent:
            fitness_deep_html += f'''
            <div class="mt-2 pt-2" style="border-top: 1px solid rgba(110,231,183,0.1);">
                <p class="text-xs font-semibold mb-2" style="color: #9ca3af">📊 Last 7 days: {len(recent)} workouts</p>'''
            for rw in recent[:5]:
                dur = parse_duration_mins(rw.get("duration", ""))
                rw_date = rw.get("date", "")[:5]  # DD/MM
                fitness_deep_html += f'''
                <div class="flex items-center gap-2 text-xs mb-1">
                    <span class="w-12 font-mono" style="color: #6b7280">{rw_date}</span>
                    <span style="color: #d1d5db">{rw.get('type', '?')}</span>
                    <span style="color: #9ca3af">{dur}m</span>
                </div>'''
            fitness_deep_html += '</div>'

        # Yoga progression tracking (20m is baseline minimum, not a goal)
        if yoga_sessions:
            avg_yoga = sum(yoga_durations) / len(yoga_durations) if yoga_durations else 0
            latest_yoga = yoga_durations[0] if yoga_durations else 0

            # Get the date of the latest yoga session for context
            latest_yoga_date = yoga_sessions[0].get("date", "") if yoga_sessions else ""
            try:
                _yoga_dt = datetime.strptime(latest_yoga_date, "%d/%m/%Y")
                _yoga_day_name = _yoga_dt.strftime("%A")  # e.g. "Wednesday"
                _yoga_date_short = _yoga_dt.strftime("%d/%m")  # e.g. "12/02"
                if _yoga_dt.date() == datetime.now().date():
                    yoga_date_label = "today"
                elif _yoga_dt.date() == (datetime.now() - timedelta(days=1)).date():
                    yoga_date_label = "yesterday"
                else:
                    yoga_date_label = f"{_yoga_day_name} {_yoga_date_short}"
            except (ValueError, TypeError):
                yoga_date_label = latest_yoga_date[:5] if latest_yoga_date else "recent"

            # Progression suggestion: always suggest next 5-min increment ABOVE current
            # Never suggest less than what was just achieved (matches embed-dashboard-in-notes.py)
            if latest_yoga >= 30:
                next_target = ((latest_yoga // 5) + 1) * 5
                yoga_status = f'''<span style="color: #6ee7b7">🔥 Yoga: {latest_yoga}m ({yoga_date_label}) — crushing it! Aim for {next_target}m next?</span>'''
            elif latest_yoga >= 25:
                yoga_status = f'''<span style="color: #6ee7b7">💪 Yoga: {latest_yoga}m ({yoga_date_label}) — strong session! Try {latest_yoga + 5}m next?</span>'''
            elif latest_yoga >= 22:
                yoga_status = f'''<span style="color: #6ee7b7">📈 Yoga: {latest_yoga}m ({yoga_date_label}) — building up, aim for {latest_yoga + 3}m next</span>'''
            elif latest_yoga >= 20:
                yoga_status = f'''<span style="color: #6ee7b7">✅ Yoga: {latest_yoga}m ({yoga_date_label}) — solid baseline, try 25m next</span>'''
            else:
                yoga_status = f'''<span style="color: #fbbf24">⚠️ Yoga: {latest_yoga}m ({yoga_date_label}) — below your 20m minimum</span>'''

            fitness_deep_html += f'''
            <div class="mt-2 pt-2" style="border-top: 1px solid rgba(110,231,183,0.1);">
                <div class="text-sm mb-1">{yoga_status}</div>'''

            # Trend over last sessions
            if len(yoga_durations) >= 3:
                recent_avg = sum(yoga_durations[:3]) / 3
                if recent_avg > avg_yoga + 2:
                    trend_text = f'📊 Trending up: {recent_avg:.0f}m recent vs {avg_yoga:.0f}m overall'
                elif recent_avg < avg_yoga - 2:
                    trend_text = f'📊 Trending down: {recent_avg:.0f}m recent vs {avg_yoga:.0f}m overall'
                else:
                    trend_text = f'📊 Consistent: ~{avg_yoga:.0f}m average across {len(yoga_sessions)} sessions'
                fitness_deep_html += f'''
                <div class="text-xs" style="color: #9ca3af">{trend_text}</div>'''
            elif len(yoga_durations) >= 2:
                fitness_deep_html += f'''
                <div class="text-xs" style="color: #9ca3af">📈 Avg: {avg_yoga:.0f}m across {len(yoga_sessions)} sessions</div>'''
            fitness_deep_html += '</div>'

        if fitness_deep_html:
            fitness_items_html += f'''
            <details class="mt-3 pt-2" style="border-top: 1px solid rgba(110,231,183,0.1);">
                <summary class="text-xs font-semibold cursor-pointer" style="color: #9ca3af">📂 Show training history and trends</summary>
                <div class="mt-2">
                    {fitness_deep_html}
                </div>
            </details>'''

        fitness_items_html += workout_checklist_html

        fitness_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(6,95,70,0.1); border: 1px solid rgba(110,231,183,0.15);">
                <h3 class="text-lg font-semibold mb-3" style="color: #6ee7b7">💪 Fitness</h3>
                {fitness_items_html}
            </div>'''
    else:
        fallback_workout = get_todays_workout()
        fallback_line = f'{fallback_workout.get("title", "Workout")} — logged in fitness-log.md' if fallback_workout.get("done") else "No workout recorded yet today"
        fallback_icon = "✅" if fallback_workout.get("done") else "⬜"
        fallback_color = "#e5e7eb" if fallback_workout.get("done") else "#6b7280"
        fitness_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(6,95,70,0.1); border: 1px solid rgba(110,231,183,0.15);">
                <h3 class="text-lg font-semibold mb-3" style="color: #6ee7b7">💪 Fitness</h3>
                <div class="flex items-start gap-2 mb-2">
                    <span style="color: {'#6ee7b7' if fallback_workout.get("done") else '#6b7280'}">{fallback_icon}</span>
                    <span class="text-sm" style="color: {fallback_color}">{fallback_line}</span>
                </div>
                {workout_checklist_html}
            </div>'''

    # === Mood tracking (native emoji selector + moodLog timeline) ===
    mood_tracking_html = ""
    mood_tracking = data.get("moodTracking", {}) if isinstance(data.get("moodTracking"), dict) else {}
    mood_log_data = data.get("moodLog", {}) if isinstance(data.get("moodLog"), dict) else {}
    mood_log_entries_raw = (
        mood_log_data.get("entries", [])
        if str(mood_log_data.get("date", "")).strip() == get_effective_date()
        else []
    )
    mood_entries = _sanitize_mood_entries_for_today(
        mood_log_entries_raw,
        now_dt=datetime.now(),
        allow_diarium_source=bool(data.get("diariumFresh", True)),
    )

    # Build timeline pills from today's mood entries
    mood_timeline_html = ""
    if mood_entries:
        pills = " \u2192 ".join(
            f'<span class="mood-pill">{html.escape(str(e.get("time","")))}&nbsp;{html.escape(str(e.get("mood","")))}</span>'
            for e in mood_entries[-4:]
        )
        mood_timeline_html = f'<div class="mood-timeline" id="qa-mood-timeline">{pills}</div>'

    # Current mood display (latest moodLog entry or diarium tone)
    diarium_tone = data.get("diariumAnalysis", {}).get("emotional_tone", "") if isinstance(data.get("diariumAnalysis"), dict) else ""
    current_mood_display = ""
    has_manual_mood = any(e.get("source") != "diarium" for e in mood_entries) if mood_entries else False
    if mood_entries:
        last_entry = mood_entries[-1]
        source_icon = "\U0001f4d4 " if last_entry.get("source") == "diarium" and not has_manual_mood else ""
        source_title = "From diary" if last_entry.get("source") == "diarium" else "Manual"
        current_mood_display = f'<span class="mood-current" title="{source_title}">{source_icon}{html.escape(str(last_entry.get("mood","")))}&nbsp;{html.escape(str(last_entry.get("label","")))}</span>'
    elif diarium_tone:
        current_mood_display = f'<span class="mood-current">{html.escape(diarium_tone)}</span>'

    # Also preserve the old check-in status for the quick-action checkbox
    mood_done = bool(mood_tracking.get("done_today")) if mood_tracking else False

    mood_tracking_html = f'''
            <div class="card rounded-xl p-5 mb-4 mood-card" style="background: rgba(88,28,135,0.1); border: 1px solid rgba(196,181,253,0.2);">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                    <span style="font-size: 1.2rem;">\U0001f3ad</span>
                    <span class="text-lg font-semibold" style="color: #c4b5fd">Mood</span>
                    {current_mood_display}
                </div>
                <p id="qa-mood-meta" class="text-sm" style="color: {"#6ee7b7" if mood_done else "#9ca3af"}; margin-bottom: 8px; display: none;"></p>
                <div class="mood-selector">
                    <div class="mood-emojis">
                        <button class="mood-btn" data-mood="\U0001f60a" data-label="happy" onclick="qaMoodSelect(this)" title="happy">\U0001f60a</button>
                        <button class="mood-btn" data-mood="\U0001f60c" data-label="calm" onclick="qaMoodSelect(this)" title="calm">\U0001f60c</button>
                        <button class="mood-btn" data-mood="\U0001f610" data-label="neutral" onclick="qaMoodSelect(this)" title="neutral">\U0001f610</button>
                        <button class="mood-btn" data-mood="\U0001f61f" data-label="worried" onclick="qaMoodSelect(this)" title="worried">\U0001f61f</button>
                        <button class="mood-btn" data-mood="\U0001f630" data-label="anxious" onclick="qaMoodSelect(this)" title="anxious">\U0001f630</button>
                        <button class="mood-btn" data-mood="\U0001f624" data-label="frustrated" onclick="qaMoodSelect(this)" title="frustrated">\U0001f624</button>
                        <button class="mood-btn" data-mood="\U0001f614" data-label="sad" onclick="qaMoodSelect(this)" title="sad">\U0001f614</button>
                    </div>
                    <div class="mood-context-btns">
                        <button class="mood-ctx active" data-ctx="morning" onclick="qaMoodCtx(this)">Morning</button>
                        <button class="mood-ctx" data-ctx="general" onclick="qaMoodCtx(this)">Now</button>
                        <button class="mood-ctx" data-ctx="evening" onclick="qaMoodCtx(this)">Evening</button>
                    </div>
                </div>
                {mood_timeline_html}
            </div>'''

    # === Mindfulness tracking (Streaks auto + manual dashboard log) ===
    mindfulness_html = ""
    mindfulness = data.get("mindfulness", {}) if isinstance(data.get("mindfulness"), dict) else {}
    if mindfulness:
        mindfulness_done = bool(mindfulness.get("done"))
        mindfulness_auto = bool(mindfulness.get("auto_done"))
        mindfulness_manual_done = mindfulness.get("manual_done")
        mindfulness_auto_source = str(mindfulness.get("auto_source", "")).strip().lower()
        mindfulness_has_manual_override = isinstance(mindfulness_manual_done, bool)
        mindfulness_auto_from_streaks = (
            mindfulness_auto and not mindfulness_has_manual_override and "streaks" in mindfulness_auto_source
        )
        mindfulness_auto_from_healthfit = (
            mindfulness_auto and not mindfulness_has_manual_override and "healthfit" in mindfulness_auto_source
        )
        mindfulness_auto_from_finch = (
            mindfulness_auto and not mindfulness_has_manual_override and "finch" in mindfulness_auto_source
        )
        mindfulness_habit = str(mindfulness.get("habit", "")).strip()
        minutes_target_raw = mindfulness.get("minutes_target", 20)
        minutes_done_raw = mindfulness.get("minutes_done", minutes_target_raw if mindfulness_done else 0)
        try:
            minutes_target = int(minutes_target_raw)
        except Exception:
            minutes_target = 20
        if minutes_target <= 0:
            minutes_target = 20
        try:
            minutes_done = int(minutes_done_raw)
        except Exception:
            minutes_done = minutes_target if mindfulness_done else 0

        if mindfulness_done:
            if mindfulness_auto_from_streaks:
                source_label = "auto from Streaks"
            elif mindfulness_auto_from_healthfit:
                source_label = "auto from HealthFit"
            elif mindfulness_auto_from_finch:
                source_label = "auto from Finch"
            else:
                source_label = "manual"
            status_text = f"✅ {minutes_done}m logged ({source_label})"
            status_color = "#6ee7b7"
        else:
            status_text = f"⬜ Target: {minutes_target}m today"
            status_color = "#9ca3af"

        if mindfulness_habit:
            status_text += f" • {mindfulness_habit}"

        progression = mindfulness.get("progression", {}) if isinstance(mindfulness.get("progression"), dict) else {}
        combined_score_raw = progression.get("combined_score")
        adherence_raw = progression.get("seven_day_mindfulness_adherence_pct")
        progression_line = "Progression updates after today&apos;s anxiety score."
        if isinstance(combined_score_raw, (int, float)):
            if isinstance(adherence_raw, (int, float)):
                progression_line = f"Mental-health progression: {float(combined_score_raw):.1f}/10 • 7-day mindfulness {int(adherence_raw)}%"
            else:
                progression_line = f"Mental-health progression: {float(combined_score_raw):.1f}/10"

        checked_attr = "checked" if mindfulness_done else ""
        if mindfulness_done:
            # Compact: done confirmation + progression collapsed
            mindfulness_html = f'''
            <div class="card rounded-xl p-4 mb-4" style="background: rgba(30,64,175,0.08); border: 1px solid rgba(147,197,253,0.15);">
                <details>
                    <summary class="cursor-pointer flex items-center gap-2">
                        <span class="text-sm font-medium" style="color: #6ee7b7">✅ Mindfulness done — {minutes_done}m</span>
                        <span class="text-xs" style="color: #6b7280">({progression_line})</span>
                    </summary>
                    <div class="mt-3">
                        <label class="flex items-center gap-3 cursor-pointer">
                            <input id="qa-mindfulness-check" type="checkbox" {checked_attr} onchange="qaToggleMindfulness(this)" class="h-4 w-4">
                            <span class="text-sm" style="color: #e5e7eb">Log {minutes_target}m mindfulness</span>
                        </label>
                        <p id="qa-mindfulness-meta" class="text-xs mt-2" style="color: {status_color}">{html.escape(status_text)}</p>
                    </div>
                </details>
            </div>'''
        else:
            mindfulness_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(30,64,175,0.12); border: 1px solid rgba(147,197,253,0.2);">
                <h3 class="text-lg font-semibold mb-3" style="color: #93c5fd">🧠 Mindfulness</h3>
                <label class="flex items-center gap-3 cursor-pointer">
                    <input id="qa-mindfulness-check" type="checkbox" {checked_attr} onchange="qaToggleMindfulness(this)" class="h-4 w-4">
                    <span class="text-sm" style="color: #e5e7eb">Log {minutes_target}m mindfulness</span>
                </label>
                <p id="qa-mindfulness-meta" class="text-xs mt-2" style="color: {status_color}">{html.escape(status_text)}</p>
                <p class="text-xs mt-1" style="color: #6b7280">{progression_line}</p>
            </div>'''

    # === Finch Self-Care Tracker ===
    finch_html = ""
    finch_data = data.get("finch", {})
    finch_summary = finch_data.get("summary", {})
    finch_streaks = finch_data.get("streaks", {})
    finch_activities = finch_data.get("activities", {}).get("activities", {})
    finch_insights = finch_data.get("insights", [])

    if finch_summary.get("status") == "active" or finch_streaks.get("current_streak", 0) > 0:
        streak_count = finch_streaks.get("current_streak", 0)
        total_days = finch_streaks.get("total_days", 0)
        total_activities = finch_summary.get("total_activities", 0)
        backup_date = finch_data.get("backup_date", "")

        # Streak badge color
        if streak_count >= 365:
            streak_color = "#6ee7b7"  # mint - amazing
            streak_emoji = "🔥"
        elif streak_count >= 30:
            streak_color = "#fbbf24"  # amber - strong
            streak_emoji = "🔥"
        else:
            streak_color = "#9ca3af"
            streak_emoji = "📅"

        # Build activities list (top self-care habits)
        activities_html = ""
        if finch_activities:
            sorted_acts = sorted(finch_activities.items(), key=lambda x: x[1], reverse=True)
            for act_name, act_count in sorted_acts[:7]:
                act_emoji = _pick_content_emoji(act_name)
                activities_html += f'<div class="flex justify-between text-xs mb-1"><span style="color: #d1d5db">{act_emoji} {act_name}</span><span style="color: #9ca3af">{act_count}x</span></div>'

        # Insights
        insights_html = ""
        for insight in finch_insights[:2]:
            insights_html += f'<p class="text-xs mb-1" style="color: #9ca3af">{insight}</p>'

        # Backup freshness warning
        backup_warning = ""
        if backup_date:
            try:
                backup_dt = datetime.strptime(backup_date, "%Y-%m-%d")
                days_old = (datetime.now() - backup_dt).days
                if days_old > 3:
                    backup_warning = f'<p class="text-xs mt-2" style="color: #fbbf24">⚠️ Backup is {days_old} days old — sync Finch</p>'
            except (ValueError, TypeError):
                pass

        finch_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(6,95,70,0.08); border: 1px solid rgba(110,231,183,0.12);">
                <div class="flex items-center justify-between mb-3">
                    <h3 class="text-lg font-semibold" style="color: #a7f3d0">🐦 Finch Self-Care</h3>
                    <div class="text-right">
                        <p class="text-2xl font-bold" style="color: {streak_color}">{streak_emoji} {streak_count}</p>
                        <p class="text-xs" style="color: #6b7280">day streak</p>
                    </div>
                </div>
                <div class="flex gap-4 mb-3">
                    <div class="flex-1 rounded-lg p-2 text-center" style="background: rgba(6,95,70,0.15);">
                        <p class="text-lg font-bold" style="color: #6ee7b7">{total_days}</p>
                        <p class="text-xs" style="color: #6b7280">total days</p>
                    </div>
                    <div class="flex-1 rounded-lg p-2 text-center" style="background: rgba(88,28,135,0.1);">
                        <p class="text-lg font-bold" style="color: #c4b5fd">{total_activities:,}</p>
                        <p class="text-xs" style="color: #6b7280">activities</p>
                    </div>
                </div>
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(110,231,183,0.1);"><p class="text-xs mb-2 font-semibold" style="color: #9ca3af">🧘 Daily habits:</p>' + activities_html + '</div>') if activities_html else ''}
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(110,231,183,0.1);">' + insights_html + '</div>') if insights_html else ''}
                {backup_warning}
            </div>'''

    # === Health compact indicator (replaces charts — returns when Biome works) ===
    # healthData is populated by main() from HealthFit (preferred) or Apple Health (fallback)
    health_html = ""
    health_data = data.get("healthData", [])
    if health_data:
        stale = data.get("healthDataStale", False)
        age = data.get("healthDataAge", 0)
        latest = health_data[-1] if health_data else {}
        avg_steps = sum(d.get("steps", 0) for d in health_data) // len(health_data) if health_data else 0
        avg_ex = sum(d.get("exercise", 0) for d in health_data) // len(health_data) if health_data else 0

        if stale:
            health_html = f'''
            <div class="rounded-lg p-3 text-center" style="background: rgba(120,53,15,0.15); border: 1px solid rgba(251,191,36,0.2);">
                <p class="text-sm" style="color: #fde68a">⚠️ Health data is {age} days old — please export</p>
            </div>'''
        else:
            latest_steps = latest.get("steps", 0)
            latest_ex = latest.get("exercise", 0)
            latest_day = latest.get("day", "?")
            today_day = datetime.now().strftime("%d")
            day_label = "today" if latest_day == today_day else f"latest ({latest_day}th)"
            health_html = f'''
            <div class="flex gap-4">
                <div class="flex-1 rounded-lg p-3 text-center" style="background: rgba(6,95,70,0.15); border: 1px solid rgba(110,231,183,0.15);">
                    <p class="text-2xl font-bold" style="color: #6ee7b7">{avg_steps:,}</p>
                    <p class="text-xs" style="color: #9ca3af">avg steps/day</p>
                    <p class="text-lg font-semibold mt-2" style="color: #34d399">{latest_steps:,}</p>
                    <p class="text-xs" style="color: #6b7280">{day_label}</p>
                </div>
                <div class="flex-1 rounded-lg p-3 text-center" style="background: rgba(88,28,135,0.15); border: 1px solid rgba(196,181,253,0.15);">
                    <p class="text-2xl font-bold" style="color: #c4b5fd">{avg_ex}m</p>
                    <p class="text-xs" style="color: #9ca3af">avg exercise</p>
                    <p class="text-lg font-semibold mt-2" style="color: #a78bfa">{latest_ex}m</p>
                    <p class="text-xs" style="color: #6b7280">{day_label}</p>
                </div>
            </div>'''

    correlation_html = ""
    corr = data.get("anxietyCorrelation", {}) if isinstance(data.get("anxietyCorrelation", {}), dict) else {}
    if corr.get("status") == "ok" and corr.get("count", 0) >= 14:
        step_corr = corr.get("step_corr")
        ex_corr = corr.get("exercise_corr")
        sleep_corr = corr.get("sleep_corr")

        def corr_text(value):
            if value is None:
                return "n/a"
            if value >= 0.35:
                return f"{value} (positive)"
            if value <= -0.35:
                return f"{value} (inverse)"
            return f"{value} (weak)"

        high_steps = corr.get("high_avg_steps")
        low_steps = corr.get("low_avg_steps")
        high_ex = corr.get("high_avg_exercise")
        low_ex = corr.get("low_avg_exercise")
        points_count = corr.get("count", 0)

        diff_bits = []
        if isinstance(high_steps, (int, float)) and isinstance(low_steps, (int, float)):
            diff_bits.append(f"High-relief days averaged {int(high_steps):,} steps vs {int(low_steps):,} on low-relief days.")
        if isinstance(high_ex, (int, float)) and isinstance(low_ex, (int, float)):
            diff_bits.append(f"Exercise averaged {high_ex:g}m vs {low_ex:g}m.")
        diff_summary = " ".join(diff_bits) if diff_bits else "Need more mixed health + anxiety score days for stronger comparison."

        correlation_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(30,64,175,0.12); border: 1px solid rgba(147,197,253,0.18);">
                <details>
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #93c5fd">📈 Anxiety Relief Correlation ({points_count} days)</summary>
                    <div class="mt-3">
                        <p class="text-xs mb-2" style="color: #94a3b8">Tracks whether your Finch anxiety scores correlate with steps, exercise, and sleep over the last 14 days — helps identify which health habits most reliably reduce anxiety.</p>
                        <p class="text-xs mb-2" style="color: #94a3b8">Last 14 days with score+health overlap: {points_count}</p>
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs mb-3">
                            <div class="rounded px-2 py-2" style="background: rgba(15,23,42,0.55); border: 1px solid rgba(148,163,184,0.2); color: #cbd5e1;">Steps corr: <span style="color: #a7f3d0">{corr_text(step_corr)}</span></div>
                            <div class="rounded px-2 py-2" style="background: rgba(15,23,42,0.55); border: 1px solid rgba(148,163,184,0.2); color: #cbd5e1;">Exercise corr: <span style="color: #a7f3d0">{corr_text(ex_corr)}</span></div>
                            <div class="rounded px-2 py-2" style="background: rgba(15,23,42,0.55); border: 1px solid rgba(148,163,184,0.2); color: #cbd5e1;">Sleep corr: <span style="color: #a7f3d0">{corr_text(sleep_corr)}</span></div>
                        </div>
                        <p class="text-sm" style="color: #dbeafe; line-height: 1.5;">{diff_summary}</p>
                    </div>
                </details>
            </div>'''


    # === Mood Patterns Correlation Card ===
    mood_correlation_html = ""
    mood_corr = data.get("moodCorrelation", {}) if isinstance(data.get("moodCorrelation"), dict) else {}
    if mood_corr.get("status") == "ok" and mood_corr.get("correlations"):
        corr_items = mood_corr["correlations"][:3]
        mood_summary = mood_corr.get("mood_summary", "")
        mood_days = mood_corr.get("days_analysed", 0)

        mood_items_html = ""
        for c in corr_items:
            conf_colour = {"high": "#6ee7b7", "medium": "#fbbf24", "low": "#94a3b8"}.get(c.get("confidence", "low"), "#94a3b8")
            mood_items_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(30,58,138,0.12); border-left: 3px solid {conf_colour}">
                <p class="text-sm" style="color: #e5e7eb">{html.escape(str(c.get("finding", "")))}</p>
                <p class="text-xs mt-1" style="color: #9ca3af">💡 {html.escape(str(c.get("recommendation", "")))}</p>
            </div>'''

        mood_correlation_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: rgba(30,58,138,0.12); border: 1px solid rgba(110,231,183,0.18);">
                <h3 class="text-lg font-semibold mb-3" style="color: #6ee7b7">📊 Mood Patterns ({mood_days}d)</h3>
                {f'<p class="text-sm mb-3" style="color: #9ca3af">{html.escape(mood_summary)}</p>' if mood_summary else ""}
                {mood_items_html}
            </div>'''

    weekly_digest = data.get("weeklyDigest", {}) if isinstance(data.get("weeklyDigest"), dict) else {}
    weekly_current_week = str(weekly_digest.get("current_week_label", "")).strip() or "this week"
    weekly_current_exists = bool(weekly_digest.get("current_exists"))
    weekly_current_path = str(weekly_digest.get("current_path", "")).strip()
    weekly_latest_name = str(weekly_digest.get("latest_name", "")).strip()
    weekly_latest_path = str(weekly_digest.get("latest_path", "")).strip()
    weekly_needs_generation = bool(weekly_digest.get("needs_generation"))
    weekly_end_of_week = bool(weekly_digest.get("is_end_of_week"))
    weekly_is_sunday = bool(weekly_digest.get("is_sunday"))

    def _to_file_url(path_value: str) -> str:
        raw = str(path_value or "").strip()
        if not raw:
            return ""
        try:
            p = Path(raw).expanduser().resolve()
            return p.as_uri()
        except Exception:
            return f"file://{url_quote(raw)}"

    weekly_current_url = _to_file_url(weekly_current_path)
    weekly_latest_url = _to_file_url(weekly_latest_path)
    weekly_status_label = "✅ Ready" if weekly_current_exists else ("⚠️ Due today" if weekly_needs_generation else "⏳ Waiting for Sunday")
    weekly_status_color = "#6ee7b7" if weekly_current_exists else ("#fbbf24" if weekly_needs_generation else "#94a3b8")
    weekly_latest_link_html = (
        f'<a id="qa-weekly-digest-latest-link" href="{html.escape(weekly_latest_url)}" style="color: #93c5fd">{html.escape(weekly_latest_name or "Latest weekly digest")}</a>'
        if weekly_latest_url
        else '<span id="qa-weekly-digest-latest-link" style="color: #6b7280">No weekly digest generated yet.</span>'
    )
    weekly_current_link_html = (
        f'<a id="qa-weekly-digest-current-link" href="{html.escape(weekly_current_url)}" style="color: #a7f3d0">{html.escape(Path(weekly_current_path).name)}</a>'
        if weekly_current_exists and weekly_current_url
        else f'<span id="qa-weekly-digest-current-link" style="color: #6b7280">Current week ({html.escape(weekly_current_week)}) digest not generated yet.</span>'
    )
    weekly_hint = (
        "Sunday reminder: generate this today so the review is ready."
        if weekly_is_sunday and not weekly_current_exists
        else "Weekly report appears here automatically once generated."
    )
    weekly_generate_btn_label = "↻ Regenerate week report" if weekly_current_exists else "📝 Generate week report"
    weekly_digest_html = f'''
        <div class="card rounded-xl p-4 mb-4" style="background: rgba(30,64,175,0.1); border: 1px solid rgba(147,197,253,0.2);">
            <div class="flex items-center justify-between gap-3 mb-2">
                <h3 class="text-lg font-semibold" style="color: #93c5fd">📅 Weekly Report ({html.escape(weekly_current_week)})</h3>
                <span id="qa-weekly-digest-status" class="optional-pill text-xs rounded px-2 py-1" style="border: 1px solid rgba(148,163,184,0.24); color: {weekly_status_color};">{weekly_status_label}</span>
            </div>
            <p class="text-xs mb-1" style="color: #cbd5e1">Current week: {weekly_current_link_html}</p>
            <p class="text-xs mb-2" style="color: #94a3b8">Latest: {weekly_latest_link_html}</p>
            <p id="qa-weekly-digest-meta" class="text-xs mb-3" style="color: #6b7280">{html.escape(weekly_hint)}</p>
            <button id="qa-weekly-digest-btn" onclick="qaGenerateWeeklyDigest(this)" class="rounded px-3 py-1.5 text-xs font-semibold" style="background: rgba(30,64,175,0.3); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">{weekly_generate_btn_label}</button>
        </div>''' if weekly_is_sunday else ""
    # === Screen Time Section ===
    screentime_html = ""
    screentime_summary_label = "📱 Screen Time"
    screentime_data = data.get("screentime", {})
    if screentime_data.get("status") == "success":
        summary = screentime_data.get("summary", {})
        avg_time = summary.get("avg_screen_time_display", "0h 0m")
        daily_metrics = screentime_data.get("daily_metrics", [])

        # Yesterday's categorized breakdown
        category_html = ""
        if daily_metrics:
            sys.path.insert(0, str(Path.home() / ".claude" / "daemon"))
            from screentime_categories import get_category_summary

            yesterday = daily_metrics[-2] if len(daily_metrics) >= 2 else daily_metrics[-1]
            top_apps = yesterday.get("top_apps", [])

            # Get categorized summary
            categories = get_category_summary(top_apps)
            for emoji, category_name, time_str in categories:
                category_html += f'<div class="flex justify-between text-xs mb-1"><span style="color: #d1d5db">{emoji} {category_name}</span><span style="color: #9ca3af">{time_str}</span></div>'

        # Warning color if avg > 6h (more strict threshold)
        try:
            hours = int(avg_time.split('h')[0])
            is_high = hours >= 6
        except Exception:
            is_high = False

        bg_color = "rgba(120,53,15,0.15)" if is_high else "rgba(88,28,135,0.15)"
        border_color = "rgba(251,191,36,0.2)" if is_high else "rgba(196,181,253,0.15)"
        text_color = "#fde68a" if is_high else "#c4b5fd"
        warning_emoji = " ⚠️" if is_high else ""
        screentime_summary_label = f"📱 Screen Time • {avg_time} (7-day avg){warning_emoji}"

        # Today's top apps breakdown
        today_apps_html = ""
        if daily_metrics:
            # Use today's data if available, else latest day
            today_data = daily_metrics[0] if daily_metrics else None
            # Find today's entry by date
            today_str = datetime.now().strftime("%Y-%m-%d")
            for dm in daily_metrics:
                if dm.get("date") == today_str:
                    today_data = dm
                    break

            if today_data:
                today_total = today_data.get("total_display", "0h 0m")
                today_top = today_data.get("top_apps", [])[:6]
                if today_top:
                    today_apps_html = f'<p class="text-xs mb-1 mt-2" style="color: #9ca3af">Today ({today_total}):</p>'
                    for app_info in today_top:
                        app_name = app_info.get("app", "Unknown")
                        app_mins = app_info.get("minutes", 0)
                        if app_mins >= 60:
                            app_time = f"{int(app_mins // 60)}h {int(app_mins % 60)}m"
                        else:
                            app_time = f"{int(app_mins)}m"
                        today_apps_html += f'<div class="flex justify-between text-xs mb-1"><span style="color: #d1d5db">{app_name}</span><span style="color: #9ca3af">{app_time}</span></div>'

        screentime_html = f'''
            <div class="rounded-lg p-3" style="background: {bg_color}; border: 1px solid {border_color};">
                <div class="flex items-center justify-between mb-2">
                    <p class="text-sm font-semibold" style="color: {text_color}">📱 Screen Time (7-day avg){warning_emoji}</p>
                    <p class="text-2xl font-bold" style="color: {text_color}">{avg_time}</p>
                </div>
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(75,85,99,0.2);">' + today_apps_html + '</div>') if today_apps_html else ''}
                <div class="mt-2 pt-2" style="border-top: 1px solid rgba(75,85,99,0.2);">
                    <p class="text-xs mb-2" style="color: #9ca3af">Yesterday by category:</p>
                    {category_html if category_html else '<p class="text-xs" style="color: #6b7280">No data</p>'}
                </div>
            </div>'''

    # === ActivityWatch Section ===
    activitywatch_html = ""
    activitywatch_summary_label = "🖥️ ActivityWatch"
    aw_data = data.get("activitywatch", {})
    if not isinstance(aw_data, dict):
        aw_data = {}

    aw_status = aw_data.get("status", "unknown")
    if aw_status == "success":
        focus_patterns = aw_data.get("focus_patterns", {})
        focus_state = focus_patterns.get("focus_state", "normal")
        total_mins = aw_data.get("total_tracked_minutes", 0)
        raw_total_mins = aw_data.get("raw_tracked_minutes", total_mins)
        afk_filter_applied = bool(aw_data.get("afk_filter_applied"))
        afk_mins = aw_data.get("afk_minutes", 0)
        job_mins = aw_data.get("job_application_minutes", 0)
        prod_mins = aw_data.get("productive_minutes", 0)
        switches = focus_patterns.get("context_switches", 0)

        def _mins_display(value):
            mins = max(int(float(value or 0)), 0)
            if mins >= 60:
                return f"{mins // 60}h {mins % 60}m"
            return f"{mins}m"

        # Focus state emoji and color
        focus_config = {
            "hyperfocus": {"emoji": "🎯", "color": "#6ee7b7", "bg": "rgba(6,95,70,0.15)"},
            "deep_work": {"emoji": "🧠", "color": "#c4b5fd", "bg": "rgba(88,28,135,0.15)"},
            "scattered": {"emoji": "💫", "color": "#fbbf24", "bg": "rgba(120,53,15,0.15)"},
            "normal": {"emoji": "📊", "color": "#9ca3af", "bg": "rgba(55,65,81,0.15)"}
        }

        config = focus_config.get(focus_state, focus_config["normal"])

        # Top apps/websites
        top_apps = aw_data.get("top_apps", [])[:5]
        top_sites = aw_data.get("top_websites", [])[:5]

        apps_html = ""
        if top_apps:
            for app_info in top_apps:
                app_name = app_info.get("app", "Unknown")
                app_mins = app_info.get("minutes", 0)
                apps_html += f'<div class="flex justify-between text-xs mb-1"><span style="color: #d1d5db">{app_name}</span><span style="color: #9ca3af">{int(app_mins)}m</span></div>'

        sites_html = ""
        if top_sites:
            for site_info in top_sites:
                domain = site_info.get("domain", "Unknown")
                if not domain or domain == "":
                    continue
                site_mins = site_info.get("minutes", 0)
                is_idle = site_info.get("likely_idle", False)
                if is_idle:
                    continue  # Silently exclude idle/background tabs
                sites_html += f'<div class="flex justify-between text-xs mb-1"><span style="color: #d1d5db">{domain}</span><span style="color: #9ca3af">{int(site_mins)}m</span></div>'

        # Format total time as hours and minutes
        total_display = _mins_display(total_mins)
        activitywatch_summary_label = f"🖥️ ActivityWatch • {focus_state.replace('_', ' ').title()} • {total_display} today"

        # Focus state label with explanation
        focus_labels = {
            "hyperfocus": "Single app 90+ min",
            "deep_work": "Avg session 30+ min",
            "scattered": "Many short sessions",
            "normal": "Mixed activity"
        }
        focus_label = focus_labels.get(focus_state, "")

        # Context switches with explanation
        switches_warning = ""
        if switches > 20:
            switches_warning = f'<div class="rounded p-2 mt-2" style="background: rgba(120,53,15,0.1); border-left: 2px solid #fbbf24"><p class="text-xs" style="color: #fbbf24">⚠️ {switches} app switches today (avg {round(total_mins / max(switches, 1), 1)}m per app)</p></div>'

        afk_note = ""
        removed_mins = float(raw_total_mins or 0) - float(total_mins or 0)
        if afk_filter_applied and removed_mins > 5:
            afk_note = (
                '<div class="rounded p-2 mt-2" style="background: rgba(17,24,39,0.45); border-left: 2px solid #6ee7b7">'
                f'<p class="text-xs" style="color: #6ee7b7">✅ Idle filtered: {_mins_display(raw_total_mins)} raw → {total_display} active'
                f' (−{_mins_display(removed_mins)} AFK/sleep)</p>'
                '</div>'
            )

        activitywatch_html = f'''
            <div class="rounded-lg p-3" style="background: {config['bg']}; border: 1px solid {config['color']}33;">
                <div class="flex items-center justify-between mb-2">
                    <div>
                        <p class="text-sm font-semibold" style="color: {config['color']}">{config['emoji']} Focus: {focus_state.upper()}</p>
                        <p class="text-xs" style="color: #6b7280">{focus_label}</p>
                    </div>
                    <div class="text-right">
                        <p class="text-2xl font-bold" style="color: {config['color']}">{total_display}</p>
                        <p class="text-xs" style="color: #6b7280">Today</p>
                    </div>
                </div>
                {afk_note}
                {switches_warning}
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(75,85,99,0.2);"><p class="text-xs mb-2" style="color: #9ca3af">💼 Job applications: ' + str(int(job_mins)) + 'm</p></div>') if job_mins > 0 else ''}
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(75,85,99,0.2);"><p class="text-xs mb-2" style="color: #9ca3af">✅ Productive: ' + str(int(prod_mins)) + 'm</p></div>') if prod_mins > 0 else ''}
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(75,85,99,0.2);"><p class="text-xs mb-2" style="color: #9ca3af">Top apps:</p>' + apps_html + '</div>') if apps_html else ''}
                {('<div class="mt-2 pt-2" style="border-top: 1px solid rgba(75,85,99,0.2);"><p class="text-xs mb-2" style="color: #9ca3af">Top websites:</p>' + sites_html + '</div>') if sites_html else ''}
            </div>'''
    else:
        status_labels = {
            "not_running": "Not running",
            "no_data": "No data yet",
            "error": "Unavailable",
            "unknown": "Unknown state",
        }
        status_colors = {
            "not_running": "#fbbf24",
            "no_data": "#9ca3af",
            "error": "#f9a8d4",
            "unknown": "#9ca3af",
        }
        status_label = status_labels.get(aw_status, aw_status.replace("_", " ").title() if aw_status else "Unknown state")
        status_color = status_colors.get(aw_status, "#9ca3af")
        activitywatch_summary_label = f"🖥️ ActivityWatch • {status_label}"
        message = aw_data.get("message", "ActivityWatch data is not available yet.")

        if aw_status in ("not_running", "error"):
            hint = "Start ActivityWatch and keep the watchers running."
        elif aw_status == "no_data":
            hint = "ActivityWatch is running but no events were captured for today yet."
        else:
            hint = "Dashboard will fill this section automatically when data arrives."

        activitywatch_html = f'''
            <div class="rounded-lg p-3" style="background: rgba(55,65,81,0.15); border: 1px solid rgba(156,163,175,0.25);">
                <div class="flex items-center justify-between mb-2">
                    <p class="text-sm font-semibold" style="color: {status_color}">📡 Status: {status_label}</p>
                </div>
                <p class="text-xs mb-2" style="color: #d1d5db">{message}</p>
                <p class="text-xs" style="color: #9ca3af">{hint}</p>
            </div>'''

    # === Pieces Workstream Activity Section ===
    pieces_html = ""
    pieces_summary_label = "🧩 Pieces"
    _pieces_d = data.get("pieces_activity", {})
    _pieces_digest_text, _pieces_digest_source = _derive_pieces_digest(_pieces_d)
    if isinstance(_pieces_d, dict) and _pieces_d.get("status") == "ok":
        _p_count = _pieces_d.get("count", 0)
        _p_digest = _pieces_digest_text
        _p_mb = _pieces_d.get("morning_brief")

        pieces_summary_label = f"🧩 Pieces • {_p_count} session{'s' if _p_count != 1 else ''} today"

        _parts = []

        # Morning Brief block (most prominent)
        if _p_mb and _p_mb.get("summary_md"):
            _mb_md = _p_mb["summary_md"]
            _tldr = ""
            if "## TL;DR" in _mb_md:
                _after = _mb_md.split("## TL;DR", 1)[1].strip()
                _tldr = _after.split("\n\n")[0].strip()
            elif "### " in _mb_md:
                _tldr = _truncate_sentence_safe(_mb_md.split("###")[0].strip(), max_len=400)
            _tldr_safe = html.escape(_tldr) if _tldr else ""
            if _tldr_safe:
                _parts.append(
                    f'<div class="rounded p-2.5 mb-3" style="background:rgba(6,95,70,0.12);border-left:2px solid rgba(110,231,183,0.5);">'
                    f'<p class="text-xs font-semibold mb-1" style="color:#6ee7b7">📋 Morning Brief</p>'
                    f'<p class="text-sm" style="color:#d1d5db;line-height:1.5;">{_tldr_safe}</p>'
                    f'</div>'
                )

        _parts.extend(
            _build_pieces_shared_parts(
                _pieces_d,
                _p_digest,
                _pieces_digest_source,
                body_color="#d1d5db",
                muted_color="#9ca3af",
            )
        )

        if _parts:
            pieces_html = (
                '<div class="rounded-lg p-3" style="background:rgba(88,28,135,0.1);border:1px solid rgba(196,181,253,0.18);">'
                + "".join(_parts)
                + "</div>"
            )

    pieces_card_html = ""
    if pieces_html:
        pieces_card_html = (
            '<details class="card"><summary class="cursor-pointer text-lg font-semibold" style="color:#c4b5fd">'
            + html.escape(pieces_summary_label)
            + '</summary><div class="mt-3">'
            + pieces_html
            + "</div></details>"
        )

    morning = data.get("morning", {})
    evening = data.get("evening", {})
    day_state_summary = data.get("day_state_summary", {}) if isinstance(data.get("day_state_summary", {}), dict) else {}

    def _summary_lines(key):
        rows = day_state_summary.get(key, []) if isinstance(day_state_summary.get(key, []), list) else []
        cleaned = [str(row).strip() for row in rows if str(row).strip()]
        if bool(data.get("diariumFresh", True)):
            cleaned = [line for line in cleaned if not _is_stale_diarium_fallback_line(line)]
        return cleaned[:3]

    def _render_day_state_block(title, emoji, lines, accent_color, bg_color):
        if not lines:
            return ""
        bullets = "".join(
            f'<li class="text-sm mb-1" style="color:#e5e7eb;line-height:1.5">{html.escape(line)}</li>'
            for line in lines[:3]
        )
        return (
            f'<div class="rounded-lg p-3 mb-2" style="background:{bg_color};border-left:3px solid {accent_color};">'
            f'<p class="text-xs font-semibold mb-2" style="color:{accent_color}">{emoji} {title}</p>'
            f'<ul style="margin:0;padding-left:1.1rem">{bullets}</ul>'
            '</div>'
        )

    morning_snapshot_html = _render_day_state_block(
        "Morning Snapshot",
        "🌅",
        _summary_lines("morning"),
        "#a7f3d0",
        "rgba(6,95,70,0.12)",
    )
    state_of_day_html = _render_day_state_block(
        "State of Day",
        "🧭",
        _summary_lines("day"),
        "#c4b5fd",
        "rgba(88,28,135,0.12)",
    )
    evening_arc_html = _render_day_state_block(
        "Evening Arc",
        "🌙",
        _summary_lines("evening"),
        "#f9a8d4",
        "rgba(131,24,67,0.12)",
    )

    def _render_section_mood_pill(tag_value, emoji, border_color, bg_color):
        tag = str(tag_value or "").strip()
        if not tag:
            return ""
        return (
            '<div style="margin: -0.25rem 0 0.75rem;">'
            f'<span class="optional-pill" style="display:inline-flex;align-items:center;gap:0.35rem;'
            f'padding:0.2rem 0.55rem;border-radius:999px;'
            f'border:1px solid {border_color};background:{bg_color};'
            f'color:#d1d5db;font-size:0.72rem;line-height:1.2;">'
            f'{emoji} {html.escape(tag.title())}'
            '</span></div>'
        )

    morning_mood_pill_html = _render_section_mood_pill(
        morning.get("mood_tag"),
        "🌤️",
        "rgba(167,243,208,0.45)",
        "rgba(6,95,70,0.22)",
    )
    evening_mood_pill_html = _render_section_mood_pill(
        evening.get("mood_tag"),
        "🌙",
        "rgba(196,181,253,0.45)",
        "rgba(88,28,135,0.22)",
    )

    # Morning card content — SPLIT: raw entries + AI insights
    morning_raw_html = ""  # Your actual Diarium entries
    morning_ai_html = ""   # AI analysis of those entries

    # Build raw morning entries
    def _render_grateful_as_list(text):
        """If text has numbered items, render as HTML ordered list. Otherwise plain text."""
        items = [i.strip() for i in re.split(r'\n\n(?=\d+\.)', text.strip()) if i.strip()]
        items = [re.sub(r'^\d+\.\s*', '', item) for item in items]
        if len(items) > 1:
            lis = ''.join(f'<li style="margin-bottom: 4px">{html.escape(item)}</li>' for item in items)
            return f'<ol style="padding-left: 1.2em; margin: 0; list-style: decimal; color: #e5e7eb; font-size: 0.875rem">{lis}</ol>'
        return f'<span>{html.escape(text)}</span>'

    if morning.get("grateful"):
        grateful_content = _render_grateful_as_list(morning.get("grateful", ""))
        morning_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(6,95,70,0.1); border-left: 3px solid #6ee7b7">
                <p class="text-xs mb-1" style="color: #6ee7b7">🙏 Grateful for</p>
                <div class="text-sm" style="color: #e5e7eb">{grateful_content}</div>
            </div>'''

    if morning.get("intent"):
        intent_emoji = _pick_content_emoji(morning.get("intent", ""))
        morning_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(88,28,135,0.1); border-left: 3px solid #c4b5fd">
                <p class="text-xs mb-1" style="color: #c4b5fd">🎯 Intent</p>
                <p class="text-sm" style="color: #e5e7eb">{intent_emoji} {morning.get("intent", "")}</p>
            </div>'''

    if morning.get("affirmation"):
        affirm_emoji = _pick_content_emoji(morning.get("affirmation", ""))
        morning_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(249,168,212,0.1); border-left: 3px solid #fbcfe8">
                <p class="text-xs mb-1" style="color: #fbcfe8">✨ Affirmation</p>
                <p class="text-sm" style="color: #e5e7eb">{affirm_emoji} {morning.get("affirmation", "")}</p>
            </div>'''

    if morning.get("body_check"):
        body_emoji = _pick_content_emoji(morning.get("body_check", ""))
        morning_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(167,243,208,0.08); border-left: 3px solid rgba(167,243,208,0.5)">
                <p class="text-xs mb-1" style="color: rgba(167,243,208,0.7)">🧘 Body check</p>
                <p class="text-sm" style="color: #e5e7eb">{body_emoji} {morning.get("body_check", "")}</p>
            </div>'''

    if morning.get("letting_go"):
        letting_emoji = _pick_content_emoji(morning.get("letting_go", ""))
        morning_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(196,181,253,0.08); border-left: 3px solid rgba(196,181,253,0.5)">
                <p class="text-xs mb-1" style="color: rgba(196,181,253,0.7)">🍃 Letting go</p>
                <p class="text-sm" style="color: #e5e7eb">{letting_emoji} {morning.get("letting_go", "")}</p>
            </div>'''

    # AI morning insights — only show emotional summary here (detailed insights go in Today's Guidance)
    # This matches embed-dashboard-in-notes.py lines 143-151
    _today_ai = get_ai_day(data.get("aiInsights", {}), get_effective_date())
    morning_api_entries = [e for e in _today_ai.get("entries", []) if e.get("source") == "morning"]
    if not bool(data.get("diariumFresh", True)):
        morning_api_entries = []
    if morning_api_entries:
        emotional_summary = morning_api_entries[0].get("emotional_summary", "")
        if emotional_summary:
            morning_ai_html = f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(88,28,135,0.08); border-left: 3px solid rgba(196,181,253,0.5)">
                <p class="text-xs mb-1" style="color: rgba(196,181,253,0.7)">🔮 Emotional tone</p>
                <p class="text-sm" style="color: #e5e7eb">{emotional_summary}</p>
            </div>'''

    # Build Pieces Morning Brief block for morning card
    _pieces_morning_brief_html = ""
    _pieces_mb2 = _pieces_d.get("morning_brief") if isinstance(_pieces_d, dict) else None
    if _pieces_mb2 and _pieces_mb2.get("summary_md"):
        _mb2_md = _pieces_mb2["summary_md"]
        _mb2_tldr = ""
        if "## TL;DR" in _mb2_md:
            _mb2_after = _mb2_md.split("## TL;DR", 1)[1].strip()
            _mb2_tldr = _mb2_after.split("\n\n")[0].strip()
        elif "### " in _mb2_md:
            _mb2_tldr = _truncate_sentence_safe(_mb2_md.split("###")[0].strip(), max_len=400)
        if _mb2_tldr:
            _pieces_morning_brief_html = (
                '<div class="rounded-lg p-3 mb-2" style="background:rgba(88,28,135,0.12);border-left:3px solid rgba(196,181,253,0.6);">'
                '<p class="text-xs font-semibold mb-1" style="color:#c4b5fd">📋 Morning Brief</p>'
                f'<p class="text-sm" style="color:#e5e7eb;line-height:1.5;">{html.escape(_mb2_tldr)}</p>'
                '</div>'
            )

    # Build final morning card with clear section headers
    morning_card_html = ""
    if morning_snapshot_html:
        morning_card_html += morning_snapshot_html
    if morning_raw_html:
        morning_card_html += f'''
            <p class="text-xs font-semibold mb-2" style="color: #9ca3af">📝 Your entries</p>
            {morning_raw_html}'''
    if _pieces_morning_brief_html:
        morning_card_html += _pieces_morning_brief_html
    if morning_ai_html:
        morning_card_html += f'''
            <div class="mt-3 pt-2" style="border-top: 1px solid rgba(167,243,208,0.1)">
            </div>
            {morning_ai_html}'''
    if not morning_card_html:
        morning_card_html = '<p class="text-sm" style="color: #6b7280">No morning data yet</p>'

    # Compact context bar (mood + weather + location + photos) — rendered in header
    context_meta_html = ""  # legacy: kept for template ref, now empty
    entry_meta = data.get("entryMeta", {}) if isinstance(data.get("entryMeta"), dict) else {}
    weather_meta = str(entry_meta.get("weather", "")).strip()
    location_meta = str(entry_meta.get("location", "")).strip()
    photo_count_meta = entry_meta.get("photo_count", 0)

    context_bar_parts = []

    # Mood pill — prefer live moodLog entries over Diarium tone, tag with data attr for JS updates
    _mood_pill_text = ""
    _mood_log_today = data.get("moodLog", {})
    _mood_log_entries = _sanitize_mood_entries_for_today(
        _mood_log_today.get("entries", []) if isinstance(_mood_log_today, dict) else [],
        now_dt=datetime.now(),
        allow_diarium_source=bool(data.get("diariumFresh", True)),
    )
    if _mood_log_entries:
        _last = _mood_log_entries[-1]
        _mood_pill_text = f'{html.escape(str(_last.get("mood","")))} {html.escape(str(_last.get("label","")))} '
    elif tone:
        _bar_emoji = tone_emojis.get(tone, "🤔")
        _mood_pill_text = f'{_bar_emoji} {tone.replace("_", " ").title()} '
    # Build pill with data-context-pill so JS can update it on tap
    _mood_pill_html = (
        f'<span data-context-pill="mood" style="display:inline-flex;align-items:center;gap:0.15rem;'
        f'padding:0.1rem 0.1rem;background:transparent;'
        f'border-radius:0.35rem;font-size:0.85rem;color:#d1d5db;white-space:nowrap;">'
        f'{_mood_pill_text or "🤔 mood"}</span>'
    )

    # Weather pill
    if weather_meta:
        context_bar_parts.append(f'🌡️ {html.escape(weather_meta)}')

    # Location pill — only named places, not raw coords
    if location_meta:
        import re as _re
        _is_raw_coords = bool(_re.match(r'^[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+$', location_meta.strip()))
        if not _is_raw_coords:
            context_bar_parts.append(f'📍 {html.escape(location_meta)}')

    # Photos pill
    if isinstance(photo_count_meta, int) and photo_count_meta > 0:
        noun = "photo" if photo_count_meta == 1 else "photos"
        context_bar_parts.append(f'📷 {photo_count_meta} {noun}')

    context_bar_html = ""
    _other_pills = ''.join(
        f'<span class="optional-pill" style="display:inline-flex;align-items:center;gap:0.15rem;'
        f'padding:0.2rem 0.5rem;background:rgba(255,255,255,0.04);'
        f'border-radius:0.4rem;font-size:0.85rem;color:#d1d5db;white-space:nowrap;">'
        f'{part}</span>'
        for part in context_bar_parts
    )
    # Mood pill always shown (even if no other context parts) — JS needs the target element
    context_bar_html = (
        '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin:0.4rem 0 0.75rem;'
        'padding:0.25rem 0;align-items:center;">'
        + _mood_pill_html + _other_pills +
        '</div>'
    )

    # Updates card (middle section between morning insights and evening)
    _raw_updates_text = str(evening.get("updates", "") or "")
    _raw_updates_dump_start = _dashboard_dump_start_index(_raw_updates_text)
    updates_text = _strip_updates_metadata(_raw_updates_text)
    _updates_dump_filtered = _raw_updates_dump_start is not None and _dashboard_dump_start_index(updates_text) is None
    if _is_effectively_empty_updates_text(updates_text):
        updates_text = ""
    updates_card_html = ""
    completed_updates_html = ""
    updates_freshness_line = "ℹ️ No updates logged yet."
    updates_freshness_level = "info"
    # Guard: if the Updates section contains a pasted journal/evening entry (prose, no bullets,
    # > 150 chars) skip rendering it — user pastes transcribed entries there due to Diarium
    # template constraints and it's not actual update items.
    _updates_has_bullets = bool(re.search(r'(?m)^[\-\*]|\[\s*[xX ]?\s*\]|\d+\.\s', updates_text or ""))
    _updates_is_prose = bool(updates_text) and len(updates_text) > 150 and not _updates_has_bullets
    if updates_text:
        updates_emoji = _pick_content_emoji(updates_text)
        updates_text_html = html.escape(updates_text).replace("\n", "<br>")
        if _updates_is_prose:
            if _updates_dump_filtered:
                updates_freshness_line = "⚠️ Dashboard dump detected in updates and stripped automatically."
                updates_freshness_level = "warn"
            else:
                updates_freshness_line = "🟡 Long updates prose condensed automatically."
                updates_freshness_level = "info"
            updates_preview = _truncate_sentence_safe(updates_text, max_len=260)
            updates_preview_html = html.escape(updates_preview).replace("\n", "<br>")
            updates_card_html = f'''
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #93c5fd">📝 Updates</h3>
        <div class="rounded-lg p-3" style="background: rgba(30,64,175,0.12); border-left: 3px solid #60a5fa">
            <p class="text-sm mb-2" style="color: #e5e7eb">{updates_emoji} {updates_preview_html}</p>
            <p class="text-xs" style="color: #93c5fd">Condensed for readability.</p>
        </div>
    </div>'''
        else:
            if _updates_dump_filtered:
                updates_freshness_line = "⚠️ Dashboard dump detected in updates and stripped automatically."
                updates_freshness_level = "warn"
            else:
                updates_freshness_line = "✅ Updates feed looks clean."
                updates_freshness_level = "ok"
            updates_card_html = f'''
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #93c5fd">📝 Updates</h3>
        <div class="rounded-lg p-3" style="background: rgba(30,64,175,0.12); border-left: 3px solid #60a5fa">
            <p class="text-sm" style="color: #e5e7eb">{updates_emoji} {updates_text_html}</p>
        </div>
    </div>'''

    # If updates text was a pasted prose journal entry, don't extract completed items from it —
    # the AI would have extracted fragments from the narrative, not real task completions.
    if _updates_is_prose:
        updates_completed_items = []
    else:
        updates_completed_items = _today_ai.get("updates_completed_today", [])
        if isinstance(updates_completed_items, list):
            updates_completed_items = [str(item).strip() for item in updates_completed_items if str(item).strip()]
        else:
            updates_completed_items = []

    # Avoid duplicate mindfulness completion in two places:
    # keep mindfulness status in the dedicated Mindfulness card, not in updates list.
    mindfulness_state = data.get("mindfulness", {}) if isinstance(data.get("mindfulness"), dict) else {}
    mindfulness_done = bool(mindfulness_state.get("done"))
    if mindfulness_done:
        def _is_mindfulness_item(text):
            ll = str(text or "").strip().lower()
            return any(token in ll for token in ("mindfulness", "mindful", "streaks"))

        updates_completed_items = [item for item in updates_completed_items if not _is_mindfulness_item(item)]

    # Filter out future-facing items — these are plans for tomorrow, not completions
    # Also drop garbage fragments: single words, very short strings, or items that look
    # like partial sentences extracted from prose (e.g. "Enough", "Nything")
    def _looks_like_real_item(text):
        t = str(text).strip()
        if len(t) < 8:
            return False  # too short to be a real task
        words = t.split()
        if len(words) < 2:
            return False  # single word = fragment
        if re.match(r'^[A-Z][a-z]{1,8}$', t):
            return False  # single capitalised word
        return True

    updates_completed_items = [
        item for item in updates_completed_items
        if "tomorrow" not in str(item).lower()
        and "next week" not in str(item).lower()
        and _looks_like_real_item(item)
    ]

    # Deduplicate completed items robustly:
    # - strip markdown wrappers
    # - drop short hash IDs often appended by task systems (e.g. [bf9cb2], "bf9cb2")
    # - normalise spacing/punctuation before comparing
    _BRACKET_ID_RE = re.compile(r"\[\s*[0-9a-f]{6,8}\s*\]", re.IGNORECASE)
    _TRAILING_ID_RE = re.compile(r"(?:\s+|^)[0-9a-f]{6,8}$", re.IGNORECASE)

    def _clean_completed_display(text):
        cleaned = str(text or "").replace("~~", "").strip()
        cleaned = _BRACKET_ID_RE.sub("", cleaned).strip()
        # Remove one or more trailing short IDs (some sources duplicate IDs in two forms)
        while cleaned:
            next_cleaned = _TRAILING_ID_RE.sub("", cleaned).strip()
            if next_cleaned == cleaned:
                break
            cleaned = next_cleaned
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—:;,.")
        return cleaned

    def _norm_completed(t):
        cleaned = _clean_completed_display(t)
        return re.sub(r"[^a-z0-9\s]", "", re.sub(r"\s+", " ", cleaned.lower())).strip()

    def _looks_like_test_noise(text):
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        compact = re.sub(r"[\s_\-]+", "", lowered)
        if "doesnotexist" in compact:
            return True
        if re.fullmatch(r"(?:test|dummy|placeholder)[a-z0-9]{4,}", compact):
            return True
        return False

    _seen_completed = set()
    _deduped_completed = []
    for _ci in updates_completed_items:
        _display = _clean_completed_display(_ci)
        if not _display:
            continue
        if _looks_like_test_noise(_display):
            continue
        _ck = _norm_completed(_display)
        if _ck and _ck not in _seen_completed:
            _seen_completed.add(_ck)
            _deduped_completed.append(_display)
    updates_completed_items = _deduped_completed

    if updates_completed_items:
        completed_rows = "".join(
            f'''<div class="flex items-start gap-2 text-sm">
                <span style="color: #6ee7b7">✅</span>
                <span style="color: #e5e7eb">{item}</span>
            </div>'''
            for item in updates_completed_items
        )
        completed_updates_html = f'''
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #6ee7b7">✅ Completed today (from updates)</h3>
        <div class="space-y-2">{completed_rows}</div>
    </div>'''

    if not updates_card_html and not updates_insights_html and not completed_updates_html:
        updates_card_html = '''
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #93c5fd">📝 Updates</h3>
        <p class="text-sm" style="color: #6b7280">No update notes logged yet today.</p>
    </div>'''

    # Evening card content — SPLIT: raw entries + AI insights
    evening_raw_html = ""  # Your actual Diarium entries
    evening_ai_html = ""   # AI analysis of those entries
    three_things = evening.get("three_things", [])
    tomorrow = evening.get("tomorrow", "")

    if three_things:
        if isinstance(three_things, list) and len(three_things) > 1:
            things_html = "".join(f'<div class="flex items-start gap-2 text-sm"><span style="color: #c4b5fd">{_pick_content_emoji(item)}</span><span style="color: #e5e7eb">{item}</span></div>' for item in three_things)
        else:
            things_text = three_things[0] if isinstance(three_things, list) and three_things else str(three_things)
            things_emoji = _pick_content_emoji(things_text)
            things_html = f'<p class="text-sm" style="color: #e5e7eb">{things_emoji} {things_text}</p>'
        evening_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(88,28,135,0.1); border-left: 3px solid #c4b5fd">
                <p class="text-xs mb-1" style="color: #c4b5fd">🌟 Three good things</p>
                {things_html}
            </div>'''

    if tomorrow:
        tomorrow_short = tomorrow  # No truncation — full-length display
        tomorrow_emoji = _pick_content_emoji(tomorrow_short)
        evening_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(131,24,67,0.1); border-left: 3px solid #f9a8d4">
                <p class="text-xs mb-1" style="color: #f9a8d4">🌅 Tomorrow</p>
                <p class="text-sm" style="color: #e5e7eb">{tomorrow_emoji} {tomorrow_short}</p>
            </div>'''

    # Carrying forward + energy from daemon cache only (no journal file parsing)
    carrying = data.get("evening", {}).get("carrying_forward", "") or data.get("aiInsights", {}).get("carrying_forward", "")
    energy = ""

    # Evening realities from ai_insights (mirrors morning intentions)
    # PRIORITIZE API-based "evening" over heuristic "daemon_evening"
    evening_entries = [e for e in _today_ai.get("entries", []) if e.get("source") == "evening"]
    if not evening_entries:  # Fallback to heuristic if no API insights yet
        evening_entries = [e for e in _today_ai.get("entries", []) if e.get("source") == "daemon_evening"]
    if evening_entries:
        evening_insights = evening_entries[0].get("insights", [])
        wins_list = [i for i in evening_insights if i.get("type") == "win"]
        connections_list = [i for i in evening_insights if i.get("type") == "connection"]
        signals_list = [i for i in evening_insights if i.get("type") == "signal"]

        # Show ALL insights grouped by type with headers in fixed order:
        # Patterns → Wins → Signals → Connections (then any remaining)
        type_config = {
            "pattern": ("🔁", "Patterns", "#c4b5fd", "rgba(196,181,253,0.08)"),
            "win": ("🏆", "Wins", "#6ee7b7", "rgba(6,95,70,0.1)"),
            "signal": ("⚡", "Signals", "#fbbf24", "rgba(251,191,36,0.08)"),
            "connection": ("🔗", "Connections", "#f9a8d4", "rgba(131,24,67,0.1)"),
        }
        # Group insights by type
        _eve_grouped = {}
        for insight in evening_insights:
            itype = insight.get("type", "win")
            if itype not in _eve_grouped:
                _eve_grouped[itype] = []
            _eve_grouped[itype].append(insight)

        # Render in fixed order
        _eve_type_order = ["pattern", "win", "signal", "connection"]
        _eve_ordered = [t for t in _eve_type_order if t in _eve_grouped]
        _eve_ordered.extend(t for t in _eve_grouped if t not in _eve_type_order)

        for itype in _eve_ordered:
            items = _eve_grouped[itype]
            icon, label, color, bg = type_config.get(itype, ("💡", itype.title(), "#9ca3af", "rgba(75,85,99,0.1)"))
            evening_ai_html += f'''
            <div class="rounded-lg p-4 mb-3" style="background: {bg}; border-left: 3px solid {color}">
                <p class="text-xs font-bold mb-3 uppercase tracking-wider" style="color: {color}; letter-spacing: 0.08em;">{icon} {label}</p>'''
            for idx, insight in enumerate(items):
                text = insight.get("text", "")
                # Break long insights into lead sentence + supporting detail
                emoji = _pick_insight_emoji(text)
                sentences = re.split(r'(?<=[.!?])\s+', text)
                wrapper_attrs = ' class="mt-3 pt-3" style="border-top: 1px solid rgba(75,85,99,0.15);"' if idx > 0 else ""
                if len(sentences) > 1 and len(text) > 120:
                    lead = sentences[0]
                    rest = ' '.join(sentences[1:])
                    evening_ai_html += f'''
                <div{wrapper_attrs}>
                    <p class="text-base font-medium mb-1" style="color: #f3f4f6; line-height: 1.7;">{emoji} {lead}</p>
                    <p class="text-sm ml-6" style="color: #9ca3af; line-height: 1.6;">{rest}</p>
                </div>'''
                else:
                    evening_ai_html += f'''
                <div{wrapper_attrs}>
                    <p class="text-base" style="color: #e5e7eb; line-height: 1.7;">{emoji} {text}</p>
                </div>'''
            evening_ai_html += '''
            </div>'''

    # Brave moment (from diarium brave/how_to_improve section) - raw entry
    brave_text = evening.get("brave", "")
    if brave_text:
        evening_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(6,95,70,0.1); border-left: 3px solid #34d399">
                <p class="text-xs mb-1" style="color: #34d399">💪 Brave moment</p>
                <p class="text-sm" style="color: #e5e7eb">{brave_text}</p>
            </div>'''

    # Evening reflections (from Diarium evening template)
    evening_reflections_text = _clean_evening_reflections_text(evening.get("evening_reflections", ""))
    if evening_reflections_text:
        evening_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(88,28,135,0.08); border-left: 3px solid rgba(196,181,253,0.5)">
                <p class="text-xs mb-1" style="color: rgba(196,181,253,0.7)">🌙 Evening reflections</p>
                <p class="text-sm" style="color: #e5e7eb">{html.escape(evening_reflections_text)}</p>
            </div>'''

    # Remember for tomorrow (from Diarium evening template)
    remember_tomorrow_text = evening.get("remember_tomorrow", "")
    if remember_tomorrow_text:
        remember_emoji = _pick_content_emoji(remember_tomorrow_text)
        evening_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(131,24,67,0.08); border-left: 3px solid rgba(249,168,212,0.5)">
                <p class="text-xs mb-1" style="color: rgba(249,168,212,0.7)">📌 Remember for tomorrow</p>
                <p class="text-sm" style="color: #e5e7eb">{remember_emoji} {remember_tomorrow_text}</p>
            </div>'''

    if carrying:
        carry_emoji = _pick_content_emoji(carrying)
        evening_raw_html += f'''
            <div class="rounded-lg p-3" style="background: rgba(120,53,15,0.1); border-left: 3px solid #fbbf24">
                <p class="text-xs mb-1" style="color: #fbbf24">📌 Carrying forward</p>
                <p class="text-sm" style="color: #e5e7eb">{carry_emoji} {carrying}</p>
            </div>'''

    # === Time-of-day awareness (used for evening section + tomorrow's guidance) ===
    current_hour = datetime.now().hour
    is_morning = current_hour < 12
    is_evening = current_hour >= 18  # Jim sets tomorrow plans in evening, not afternoon

    # Build unified "What you did today" — narrative paragraph from all sources + Pieces collapsible
    _pieces_day_html = ""
    _p_digest2 = _pieces_digest_text if isinstance(_pieces_d, dict) else ""
    _p_digest2_source = _pieces_digest_source if isinstance(_pieces_d, dict) else ""
    _p_summaries2 = _pieces_d.get("summaries", []) if isinstance(_pieces_d, dict) else []

    # Gather all data sources for narrative
    _tadah_cat_data = data.get("taDahCategorised", {})
    _tadah_total = _tadah_cat_data.get("total_items", len(tadah_flat)) if isinstance(_tadah_cat_data, dict) else len(tadah_flat)
    _tadah_themes = _tadah_cat_data.get("themes", {}) if isinstance(_tadah_cat_data, dict) else {}
    _latest_health = health_data[-1] if health_data else {}
    _health_age = data.get("healthDataAge", 0)
    _steps_val = int(_latest_health.get("steps", 0) or 0) if _health_age <= 1 else 0
    _ex_val = int(_latest_health.get("exercise", 0) or 0) if _health_age <= 1 else 0
    _wc = _today_ai.get("workout_checklist", {}) if isinstance(_today_ai, dict) else {}
    _sf = _wc.get("session_feedback", {}) if isinstance(_wc, dict) else {}
    _session_type = (_sf.get("session_type", "") or "").strip()
    _session_dur = _sf.get("duration_minutes")
    _body_feel = (_sf.get("body_feel", "") or "").strip()
    _p_count2 = _pieces_d.get("count", 0) if isinstance(_pieces_d, dict) else 0

    _effective_today_key = get_effective_date()

    def _narrative_contradiction_reason(raw_text):
        return narrative_contradiction_reason(
            raw_text,
            current_hour=current_hour,
            tadah_total=int(_tadah_total or 0),
            steps_val=int(_steps_val or 0),
            ex_val=int(_ex_val or 0),
            session_type=_session_type,
        )

    _narrative, _narrative_freshness = compose_day_narrative(
        today_ai=_today_ai,
        data=data,
        updates_text=updates_text,
        tadah_flat=tadah_flat,
        steps_val=int(_steps_val or 0),
        session_type=_session_type,
        session_dur=_session_dur,
        pieces_count=int(_p_count2 or 0),
        current_hour=current_hour,
        effective_today_key=_effective_today_key,
        iso_to_ts=_iso_to_ts,
        clock_hhmm=_clock_hhmm,
        truncate_sentence_safe=_truncate_sentence_safe,
        contradiction_reason_fn=_narrative_contradiction_reason,
        is_updates_verification_noise_text=_is_updates_verification_noise_text,
        looks_like_test_noise=_looks_like_test_noise,
    )

    # Standalone "What you did today" card — shown always (not gated by evening)
    _has_day_data = bool(_narrative or _p_digest2 or _p_summaries2)
    _pieces_day_html = ""
    if _has_day_data:
        if _narrative:
            # Split into paragraphs on blank lines or sentence-group boundaries
            _paras = split_day_narrative_paragraphs(_narrative)
            _narrative_html = (
                '<div id="qa-day-narrative-body">'
                + "".join(
                    f'<p style="color:#e5e7eb;font-size:0.9rem;line-height:1.75;margin-bottom:0.75rem;">'
                    f'{html.escape(p)}</p>'
                    for p in _paras
                )
                + '</div>'
            )
        else:
            _narrative_html = (
                '<div id="qa-day-narrative-body">'
                '<p style="color:#6b7280;font-size:0.85rem;">No activity data yet today.</p>'
                '</div>'
            )
        _pieces_day_html = (
            '<div class="card mb-4" style="border-left:4px solid #a78bfa;">'
            '<h3 class="text-lg font-semibold mb-3" style="color:#a78bfa">🗓️ What you did today</h3>'
            + _narrative_html
            + '</div>'
        )

    # Build final evening card with clear section headers
    # TIME-OF-DAY AWARENESS: keep evening entries hidden until evening close window
    # NOTE: _pieces_day_html is now its own standalone section — NOT inserted here
    evening_card_html = ""
    if not is_evening:
        if evening_arc_html:
            evening_card_html += evening_arc_html
        if not evening_card_html:
            evening_card_html = '<p class="text-sm" style="color: #6b7280">Evening entries appear after 18:00</p>'
    else:
        if evening_arc_html:
            evening_card_html += evening_arc_html
        if evening_raw_html:
            evening_card_html += f'''
                <p class="text-xs font-semibold mb-2" style="color: #9ca3af">📝 Your entries</p>
                {evening_raw_html}'''
        # Evening AI insights now go ONLY in unified "Today's Guidance" section
        if not evening_card_html:
            evening_card_html = '<p class="text-sm" style="color: #6b7280">No evening data yet</p>'

    effective_today = get_effective_date()
    # Strict daily reset: no automatic carry-forward widgets from yesterday.
    carry_forward_html = ""

        # Tomorrow's Guidance card
    # TIME-OF-DAY LOGIC (matches embed-dashboard-in-notes.py):
    # - Morning: Show yesterday's TOMORROW PLANS as "Yesterday's Plan for Today"
    # - Evening (after 18:00): Show Jim's TOMORROW PLANS from Diarium
    # - NEVER parrot daily_guidance as tomorrow's guidance (causes duplication)
    # - Jim sets tomorrow plans in the evening, so only flag after 18:00
    suggestions_html = ""
    jim_tomorrow = data.get("evening", {}).get("tomorrow", "")
    jim_remember = data.get("evening", {}).get("remember_tomorrow", "")
    try:
        _tomorrow_dt = datetime.strptime(effective_today, "%Y-%m-%d") + timedelta(days=1)
    except Exception:
        _tomorrow_dt = datetime.now() + timedelta(days=1)
    tomorrow_is_weekend = _tomorrow_dt.weekday() >= 5

    # AI insights context (needed for both tomorrow guidance and today's guidance)
    _ai_for_guidance = get_ai_day(data.get("aiInsights", {}), effective_today)
    _guidance_is_today = _ai_for_guidance.get("status") == "success"

    # Check for AI-generated tomorrow guidance first (from daemon's _generate_tomorrow_guidance)
    _ai_tomorrow = _ai_for_guidance.get("tomorrow_guidance", {}) if _guidance_is_today else {}
    _tomorrow_lines = _ai_tomorrow.get("lines", []) if _ai_tomorrow else []
    if not bool(data.get("diariumFresh", True)):
        _tomorrow_lines = []

    if is_evening:
        raw_tomorrow_sources = [jim_tomorrow, jim_remember]
        tomorrow_lines_for_display = []

        # Prefer AI guidance, but suppress lines that simply parrot raw journal wording.
        for item in _tomorrow_lines[:6]:
            t_text = str(item.get("text", "")).strip()
            if not t_text:
                continue
            if tomorrow_is_weekend and _looks_work_guidance_text(t_text):
                continue
            if (jim_tomorrow or jim_remember) and _parrot_overlap(t_text, raw_tomorrow_sources) >= 0.68:
                continue
            tomorrow_lines_for_display.append({
                "emoji": item.get("emoji", "💡"),
                "text": t_text,
            })

        # If AI guidance is absent/too parroted, reframe from journal context.
        if not tomorrow_lines_for_display and (jim_tomorrow or jim_remember):
            tomorrow_lines_for_display = _build_tomorrow_action_lines(
                jim_tomorrow,
                jim_remember,
                weekend_mode=tomorrow_is_weekend,
            )

        # If only one AI line survived, top up with reframed lines.
        if (jim_tomorrow or jim_remember) and len(tomorrow_lines_for_display) < 2:
            extras = _build_tomorrow_action_lines(
                jim_tomorrow,
                jim_remember,
                weekend_mode=tomorrow_is_weekend,
            )
            existing_texts = [str(i.get("text", "")) for i in tomorrow_lines_for_display]
            for extra in extras:
                if len(tomorrow_lines_for_display) >= 4:
                    break
                if _parrot_overlap(extra.get("text", ""), existing_texts) >= 0.7:
                    continue
                tomorrow_lines_for_display.append(extra)

        if tomorrow_lines_for_display:
            tomorrow_items_html = ""
            for item in tomorrow_lines_for_display[:5]:
                t_emoji = item.get("emoji", "💡")
                t_text = str(item.get("text", "")).strip()
                if not t_text:
                    continue
                tomorrow_items_html += f'''
                <div class="flex items-start gap-2 mb-3">
                    <span class="text-lg">{t_emoji}</span>
                    <p class="text-sm" style="color: #e5e7eb; line-height: 1.6">{t_text}</p>
                </div>'''

            if tomorrow_items_html:
                tomorrow_subnote = "Actionable plan rebuilt from tonight&apos;s notes."
                if tomorrow_is_weekend:
                    tomorrow_subnote = "Weekend mode active: recovery/family actions prioritised."
                suggestions_html = f'''
    <div class="card" style="border: 1px solid rgba(167,243,208,0.1)">
        <h3 class="text-sm font-semibold mb-2" style="color: rgba(167,243,208,0.6)">🌅 Tomorrow\'s Guidance</h3>
        <p class="text-xs mb-3" style="color: #6b7280">{tomorrow_subnote}</p>
        {tomorrow_items_html}
    </div>'''
    # === TODAY'S GUIDANCE (from daily_guidance.lines — actionable tips, shown in day+evening) ===
    todays_guidance_html = ""
    _daily_guidance_payload = _ai_for_guidance.get("daily_guidance", {}) if _guidance_is_today else {}
    _guidance_lines = _daily_guidance_payload.get("lines", []) if isinstance(_daily_guidance_payload, dict) else []
    _guidance_path = str(_daily_guidance_payload.get("path", "")).strip() if isinstance(_daily_guidance_payload, dict) else ""
    if not bool(data.get("diariumFresh", True)) and _guidance_path != "pieces_fallback":
        _guidance_lines = []
    if bool(data.get("diariumFresh", True)) and _guidance_path == "pieces_fallback":
        _guidance_lines = [
            line for line in _guidance_lines
            if not _is_stale_diarium_guidance_text(str(line.get("text", "")) if isinstance(line, dict) else str(line))
        ]

    if _guidance_lines or state_of_day_html:
        guidance_items_html = ""
        for item in _guidance_lines[:5]:
            g_emoji = item.get("emoji", "💡")
            g_text = item.get("text", "").strip()
            if is_evening and tomorrow_is_weekend and _looks_work_guidance_text(g_text):
                continue
            if g_text:
                guidance_items_html += f'''
                <div class="flex items-start gap-2 mb-3">
                    <span class="text-lg">{g_emoji}</span>
                    <p class="text-sm" style="color: #e5e7eb; line-height: 1.6">{g_text}</p>
                </div>'''
        if guidance_items_html or state_of_day_html:
            todays_guidance_html = f'''
    <div class="card" style="border: 1px solid rgba(196,181,253,0.15)">
        <h3 class="text-sm font-semibold mb-3" style="color: #c4b5fd">💡 Today\'s Guidance</h3>
        {state_of_day_html}
        {guidance_items_html}
    </div>'''

    state_vector_payload = {}
    state_vector_html = ""
    raw_cache_for_state = data.get("_raw_cache", {}) if isinstance(data.get("_raw_cache", {}), dict) else {}
    if raw_cache_for_state:
        try:
            state_vector_payload = build_daily_state_vector(
                raw_cache_for_state,
                today=effective_today,
                mood_slots={
                    "morning": str(morning.get("mood_tag", "")).strip(),
                    "evening": str(evening.get("mood_tag", "")).strip(),
                    "unscoped": str(morning.get("mood_tag", "") or evening.get("mood_tag", "")).strip(),
                },
                action_items=display_action_items,
                future_action_items=tomorrow_queue_items if isinstance(tomorrow_queue_items, list) else [],
                completed_action_items=completed_items if isinstance(completed_items, list) else [],
            )
        except Exception:
            state_vector_payload = {}
        state_vector_html = build_state_vector_html(state_vector_payload)
    if state_vector_payload:
        data["stateVector"] = state_vector_payload

    # Lean mode (default): reduce repeated suggestion surfaces to one ranked intervention card.
    feature_flags_payload = data.get("feature_flags", {}) if isinstance(data.get("feature_flags", {}), dict) else {}
    lean_mode_enabled = bool(feature_flags_payload.get("dashboard_lean_mode", True))
    if lean_mode_enabled:
        guidance_section_html = f"{state_vector_html}{intervention_html or todays_guidance_html or insights_fallback_html}"
        support_section_html = ""
    else:
        guidance_section_html = f"{todays_guidance_html}{insights_fallback_html}"
        support_section_html = f"{state_vector_html}{support_html}{intervention_html}"

    # === Ta-Dah Categorisation (theme breakdown) ===
    # Recompute themes from actual ta-dah items using dashboard's own categoriser
    # This ensures ALL categories appear (daemon's ta_dah_categorised can miss some)
    tadah_cat_html = ""
    ta_dah_cat = data.get("taDahCategorised", {})
    _recomputed_themes = {}
    if tadah_flat:
        for _item in tadah_flat:
            _cat = _get_category(_item)
            _recomputed_themes[_cat] = _recomputed_themes.get(_cat, 0) + 1
        # Remove "uncategorised" if it exists — only show meaningful categories
        _recomputed_themes.pop("uncategorised", None)
    if not _recomputed_themes and ta_dah_cat:
        _recomputed_themes = ta_dah_cat.get("themes", {})
    _theme_date_ok = (ta_dah_cat and ta_dah_cat.get("date") == get_effective_date()) or bool(tadah_flat)
    if _theme_date_ok and _recomputed_themes:
        theme_labels = {
            'family': '👨‍👩‍👧 Family', 'emotional_growth': '🌱 Growth', 'self_care': '🧘 Self-care',
            'work': '💼 Work', 'household': '🏠 Household', 'creative': '🎬 Creative',
            'social': '💬 Social', 'admin': '📋 Admin',
        }
        themes = _recomputed_themes
        total = sum(themes.values())
        theme_items_html = ""
        # Sort by count descending for visual clarity
        for theme, count in sorted(themes.items(), key=lambda x: -x[1]):
            label = theme_labels.get(theme, theme.title())
            pct = round(count / total * 100) if total > 0 else 0
            bar_color = {"family": "#f9a8d4", "emotional_growth": "#fbbf24", "self_care": "#6ee7b7", "work": "#c4b5fd", "household": "#86efac", "creative": "#f472b6", "social": "#e9d5ff", "admin": "#fdba74"}.get(theme, "#9ca3af")
            theme_items_html += f'''
                <div class="flex items-center gap-2 mb-2">
                    <span class="w-32 text-sm" style="color: #d1d5db">{label}</span>
                    <div class="flex-1 h-2 rounded-full overflow-hidden" style="background: #1f2937">
                        <div class="h-full rounded-full" style="width:{pct}%;background:{bar_color}"></div>
                    </div>
                    <span class="w-8 text-xs text-right" style="color: #9ca3af">{count}</span>
                </div>'''
        tadah_cat_html = f'''
    <div class="card">
        <h3 class="text-lg font-semibold mb-3" style="color: #6ee7b7">✅ Ta-Dah Themes ({total} items)</h3>
        {theme_items_html}
    </div>'''

    # === How Today Felt (conclusion synthesis) — date-gated to today only ===
    how_felt_html = ""
    _how_felt_ai_today = get_ai_day(data.get("aiInsights", {}), get_effective_date())
    _how_felt_is_today = _how_felt_ai_today.get("status") == "success"
    emotional_summary = _pick_primary_summary_for_how_felt(_how_felt_ai_today) if _how_felt_is_today else ""
    tone = data.get("diariumAnalysis", {}).get("emotional_tone", "") if _how_felt_is_today else ""
    felt_themes = _recomputed_themes if _recomputed_themes else (ta_dah_cat.get("themes", {}) if ta_dah_cat else {})
    felt_total = sum(felt_themes.values()) if felt_themes else (ta_dah_cat.get("total_items", 0) if ta_dah_cat else 0)

    # Get evening emotional summary for richer "How Today Felt" (date-gated)
    _how_felt_entries = _how_felt_ai_today.get("entries", []) if isinstance(_how_felt_ai_today.get("entries", []), list) else []
    eve_felt_entries = [
        e for e in _how_felt_entries
        if isinstance(e, dict) and e.get("source") in ("evening", "daemon_evening")
    ]
    eve_felt_summary = ""
    eve_felt_entry = None
    for entry in reversed(eve_felt_entries):
        summary = str(entry.get("emotional_summary", "")).strip()
        if summary and not _looks_like_weekly_digest_summary(summary) and not _is_tracker_metadata_leak_text(summary):
            eve_felt_summary = summary
            eve_felt_entry = entry
            break
    if eve_felt_entry is None and eve_felt_entries:
        eve_felt_entry = eve_felt_entries[-1]
    eve_felt_insights = eve_felt_entry.get("insights", []) if isinstance(eve_felt_entry, dict) else []
    eve_patterns = [
        i for i in eve_felt_insights
        if i.get("type") == "pattern"
        and not _is_tracker_metadata_leak_text(i.get("text", ""))
    ]
    eve_signals = [
        i for i in eve_felt_insights
        if i.get("type") == "signal"
        and not _is_stale_missing_reflection_signal(i.get("text", ""))
        and not _is_tracker_metadata_leak_text(i.get("text", ""))
    ]

    # Always show if we have ANY data
    if emotional_summary or tone or felt_themes or eve_felt_summary:
        felt_parts = ""

        # Evening emotional summary (rich prose — primary)
        if eve_felt_summary:
            felt_parts += f'''
            <p class="text-sm mb-3" style="color: #e5e7eb; line-height: 1.6">{eve_felt_summary}</p>'''

        # Latest overall summary (secondary)
        if emotional_summary and emotional_summary != eve_felt_summary:
            felt_parts += f'''
            <p class="text-sm mb-3" style="color: #d1d5db; line-height: 1.6">{emotional_summary}</p>'''

        # Key patterns from evening
        if eve_patterns:
            for p in eve_patterns:
                felt_parts += f'''
            <div class="flex items-start gap-2 mb-2">
                <span style="color: #c4b5fd">🔄</span>
                <p class="text-sm" style="color: #d1d5db">{p.get("text", "")}</p>
            </div>'''

        # Signals to watch
        if eve_signals:
            for s in eve_signals:
                felt_parts += f'''
            <div class="flex items-start gap-2 mb-2">
                <span style="color: #fbbf24">⚠️</span>
                <p class="text-sm" style="color: #d1d5db">{s.get("text", "")}</p>
            </div>'''

        if felt_themes and felt_total > 0:
            theme_labels_simple = {'family': 'family', 'self_care': 'self-care', 'work': 'work',
                                   'household': 'household', 'creative': 'creative'}
            top_theme = list(felt_themes.keys())[0]
            top_label = theme_labels_simple.get(top_theme, top_theme)
            felt_parts += f'''
            <p class="text-xs" style="color: #9ca3af">Day shaped by {top_label} ({felt_themes[top_theme]}/{felt_total} items)</p>'''

        if tone and tone != "neutral" and not emotional_summary and not eve_felt_summary:
            tone_emojis = {"anxious": "😰", "low_energy": "😔", "positive": "😊", "frustrated": "😤"}
            felt_parts += f'''
            <p class="text-sm" style="color: #d1d5db">{tone_emojis.get(tone, '🤔')} {tone.replace('_', ' ').title()}</p>'''

        how_felt_html = f'''
    <div class="card" style="border: 1px solid rgba(196,181,253,0.1)">
        <h3 class="text-lg font-semibold mb-3" style="color: #c4b5fd">💭 How Today Felt</h3>
        {felt_parts}
    </div>'''

    # Beads maintenance tasks (collapsed at bottom)
    backlog_html = ""
    try:
        import subprocess
        # Optional backlog section should never block dashboard generation.
        health_path = Path.home() / "Documents/Claude Projects/HEALTH"
        beads = _read_open_issues_from_jsonl(health_path, limit=200)
        if not beads:
            try:
                result = subprocess.run(
                    ["bd", "list", "--status=open", "--json"],
                    cwd=health_path,
                    capture_output=True,
                    text=True,
                    timeout=12,
                )
                if result.returncode == 0:
                    parsed = json.loads(result.stdout or "[]")
                    if isinstance(parsed, list):
                        beads = parsed
            except subprocess.TimeoutExpired:
                beads = []
            except Exception:
                beads = []

        if beads:
            # Group by priority
            p1_beads = [b for b in beads if b.get("priority") == 1]
            p2_beads = [b for b in beads if b.get("priority") == 2]
            p3_beads = [b for b in beads if b.get("priority") == 3]

            # Type icons
            type_icons = {"epic": "🎯", "task": "📋", "chore": "🔧", "feature": "✨", "bug": "🐛"}

            if p1_beads or p2_beads or p3_beads:
                beads_lines = []

                # P1 (High Priority)
                if p1_beads:
                    beads_lines.append('<p class="text-xs font-semibold mt-2 mb-1" style="color: #ef4444">🔥 Priority 1 (High)</p>')
                    for bead in p1_beads[:5]:
                        icon = type_icons.get(bead.get("issue_type", "task"), "📋")
                        beads_lines.append(f'<p class="text-xs py-1" style="color: #9ca3af; border-bottom: 1px solid rgba(75,85,99,0.2)">{icon} {bead["id"]}: {bead["title"]}</p>')

                # P2 (Medium Priority)
                if p2_beads:
                    beads_lines.append('<p class="text-xs font-semibold mt-3 mb-1" style="color: #fbbf24">📌 Priority 2 (Medium)</p>')
                    for bead in p2_beads[:5]:
                        icon = type_icons.get(bead.get("issue_type", "task"), "📋")
                        beads_lines.append(f'<p class="text-xs py-1" style="color: #9ca3af; border-bottom: 1px solid rgba(75,85,99,0.2)">{icon} {bead["id"]}: {bead["title"]}</p>')

                # P3 summary (don't list all)
                if p3_beads:
                    beads_lines.append(f'<p class="text-xs mt-3" style="color: #6b7280">💡 {len(p3_beads)} low-priority tasks in backlog</p>')

                total_count = len(p1_beads) + len(p2_beads) + len(p3_beads)
                backlog_html = f'''
    <details class="card" style="border: 1px solid rgba(75,85,99,0.15)">
        <summary class="cursor-pointer text-sm" style="color: #6b7280">🎯 Maintenance Tasks ({total_count} open)</summary>
        <div class="mt-3">
            {"".join(beads_lines)}
            <p class="text-xs mt-3" style="color: #4b5563">Run <code>bd ready</code> to see what's ready to work on</p>
        </div>
    </details>'''
    except Exception:
        # Keep this card optional and silent on failure.
        pass

    # Data source file paths for section header hyperlinks
    home = str(Path.home())
    journal_today = f"file://{home}/Documents/Claude Projects/claude-shared/journal/{get_effective_date()}.md"
    wins_file = f"file://{home}/Documents/Claude Projects/claude-shared/wins.md"
    streaks_dir = f"file://{home}/Library/CloudStorage/GoogleDrive-james.cherry01@gmail.com/My Drive/Streaks Backup"

    # Diarium image — used in header
    diarium_image_tag = ""
    diarium_images = data.get("diarium_images", [])
    if diarium_images:
        img = diarium_images[0]
        if isinstance(img, dict):
            file_url = ""
            remote_url = ""

            img_path = str(img.get("path", "")).strip()
            if img_path:
                file_url = f"file://{img_path}"

            img_filename = str(img.get("filename", "")).strip()
            if img_filename:
                remote_url = f"/assets/diarium/{url_quote(img_filename)}"

            if file_url or remote_url:
                diarium_image_tag = (
                    f'<img id="diarium-header-image" src="" '
                    f'data-file-src="{html.escape(file_url, quote=True)}" '
                    f'data-remote-src="{html.escape(remote_url, quote=True)}" '
                    'alt="Today" class="rounded-2xl object-cover flex-shrink-0" '
                    'style="width: 100px; height: 100px; border: 2px solid rgba(249,168,212,0.3);" '
                    'onerror="this.style.display=\'none\'"/>'
                )

    system_status_html = ""
    system_needs_attention = False
    runtime = data.get("runtimeStatus", {}) if isinstance(data.get("runtimeStatus", {}), dict) else {}
    system_view = build_system_status_html(runtime)
    system_status_html = str(system_view.get("html", "") or "")
    system_needs_attention = bool(system_view.get("needs_attention"))
    _cache_age_live = system_view.get("cache_age_minutes")
    _cache_state = compute_cache_freshness(_cache_age_live)
    cache_fresh_line = str(_cache_state.get("line", "") or "ℹ️ Cache age unknown.")
    cache_fresh_level = str(_cache_state.get("level", "") or "info")

    _source_date_live = str(data.get("diariumDataDate", "") or "").strip()
    _diarium_is_fresh = bool(data.get("diariumFresh", True))
    _diarium_state = compute_diarium_freshness(_diarium_is_fresh, _source_date_live, effective_today)
    diarium_fresh_line = str(_diarium_state.get("line", "") or "ℹ️ Journal freshness unknown.")
    diarium_fresh_level = str(_diarium_state.get("level", "") or "info")

    _diarium_pickup_state = compute_diarium_pickup_freshness(data.get("diariumPickupStatus", {}), _clock_hhmm)
    diarium_pickup_line = str(_diarium_pickup_state.get("line", "") or "📓 Pickup status unavailable.")
    diarium_pickup_level = str(_diarium_pickup_state.get("level", "") or "info")

    narrative_fresh_line = str(_narrative_freshness.get("line", "") or "ℹ️ Narrative freshness unknown.")
    narrative_fresh_level = str(_narrative_freshness.get("level", "info") or "info").lower()
    if narrative_fresh_level not in {"ok", "info", "warn", "error"}:
        narrative_fresh_level = "info"

    _mood_state = compute_mood_freshness(
        morning,
        evening,
        mood_entries,
        current_hour=current_hour,
        diarium_fresh=bool(data.get("diariumFresh", True)),
    )
    mood_fresh_line = str(_mood_state.get("line", "") or "ℹ️ Mood freshness unknown.")
    mood_fresh_level = str(_mood_state.get("level", "") or "info")

    ai_path_status = resolve_ai_path_status(data, _clock_hhmm)
    ai_path_line = str(ai_path_status.get("line", "") or "ℹ️ AI path telemetry unavailable.")
    ai_path_level = str(ai_path_status.get("level", "") or "info")

    freshness_overview = compute_freshness_overview(
        diarium_fresh_level=diarium_fresh_level,
        diarium_pickup_level=diarium_pickup_level,
        narrative_fresh_level=narrative_fresh_level,
        updates_freshness_level=updates_freshness_level,
        mood_fresh_level=mood_fresh_level,
        cache_fresh_level=cache_fresh_level,
    )
    updates_fresh_level = freshness_overview["updates_fresh_level"]
    freshness_overall_line = freshness_overview["overall_line"]
    freshness_overall_level = freshness_overview["overall_level"]
    freshness_watch_html = build_freshness_watch_html(
        ai_path_line=ai_path_line,
        ai_path_level=ai_path_level,
        freshness_overall_line=freshness_overall_line,
        freshness_overall_level=freshness_overall_level,
        auto_open=bool(freshness_overview.get("auto_open")),
        diarium_fresh_level=diarium_fresh_level,
        diarium_fresh_line=diarium_fresh_line,
        diarium_pickup_level=diarium_pickup_level,
        diarium_pickup_line=diarium_pickup_line,
        narrative_fresh_level=narrative_fresh_level,
        narrative_fresh_line=narrative_fresh_line,
        updates_fresh_level=updates_fresh_level,
        updates_freshness_line=updates_freshness_line,
        mood_fresh_level=mood_fresh_level,
        mood_fresh_line=mood_fresh_line,
        cache_fresh_level=cache_fresh_level,
        cache_fresh_line=cache_fresh_line,
    )

    stale_notice_html = build_stale_notice_html(
        diarium_fresh=_diarium_is_fresh,
        source_date=data.get("diariumDataDate"),
        reason=data.get("diariumFreshReason"),
    )
    important_thing_warning_html = build_important_thing_warning_html(
        diarium_fresh=_diarium_is_fresh,
        important_thing_missing=bool(data.get("importantThingMissing", False)),
    )

    ideas_status_html = ""
    ideas_payload = data.get("appleNotesIdeas", {}) if isinstance(data.get("appleNotesIdeas", {}), dict) else {}
    if ideas_payload:
        ideas_status_html = build_ideas_status_html(ideas_payload, _clock_hhmm)
    dashboard_action_state = load_dashboard_action_state(effective_today)
    action_items_updated_at = str(dashboard_action_state.get("updated_at", "")).strip()
    action_items_stale_reason = ""
    if action_items_updated_at and not action_items_updated_at.startswith(effective_today):
        action_items_stale_reason = "Dashboard action queue has not been regenerated for today's date."
    weekly_digest_payload = data.get("weeklyDigest", {}) if isinstance(data.get("weeklyDigest", {}), dict) else {}
    weekly_current_path = str(weekly_digest_payload.get("current_path", "")).strip()
    weekly_current_file = Path(weekly_current_path) if weekly_current_path else None
    morning_note_for_freshness = "\n".join(
        part for part in (
            str(morning.get("grateful", "")).strip(),
            str(morning.get("intent", "")).strip(),
            str(morning.get("affirmation", "")).strip(),
            str(morning.get("body_check", "")).strip(),
            str(morning.get("letting_go", "")).strip(),
        )
        if part
    )
    section_freshness_registry = data.get("sectionFreshness", {}) if isinstance(data.get("sectionFreshness", {}), dict) else {}
    if not section_freshness_registry:
        section_freshness_registry = build_today_section_freshness_registry(
            {
                "film_data": data.get("film_data", {}),
                "pieces_activity": data.get("pieces_activity", {}),
                "calendar": data.get("calendarStatus", {}),
                "job_boards": data.get("jobBoards", {}),
                "linkedin_jobs": data.get("linkedinJobs", {}),
                "applications": data.get("applications", {}),
                "healthfit": data.get("healthfit", {}),
                "streaks": data.get("streaks", {}),
                "apple_health": data.get("appleHealth", {}),
                "autosleep": data.get("autosleep", {}),
            },
            today=effective_today,
            cache_timestamp=str(data.get("cacheTimestamp", "")).strip(),
            diarium_fresh=_diarium_is_fresh,
            diarium_source_date=_source_date_live,
            diarium_fresh_reason=str(data.get("diariumFreshReason", "")).strip(),
            morning_note=morning_note_for_freshness,
            evening_note=str(evening.get("evening_reflections", "")).strip(),
            diary_updates=str(evening.get("updates", "")).strip(),
            guidance_lines=_guidance_lines,
            action_items=display_action_items,
            future_action_items=tomorrow_queue_items if isinstance(tomorrow_queue_items, list) else [],
            action_items_updated_at=action_items_updated_at,
            action_items_stale_reason=action_items_stale_reason,
            ideas_payload=ideas_payload,
            mood_entries=mood_entries,
            mood_state=_mood_state,
            updates_state={"line": updates_freshness_line, "level": updates_fresh_level},
            cache_state=_cache_state,
            narrative_state=_narrative_freshness,
            weekly_current_file=weekly_current_file,
            now=datetime.now(),
        )
        data["sectionFreshness"] = section_freshness_registry
    section_freshness_html = build_section_freshness_html(section_freshness_registry, _clock_hhmm)
    backend_status_pills_html = build_backend_status_pills_html(
        ai_path_line=ai_path_line,
        ai_path_level=ai_path_level,
        freshness_overall_line=freshness_overall_line,
        freshness_overall_level=freshness_overall_level,
        ideas_payload=ideas_payload,
        section_registry=section_freshness_registry,
        clock_hhmm=_clock_hhmm,
    )
    ideas_counts = ideas_payload.get("counts", {}) if isinstance(ideas_payload.get("counts", {}), dict) else {}
    try:
        ideas_new_count = int(ideas_counts.get("new_items", ideas_payload.get("new_items_count", 0)))
    except Exception:
        ideas_new_count = 0
    try:
        ideas_created_count = int(ideas_counts.get("beads_created", 0))
    except Exception:
        ideas_created_count = 0
    try:
        ideas_failed_count = int(ideas_counts.get("beads_failed", 0))
    except Exception:
        ideas_failed_count = 0
    try:
        ideas_retried_count = int(ideas_counts.get("retried", 0))
    except Exception:
        ideas_retried_count = 0
    try:
        ideas_retry_queue_count = int(ideas_payload.get("retry_queue_count", 0))
    except Exception:
        ideas_retry_queue_count = 0
    ideas_status_value = str(ideas_payload.get("status", "") or "").strip().lower()
    section_attention_count = int(section_freshness_registry.get("attention_count", 0) or 0)
    show_freshness_watch_card = str(freshness_overall_level or "").strip().lower() in {"warn", "error"}
    show_ideas_status_card = bool(ideas_status_html) and (
        ideas_status_value not in {"success", "ok"}
        or ideas_new_count > 0
        or ideas_created_count > 0
        or ideas_failed_count > 0
        or ideas_retried_count > 0
        or ideas_retry_queue_count > 0
    )
    show_section_freshness_card = bool(section_freshness_html) and section_attention_count > 0
    status_static_card_count = int(bool(important_thing_warning_html)) + int(bool(stale_notice_html))
    status_cards_visible = (
        status_static_card_count > 0
        or show_freshness_watch_card
        or show_ideas_status_card
        or show_section_freshness_card
    )
    freshness_watch_hidden_attr = "" if show_freshness_watch_card else ' hidden="hidden"'
    ideas_status_hidden_attr = "" if show_ideas_status_card else ' hidden="hidden"'
    section_freshness_hidden_attr = "" if show_section_freshness_card else ' hidden="hidden"'
    status_cards_section_hidden_attr = "" if status_cards_visible else ' hidden="hidden"'

    # Action controls (writes through local API) — rendered inside Action Points.
    # Read API token for bearer auth (iPhone iCloud file:// access)
    _api_token_path = Path.home() / ".claude" / "config" / "api-token.txt"
    try:
        qa_api_token = _api_token_path.read_text().strip()
    except Exception:
        qa_api_token = ""

    # Compute Mac's LAN IP so iPhone on same WiFi can reach the API server
    def _get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    qa_local_ip = _get_local_ip()
    _qa_remote = data.get("remoteAccess", {}) if isinstance(data.get("remoteAccess"), dict) else {}
    qa_cf_url = str(_qa_remote.get("cloudflare_url", "") or _qa_remote.get("tailscale_url", "")).strip()

    qa_today = get_effective_date()
    qa_ai = data.get("aiInsights", {}) if isinstance(data.get("aiInsights", {}), dict) else {}
    qa_today_day = get_ai_day(qa_ai, qa_today)
    qa_mindfulness = data.get("mindfulness", {}) if isinstance(data.get("mindfulness"), dict) else {}
    qa_mindfulness_target_raw = qa_mindfulness.get("minutes_target", 20)
    try:
        qa_mindfulness_target = int(qa_mindfulness_target_raw)
    except Exception:
        qa_mindfulness_target = 20
    if qa_mindfulness_target <= 0:
        qa_mindfulness_target = 20
    qa_mindfulness_done = bool(qa_mindfulness.get("done"))
    qa_mindfulness_minutes_done_raw = qa_mindfulness.get("minutes_done", qa_mindfulness_target if qa_mindfulness_done else 0)
    try:
        qa_mindfulness_minutes_done = int(qa_mindfulness_minutes_done_raw)
    except Exception:
        qa_mindfulness_minutes_done = qa_mindfulness_target if qa_mindfulness_done else 0
    qa_mindfulness_state = {
        "done": qa_mindfulness_done,
        "manual_done": qa_mindfulness.get("manual_done"),
        "auto_done": bool(qa_mindfulness.get("auto_done")),
        "auto_source": qa_mindfulness.get("auto_source", ""),
        "source": qa_mindfulness.get("source", ""),
        "habit": qa_mindfulness.get("habit", ""),
        "minutes_target": qa_mindfulness_target,
        "minutes_done": qa_mindfulness_minutes_done,
        "progression": qa_mindfulness.get("progression", {}),
    }
    qa_mood = data.get("moodTracking", {}) if isinstance(data.get("moodTracking"), dict) else {}
    qa_mood_state = {
        "done": bool(qa_mood.get("done_today")),
        "streaks_done_today": bool(qa_mood.get("streaks_done_today")),
        "manual_done_today": bool(qa_mood.get("manual_done_today")),
        "source": str(qa_mood.get("source", "")).strip(),
        "manual_source": str(qa_mood.get("manual_source", "")).strip(),
        "habit": str(qa_mood.get("habit", "")).strip(),
        "latest_completed": str(qa_mood.get("latest_completed", "")).strip(),
        "updated_at": str(qa_mood.get("updated_at", "")).strip(),
    }
    qa_workout_checklist = data.get("workoutChecklist", {}) if isinstance(data.get("workoutChecklist"), dict) else {}
    qa_workout_post = qa_workout_checklist.get("post_workout", {}) if isinstance(qa_workout_checklist.get("post_workout"), dict) else {}
    qa_workout_feedback = qa_workout_checklist.get("session_feedback", {}) if isinstance(qa_workout_checklist.get("session_feedback"), dict) else {}

    qa_workout_checklist_state = {
        "recovery_gate": str(qa_workout_checklist.get("recovery_gate", "unknown")).strip().lower(),
        "calf_done": bool(qa_workout_checklist.get("calf_done", False)),
        "post_workout": {
            "rpe": coerce_optional_int(qa_workout_post.get("rpe"), 1, 10),
            "pain": coerce_optional_int(qa_workout_post.get("pain"), 0, 10),
            "energy_after": coerce_optional_int(qa_workout_post.get("energy_after"), 1, 10),
        },
        "session_feedback": {
            "duration_minutes": coerce_optional_int(qa_workout_feedback.get("duration_minutes"), 5, 240),
            "intensity": str(qa_workout_feedback.get("intensity", "")).strip().lower(),
            "session_type": str(qa_workout_feedback.get("session_type", "")).strip().lower(),
            "body_feel": str(qa_workout_feedback.get("body_feel", "")).strip().lower(),
            "session_note": str(qa_workout_feedback.get("session_note", "")).strip()[:280],
            "anxiety_reduction_score": coerce_optional_int(qa_workout_feedback.get("anxiety_reduction_score"), 0, 10),
        },
    }
    if qa_workout_checklist_state["recovery_gate"] not in {"pass", "fail", "unknown"}:
        qa_workout_checklist_state["recovery_gate"] = "unknown"
    qa_workout_signals_raw = data.get("workoutChecklistSignals", {}) if isinstance(data.get("workoutChecklistSignals"), dict) else {}
    qa_workout_signals_state = {
        "healthfit_export_today": bool(qa_workout_signals_raw.get("healthfit_export_today")),
        "streaks_export_today": bool(qa_workout_signals_raw.get("streaks_export_today")),
        "anxiety_saved_today": bool(qa_workout_signals_raw.get("anxiety_saved_today")),
        "reflection_saved_today": bool(qa_workout_signals_raw.get("reflection_saved_today")),
        "recovery_signal": str(qa_workout_signals_raw.get("recovery_signal", "unknown")).strip().lower(),
        "recovery_signal_detail": str(qa_workout_signals_raw.get("recovery_signal_detail", "")).strip(),
    }
    if qa_workout_signals_state["recovery_signal"] not in {"pass", "fail", "caution", "unknown"}:
        qa_workout_signals_state["recovery_signal"] = "unknown"
    qa_workout_progression_state = data.get("workoutProgression", {}) if isinstance(data.get("workoutProgression"), dict) else {}
    qa_workout_progression_weights_state = data.get("workoutProgressionWeights", {}) if isinstance(data.get("workoutProgressionWeights"), dict) else {}
    qa_end_day_raw = qa_today_day.get("end_day", {}) if isinstance(qa_today_day.get("end_day", {}), dict) else {}
    qa_end_day_date = str(qa_end_day_raw.get("date", "")).strip()
    qa_end_day_ran_at = str(qa_end_day_raw.get("ran_at", "")).strip()
    qa_end_day_source = str(qa_end_day_raw.get("source", "")).strip()
    qa_end_day_state = {
        "done_today": bool(qa_end_day_date and qa_end_day_date == qa_today),
        "date": qa_end_day_date,
        "ran_at": qa_end_day_ran_at,
        "source": qa_end_day_source,
    }

    qa_end_day_done_today = bool(qa_end_day_state.get("done_today"))
    qa_end_day_status_text = end_day_status_text(qa_end_day_state)
    qa_end_day_status_color = "#6ee7b7" if qa_end_day_done_today else "#94a3b8"
    qa_today_score_raw = qa_today_day.get("anxiety_reduction_score") if isinstance(qa_today_day, dict) else None
    qa_slider_value = int(round(float(qa_today_score_raw))) if isinstance(qa_today_score_raw, (int, float)) else 5
    qa_points, qa_week_avg = _anxiety_week_points(qa_ai, qa_today, days=7)
    qa_spark = _anxiety_sparkline(qa_points)
    qa_history_items = []
    for day_key, score in qa_points:
        if score is None:
            continue
        try:
            day_label = datetime.strptime(day_key, "%Y-%m-%d").strftime("%a")
        except Exception:
            day_label = day_key
        qa_history_items.append(f"{day_label} {score:g}")

    if qa_week_avg is not None:
        qa_week_summary_html = f'''
            <div class="mt-2 rounded px-2 py-2" style="background: rgba(30,41,59,0.45); border: 1px solid rgba(251,191,36,0.15);">
                <p class="text-xs" style="color: #fcd34d">📊 This week avg: <span class="font-semibold">{qa_week_avg:g} / 10</span></p>
                <p class="text-xs mt-1" style="color: #9ca3af">Trend: <span style="letter-spacing: 1px">{qa_spark}</span></p>
                <p class="text-xs mt-1" style="color: #6b7280">{' • '.join(qa_history_items) if qa_history_items else 'No scored days yet.'}</p>
            </div>
        '''
    else:
        qa_week_summary_html = '''
            <div class="mt-2 rounded px-2 py-2" style="background: rgba(30,41,59,0.45); border: 1px solid rgba(251,191,36,0.12);">
                <p class="text-xs" style="color: #9ca3af">📊 This week avg: — / 10</p>
                <p class="text-xs mt-1" style="color: #6b7280">Add a score to start the weekly trend.</p>
            </div>
        '''

    qa_todo_options = []
    qa_todo_seen = set()
    qa_todo_keys = set()
    for raw_todo in display_action_items if isinstance(display_action_items, list) else []:
        if isinstance(raw_todo, dict) and raw_todo.get("done"):
            continue
        task_text = str(raw_todo.get("task", "")).strip() if isinstance(raw_todo, dict) else str(raw_todo).strip()
        if not task_text:
            continue
        task_key = _task_match_key(task_text)
        if not task_key:
            continue
        if task_key in qa_todo_seen:
            continue
        qa_todo_seen.add(task_key)
        qa_todo_keys.add(task_key)
        qa_todo_options.append(task_text)

    qa_loop_options = []
    qa_loop_seen = set()
    qa_loop_hidden_by_actions = 0
    for raw_loop in open_loop_items if isinstance(open_loop_items, list) else []:
        loop_text = str(raw_loop).strip()
        if not loop_text:
            continue
        loop_key = _task_match_key(loop_text)
        if loop_key in qa_loop_seen:
            continue
        if loop_key in qa_todo_keys:
            qa_loop_hidden_by_actions += 1
            continue
        qa_loop_seen.add(loop_key)
        qa_loop_options.append(loop_text)

    qa_loop_rows_html = ""
    if qa_loop_options:
        for loop_text in qa_loop_options[:10]:
            loop_emoji = _pick_content_emoji(loop_text)
            loop_compact = _compact_task_text(loop_text, max_len=120)
            qa_loop_rows_html += f'''
            <div class="rounded-lg px-3 py-2.5 mb-2 flex items-start gap-2" data-qa-row="loop" style="background: rgba(120,53,15,0.28); border: 1px solid rgba(251,191,36,0.25);">
                <span class="text-sm" style="line-height: 1.4;">{loop_emoji}</span>
                <span class="text-sm font-medium flex-1" title="{html.escape(loop_text, quote=True)}" style="color: #fde68a; line-height: 1.45;">{html.escape(loop_compact)}</span>
                <button onclick="qaCompleteLoopFromButton(this)" data-text="{html.escape(loop_text, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(6,95,70,0.35); color: #6ee7b7; border: 1px solid rgba(110,231,183,0.35);">Close</button>
            </div>'''
    else:
        qa_loop_rows_html = '<p class="text-sm" style="color: #9ca3af">No extra open loops right now.</p>'

    qa_loop_hidden_note_html = ""
    if qa_loop_hidden_by_actions:
        qa_loop_hidden_note_html = f'<p class="text-xs mt-1" style="color: #94a3b8">{qa_loop_hidden_by_actions} loop(s) already shown above as action items.</p>'

    qa_counts_html = f'''
        <div class="flex flex-wrap gap-2 mb-3">
            <span class="optional-pill rounded px-2 py-1 text-xs" style="background: rgba(131,24,67,0.28); color: #fbcfe8; border: 1px solid rgba(249,168,212,0.25);">Action items: {len(qa_todo_options)}</span>
            <span class="optional-pill rounded px-2 py-1 text-xs" style="background: rgba(120,53,15,0.28); color: #fde68a; border: 1px solid rgba(251,191,36,0.25);">Open loops: {len(qa_loop_options)}</span>
        </div>
    '''

    qa_one_thing_html = ""
    if qa_todo_options:
        one_text = one_thing_candidates[0] if one_thing_candidates else qa_todo_options[0]
        one_hash = _task_completion_hash(one_text)
        one_emoji = _pick_content_emoji(one_text)
        one_compact = _compact_task_text(one_text, max_len=155)
        qa_one_thing_html = f'''
        <div data-qa-one-thing="1" class="rounded-lg px-3 py-3 mb-3" style="background: rgba(6,95,70,0.2); border: 1px solid rgba(110,231,183,0.26);">
            <p class="text-xs font-semibold mb-1" style="color: #a7f3d0">🎯 One Thing Now</p>
            <p data-qa-one-thing-text="1" class="text-sm mb-2" title="{html.escape(one_text, quote=True)}" style="color: #d1fae5; line-height: 1.45;">{one_emoji} {html.escape(one_compact)}</p>
            <div data-qa-one-thing-actions="1" class="flex flex-wrap items-center gap-2">
                <button data-qa-one-thing-start="1" onclick="qaStartOneThing(this)" data-text="{html.escape(one_text, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(30,64,175,0.32); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">Start</button>
                <button data-qa-one-thing-done="1" onclick="qaCompleteTodoFromButton(this)" data-text="{html.escape(one_text, quote=True)}" data-task-hash="{html.escape(one_hash, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(131,24,67,0.35); color: #fbcfe8; border: 1px solid rgba(249,168,212,0.35);">☐ Done</button>
                <button data-qa-one-thing-defer="1" onclick="qaDeferTodoFromButton(this)" data-text="{html.escape(one_text, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(30,58,138,0.35); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">⏭️ Defer</button>
            </div>
        </div>
        '''

    def _qa_missing_yoga_feedback(checklist_state, anxiety_score):
        state = checklist_state if isinstance(checklist_state, dict) else {}
        feedback = state.get("session_feedback", {}) if isinstance(state.get("session_feedback"), dict) else {}
        missing = []
        if coerce_optional_int(feedback.get("duration_minutes"), 5, 240) is None:
            missing.append("duration")
        if str(feedback.get("intensity", "")).strip().lower() not in {"easy", "moderate", "hard"}:
            missing.append("intensity")
        if str(feedback.get("session_type", "")).strip().lower() not in {"somatic", "yin", "flow", "mobility", "restorative", "other"}:
            missing.append("type")
        if str(feedback.get("body_feel", "")).strip().lower() not in {"relaxed", "neutral", "tight", "sore", "energised", "fatigued"}:
            missing.append("body feel")
        score = _to_float(anxiety_score)
        if score is None:
            missing.append("anxiety")
        return missing

    def _qa_missing_weights_feedback(checklist_state, recovery_signal="unknown"):
        state = checklist_state if isinstance(checklist_state, dict) else {}
        post = state.get("post_workout", {}) if isinstance(state.get("post_workout"), dict) else {}
        missing = []
        recovery = str(state.get("recovery_gate", "")).strip().lower()
        signal = str(recovery_signal or "").strip().lower()
        recovery_required = signal in {"pass", "fail", "caution"}
        if recovery_required and recovery not in {"pass", "fail"}:
            missing.append("recovery gate")
        if coerce_optional_int(post.get("rpe"), 1, 10) is None:
            missing.append("RPE")
        if coerce_optional_int(post.get("pain"), 0, 10) is None:
            missing.append("pain")
        if coerce_optional_int(post.get("energy_after"), 1, 10) is None:
            missing.append("energy")
        return missing

    qa_quick_mood = mood_tracking if isinstance(mood_tracking, dict) else {}
    qa_quick_mood_done = bool(qa_quick_mood.get("done_today"))
    qa_quick_mood_habit = str(qa_quick_mood.get("habit", "")).strip() or "Mood check-in"
    qa_quick_workout = workout if isinstance(workout, dict) else get_todays_workout()
    qa_quick_workout_trackable = qa_quick_workout.get("type") in {"weights", "yoga"}
    qa_quick_workout_done = bool(qa_quick_workout.get("done")) if qa_quick_workout_trackable else False
    qa_quick_workout_title = str(qa_quick_workout.get("title", "Workout")).strip() or "Workout"
    qa_quick_workout_type = str(qa_quick_workout.get("type", "")).strip().lower()
    qa_prompt_title = ""
    qa_prompt_hint = ""
    qa_prompt_missing_fields = []
    if qa_quick_workout_done and qa_quick_workout_type == "yoga":
        qa_prompt_missing_fields = _qa_missing_yoga_feedback(qa_workout_checklist_state, qa_today_score_raw)
        qa_prompt_title = "🧾 Add yoga details to unlock progression advice"
        qa_prompt_hint = "What I need:"
    elif qa_quick_workout_done and qa_quick_workout_type == "weights":
        qa_prompt_missing_fields = _qa_missing_weights_feedback(
            qa_workout_checklist_state,
            qa_workout_signals_state.get("recovery_signal", "unknown"),
        )
        qa_prompt_title = "🧾 Add weights details to unlock progression advice"
        qa_prompt_hint = "What I need:"
    qa_yoga_prompt_needed = bool(qa_prompt_missing_fields)
    qa_yoga_missing_text = ", ".join(qa_prompt_missing_fields)
    qa_yoga_nudge_html = ""
    if qa_yoga_prompt_needed:
        qa_yoga_nudge_html = f'''
        <div id="qa-yoga-feedback-nudge" class="rounded-lg px-3 py-3 mb-3" data-needed="true" style="background: rgba(30,64,175,0.16); border: 1px solid rgba(147,197,253,0.3);">
            <p id="qa-yoga-feedback-title" class="text-xs font-semibold mb-1" style="color: #bfdbfe">{html.escape(qa_prompt_title)}</p>
            <p class="text-xs mb-2" style="color: #cbd5e1"><span id="qa-yoga-feedback-hint">{html.escape(qa_prompt_hint)}</span> <span id="qa-yoga-feedback-missing">{html.escape(qa_yoga_missing_text)}</span></p>
            <button onclick="qaOpenWorkoutChecklist(true)" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(30,64,175,0.35); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">Open workout checklist</button>
        </div>
        '''
    else:
        qa_yoga_nudge_html = '''
        <div id="qa-yoga-feedback-nudge" class="rounded-lg px-3 py-3 mb-3" data-needed="false" style="display:none; background: rgba(30,64,175,0.16); border: 1px solid rgba(147,197,253,0.3);">
            <p id="qa-yoga-feedback-title" class="text-xs font-semibold mb-1" style="color: #bfdbfe">🧾 Add details to unlock progression advice</p>
            <p class="text-xs mb-2" style="color: #cbd5e1"><span id="qa-yoga-feedback-hint">What I need:</span> <span id="qa-yoga-feedback-missing"></span></p>
            <button onclick="qaOpenWorkoutChecklist(true)" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(30,64,175,0.35); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">Open workout checklist</button>
        </div>
        '''
    qa_quick_done_count = int(bool(qa_mindfulness_done)) + int(bool(qa_quick_workout_done)) + int(bool(qa_quick_mood_done))
    qa_quick_done_total = 3 if qa_quick_workout_trackable else 2
    qa_quick_meta = f"{qa_quick_done_count}/{qa_quick_done_total} check-ins done."
    qa_quick_workout_html = ""
    if qa_quick_workout_trackable:
        qa_quick_workout_checked = "checked" if qa_quick_workout_done else ""
        qa_quick_workout_html = f'''
            <label class="rounded px-2 py-1 text-xs flex items-center gap-1.5" style="background: rgba(6,95,70,0.2); border: 1px solid rgba(110,231,183,0.26); color: #d1fae5;">
                <input id="qa-quick-workout-check" type="checkbox" {qa_quick_workout_checked} onchange="qaQuickToggleWorkout(this)" class="h-3.5 w-3.5">
                💪 {html.escape(qa_quick_workout_title)}
            </label>
        '''

    qa_quick_end_day_html = ""
    qa_quick_end_day_label = "✅ End Day done" if qa_end_day_done_today else "🌙 End Day now"
    qa_quick_end_day_disabled = "disabled" if qa_end_day_done_today else ""
    qa_quick_end_day_opacity = "0.72" if qa_end_day_done_today else "1"
    if is_evening:
        qa_quick_end_day_html = f'''
            <button id="qa-quick-end-day" onclick="qaRunEndDay(this)" {qa_quick_end_day_disabled} class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(120,53,15,0.35); color: #fde68a; border: 1px solid rgba(251,191,36,0.35); opacity: {qa_quick_end_day_opacity};">
                {qa_quick_end_day_label}
            </button>
        '''

    qa_quick_mind_checked = "checked" if qa_mindfulness_done else ""
    qa_quick_mood_checked = "checked" if qa_quick_mood_done else ""
    qa_quick_bar_html = f'''
        <div class="rounded-lg px-3 py-3 mb-3" style="background: rgba(30,64,175,0.14); border: 1px solid rgba(147,197,253,0.24);">
            <p class="text-xs font-semibold mb-2" style="color: #bfdbfe">⚡ Done for today</p>
            <div class="flex flex-wrap gap-2">
                <label class="rounded px-2 py-1 text-xs flex items-center gap-1.5" style="background: rgba(6,95,70,0.2); border: 1px solid rgba(110,231,183,0.26); color: #d1fae5;">
                    <input id="qa-quick-mindfulness-check" type="checkbox" {qa_quick_mind_checked} onchange="qaQuickToggleMindfulness(this)" class="h-3.5 w-3.5">
                    🧠 Mindfulness
                </label>
                {qa_quick_workout_html}
                <label class="rounded px-2 py-1 text-xs flex items-center gap-1.5" style="background: rgba(88,28,135,0.2); border: 1px solid rgba(196,181,253,0.26); color: #e9d5ff;">
                    <input id="qa-quick-mood-check" type="checkbox" {qa_quick_mood_checked} onchange="qaToggleMoodQuick(this)" class="h-3.5 w-3.5">
                    🙂 {html.escape(qa_quick_mood_habit)}
                </label>
                <span id="qa-mood-save-state" hidden="hidden" class="text-xs rounded px-2 py-1" style="color: #94a3b8; border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.45);">synced</span>
                {qa_quick_end_day_html}
            </div>
            <p id="qa-quick-done-meta" class="text-xs mt-2" style="color: #93c5fd">{html.escape(qa_quick_meta)}</p>
        </div>
    '''

    qa_yoga_evening_hint_html = ""
    if qa_yoga_prompt_needed:
        qa_yoga_evening_hint_html = f'''
            <p class="text-xs mt-2" style="color: #93c5fd">🧾 Still missing yoga details: {html.escape(qa_yoga_missing_text)}.</p>
        '''

    qa_evening_unlock_hidden_attr = "" if is_evening else ' hidden="hidden"'
    qa_anxiety_relief_html = f'''
        <div id="qa-anxiety-relief-wrap"{qa_evening_unlock_hidden_attr}>
            <div class="mt-4 pt-4" style="border-top: 1px solid rgba(251,191,36,0.16);">
                <label class="text-xs block mb-1" style="color: #fbbf24">📉 Rate today's anxiety relief (0-10)</label>
                <div class="flex items-center gap-3">
                    <input id="qa-anxiety-score" type="range" min="0" max="10" step="1" value="{qa_slider_value}" class="flex-1" oninput="qaOnAnxietyInput(this)" onchange="qaOnAnxietyInput(this, true)">
                    <span id="qa-anxiety-score-val" class="text-sm font-semibold" style="color: #fcd34d">{qa_slider_value}</span>
                    <span id="qa-anxiety-save-state" hidden="hidden" class="text-xs rounded px-2 py-1" style="color: #94a3b8; border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.45);">synced</span>
                </div>
                {qa_yoga_evening_hint_html}
                {qa_week_summary_html}
            </div>
        </div>
    '''

    qa_end_day_label = "✅ End Day done" if qa_end_day_done_today else "🌙 End Day (after diary)"
    qa_end_day_disabled = "disabled" if qa_end_day_done_today else ""
    qa_end_day_opacity = "0.72" if qa_end_day_done_today else "1"
    qa_end_day_controls_html = f'''
        <div id="qa-end-day-wrap"{qa_evening_unlock_hidden_attr}>
            <div class="flex items-center gap-2 flex-wrap">
                <button id="qa-end-day-btn" onclick="qaRunEndDay(this)" {qa_end_day_disabled} class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(120,53,15,0.35); color: #fde68a; border: 1px solid rgba(251,191,36,0.35); opacity: {qa_end_day_opacity};">{qa_end_day_label}</button>
            </div>
            <p id="qa-end-day-status" class="text-xs mt-1" style="color: {qa_end_day_status_color}">{html.escape(qa_end_day_status_text)}</p>
        </div>
    '''
    qa_end_day_command_option = '{ label: "Action: End day (after diary)", run: () => { if (typeof qaRunEndDay === "function") qaRunEndDay(document.getElementById("qa-end-day-btn")); } },' if is_evening else ""

    daily_report_story_text = ""
    daily_report_tomorrow_text = ""
    daily_report_meta_html = ""
    _daily_report_saved = parse_saved_report_html(DAILY_REPORT_FILE)
    _daily_report_cache = load_daemon_cache()
    _daily_report_ctx = build_daily_report_context(
        _daily_report_cache,
        parse_daily_report_journal(effective_today),
        effective_today,
    )
    _daily_report_ready = bool(is_evening or qa_end_day_done_today)
    if _daily_report_ready and report_is_evening_ready(
        _daily_report_saved,
        expected_date=effective_today,
        cache_timestamp=str(data.get("cacheTimestamp", "") or ""),
    ):
        daily_report_story_text = str(_daily_report_saved.get("today_story", "") or "").strip()
        daily_report_tomorrow_text = str(_daily_report_saved.get("tomorrow_text", "") or "").strip()
    if not daily_report_story_text:
        fallback_story_candidates = [
            compose_daily_report_today_fallback(_daily_report_ctx),
            str(_narrative or "").strip(),
            str(eve_felt_summary or "").strip(),
            str(emotional_summary or "").strip(),
        ]
        daily_report_story_text = next((item for item in fallback_story_candidates if str(item).strip()), "")
        daily_report_meta_html = '<p class="text-xs mb-3" style="color:#94a3b8">Built from the latest same-day dashboard data.</p>' if daily_report_story_text else ""
    if not daily_report_tomorrow_text:
        daily_report_tomorrow_text = compose_daily_report_tomorrow_fallback(
            _daily_report_ctx,
            now_hour=current_hour if _daily_report_ready else 18,
        )
    if not daily_report_tomorrow_text:
        daily_report_tomorrow_text = "Tomorrow, keep the plan light and specific: one meaningful task first, then reassess your energy."

    def _daily_report_prose_html(raw_text, palette):
        paras = [p.strip() for p in re.split(r"\n{2,}", str(raw_text or "")) if p.strip()]
        if not paras:
            return '<p class="text-sm" style="color:#94a3b8">Not ready yet.</p>'
        rows = []
        for idx, para in enumerate(paras):
            bg, border, colour = palette[idx % len(palette)]
            rows.append(
                f'<div class="rounded-lg px-4 py-3 mb-3" style="background:{bg}; border-left:3px solid {border}; color:{colour}; line-height:1.75;">'
                f'{html.escape(para)}'
                f'</div>'
            )
        return "".join(rows)

    _daily_story_palette = [
        ("rgba(6,95,70,0.16)", "#6ee7b7", "#e5e7eb"),
        ("rgba(131,24,67,0.14)", "#f9a8d4", "#e5e7eb"),
        ("rgba(120,53,15,0.16)", "#fbbf24", "#e5e7eb"),
        ("rgba(30,64,175,0.14)", "#93c5fd", "#e5e7eb"),
    ]
    _daily_tomorrow_palette = [
        ("rgba(131,24,67,0.14)", "#f9a8d4", "#fce7f3"),
        ("rgba(120,53,15,0.16)", "#fbbf24", "#fef3c7"),
    ]
    daily_report_html = ""
    if daily_report_story_text or daily_report_tomorrow_text:
        daily_report_html = f'''
        <div class="card" style="border: 1px solid rgba(110,231,183,0.18); background: rgba(15,23,42,0.74);">
            <div class="flex items-center justify-between gap-3 mb-3">
                <div>
                    <h3 class="text-lg font-semibold" style="color:#a7f3d0">📖 Daily report</h3>
                    <p class="text-xs mt-1" style="color:#94a3b8">End-of-day synthesis without leaving the dashboard.</p>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                    <button type="button" onclick="qaExitReportFocus()" class="rounded px-2.5 py-1.5 text-xs font-semibold" style="background: rgba(30,64,175,0.22); color:#bfdbfe; border:1px solid rgba(147,197,253,0.28);">🌐 Dashboard</button>
                </div>
            </div>
            {daily_report_meta_html}
            <div class="mb-4">
                <p class="text-xs font-semibold mb-2" style="color:#6ee7b7">📖 Today&apos;s story</p>
                {_daily_report_prose_html(daily_report_story_text, _daily_story_palette)}
            </div>
            <div>
                <p class="text-xs font-semibold mb-2" style="color:#f9a8d4">🌅 Tomorrow</p>
                {_daily_report_prose_html(daily_report_tomorrow_text, _daily_tomorrow_palette)}
            </div>
        </div>
        '''
    daily_report_control_hidden_attr = "" if daily_report_html and _daily_report_ready else ' hidden="hidden"'
    qa_daily_report_focus_btn_html = f'''
        <button id="qa-daily-report-focus-btn" onclick="qaOpenReportFocus()" type="button" class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(6,95,70,0.28); color:#a7f3d0; border:1px solid rgba(110,231,183,0.3);">
            📖 Focus report
        </button>
    ''' if daily_report_html else ""
    qa_report_command_option = '{ label: "Focus: Report", run: () => { if (typeof qaOpenReportFocus === "function") qaOpenReportFocus(); } },' if daily_report_html else ""

    # --- Schedule Insight callout (from Haiku feasibility analysis) ---
    schedule_insight_html = ""
    if _schedule_insight and _sa_today:
        _risk_styles = {
            "low":    {"bg": "rgba(6,95,70,0.2)",    "border": "rgba(110,231,183,0.26)", "text": "#a7f3d0", "dot": "🟢"},
            "medium": {"bg": "rgba(120,53,15,0.2)",  "border": "rgba(251,191,36,0.26)",  "text": "#fde68a", "dot": "🟡"},
            "high":   {"bg": "rgba(153,27,27,0.2)",  "border": "rgba(248,113,113,0.26)", "text": "#fca5a5", "dot": "🔴"},
        }
        _rs = _risk_styles.get(_burnout_risk, _risk_styles["low"])
        _density_txt = _schedule_density.capitalize() if _schedule_density else ""
        _density_badge = (
            f' <span class="rounded px-1.5 py-0.5 text-xs" style="background:rgba(148,163,184,0.18);'
            f'color:#cbd5e1;border:1px solid rgba(148,163,184,0.24);">'
            f'{html.escape(_density_txt)}</span>'
        ) if _density_txt else ""
        schedule_insight_html = f'''
        <div class="rounded-lg px-3 py-2.5 mb-3" style="background:{_rs["bg"]};border:1px solid {_rs["border"]};">
            <p class="text-xs font-semibold mb-1" style="color:{_rs["text"]}">{_rs["dot"]} Schedule{_density_badge}</p>
            <p class="text-sm" style="color:{_rs["text"]};line-height:1.45;">{html.escape(_schedule_insight)}</p>
        </div>'''

    action_items_html = rf'''
    <div class="card rounded-xl p-5 mb-4" style="background: rgba(131,24,67,0.15); border: 1px solid rgba(249,168,212,0.2);">
        <h3 class="text-lg font-semibold mb-2" style="color: #fbcfe8">✅ Action Items</h3>
        {qa_quick_bar_html}
        {qa_yoga_nudge_html}
        {qa_counts_html}
        {schedule_insight_html}
        {qa_one_thing_html}
        {action_items_list_html}

        <details class="mt-4 pt-4" style="border-top: 1px solid rgba(251,191,36,0.16);">
            <summary class="text-xs font-semibold cursor-pointer" style="color: #fde68a">🔄 Open Loops ({len(qa_loop_options)})</summary>
            <p class="text-xs mt-2 mb-2" style="color: rgba(253,230,138,0.65)">Items still taking mental space.</p>
            <div class="mb-2">
                {qa_loop_rows_html}
            </div>
            {qa_loop_hidden_note_html}
        </details>

        <details class="mt-4 pt-4" style="border-top: 1px solid rgba(148,163,184,0.16);">
            <summary class="text-xs font-semibold cursor-pointer" style="color: #94a3b8">Manual close</summary>
            <div class="mt-2 space-y-2">
                <div class="flex gap-2">
                    <input id="qa-todo-text" type="text" placeholder="Action item text..." class="flex-1 rounded px-3 py-2 text-sm" style="background: rgba(15,23,42,0.7); border: 1px solid rgba(249,168,212,0.3); color: #e5e7eb;">
                    <button onclick="qaCompleteTodo()" class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(131,24,67,0.35); color: #fbcfe8; border: 1px solid rgba(249,168,212,0.35);">Done</button>
                </div>
                <div class="flex gap-2">
                    <input id="qa-loop-text" type="text" placeholder="Open loop text..." class="flex-1 rounded px-3 py-2 text-sm" style="background: rgba(15,23,42,0.7); border: 1px solid rgba(110,231,183,0.25); color: #e5e7eb;">
                    <button onclick="qaCompleteLoop()" class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(6,95,70,0.35); color: #6ee7b7; border: 1px solid rgba(110,231,183,0.35);">Close</button>
                </div>
            </div>
        </details>

        {qa_anxiety_relief_html}

        <div class="mt-4 pt-4 space-y-2" style="border-top: 1px solid rgba(148,163,184,0.16);">
            {qa_end_day_controls_html}
            <div id="qa-daily-report-focus-wrap"{daily_report_control_hidden_attr}>
                {qa_daily_report_focus_btn_html}
            </div>
            <div class="flex items-center gap-2 flex-wrap" style="display:none">
                <span id="qa-sync-pause-meta" class="text-xs" style="color: #94a3b8">Live sync active</span>
                <button id="qa-sync-pause-10" onclick="qaSetSyncPause(10)" style="display:none">Pause 10m</button>
                <button id="qa-sync-pause-30" onclick="qaSetSyncPause(30)" style="display:none">Pause 30m</button>
                <button id="qa-sync-resume" onclick="qaSetSyncPause(0)" style="display:none">Resume</button>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
                <button id="qa-refresh-btn" onclick="qaRefreshData(this)" class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(30,64,175,0.35); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">🔄 Refresh Data Now</button>
                <span class="text-xs" style="color: #94a3b8">Runs live daemon refresh via API.</span>
            </div>
        </div>

        <p id="qa-status" class="text-xs mt-3" style="color: #9ca3af">Ready.</p>
    </div>

    <script>
    const QA_API_TOKEN = "{qa_api_token}";
    const QA_LOCAL_IP = "{qa_local_ip}";
    const QA_CF_URL = "{qa_cf_url}";
    const QA_API_BASE = (() => {{
        if (typeof window !== "undefined" && window.location) {{
            const protocol = (window.location.protocol || "").toLowerCase();
            if (protocol === "http:" || protocol === "https:") {{
                return window.location.origin;
            }}
            // file:// — iPhone via iCloud or Mac local.
            // Prefer Cloudflare/Tailscale URL (https://) — file:// can't reach http:// on iOS/Mac.
            if (typeof QA_CF_URL !== "undefined" && QA_CF_URL) {{
                return QA_CF_URL;
            }}
            if (typeof QA_LOCAL_IP !== "undefined" && QA_LOCAL_IP && QA_LOCAL_IP !== "127.0.0.1") {{
                return `http://${{QA_LOCAL_IP}}:8765`;
            }}
        }}
        return "http://127.0.0.1:8765";
    }})();
    const QA_IS_FILE_PROTOCOL = (typeof window !== "undefined") &&
        window.location && (window.location.protocol || "").toLowerCase() === "file:";

    function qaGetPendingCompletions() {{
        try {{ return JSON.parse(localStorage.getItem("qa.pending_completions") || "[]"); }}
        catch (_e) {{ return []; }}
    }}
    function qaAddPendingCompletion(kind, text, meta = {{}}) {{
        const pending = qaGetPendingCompletions();
        const key = (kind + ":" + text).toLowerCase().trim();
        if (pending.some(p => (p.kind + ":" + p.text).toLowerCase().trim() === key)) return;
        const row = Object.assign({{ kind, text, queued_at: new Date().toISOString() }}, (meta && typeof meta === "object") ? meta : {{}});
        pending.push(row);
        try {{ localStorage.setItem("qa.pending_completions", JSON.stringify(pending)); }} catch(_e) {{}}
    }}
    function qaRemovePendingCompletion(kind, text) {{
        const pending = qaGetPendingCompletions();
        const key = (kind + ":" + text).toLowerCase().trim();
        const filtered = pending.filter(p => (p.kind + ":" + p.text).toLowerCase().trim() !== key);
        try {{ localStorage.setItem("qa.pending_completions", JSON.stringify(filtered)); }} catch(_e) {{}}
    }}
    function qaCompletionKey(kind, text) {{
        const cleanedKind = String(kind || "").trim().toLowerCase();
        const cleanedText = String(text || "").toLowerCase().replace(/\\s+/g, " ").trim();
        return `${{cleanedKind}}:${{cleanedText}}`;
    }}
    function qaLocalCompletionsStorageKey() {{
        return `qa.local_completions.${{qaEffectiveDateKey() || "unknown"}}`;
    }}
    function qaGetLocalCompletions() {{
        try {{
            const raw = localStorage.getItem(qaLocalCompletionsStorageKey()) || "{{}}";
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === "object" ? parsed : {{}};
        }} catch (_e) {{
            return {{}};
        }}
    }}
    function qaSetLocalCompletion(kind, text, done) {{
        const key = qaCompletionKey(kind, text);
        if (!key || key === ":") return;
        const current = qaGetLocalCompletions();
        if (done) {{
            current[key] = new Date().toISOString();
        }} else {{
            delete current[key];
        }}
        try {{ localStorage.setItem(qaLocalCompletionsStorageKey(), JSON.stringify(current)); }} catch(_e) {{}}
    }}
    function qaHasLocalCompletion(kind, text) {{
        const key = qaCompletionKey(kind, text);
        if (!key || key === ":") return false;
        const current = qaGetLocalCompletions();
        return Boolean(current[key]);
    }}
    function qaLocalDeferredStorageKey() {{
        return `qa.local_deferred.${{qaEffectiveDateKey() || "unknown"}}`;
    }}
    function qaGetLocalDeferredMap() {{
        try {{
            const raw = localStorage.getItem(qaLocalDeferredStorageKey()) || "{{}}";
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === "object" ? parsed : {{}};
        }} catch (_e) {{
            return {{}};
        }}
    }}
    function qaSetLocalDeferred(text, targetDate) {{
        const key = qaCompletionKey("todo", text);
        if (!key || key === ":") return;
        const current = qaGetLocalDeferredMap();
        current[key] = {{
            target_date: String(targetDate || "").trim(),
            at: new Date().toISOString(),
        }};
        try {{ localStorage.setItem(qaLocalDeferredStorageKey(), JSON.stringify(current)); }} catch(_e) {{}}
    }}
    function qaGetLocalDeferred(text) {{
        const key = qaCompletionKey("todo", text);
        if (!key || key === ":") return null;
        const current = qaGetLocalDeferredMap();
        const entry = current[key];
        return (entry && typeof entry === "object") ? entry : null;
    }}
    function qaFormatDeferDate(dateStr) {{
        const raw = String(dateStr || "").trim();
        if (!raw) return "tomorrow";
        const parsed = new Date(raw + "T00:00:00");
        if (Number.isNaN(parsed.getTime())) return raw;
        return parsed.toLocaleDateString(undefined, {{ day: "numeric", month: "short" }});
    }}
    function qaApplyTodoDeferredUi(text, targetDate = "", isQueued = false) {{
        const target = qaCompletionKey("todo", text);
        if (!target) return;
        const deferLabel = qaFormatDeferDate(targetDate);
        document.querySelectorAll("button[data-text]").forEach((btn) => {{
            const btnTextKey = qaCompletionKey("todo", btn.dataset.text || "");
            if (btnTextKey !== target) return;
            const row = btn.closest("[data-qa-row='todo']");
            if (row) {{
                const inTomorrowQueue = Boolean(row.closest("[data-qa-tomorrow-queue='1']"));
                if (!inTomorrowQueue) {{
                    row.style.display = "none";
                }}
            }}
            const oneThingWrap = btn.closest("[data-qa-one-thing='1']");
            if (oneThingWrap) {{
                oneThingWrap.style.display = "none";
            }}
        }});
        const status = document.getElementById("qa-status");
        if (status) {{
            status.textContent = isQueued
                ? `📶 Deferred locally (${{deferLabel}}); will sync when API is reachable.`
                : `⏭️ Deferred to ${{deferLabel}}.`;
            status.style.color = isQueued ? "#fbbf24" : "#93c5fd";
        }}
    }}
    function qaApplyTodoDoneUi(text) {{
        const target = qaCompletionKey("todo", text);
        if (!target) return;
        document.querySelectorAll("button[data-text]").forEach((btn) => {{
            const onclickValue = String(btn.getAttribute("onclick") || "");
            if (!onclickValue.includes("qaCompleteTodoFromButton")) return;
            if (qaCompletionKey("todo", btn.dataset.text || "") !== target) return;
            btn.disabled = true;
            btn.textContent = "☑ Done";
            btn.style.background = "rgba(30,64,175,0.26)";
            btn.style.color = "#bfdbfe";
            btn.style.borderColor = "rgba(147,197,253,0.35)";
            const row = btn.closest("[data-qa-row='todo']");
            if (row) {{
                row.style.opacity = "0.55";
                const taskLine = row.querySelector("p");
                if (taskLine) {{
                    taskLine.style.textDecoration = "line-through";
                    taskLine.style.textDecorationThickness = "1.5px";
                    taskLine.style.textDecorationColor = "rgba(148,163,184,0.85)";
                    taskLine.style.color = "#cbd5e1";
                }}
                const offlineMsg = row.querySelector(".qa-offline-msg");
                if (offlineMsg) offlineMsg.remove();
            }}
            const oneThingWrap = btn.closest("[data-qa-one-thing='1']");
            if (oneThingWrap) {{
                oneThingWrap.style.opacity = "0.72";
                oneThingWrap.style.background = "rgba(15,23,42,0.52)";
                oneThingWrap.style.borderColor = "rgba(148,163,184,0.3)";
                const taskLine = oneThingWrap.querySelector("[data-qa-one-thing-text='1']");
                if (taskLine) {{
                    taskLine.style.textDecoration = "line-through";
                    taskLine.style.textDecorationThickness = "1.5px";
                    taskLine.style.textDecorationColor = "rgba(148,163,184,0.85)";
                    taskLine.style.color = "#cbd5e1";
                }}
                const offlineMsg = oneThingWrap.querySelector(".qa-offline-msg");
                if (offlineMsg) offlineMsg.remove();
                oneThingWrap.querySelectorAll("button").forEach((actionBtn) => {{
                    actionBtn.disabled = true;
                    if (actionBtn === btn) return;
                    actionBtn.style.opacity = "0.6";
                    actionBtn.style.background = "rgba(51,65,85,0.34)";
                    actionBtn.style.color = "#cbd5e1";
                    actionBtn.style.borderColor = "rgba(148,163,184,0.28)";
                }});
            }}
        }});
    }}
    function qaApplyLoopClosedUi(text) {{
        const target = qaCompletionKey("loop", text);
        if (!target) return;
        document.querySelectorAll("button[data-text]").forEach((btn) => {{
            const onclickValue = String(btn.getAttribute("onclick") || "");
            if (!onclickValue.includes("qaCompleteLoopFromButton")) return;
            if (qaCompletionKey("loop", btn.dataset.text || "") !== target) return;
            btn.disabled = true;
            btn.textContent = "Closed";
            btn.style.background = "rgba(6,95,70,0.35)";
            btn.style.color = "#6ee7b7";
            btn.style.borderColor = "rgba(110,231,183,0.35)";
            const row = btn.closest("[data-qa-row='loop']");
            if (row) {{
                row.style.opacity = "0.55";
                const offlineMsg = row.querySelector(".qa-offline-msg");
                if (offlineMsg) offlineMsg.remove();
            }}
        }});
    }}
    function qaApplyLocalCompletionUi() {{
        document.querySelectorAll("button[data-text]").forEach((btn) => {{
            const onclickValue = String(btn.getAttribute("onclick") || "");
            const text = String(btn.dataset.text || "");
            if (!text) return;
            const deferred = qaGetLocalDeferred(text);
            if (deferred) {{
                qaApplyTodoDeferredUi(text, String(deferred.target_date || "").trim(), true);
                return;
            }}
            if (onclickValue.includes("qaCompleteTodoFromButton")) {{
                if (qaHasLocalCompletion("todo", text)) qaApplyTodoDoneUi(text);
                return;
            }}
            if (onclickValue.includes("qaCompleteLoopFromButton")) {{
                if (qaHasLocalCompletion("loop", text)) qaApplyLoopClosedUi(text);
            }}
        }});
    }}
    async function qaRetryPendingCompletions() {{
        const pending = [...qaGetPendingCompletions()];
        for (const item of pending) {{
            let ok = null;
            if (item.kind === "loop") {{
                ok = await qaCompleteLoopText(item.text);
            }} else if (item.kind === "todo_defer") {{
                ok = await qaDeferTodoText(item.text, item.target_date || qaTomorrowDateKey());
                if (ok) {{
                    qaSetLocalDeferred(item.text, item.target_date || qaTomorrowDateKey());
                    qaApplyTodoDeferredUi(item.text, item.target_date || qaTomorrowDateKey(), true);
                }}
            }} else {{
                ok = await qaCompleteTodoText(item.text);
            }}
            if (ok) qaRemovePendingCompletion(item.kind, item.text);
        }}
    }}
    function qaGetPendingScratch() {{
        try {{ return JSON.parse(localStorage.getItem("qa.pending_scratch") || "[]"); }}
        catch (_e) {{ return []; }}
    }}
    function qaAddPendingScratch(section, text) {{
        const pending = qaGetPendingScratch();
        const key = (section + ":" + text).toLowerCase().trim();
        if (pending.some(p => (p.section + ":" + p.text).toLowerCase().trim() === key)) return;
        pending.push({{ section, text, queued_at: new Date().toISOString() }});
        try {{ localStorage.setItem("qa.pending_scratch", JSON.stringify(pending)); }} catch(_e) {{}}
    }}
    function qaRemovePendingScratch(section, text) {{
        const pending = qaGetPendingScratch();
        const key = (section + ":" + text).toLowerCase().trim();
        const filtered = pending.filter(p => (p.section + ":" + p.text).toLowerCase().trim() !== key);
        try {{ localStorage.setItem("qa.pending_scratch", JSON.stringify(filtered)); }} catch(_e) {{}}
    }}
    async function qaSaveScratchText(sectionId, text) {{
        const cleaned = String(text || "").trim();
        if (!cleaned) return null;
        const ui = await qaPostWithRetry("/v1/ui/journal/scratch", {{
            section: sectionId,
            text: cleaned,
        }}, {{ retries: 1, label: "scratch save" }});
        if (ui && ui.status === "ok") return ui;
        return await qaPostWithRetry("/v1/journal/scratch", {{
            section: sectionId,
            text: cleaned,
        }}, {{ retries: 1, label: "scratch save" }});
    }}
    async function qaRetryPendingScratch() {{
        const pending = [...qaGetPendingScratch()];
        for (const item of pending) {{
            const ok = await qaSaveScratchText(item.section, item.text);
            if (ok && ok.status === "ok") {{
                qaRemovePendingScratch(item.section, item.text);
                if (typeof qaApplyNarrativeFromScratch === "function") {{
                    qaApplyNarrativeFromScratch(item.section, item.text);
                }}
                if (typeof qaSyncTodayFromApi === "function") {{
                    qaSyncTodayFromApi({{ force: true }}).catch(() => {{}});
                }}
                if (typeof qaSyncRenderStatus === "function") {{
                    qaSyncRenderStatus({{ force: true }}).catch(() => {{}});
                }}
            }}
        }}
    }}
    function qaSaveScratchPad(el) {{
        if (!el || !el.dataset.storageKey) return;
        try {{ localStorage.setItem(el.dataset.storageKey, el.value); }} catch(_e) {{}}
    }}
    async function qaScratchSubmit(sectionId) {{
        const textarea = document.getElementById("qa-scratch-" + sectionId);
        const btn = document.getElementById("qa-scratch-submit-" + sectionId);
        const statusEl = document.getElementById("qa-scratch-status-" + sectionId);
        if (!textarea || !textarea.value.trim()) {{
            if (statusEl) {{ statusEl.textContent = "Nothing to save"; statusEl.style.color = "#fbbf24"; }}
            return;
        }}
        if (btn) btn.disabled = true;
        if (statusEl) {{ statusEl.textContent = "Saving…"; statusEl.style.color = "#93c5fd"; }}
        const scratchText = textarea.value.trim();
        const data = await qaSaveScratchText(sectionId, scratchText);
        if (data && data.status === "ok") {{
            qaRemovePendingScratch(sectionId, scratchText);
            if (statusEl) {{ statusEl.textContent = "✓ Saved to journal"; statusEl.style.color = "#6ee7b7"; }}
            try {{ localStorage.removeItem(textarea.dataset.storageKey); }} catch(_e) {{}}
            if (typeof qaApplyNarrativeFromScratch === "function") {{
                qaApplyNarrativeFromScratch(sectionId, scratchText);
            }}
            textarea.value = "";
            if (typeof qaSyncTodayFromApi === "function") {{
                qaSyncTodayFromApi({{ force: true }}).catch(() => {{}});
            }}
            if (typeof qaSyncRenderStatus === "function") {{
                qaSyncRenderStatus({{ force: true }}).catch(() => {{}});
            }}
            setTimeout(() => {{ if (statusEl) statusEl.textContent = ""; }}, 4000);
        }} else {{
            qaAddPendingScratch(sectionId, scratchText);
            if (statusEl) {{
                statusEl.textContent = "📶 Queued — will sync when API is reachable";
                statusEl.style.color = "#fbbf24";
            }}
        }}
        if (btn) btn.disabled = false;
    }}
    function qaLoadScratchPads() {{
        document.querySelectorAll("textarea[data-storage-key]").forEach(ta => {{
            try {{
                const saved = localStorage.getItem(ta.dataset.storageKey);
                if (saved !== null) ta.value = saved;
            }} catch(_e) {{}}
        }});
    }}
    document.addEventListener("DOMContentLoaded", function() {{
        qaLoadScratchPads();
    }});
    if (typeof window !== "undefined") {{
        window.addEventListener("online", () => {{ qaRetryPendingScratch(); }});
        window.addEventListener("focus", () => {{ qaRetryPendingScratch(); }});
    }}
    if (typeof document !== "undefined") {{
        document.addEventListener("visibilitychange", () => {{
            if (!document.hidden) qaRetryPendingScratch();
        }});
    }}
    const QA_MINDFULNESS_DATE = "{qa_today}";
    const QA_MINDFULNESS_TARGET = {qa_mindfulness_target};
    const QA_MINDFULNESS_INITIAL = {json.dumps(qa_mindfulness_state)};
    const QA_MOOD_INITIAL = {json.dumps(qa_mood_state)};
    const QA_WORKOUT_CHECKLIST_INITIAL = {json.dumps(qa_workout_checklist_state)};
    const QA_WORKOUT_TYPE_INITIAL = "{html.escape(qa_quick_workout_type)}";
    const QA_WORKOUT_DONE_INITIAL = {str(bool(qa_quick_workout_done)).lower()};
    const QA_ANXIETY_SCORE_INITIAL = {json.dumps(_to_float(qa_today_score_raw))};
    const QA_WORKOUT_SIGNALS_INITIAL = {json.dumps(qa_workout_signals_state)};
    const QA_WORKOUT_PROGRESSION_INITIAL = {json.dumps(qa_workout_progression_state)};
    const QA_WORKOUT_WEIGHTS_PROGRESSION_INITIAL = {json.dumps(qa_workout_progression_weights_state)};
    const QA_END_DAY_INITIAL = {json.dumps(qa_end_day_state)};
    const QA_SYSTEM_STATUS_INITIAL = {json.dumps(runtime)};
    const QA_SYNC_PAUSE_KEY = "dashboard.live.sync.pause.until.v1";
    let qaMindfulnessSaving = false;
    let qaMindfulnessDesiredDone = null;
    let qaMoodSaving = false;
    let qaMoodEntrySaving = false;
    let qaMoodEntryLastAt = 0;
    let qaWorkoutSaving = false;
    let qaCurrentWorkoutType = String(QA_WORKOUT_TYPE_INITIAL || "").toLowerCase();
    let qaCurrentWorkoutDone = Boolean(QA_WORKOUT_DONE_INITIAL);
    let qaCurrentWorkoutSignals = (QA_WORKOUT_SIGNALS_INITIAL && typeof QA_WORKOUT_SIGNALS_INITIAL === "object")
        ? QA_WORKOUT_SIGNALS_INITIAL
        : {{}};
    const qaAnxietySeed = Number(QA_ANXIETY_SCORE_INITIAL);
    let qaCurrentAnxietyScore = Number.isFinite(qaAnxietySeed) ? qaAnxietySeed : null;
    let qaAnxietySaveTimer = null;
    let qaAnxietySaveInFlight = false;
    let qaAnxietyPendingScore = null;
    let qaYogaPromptAutoOpened = false;
    let qaLiveSyncPausedUntil = 0;
    let qaEndDayState = (QA_END_DAY_INITIAL && typeof QA_END_DAY_INITIAL === "object") ? QA_END_DAY_INITIAL : {{ done_today: false, date: "", ran_at: "", source: "" }};
    let qaEndDayRunning = false;
    let qaSystemStatusFailureCount = 0;
    let qaSystemPollInFlight = false;
    let qaLastSystemStatus = (QA_SYSTEM_STATUS_INITIAL && typeof QA_SYSTEM_STATUS_INITIAL === "object") ? QA_SYSTEM_STATUS_INITIAL : null;
    let qaTodaySyncInFlight = false;
    let qaServerEffectiveDate = String(QA_MINDFULNESS_DATE || "").trim();
    let qaFreshnessState = {{
        diarium: "info",
        diarium_pickup: "info",
        narrative: "info",
        updates: "info",
        mood: "info",
        cache: "info",
    }};
    const qaGetInFlight = new Map();
    const QA_TAB_ID = `tab-${{Math.random().toString(36).slice(2)}}-${{Date.now().toString(36)}}`;
    const QA_LEADER_DISABLE_KEY = "dashboard.live.sync.leader.disabled.v1";
    const QA_LEADER_LEASE_KEY = "dashboard.live.sync.leader.lease.v1";
    const QA_LEADER_SYSTEM_KEY = "dashboard.live.sync.system.latest.v1";
    const QA_LEADER_TODAY_KEY = "dashboard.live.sync.today.latest.v1";
    const QA_LEADER_CHANNEL_NAME = "dashboard.live.sync.v1";
    const QA_TODAY_PAYLOAD_VERSION = 2;
    const QA_LEADER_HEARTBEAT_MS = 8000;
    const QA_LEADER_TTL_MS = 22000;
    let qaLeaderModeDisabled = false;
    let qaIsPollLeader = false;
    let qaLeaderHeartbeatHandle = null;
    let qaLeaderBroadcast = null;

    function qaParseJson(raw, fallback = null) {{
        if (!raw || typeof raw !== "string") return fallback;
        try {{
            return JSON.parse(raw);
        }} catch (_err) {{
            return fallback;
        }}
    }}

    function qaBuildTodayEnvelope(todayPayload) {{
        const safeToday = (todayPayload && typeof todayPayload === "object") ? todayPayload : {{}};
        const effectiveDateRaw = String(safeToday.effective_date || safeToday.date || qaEffectiveDateKey()).trim();
        const effectiveDate = effectiveDateRaw || qaEffectiveDateKey();
        return {{
            payload_version: QA_TODAY_PAYLOAD_VERSION,
            effective_date: effectiveDate,
            saved_at: new Date().toISOString(),
            today: safeToday,
        }};
    }}

    function qaParseTodayEnvelope(payload) {{
        if (!payload || typeof payload !== "object") return null;
        // New envelope format
        if (payload.today && typeof payload.today === "object") {{
            const dateRaw = String(payload.effective_date || payload.today.effective_date || payload.today.date || "").trim();
            return {{
                payload_version: Number(payload.payload_version || QA_TODAY_PAYLOAD_VERSION),
                effective_date: dateRaw || qaEffectiveDateKey(),
                saved_at: payload.saved_at || "",
                today: payload.today,
            }};
        }}
        // Legacy format (direct today payload)
        const legacyDate = String(payload.effective_date || payload.date || "").trim();
        return {{
            payload_version: 1,
            effective_date: legacyDate || qaEffectiveDateKey(),
            saved_at: payload.saved_at || "",
            today: payload,
        }};
    }}

    function qaEnvelopeIsToday(envelope) {{
        if (!envelope || typeof envelope !== "object") return false;
        const expected = qaEffectiveDateKey();
        const got = String(envelope.effective_date || "").trim();
        if (!got) return true;
        return got === expected;
    }}

    function qaLeaderModeEnabled() {{
        return !qaLeaderModeDisabled;
    }}

    function qaLoadLeaderModeSetting() {{
        let disabled = false;
        try {{
            disabled = localStorage.getItem(QA_LEADER_DISABLE_KEY) === "1";
        }} catch (_err) {{
            disabled = false;
        }}
        try {{
            const params = new URLSearchParams(window.location.search || "");
            const leaderMode = String(params.get("leaderMode") || "").trim().toLowerCase();
            if (["off", "0", "false", "disabled"].includes(leaderMode)) {{
                disabled = true;
                localStorage.setItem(QA_LEADER_DISABLE_KEY, "1");
            }} else if (["on", "1", "true", "enabled"].includes(leaderMode)) {{
                disabled = false;
                localStorage.removeItem(QA_LEADER_DISABLE_KEY);
            }}
        }} catch (_err) {{}}
        qaLeaderModeDisabled = disabled;
    }}

    function qaReadLeaderLease() {{
        try {{
            return qaParseJson(localStorage.getItem(QA_LEADER_LEASE_KEY), null);
        }} catch (_err) {{
            return null;
        }}
    }}

    function qaWriteLeaderLease(expiresAt) {{
        const lease = {{
            tab_id: QA_TAB_ID,
            started_at: Date.now(),
            expires_at: Number(expiresAt) || (Date.now() + QA_LEADER_TTL_MS),
        }};
        try {{
            localStorage.setItem(QA_LEADER_LEASE_KEY, JSON.stringify(lease));
        }} catch (_err) {{}}
    }}

    function qaBecomeLeader(reason = "") {{
        qaWriteLeaderLease(Date.now() + QA_LEADER_TTL_MS);
        qaIsPollLeader = true;
        qaBroadcastLive("leader", {{
            tab_id: QA_TAB_ID,
            reason: reason || "heartbeat",
            at: Date.now(),
        }});
    }}

    function qaTryAcquireLeader(reason = "") {{
        if (!qaLeaderModeEnabled()) {{
            qaIsPollLeader = false;
            return false;
        }}
        const now = Date.now();
        const lease = qaReadLeaderLease();
        const leaseTab = lease && typeof lease.tab_id === "string" ? lease.tab_id : "";
        const leaseExpiry = lease ? Number(lease.expires_at || 0) : 0;
        const leaseAlive = Number.isFinite(leaseExpiry) && leaseExpiry > now;

        if (!leaseAlive || leaseTab === QA_TAB_ID) {{
            qaBecomeLeader(reason || (leaseAlive ? "renew" : "acquire"));
            return true;
        }}

        qaIsPollLeader = false;
        return false;
    }}

    function qaCanRunNetworkPoll(options = {{}}) {{
        const force = Boolean(options.force);
        if (force) return true;
        if (!qaLeaderModeEnabled()) return true;
        return qaIsPollLeader;
    }}

    function qaBroadcastLive(kind, payload) {{
        if (!qaLeaderModeEnabled()) return;
        let safePayload = payload || null;
        if (String(kind || "").toLowerCase() === "today") {{
            safePayload = qaBuildTodayEnvelope(payload);
        }}
        const msg = {{
            kind: String(kind || ""),
            payload: safePayload,
            tab_id: QA_TAB_ID,
            ts: Date.now(),
        }};
        if (!msg.kind) return;
        if (qaLeaderBroadcast && typeof qaLeaderBroadcast.postMessage === "function") {{
            try {{
                qaLeaderBroadcast.postMessage(msg);
            }} catch (_err) {{}}
        }}
        const key = kind === "system" ? QA_LEADER_SYSTEM_KEY : (kind === "today" ? QA_LEADER_TODAY_KEY : "");
        if (!key) return;
        try {{
            localStorage.setItem(key, JSON.stringify(msg));
        }} catch (_err) {{}}
    }}

    function qaFormatClockTime(rawIso) {{
        const raw = String(rawIso || "").trim();
        if (!raw) return "";
        const stamp = new Date(raw);
        if (Number.isNaN(stamp.getTime())) return "";
        return stamp.toLocaleTimeString([], {{ hour: "2-digit", minute: "2-digit" }});
    }}

    function qaNormalizeEndDayState(state) {{
        const safe = (state && typeof state === "object") ? state : {{}};
        const date = String(safe.date || "").trim();
        const ranAt = String(safe.ran_at || "").trim();
        const source = String(safe.source || "").trim();
        const doneToday = Boolean(safe.done_today) || Boolean(date && date === qaEffectiveDateKey());
        return {{
            done_today: doneToday,
            date,
            ran_at: ranAt,
            source,
        }};
    }}

    function qaEndDayStatusLabel(state) {{
        const safe = qaNormalizeEndDayState(state);
        if (!safe.done_today) {{
            return "⬜ End Day not run yet.";
        }}
        const when = qaFormatClockTime(safe.ran_at);
        if (when) {{
            return `✅ End Day already run at ${{when}}.`;
        }}
        return "✅ End Day already run today.";
    }}

    function qaIsEveningUnlockOpen() {{
        return new Date().getHours() >= 18;
    }}

    function qaSyncEveningUnlockVisibility() {{
        const unlocked = qaIsEveningUnlockOpen();
        const anxietyWrap = document.getElementById("qa-anxiety-relief-wrap");
        if (anxietyWrap) {{
            anxietyWrap.hidden = !unlocked;
        }}
        const endDayWrap = document.getElementById("qa-end-day-wrap");
        if (endDayWrap) {{
            endDayWrap.hidden = !unlocked;
        }}
        const reportSection = document.getElementById("daily-report");
        if (reportSection) {{
            reportSection.hidden = !unlocked;
        }}
        const reportChip = document.getElementById("focus-report-chip");
        if (reportChip) {{
            reportChip.hidden = !unlocked;
        }}
        const reportButtonWrap = document.getElementById("qa-daily-report-focus-wrap");
        if (reportButtonWrap) {{
            reportButtonWrap.hidden = !unlocked;
        }}
    }}

    function qaApplyEndDayState(state) {{
        qaEndDayState = qaNormalizeEndDayState(state);
        const done = Boolean(qaEndDayState.done_today);
        const statusLine = document.getElementById("qa-end-day-status");
        if (statusLine) {{
            statusLine.textContent = qaEndDayStatusLabel(qaEndDayState);
            statusLine.style.color = done ? "#6ee7b7" : "#94a3b8";
        }}
        const mainBtn = document.getElementById("qa-end-day-btn");
        if (mainBtn) {{
            if (qaEndDayRunning) {{
                mainBtn.disabled = true;
                mainBtn.textContent = "Running...";
                mainBtn.style.opacity = "0.85";
            }} else {{
                mainBtn.disabled = done;
                mainBtn.textContent = done ? "✅ End Day done" : "🌙 End Day (after diary)";
                mainBtn.style.opacity = done ? "0.72" : "1";
            }}
        }}
        const quickBtn = document.getElementById("qa-quick-end-day");
        if (quickBtn) {{
            if (qaEndDayRunning) {{
                quickBtn.disabled = true;
                quickBtn.textContent = "Running...";
                quickBtn.style.opacity = "0.85";
            }} else {{
                quickBtn.disabled = done;
                quickBtn.textContent = done ? "✅ End Day done" : "🌙 End Day now";
                quickBtn.style.opacity = done ? "0.72" : "1";
            }}
        }}
    }}

    function qaNarrativeLooksNoisy(line) {{
        const low = String(line || "").toLowerCase();
        if (!low) return true;
        if (/test[-_ ]?(item|entry|stub|dummy|does)|doesnotexist|abc123|~{{2,}}/.test(low)) return true;
        if (/internalised\\s+\\d+\\s+item\\(s\\)/.test(low)) return true;
        if (/\\[[a-f0-9]{{6,}}\\]$/.test(low)) return true;
        return false;
    }}

    function qaTruncateSentenceSafe(rawText, maxLen = 360) {{
        const text = String(rawText || "").replace(/\\s+/g, " ").trim();
        if (!text || text.length <= maxLen) return text;
        const cuts = [
            text.lastIndexOf(". ", maxLen),
            text.lastIndexOf("! ", maxLen),
            text.lastIndexOf("? ", maxLen),
        ];
        const cut = Math.max(...cuts);
        if (cut >= Math.floor(maxLen * 0.6)) {{
            return text.slice(0, cut + 1).trim();
        }}
        return text.slice(0, maxLen).replace(/[ ,;:-]+$/, "") + "…";
    }}

    function qaBuildScratchNarrativeSentence(sectionId, rawText) {{
        const section = String(sectionId || "").toLowerCase().trim();
        const raw = String(rawText || "").trim();
        if (!raw) return "";
        const seen = new Set();
        const lines = [];
        for (const chunk of raw.split(/\\n+/)) {{
            let line = String(chunk || "").trim();
            if (!line) continue;
            if (/^\\*\\[\\d{{1,2}}:\\d{{2}}\\s+via dashboard\\]\\*$/i.test(line)) continue;
            line = line.replace(/^[\\-\\*•]\\s*/, "").trim();
            if (!line) continue;
            if (/^\\*\\*ta-?dah list:\\*\\*$/i.test(line)) continue;
            if (qaNarrativeLooksNoisy(line)) continue;
            const key = line.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
            if (!key || seen.has(key)) continue;
            seen.add(key);
            lines.push(line.replace(/[.]+$/, ""));
            if (section === "updates" && lines.length >= 3) break;
            if (section !== "updates" && lines.length >= 1) break;
        }}
        if (!lines.length) return "";
        let sentence = "";
        if (section === "morning") sentence = `Morning focus: ${{lines[0]}}.`;
        else if (section === "evening") sentence = `Evening reflection: ${{lines[0]}}.`;
        else sentence = `Day updates: ${{lines.join("; ")}}.`;
        return qaTruncateSentenceSafe(sentence, 380);
    }}

    function qaInjectNarrativeSentence(sentence, options = {{}}) {{
        const body = document.getElementById("qa-day-narrative-body");
        if (!body) return;
        const text = String(sentence || "").trim();
        if (!text) return;
        const replace = Boolean(options && options.replace);
        const bodyNorm = String(body.textContent || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
        const sentNorm = text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
        if (sentNorm && bodyNorm.includes(sentNorm.slice(0, 48))) return;
        const p = document.createElement("p");
        p.style.color = "#e5e7eb";
        p.style.fontSize = "0.9rem";
        p.style.lineHeight = "1.75";
        p.style.marginBottom = "0.75rem";
        p.textContent = text;
        if (replace) body.innerHTML = "";
        body.appendChild(p);
    }}

    function qaApplyNarrativeFromScratch(sectionId, scratchText) {{
        const sentence = qaBuildScratchNarrativeSentence(sectionId, scratchText);
        if (!sentence) return;
        qaInjectNarrativeSentence(sentence, {{ replace: false }});
    }}

    function qaApplyNarrativeFromToday(snapshot) {{
        const body = document.getElementById("qa-day-narrative-body");
        if (!body) return;
        const safe = (snapshot && typeof snapshot === "object") ? snapshot : null;
        if (!safe) return;
        const meta = (safe.narrative_meta && typeof safe.narrative_meta === "object") ? safe.narrative_meta : {{}};
        const freshness = String(meta.freshness_state || "").toLowerCase();
        const sections = [
            qaBuildScratchNarrativeSentence("morning", safe.morning_note || ""),
            qaBuildScratchNarrativeSentence("updates", safe.diary_updates || ""),
            qaBuildScratchNarrativeSentence("evening", safe.evening_note || ""),
        ].filter(Boolean);
        if (!sections.length) return;
        const replace = freshness !== "fresh";
        sections.forEach((sentence, index) => {{
            qaInjectNarrativeSentence(sentence, {{ replace: replace && index === 0 }});
        }});
    }}

    let qaRenderStatusToken = "";
    let qaRenderStatusInFlight = false;

    function qaShouldSkipLivePatch(sectionEl) {{
        if (!sectionEl) return true;
        if (dashboardIsBusyForRefresh()) return true;
        const active = document.activeElement;
        if (active && typeof sectionEl.contains === "function" && sectionEl.contains(active)) {{
            const tag = String(active.tagName || "").toUpperCase();
            if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || active.isContentEditable) {{
                return true;
            }}
        }}
        return false;
    }}

    function qaCaptureScratchDrafts(sectionEl) {{
        const drafts = [];
        if (!sectionEl) return drafts;
        sectionEl.querySelectorAll("textarea[data-storage-key]").forEach((ta) => {{
            drafts.push({{
                key: String(ta.dataset.storageKey || ""),
                value: String(ta.value || ""),
                id: String(ta.id || ""),
            }});
        }});
        return drafts;
    }}

    function qaRestoreScratchDrafts(sectionEl, drafts) {{
        if (!sectionEl || !Array.isArray(drafts) || !drafts.length) return;
        const textareas = Array.from(sectionEl.querySelectorAll("textarea[data-storage-key]"));
        drafts.forEach((entry) => {{
            const key = String(entry && entry.key || "");
            const value = String(entry && entry.value || "");
            if (!key || !value) return;
            const match = textareas.find((ta) => String(ta.dataset.storageKey || "") === key || String(ta.id || "") === String(entry.id || ""));
            if (match) {{
                match.value = value;
            }}
        }});
    }}

    function qaPatchSectionFromDoc(doc, sectionId) {{
        const current = document.getElementById(sectionId);
        const incoming = doc ? doc.getElementById(sectionId) : null;
        if (!current || !incoming) return false;
        if (qaShouldSkipLivePatch(current)) return false;
        const drafts = qaCaptureScratchDrafts(current);
        current.innerHTML = incoming.innerHTML;
        qaRestoreScratchDrafts(current, drafts);
        return true;
    }}

    function qaPatchNarrativeFromDoc(doc) {{
        const current = document.getElementById("qa-day-narrative-body");
        const incoming = doc ? doc.getElementById("qa-day-narrative-body") : null;
        if (!current || !incoming) return false;
        const parentSection = current.closest("section");
        if (parentSection && qaShouldSkipLivePatch(parentSection)) return false;
        current.innerHTML = incoming.innerHTML;
        return true;
    }}

    async function qaFetchDashboardHtmlDoc() {{
        const targetUrl = `${{QA_API_BASE}}/dashboard?_=${{Date.now()}}`;
        const headers = new Headers();
        if (QA_API_TOKEN) headers.set("Authorization", `Bearer ${{QA_API_TOKEN}}`);
        const response = await fetch(targetUrl, {{
            method: "GET",
            headers,
            credentials: "include",
            cache: "no-store",
        }});
        if (!response.ok) return null;
        const htmlText = await response.text();
        if (!htmlText) return null;
        const parser = new DOMParser();
        return parser.parseFromString(htmlText, "text/html");
    }}

    async function qaPullRenderedSections(reason = "render_status") {{
        const doc = await qaFetchDashboardHtmlDoc();
        if (!doc) return false;
        const patched = [
            qaPatchSectionFromDoc(doc, "morning"),
            qaPatchSectionFromDoc(doc, "updates"),
            qaPatchSectionFromDoc(doc, "evening"),
            qaPatchNarrativeFromDoc(doc),
        ].some(Boolean);
        if (patched) {{
            qaApplyLocalCompletionUi();
            qaLoadScratchPads();
            const status = document.getElementById("qa-status");
            if (status) {{
                status.textContent = reason === "scratch" ? "✅ Dashboard sections refreshed." : "🔄 Synced latest sections.";
                status.style.color = "#93c5fd";
            }}
        }}
        return patched;
    }}

    async function qaSyncRenderStatus(options = {{}}) {{
        const force = Boolean(options && options.force);
        if (!force && qaIsLiveSyncPaused()) return;
        if (!qaCanRunNetworkPoll({{ force }})) return;
        if (qaRenderStatusInFlight) return;
        qaRenderStatusInFlight = true;
        try {{
            const payload = await qaGet("/v1/ui/render/status", {{ coalesce: true }});
            const render = (payload && payload.render && typeof payload.render === "object") ? payload.render : null;
            if (!render) return;
            const token = String(render.render_token || "").trim();
            if (!token) return;
            if (!qaRenderStatusToken) {{
                qaRenderStatusToken = token;
                return;
            }}
            if (token === qaRenderStatusToken) return;
            qaRenderStatusToken = token;
            await qaPullRenderedSections(force ? "scratch" : "render_status");
        }} catch (_err) {{
            // Best-effort sync only; keep dashboard usable when API/html pull is unavailable.
        }} finally {{
            qaRenderStatusInFlight = false;
        }}
    }}

    function qaApplyLiveToday(today) {{
        const snapshot = (today && typeof today === "object") ? today : null;
        if (!snapshot) return;
        qaSetServerEffectiveDate(snapshot.effective_date || snapshot.date || "");
        if (snapshot.end_day && typeof snapshot.end_day === "object") {{
            qaApplyEndDayState(snapshot.end_day);
        }}
        const anxietyBusy = Boolean(qaAnxietySaveInFlight || qaAnxietyPendingScore !== null || qaAnxietySaveTimer);
        const liveScore = Number(snapshot.anxiety_reduction_score);
        if (!anxietyBusy && Number.isFinite(liveScore)) {{
            qaApplyAnxietyScore(liveScore);
            qaSetAnxietySaveState("synced");
        }} else if (!anxietyBusy) {{
            qaCurrentAnxietyScore = null;
        }}
        if (snapshot.workout_checklist && typeof snapshot.workout_checklist === "object") {{
            qaApplyWorkoutChecklistState(snapshot.workout_checklist);
        }}
        if (snapshot.workout_checklist_signals && typeof snapshot.workout_checklist_signals === "object") {{
            qaApplyWorkoutChecklistSignals(snapshot.workout_checklist_signals);
        }}
        if (snapshot.workout_progression && typeof snapshot.workout_progression === "object") {{
            qaApplyWorkoutProgression(snapshot.workout_progression);
        }}
        if (snapshot.workout_progression_weights && typeof snapshot.workout_progression_weights === "object") {{
            qaApplyWeightsProgression(snapshot.workout_progression_weights);
        }}
        if (!qaWorkoutSaving && snapshot.workout && typeof snapshot.workout === "object") {{
            const done = Boolean(snapshot.workout.done);
            const rawLabel = String(snapshot.workout.workout || "").trim();
            const workoutType = String(snapshot.workout.type || "").toLowerCase();
            if (workoutType) {{
                qaCurrentWorkoutType = workoutType;
            }}
            qaCurrentWorkoutDone = done;
            const workoutLabel = rawLabel || (
                String(snapshot.workout.type || "").toLowerCase() === "yoga" ? "Yoga"
                    : String(snapshot.workout.type || "").toLowerCase() === "weights" ? "Workout"
                    : "Workout"
            );
            qaApplyWorkoutState(done, workoutLabel);
        }}
        if (!qaMindfulnessSaving && snapshot.mindfulness && typeof snapshot.mindfulness === "object") {{
            const updated = Object.assign({{}}, snapshot.mindfulness);
            if (snapshot.mental_health_progression && typeof snapshot.mental_health_progression === "object") {{
                updated.progression = snapshot.mental_health_progression;
            }}
            qaApplyMindfulnessState(updated);
        }}
        if (!qaMoodSaving && snapshot.mood_checkin && typeof snapshot.mood_checkin === "object") {{
            qaApplyMoodState(snapshot.mood_checkin);
            qaSetMoodSaveState("synced");
        }}
        if (Array.isArray(snapshot.calendar)) {{
            qaApplyCalendarState(snapshot.calendar);
        }}
        qaUpdateFreshnessFromToday(snapshot);
        qaApplyNarrativeFromToday(snapshot);
        qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
    }}

    function qaApplyCalendarState(events) {{
        const container = document.getElementById("qa-calendar-body");
        if (!container) return;
        if (!events || events.length === 0) {{
            container.innerHTML = '<p class="text-sm" style="color:#6b7280">No events today</p>';
            return;
        }}
        const blocks = [
            {{ label: "Morning (6am\u201312pm)", min: 6, max: 12 }},
            {{ label: "Afternoon (12pm\u20135pm)", min: 12, max: 17 }},
            {{ label: "Evening (5pm\u20139pm)", min: 17, max: 21 }},
            {{ label: "Night (9pm\u20136am)", min: 21, max: 30 }},
        ];
        const allDay = events.filter(e => e.time === "All day");
        const timed = events.filter(e => e.time !== "All day");
        function eventEmoji(e) {{
            if (e.type === "task") return "📌";
            if (e.type === "work") return "💼";
            return "📅";
        }}
        function eventColor(e) {{
            if (e.type === "task") return "#fbbf24";
            if (e.type === "work") return "#93c5fd";
            return "#e5e7eb";
        }}
        function renderEvent(e) {{
            return `<div class="flex items-center gap-2 text-sm ml-2">
                <span class="w-14 font-mono text-xs" style="color:#9ca3af">${{e.time}}</span>
                <span style="font-size:0.9rem">${{eventEmoji(e)}}</span>
                <span style="color:${{eventColor(e)}}">${{e.event}}</span>
            </div>`;
        }}
        let html = "";
        if (allDay.length) {{
            html += `<div class="mb-3"><div class="text-xs font-semibold mb-1" style="color:#6b7280">All day</div>`;
            allDay.forEach(e => {{ html += renderEvent(e); }});
            html += "</div>";
        }}
        blocks.forEach(block => {{
            const evs = timed.filter(e => {{
                const rawHour = (e.hour !== undefined && e.hour >= 0) ? e.hour : parseInt(e.time.split(":")[0], 10);
                if (Number.isNaN(rawHour)) return false;
                const h = rawHour < 6 ? rawHour + 24 : rawHour;
                return h >= block.min && h < block.max;
            }});
            if (!evs.length) return;
            html += `<div class="mb-3"><div class="text-xs font-semibold mb-1" style="color:#6b7280">${{block.label}}</div>`;
            evs.forEach(e => {{ html += renderEvent(e); }});
            html += "</div>";
        }});
        container.innerHTML = html;
    }}

    function qaHandleLiveMessage(message) {{
        if (!message || typeof message !== "object") return;
        if (String(message.tab_id || "") === QA_TAB_ID) return;
        const kind = String(message.kind || "").toLowerCase();
        if (kind === "system" && message.payload && typeof message.payload === "object") {{
            qaUpdateSystemStatus(message.payload);
            return;
        }}
        if (kind === "today" && message.payload && typeof message.payload === "object") {{
            const envelope = qaParseTodayEnvelope(message.payload);
            if (!envelope || !envelope.today) return;
            if (!qaEnvelopeIsToday(envelope)) {{
                try {{
                    localStorage.removeItem(QA_LEADER_TODAY_KEY);
                }} catch (_err) {{}}
                return;
            }}
            qaApplyLiveToday(envelope.today);
            return;
        }}
        if (kind === "leader") {{
            const lease = qaReadLeaderLease();
            const leaseTab = lease && typeof lease.tab_id === "string" ? lease.tab_id : "";
            if (leaseTab && leaseTab !== QA_TAB_ID) {{
                qaIsPollLeader = false;
            }}
        }}
    }}

    function qaStartLeaderCoordination() {{
        qaLoadLeaderModeSetting();
        if (!qaLeaderModeEnabled()) {{
            qaIsPollLeader = false;
            return;
        }}
        try {{
            if (typeof BroadcastChannel !== "undefined") {{
                qaLeaderBroadcast = new BroadcastChannel(QA_LEADER_CHANNEL_NAME);
                qaLeaderBroadcast.onmessage = (event) => qaHandleLiveMessage(event ? event.data : null);
            }}
        }} catch (_err) {{
            qaLeaderBroadcast = null;
        }}

        const applyCached = (key) => {{
            try {{
                const row = qaParseJson(localStorage.getItem(key), null);
                if (!row) return;
                if (key === QA_LEADER_TODAY_KEY) {{
                    const envelope = qaParseTodayEnvelope(row.payload);
                    if (!envelope || !qaEnvelopeIsToday(envelope)) {{
                        try {{
                            localStorage.removeItem(key);
                        }} catch (_err) {{}}
                        return;
                    }}
                    row.payload = envelope;
                }}
                if (row) qaHandleLiveMessage(row);
            }} catch (_err) {{}}
        }};
        applyCached(QA_LEADER_SYSTEM_KEY);
        applyCached(QA_LEADER_TODAY_KEY);

        qaTryAcquireLeader("startup");
        if (qaLeaderHeartbeatHandle) {{
            clearInterval(qaLeaderHeartbeatHandle);
        }}
        qaLeaderHeartbeatHandle = window.setInterval(() => {{
            if (!qaLeaderModeEnabled()) return;
            if (qaIsPollLeader) {{
                qaBecomeLeader("heartbeat");
                return;
            }}
            qaTryAcquireLeader("contender");
        }}, QA_LEADER_HEARTBEAT_MS);

        window.addEventListener("storage", (event) => {{
            if (!event) return;
            const key = String(event.key || "");
            if (key === QA_LEADER_LEASE_KEY && qaLeaderModeEnabled()) {{
                const lease = qaParseJson(event.newValue || "", null);
                const leaseTab = lease && typeof lease.tab_id === "string" ? lease.tab_id : "";
                const leaseExpiry = lease ? Number(lease.expires_at || 0) : 0;
                if (leaseTab && leaseTab !== QA_TAB_ID && leaseExpiry > Date.now()) {{
                    qaIsPollLeader = false;
                }} else if (!qaIsPollLeader) {{
                    qaTryAcquireLeader("storage");
                }}
                return;
            }}
            if ((key === QA_LEADER_SYSTEM_KEY || key === QA_LEADER_TODAY_KEY) && event.newValue) {{
                qaHandleLiveMessage(qaParseJson(event.newValue, null));
            }}
        }});
    }}

    function getTodayKey() {{
        const now = new Date();
        const effective = new Date(now.getTime());
        // Mirror backend effective-date rollover: before 03:00 counts as previous day.
        if (now.getHours() < 3) {{
            effective.setDate(effective.getDate() - 1);
        }}
        const year = String(effective.getFullYear());
        const month = String(effective.getMonth() + 1).padStart(2, "0");
        const day = String(effective.getDate()).padStart(2, "0");
        return `${{year}}-${{month}}-${{day}}`;
    }}

    function qaSetServerEffectiveDate(rawDate) {{
        const value = String(rawDate || "").trim();
        if (/^\d{{4}}-\d{{2}}-\d{{2}}$/.test(value)) {{
            qaServerEffectiveDate = value;
        }}
    }}

    function qaEffectiveDateKey() {{
        const key = String(qaServerEffectiveDate || "").trim() || getTodayKey();
        return key || QA_MINDFULNESS_DATE;
    }}

    function qaHandleAuthFailure() {{
        const status = document.getElementById("qa-status");
        if (status) {{
            status.textContent = "🔐 Session expired. Reloading secured dashboard...";
            status.style.color = "#fbbf24";
        }}
        setTimeout(() => {{
            try {{
                window.location.replace(`${{QA_API_BASE}}/dashboard?reauth=1`);
            }} catch (_err) {{}}
        }}, 180);
    }}

    async function qaFetchWithTimeout(path, options = {{}}, timeoutMs = 9000) {{
        const ms = Math.max(1500, Number(timeoutMs) || 9000);
        const supportsAbort = typeof AbortController !== "undefined";
        let controller = null;
        const finalOptions = Object.assign({{}}, options, {{
            credentials: "include",
        }});
        if (supportsAbort) {{
            controller = new AbortController();
            finalOptions.signal = controller.signal;
        }}
        let timer = null;
        const timeoutPromise = new Promise((_, reject) => {{
            timer = setTimeout(() => {{
                try {{
                    if (controller && typeof controller.abort === "function") controller.abort();
                }} catch (_err) {{}}
                const err = new Error("Request timed out");
                err.name = "TimeoutError";
                reject(err);
            }}, ms);
        }});
        try {{
            return await Promise.race([
                fetch(`${{QA_API_BASE}}${{path}}`, finalOptions),
                timeoutPromise,
            ]);
        }} finally {{
            if (timer) clearTimeout(timer);
        }}
    }}

    async function qaGet(path, options = {{}}) {{
        const status = document.getElementById("qa-status");
        const isFileProtocol = typeof window !== "undefined" && window.location && (window.location.protocol || "").toLowerCase() === "file:";
        const requestPath = String(path || "").trim();
        const coalesce = !options || options.coalesce !== false;
        const key = requestPath || String(path || "");
        if (coalesce) {{
            const existing = qaGetInFlight.get(key);
            if (existing) {{
                return existing;
            }}
        }}

        window.__qaPendingRequests = Number(window.__qaPendingRequests || 0) + 1;
        let requestPromise = null;
        requestPromise = (async () => {{
            try {{
                const response = await qaFetchWithTimeout(requestPath, {{
                    method: "GET",
                    headers: (typeof QA_API_TOKEN !== "undefined" && QA_API_TOKEN ? {{ "Authorization": "Bearer " + QA_API_TOKEN }} : {{}})
                }}, 12000);
                const text = await response.text();
                let data = null;
                try {{
                    data = JSON.parse(text);
                }} catch (_err) {{
                    data = {{ detail: text }};
                }}
                if (response.status === 401) {{
                    qaHandleAuthFailure();
                    return null;
                }}
                if (!response.ok) {{
                    return null;
                }}
                return data;
            }} catch (_err) {{
                // file:// protocol: API sync is best-effort, data is pre-embedded — fail silently
                if (isFileProtocol) {{
                    return null;
                }}
                if (status) {{
                    status.textContent = "⏸️ API unavailable — using cached data";
                    status.style.color = "#9ca3af";
                }}
                return null;
            }} finally {{
                window.__qaPendingRequests = Math.max(0, Number(window.__qaPendingRequests || 1) - 1);
                if (coalesce) {{
                    const current = qaGetInFlight.get(key);
                    if (current === requestPromise) {{
                        qaGetInFlight.delete(key);
                    }}
                }}
            }}
        }})();
        if (coalesce) {{
            qaGetInFlight.set(key, requestPromise);
        }}
        return requestPromise;
    }}

    async function qaPost(path, payload) {{
        const status = document.getElementById("qa-status");
        if (status) {{
            status.textContent = "⏳ Sending...";
            status.style.color = "#93c5fd";
        }}
        window.__qaPendingRequests = Number(window.__qaPendingRequests || 0) + 1;
        try {{
            const response = await qaFetchWithTimeout(path, {{
                method: "POST",
                headers: Object.assign(
                    {{ "Content-Type": "application/json" }},
                    (typeof QA_API_TOKEN !== "undefined" && QA_API_TOKEN ? {{ "Authorization": "Bearer " + QA_API_TOKEN }} : {{}})
                ),
                body: JSON.stringify(payload)
            }}, 9000);
            const text = await response.text();
            let data = null;
            try {{
                data = JSON.parse(text);
            }} catch (_err) {{
                data = {{ detail: text }};
            }}
            if (response.status === 401) {{
                qaHandleAuthFailure();
                return null;
            }}
            if (!response.ok) {{
                const detail = (data && (data.detail || data.message)) ? JSON.stringify(data.detail || data.message) : `HTTP ${{response.status}}`;
                if (status) {{
                    status.textContent = "❌ " + detail;
                    status.style.color = "#fca5a5";
                }}
                return null;
            }}
            if (status) {{
                status.textContent = "✅ Saved";
                status.style.color = "#6ee7b7";
            }}
            return data;
        }} catch (err) {{
            const timeoutNames = new Set(["aborterror", "timeouterror"]);
            const timeout = err && timeoutNames.has(String(err.name || "").toLowerCase());
            if (status) {{
                status.textContent = timeout
                    ? "⏱️ Request timed out. Reload dashboard and retry."
                    : "❌ API unavailable: " + err.message;
                status.style.color = "#fca5a5";
            }}
            return null;
        }} finally {{
            window.__qaPendingRequests = Math.max(0, Number(window.__qaPendingRequests || 1) - 1);
        }}
    }}

    function qaDelay(ms) {{
        return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
    }}

    async function qaPostWithRetry(path, payload, options = {{}}) {{
        const retriesRaw = Number(options.retries);
        const retries = Number.isFinite(retriesRaw) ? Math.max(0, Math.min(3, Math.round(retriesRaw))) : 1;
        const backoffRaw = Number(options.backoffMs);
        const backoffMs = Number.isFinite(backoffRaw) ? Math.max(120, backoffRaw) : 380;
        const label = String(options.label || "save");
        const status = document.getElementById("qa-status");

        for (let attempt = 0; attempt <= retries; attempt += 1) {{
            const data = await qaPost(path, payload);
            if (data) return data;
            if (attempt < retries) {{
                if (status) {{
                    status.textContent = `↻ Retrying ${{label}}...`;
                    status.style.color = "#fbbf24";
                }}
                await qaDelay(backoffMs * (attempt + 1));
            }}
        }}
        return null;
    }}

    function qaLoadSyncPauseState() {{
        let value = 0;
        try {{
            value = Number(localStorage.getItem(QA_SYNC_PAUSE_KEY) || "0");
        }} catch (_err) {{
            value = 0;
        }}
        if (!Number.isFinite(value) || value <= Date.now()) {{
            qaLiveSyncPausedUntil = 0;
            try {{
                localStorage.removeItem(QA_SYNC_PAUSE_KEY);
            }} catch (_err) {{}}
            return;
        }}
        qaLiveSyncPausedUntil = value;
    }}

    function qaIsLiveSyncPaused() {{
        return Number.isFinite(qaLiveSyncPausedUntil) && qaLiveSyncPausedUntil > Date.now();
    }}

    function qaUpdateSyncPauseUi() {{
        const meta = document.getElementById("qa-sync-pause-meta");
        const btn10 = document.getElementById("qa-sync-pause-10");
        const btn30 = document.getElementById("qa-sync-pause-30");
        const btnResume = document.getElementById("qa-sync-resume");
        const paused = qaIsLiveSyncPaused();
        const remainMs = Math.max(0, qaLiveSyncPausedUntil - Date.now());
        const remainMin = Math.ceil(remainMs / 60000);
        if (meta) {{
            meta.textContent = paused ? `Live sync paused (${{remainMin}}m left)` : "Live sync active";
            meta.style.color = paused ? "#fbbf24" : "#94a3b8";
        }}
        if (btn10) {{
            btn10.style.opacity = paused ? "0.8" : "1";
        }}
        if (btn30) {{
            btn30.style.opacity = paused ? "0.8" : "1";
        }}
        if (btnResume) {{
            btnResume.style.opacity = paused ? "1" : "0.85";
        }}
    }}

    function qaSetSyncPause(minutes) {{
        const minsRaw = Number(minutes);
        const mins = Number.isFinite(minsRaw) ? Math.max(0, Math.round(minsRaw)) : 0;
        if (mins <= 0) {{
            qaLiveSyncPausedUntil = 0;
            try {{
                localStorage.removeItem(QA_SYNC_PAUSE_KEY);
            }} catch (_err) {{}}
            const status = document.getElementById("qa-status");
            if (status) {{
                status.textContent = "✅ Live sync resumed";
                status.style.color = "#6ee7b7";
            }}
            qaUpdateSyncPauseUi();
            qaSyncTodayFromApi({{ force: true }});
            qaSyncRenderStatus({{ force: true }});
            if (typeof window.pollSystemStatus === "function") {{
                window.pollSystemStatus();
            }} else if (typeof pollSystemStatus === "function") {{
                pollSystemStatus();
            }}
            return;
        }}
        qaLiveSyncPausedUntil = Date.now() + (mins * 60 * 1000);
        try {{
            localStorage.setItem(QA_SYNC_PAUSE_KEY, String(qaLiveSyncPausedUntil));
        }} catch (_err) {{}}
        const status = document.getElementById("qa-status");
        if (status) {{
            status.textContent = `📖 Live sync paused for ${{mins}}m`;
            status.style.color = "#fbbf24";
        }}
        qaUpdateSyncPauseUi();
    }}

    function qaNormalizeFreshLevel(level) {{
        const raw = String(level || "").toLowerCase();
        return ["ok", "info", "warn", "error"].includes(raw) ? raw : "info";
    }}

    function qaFreshLevelColor(level) {{
        const normalized = qaNormalizeFreshLevel(level);
        if (normalized === "ok") return "#6ee7b7";
        if (normalized === "warn") return "#fbbf24";
        if (normalized === "error") return "#fca5a5";
        return "#93c5fd";
    }}

    function qaSetFreshnessLine(id, text, level) {{
        const el = document.getElementById(id);
        if (!el) return;
        const normalized = qaNormalizeFreshLevel(level);
        el.dataset.level = normalized;
        el.textContent = String(text || "").trim();
        el.style.color = qaFreshLevelColor(normalized);
    }}

    function qaSetBackendPill(id, text, level, title = "", shortText = "") {{
        const el = document.getElementById(id);
        if (!el) return;
        const normalized = qaNormalizeFreshLevel(level);
        const fullLabel = String(text || "").trim();
        const shortLabel = String(shortText || "").trim() || fullLabel;
        el.dataset.level = normalized;
        el.dataset.fullLabel = fullLabel;
        el.dataset.shortLabel = shortLabel;
        el.textContent = qaBackendPillTextForViewport(el);
        el.style.color = "";
        el.title = title ? String(title) : "";
    }}

    function qaBackendPillTextForViewport(el) {{
        if (!el) return "";
        const fullLabel = String(el.dataset.fullLabel || el.textContent || "").trim();
        const shortLabel = String(el.dataset.shortLabel || fullLabel).trim() || fullLabel;
        return window.innerWidth <= 640 ? shortLabel : fullLabel;
    }}

    function qaCompactAiPathPillLabel(line) {{
        const raw = String(line || "").trim();
        const lower = raw.toLowerCase();
        if (lower.includes("last run:")) {{
            const label = raw.split(":").slice(1).join(":").split("•")[0].trim();
            if (label) return `🤖 ${{label}}`;
        }}
        if (lower.includes("no calls yet")) return "🤖 Ready";
        if (lower.includes("unavailable")) return "🤖 AI path";
        return "🤖 AI";
    }}

    function qaCompactAiPathPillShortLabel(line) {{
        const full = qaCompactAiPathPillLabel(line).toLowerCase();
        if (full.includes("codex cli")) return "🤖 CLI";
        if (full.includes("claude")) return "🤖 Claude";
        if (full.includes("ready")) return "🤖 Ready";
        return "🤖 AI";
    }}

    function qaCompactFreshnessPillLabel(level) {{
        const normalized = qaNormalizeFreshLevel(level);
        if (normalized === "ok") return "🧭 Fresh";
        if (normalized === "warn") return "🧭 Attention";
        if (normalized === "error") return "🧭 Stale";
        return "🧭 Watching";
    }}

    function qaCompactFreshnessPillShortLabel(level) {{
        const normalized = qaNormalizeFreshLevel(level);
        if (normalized === "ok") return "🧭 Fresh";
        if (normalized === "warn") return "🧭 Alert";
        if (normalized === "error") return "🧭 Stale";
        return "🧭 Watch";
    }}

    function qaApplyBackendPillVisibility() {{
        const summary = document.getElementById("qa-backend-summary-pill");
        const detailPills = Array.from(document.querySelectorAll(".backend-pill-detail"));
        if (!detailPills.length) return;
        const rank = {{ ok: 0, info: 1, warn: 2, error: 3 }};
        let worstLevel = "ok";
        let attentionCount = 0;
        const summaryTitleBits = [];
        detailPills.forEach((el) => {{
            const level = qaNormalizeFreshLevel(el.dataset.level || "info");
            if ((rank[level] ?? 1) > (rank[worstLevel] ?? 0)) {{
                worstLevel = level;
            }}
            if (level === "warn" || level === "error") {{
                attentionCount += 1;
            }}
            const fullLabel = String(el.dataset.fullLabel || el.textContent || "").trim();
            const title = String(el.title || "").trim();
            el.textContent = qaBackendPillTextForViewport(el);
            summaryTitleBits.push(title ? `${{fullLabel}} — ${{title}}` : fullLabel);
        }});
        const showDetails = attentionCount > 0;
        const summaryFull = {{
            ok: "🟢 Live ok",
            info: "🔵 Live watching",
            warn: attentionCount ? `🟡 Live attention ${{attentionCount}}` : "🟡 Live attention",
            error: attentionCount ? `🔴 Live alert ${{attentionCount}}` : "🔴 Live alert",
        }}[worstLevel] || "🔵 Live watching";
        const summaryShort = {{
            ok: "🟢 Live",
            info: "🔵 Live",
            warn: "🟡 Live",
            error: "🔴 Live",
        }}[worstLevel] || "🔵 Live";
        if (summary) {{
            summary.dataset.level = worstLevel;
            summary.dataset.fullLabel = summaryFull;
            summary.dataset.shortLabel = summaryShort;
            summary.title = summaryTitleBits.join(" • ");
            summary.textContent = qaBackendPillTextForViewport(summary);
            summary.hidden = showDetails;
        }}
        detailPills.forEach((el) => {{
            el.hidden = !showDetails;
        }});
        const row = (summary && summary.closest(".backend-pill-row"))
            || (detailPills[0] && detailPills[0].closest(".backend-pill-row"));
        if (row) {{
            row.dataset.mode = showDetails ? "detail" : "summary";
        }}
    }}

    function qaUpdateBackendSummaryPills(snapshot) {{
        const safe = (snapshot && typeof snapshot === "object") ? snapshot : null;
        if (!safe) return;
        const freshness = (safe.freshness && typeof safe.freshness === "object") ? safe.freshness : null;
        if (freshness && freshness.ai_path && typeof freshness.ai_path === "object") {{
            const aiLine = String(freshness.ai_path.line || "").trim();
            const aiLevel = qaNormalizeFreshLevel(freshness.ai_path.level || "info");
            qaSetBackendPill(
                "qa-fresh-ai-path-inline",
                qaCompactAiPathPillLabel(aiLine),
                aiLevel,
                aiLine,
                qaCompactAiPathPillShortLabel(aiLine),
            );
        }}
        if (freshness && freshness.overall && typeof freshness.overall === "object") {{
            const overallLine = String(freshness.overall.line || "").trim();
            const overallLevel = qaNormalizeFreshLevel(freshness.overall.level || "info");
            qaSetBackendPill(
                "qa-backend-fresh-pill",
                qaCompactFreshnessPillLabel(overallLevel),
                overallLevel,
                overallLine,
                qaCompactFreshnessPillShortLabel(overallLevel),
            );
        }}
        const sectionRegistry = (safe.section_freshness && typeof safe.section_freshness === "object")
            ? safe.section_freshness
            : ((freshness && freshness.sections && typeof freshness.sections === "object") ? freshness.sections : null);
        if (sectionRegistry) {{
            const sectionLevel = qaNormalizeFreshLevel(sectionRegistry.worst_level || "info");
            const attentionCount = Number(sectionRegistry.attention_count || 0);
            const counts = (sectionRegistry.counts && typeof sectionRegistry.counts === "object") ? sectionRegistry.counts : {{}};
            const sectionLabel = attentionCount ? `🧭 Sections ${{attentionCount}}` : "🧭 Sections ok";
            const sectionShortLabel = attentionCount ? `🧭 Sect ${{attentionCount}}` : "🧭 Sect ok";
            const sectionTitle = `Section freshness • attention ${{attentionCount}} • ok ${{counts.ok || 0}} • info ${{counts.info || 0}} • warn ${{counts.warn || 0}} • error ${{counts.error || 0}}`;
            qaSetBackendPill("qa-backend-sections-pill", sectionLabel, sectionLevel, sectionTitle, sectionShortLabel);
        }}
        if (safe.apple_notes_ideas && typeof safe.apple_notes_ideas === "object") {{
            const ideas = safe.apple_notes_ideas;
            const ideasCounts = (ideas.counts && typeof ideas.counts === "object") ? ideas.counts : {{}};
            const ideasStatus = String(ideas.status || "").trim().toLowerCase() || "unknown";
            const ideasNew = Number(ideasCounts.new_items ?? ideas.new_items_count ?? 0) || 0;
            const ideasCreated = Number(ideasCounts.beads_created ?? 0) || 0;
            const ideasFailed = Number(ideasCounts.beads_failed ?? 0) || 0;
            const ideasRetried = Number(ideasCounts.retried ?? 0) || 0;
            const ideasQueue = Number(ideas.retry_queue_count ?? 0) || 0;
            const ideasLastRun = String(ideas.last_run || "").trim();
            let ideasLevel = "ok";
            let ideasLabel = "💡 Ideas ok";
            let ideasShortLabel = "💡 ok";
            if (!["success", "ok"].includes(ideasStatus)) {{
                ideasLevel = ideasStatus === "error" ? "error" : "warn";
                ideasLabel = "💡 Ideas issue";
                ideasShortLabel = "💡 issue";
            }} else if (ideasFailed || ideasQueue) {{
                ideasLevel = "warn";
                ideasLabel = "💡 Ideas retry";
                ideasShortLabel = "💡 retry";
            }} else if (ideasNew || ideasCreated) {{
                ideasLevel = "ok";
                ideasLabel = `💡 ${{ideasNew || ideasCreated}} new`;
                ideasShortLabel = ideasLabel;
            }} else if (ideasRetried) {{
                ideasLevel = "info";
                ideasLabel = "💡 Ideas checked";
                ideasShortLabel = "💡 checked";
            }}
            if (ideasLastRun) {{
                const hm = qaClockHm(ideasLastRun);
                if (hm) ideasLabel += ` ${{hm}}`;
            }}
            const ideasTitle = `status ${{ideasStatus}} • new ${{ideasNew}} • beads ${{ideasCreated}} • failed ${{ideasFailed}} • retried ${{ideasRetried}} • queue ${{ideasQueue}}${{ideasLastRun ? ` • last run ${{ideasLastRun}}` : ""}}`;
            qaSetBackendPill("qa-backend-ideas-pill", ideasLabel, ideasLevel, ideasTitle, ideasShortLabel);
        }}
        qaApplyBackendPillVisibility();
    }}

    function qaEscapeHtml(value) {{
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }}

    function qaClockHm(raw) {{
        const text = String(raw || "").trim();
        if (!text) return "";
        const isoMatch = text.match(/T(\d{{2}}:\d{{2}})/);
        if (isoMatch) return isoMatch[1];
        return text.slice(0, 16);
    }}

    function qaBuildSectionFreshnessHtml(registry) {{
        const safe = (registry && typeof registry === "object") ? registry : null;
        const ordered = safe && Array.isArray(safe.ordered) ? safe.ordered : [];
        if (!ordered.length) return "";
        const counts = safe && safe.counts && typeof safe.counts === "object" ? safe.counts : {{}};
        const attentionCount = Number(safe.attention_count || 0);
        const worstLevel = qaNormalizeFreshLevel(safe.worst_level || "info");
        const summaryLabel = attentionCount
            ? `🧭 Section freshness (${{attentionCount}} need attention)`
            : "🧭 Section freshness (all monitored)";
        const summaryColour = {{
            ok: "#a7f3d0",
            info: "#93c5fd",
            warn: "#fde68a",
            error: "#fca5a5",
        }}[worstLevel] || "#93c5fd";
        const toneMap = {{
            ok: ["🟢", "#a7f3d0", "rgba(6,95,70,0.22)", "rgba(110,231,183,0.22)"],
            info: ["🔵", "#bfdbfe", "rgba(30,64,175,0.18)", "rgba(147,197,253,0.22)"],
            warn: ["🟡", "#fde68a", "rgba(120,53,15,0.22)", "rgba(251,191,36,0.22)"],
            error: ["🔴", "#fca5a5", "rgba(127,29,29,0.22)", "rgba(239,68,68,0.22)"],
        }};
        const rowsHtml = ordered.map((rawItem) => {{
            const item = (rawItem && typeof rawItem === "object") ? rawItem : {{}};
            const level = qaNormalizeFreshLevel(item.level || item.freshness_state || "info");
            const tone = toneMap[level] || toneMap.info;
            const metaBits = [];
            const sourceDate = String(item.source_date || "").trim();
            const updatedAt = String(item.updated_at || "").trim();
            const staleReason = String(item.stale_reason || "").trim();
            if (sourceDate) metaBits.push(`source ${{qaEscapeHtml(sourceDate)}}`);
            if (updatedAt) metaBits.push(`updated ${{qaEscapeHtml(qaClockHm(updatedAt) || updatedAt.slice(0, 16))}}`);
            if (item.fallback_in_use) metaBits.push("fallback");
            const metaHtml = metaBits.length
                ? `<p class="text-xs mt-1" style="color:#94a3b8">${{metaBits.join(" • ")}}</p>`
                : "";
            const reasonHtml = (staleReason && (level === "warn" || level === "error"))
                ? `<p class="text-xs mt-1" style="color:#fcd34d">${{qaEscapeHtml(staleReason)}}</p>`
                : "";
            return `<div class="rounded-lg px-3 py-2.5" style="border:1px solid ${{tone[3]}}; background:${{tone[2]}};">`
                + `<div class="flex items-center gap-2 flex-wrap"><span class="text-xs font-semibold" style="color:${{tone[1]}}">${{tone[0]}} ${{qaEscapeHtml(item.label || item.id || "Section")}}</span></div>`
                + `<p class="text-xs mt-1" style="color:#e5e7eb">${{qaEscapeHtml(item.line || "No freshness note.")}}</p>`
                + metaHtml
                + reasonHtml
                + `</div>`;
        }}).join("");
        const countsLabel = `ok ${{counts.ok || 0}} • info ${{counts.info || 0}} • warn ${{counts.warn || 0}} • error ${{counts.error || 0}}`;
        const openAttr = attentionCount ? " open" : "";
        return `<div class="card mt-2" style="border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.58);">`
            + `<details${{openAttr}}>`
            + `<summary class="text-sm font-semibold cursor-pointer" style="color: ${{summaryColour}};">${{qaEscapeHtml(summaryLabel)}}</summary>`
            + `<p class="text-xs mt-2" style="color:#94a3b8">Every major card now reports its own freshness state • ${{qaEscapeHtml(countsLabel)}}</p>`
            + `<div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">${{rowsHtml}}</div>`
            + `</details></div>`;
    }}

    function qaUpdateSectionFreshnessFromToday(today) {{
        const wrap = document.getElementById("qa-section-freshness-wrap");
        if (!wrap) return;
        const snapshot = (today && typeof today === "object") ? today : null;
        if (!snapshot) return;
        const registry = (snapshot.section_freshness && typeof snapshot.section_freshness === "object")
            ? snapshot.section_freshness
            : ((snapshot.freshness && typeof snapshot.freshness === "object" && snapshot.freshness.sections && typeof snapshot.freshness.sections === "object")
                ? snapshot.freshness.sections
                : null);
        if (!registry) return;
        wrap.innerHTML = qaBuildSectionFreshnessHtml(registry);
    }}

    function qaUpdateStatusCardsVisibility(snapshot = null) {{
        const section = document.getElementById("qa-status-cards-section");
        const freshnessWrap = document.getElementById("qa-freshness-watch-wrap");
        const sectionWrap = document.getElementById("qa-section-freshness-wrap");
        if (!section) return;

        const safe = (snapshot && typeof snapshot === "object") ? snapshot : null;
        const freshness = (safe && safe.freshness && typeof safe.freshness === "object") ? safe.freshness : null;
        const overallLevel = freshness && freshness.overall && typeof freshness.overall === "object"
            ? qaNormalizeFreshLevel(freshness.overall.level || "info")
            : qaNormalizeFreshLevel((document.getElementById("qa-fresh-overall") || {{ dataset: {{}} }}).dataset.level || "info");
        const showFreshnessWrap = overallLevel === "warn" || overallLevel === "error";
        if (freshnessWrap) {{
            freshnessWrap.hidden = !showFreshnessWrap;
        }}

        const registry = safe && safe.section_freshness && typeof safe.section_freshness === "object"
            ? safe.section_freshness
            : (freshness && freshness.sections && typeof freshness.sections === "object" ? freshness.sections : null);
        const attentionCount = registry ? Number(registry.attention_count || 0) : Number(sectionWrap && !sectionWrap.hidden);
        const showSectionWrap = attentionCount > 0;
        if (sectionWrap) {{
            sectionWrap.hidden = !showSectionWrap;
        }}

        const ideasWrap = document.getElementById("qa-ideas-status-wrap");
        const staticCards = Number(section.dataset.staticCards || 0) || 0;
        const ideasVisible = ideasWrap ? !ideasWrap.hidden : false;
        section.hidden = !(staticCards > 0 || showFreshnessWrap || showSectionWrap || ideasVisible);
    }}

    function qaRefreshFreshnessOverall() {{
        const rank = {{ ok: 0, info: 1, warn: 2, error: 3 }};
        const levels = Object.values(qaFreshnessState || {{}}).map((v) => qaNormalizeFreshLevel(v));
        let maxLevel = "info";
        let maxRank = 1;
        for (const level of levels) {{
            const value = rank[level] ?? 1;
            if (value > maxRank) {{
                maxRank = value;
                maxLevel = level;
            }}
        }}
        let text = "🔵 Freshness auto-check: waiting for later-day inputs.";
        if (maxLevel === "ok") text = "🟢 Freshness auto-check: all clear.";
        if (maxLevel === "warn") text = "🟡 Freshness auto-check: issue detected, dashboard is guarding.";
        if (maxLevel === "error") text = "🔴 Freshness auto-check: critical issue detected.";
        qaSetFreshnessLine("qa-fresh-overall", text, maxLevel);
        const overallEl = document.getElementById("qa-fresh-overall");
        const freshDetails = document.querySelector("#qa-freshness-watch details");
        if (freshDetails) {{
            const lvl = overallEl ? (overallEl.dataset.level || "ok") : "ok";
            if (lvl === "warn" || lvl === "error") {{
                freshDetails.setAttribute("open", "");
                freshDetails.dataset.autoOpened = "1";
            }} else if (freshDetails.dataset.autoOpened === "1") {{
                freshDetails.removeAttribute("open");
                delete freshDetails.dataset.autoOpened;
            }}
        }}
    }}

    function qaPrimeFreshnessStateFromDom() {{
        const mapping = {{
            diarium: "qa-fresh-diarium",
            diarium_pickup: "qa-fresh-diarium-pickup",
            narrative: "qa-fresh-narrative",
            updates: "qa-fresh-updates",
            mood: "qa-fresh-mood",
            cache: "qa-fresh-cache",
        }};
        Object.entries(mapping).forEach(([key, id]) => {{
            const el = document.getElementById(id);
            if (!el) return;
            qaFreshnessState[key] = qaNormalizeFreshLevel(el.dataset.level || "info");
        }});
        const aiPathEl = document.getElementById("qa-fresh-ai-path");
        if (aiPathEl) {{
            qaSetFreshnessLine("qa-fresh-ai-path", aiPathEl.textContent || "", aiPathEl.dataset.level || "info");
        }}
        qaRefreshFreshnessOverall();
        qaUpdateBackendSummaryPills({{
            freshness: {{
                ai_path: aiPathEl ? {{ line: aiPathEl.textContent || "", level: aiPathEl.dataset.level || "info" }} : null,
                overall: {{
                    line: (document.getElementById("qa-fresh-overall") || {{}}).textContent || "",
                    level: (document.getElementById("qa-fresh-overall") || {{ dataset: {{}} }}).dataset.level || "info",
                }},
            }},
            section_freshness: null,
            apple_notes_ideas: null,
        }});
        qaUpdateStatusCardsVisibility();
    }}

    function qaUpdateFreshnessFromToday(today) {{
        const snapshot = (today && typeof today === "object") ? today : null;
        if (!snapshot) return;
        const freshness = (snapshot.freshness && typeof snapshot.freshness === "object")
            ? snapshot.freshness
            : null;
        if (freshness) {{
            const mapping = {{
                diarium: "qa-fresh-diarium",
                diarium_pickup: "qa-fresh-diarium-pickup",
                narrative: "qa-fresh-narrative",
                updates: "qa-fresh-updates",
                mood: "qa-fresh-mood",
                cache: "qa-fresh-cache",
            }};
            Object.entries(mapping).forEach(([key, id]) => {{
                const node = freshness[key];
                if (!node || typeof node !== "object") return;
                const level = qaNormalizeFreshLevel(node.level || "info");
                qaFreshnessState[key] = level;
                qaSetFreshnessLine(id, String(node.line || ""), level);
            }});
            const aiPathNode = (freshness.ai_path && typeof freshness.ai_path === "object")
                ? freshness.ai_path
                : null;
            if (aiPathNode) {{
                const aiLevel = qaNormalizeFreshLevel(aiPathNode.level || "info");
                qaSetFreshnessLine("qa-fresh-ai-path", String(aiPathNode.line || ""), aiLevel);
            }}
            const overallNode = (freshness.overall && typeof freshness.overall === "object")
                ? freshness.overall
                : null;
            if (overallNode) {{
                qaSetFreshnessLine(
                    "qa-fresh-overall",
                    String(overallNode.line || "🔵 Freshness auto-check: waiting for later-day inputs."),
                    qaNormalizeFreshLevel(overallNode.level || "info"),
                );
                const freshDetails = document.querySelector("#qa-freshness-watch details");
                if (freshDetails) {{
                    if (overallNode.auto_open) {{
                        freshDetails.setAttribute("open", "");
                        freshDetails.dataset.autoOpened = "1";
                    }} else if (freshDetails.dataset.autoOpened === "1") {{
                        freshDetails.removeAttribute("open");
                        delete freshDetails.dataset.autoOpened;
                    }}
                }}
            }} else {{
                qaRefreshFreshnessOverall();
            }}
            const updatedLine = document.getElementById("qa-fresh-updated");
            if (updatedLine) {{
                const now = new Date();
                const hh = String(now.getHours()).padStart(2, "0");
                const mm = String(now.getMinutes()).padStart(2, "0");
                updatedLine.textContent = `Auto-check updated ${{hh}}:${{mm}} • every 30s while this tab is open.`;
            }}
            qaUpdateBackendSummaryPills(snapshot);
            qaUpdateSectionFreshnessFromToday(snapshot);
            qaUpdateStatusCardsVisibility(snapshot);
            return;
        }}
        qaUpdateBackendSummaryPills(snapshot);
        qaUpdateSectionFreshnessFromToday(snapshot);
        qaUpdateStatusCardsVisibility(snapshot);
        const effective = String(snapshot.effective_date || qaEffectiveDateKey() || "").trim();

        const diariumFresh = snapshot.diarium_fresh !== false;
        const diariumDate = String(snapshot.diarium_source_date || "").trim();
        let diariumLevel = "info";
        let diariumLine = "ℹ️ Journal freshness unknown.";
        if (!diariumFresh) {{
            diariumLevel = "error";
            diariumLine = `🔴 Journal stale (source: ${{diariumDate || "unknown"}}).`;
        }} else if (diariumDate && effective && diariumDate !== effective) {{
            diariumLevel = "warn";
            diariumLine = `⚠️ Journal date mismatch (${{diariumDate}} vs ${{effective}}).`;
        }} else {{
            diariumLevel = "ok";
            diariumLine = `✅ Journal source is today (${{diariumDate || effective || "today"}}).`;
        }}
        qaFreshnessState.diarium = diariumLevel;
        qaSetFreshnessLine("qa-fresh-diarium", diariumLine, diariumLevel);

        const pickup = (snapshot.diarium_pickup_status && typeof snapshot.diarium_pickup_status === "object")
            ? snapshot.diarium_pickup_status
            : {{}};
        const pickupStatus = String(pickup.status || "").trim().toLowerCase();
        const pickupReason = String(pickup.reason || "").trim();
        const pickupFile = String(pickup.latest_file || "").trim();
        const pickupFileName = pickupFile ? pickupFile.split("/").pop() : "none";
        const pickupMtimeRaw = String(pickup.latest_file_mtime || "").trim();
        const pickupMtime = qaFormatClockTime(pickupMtimeRaw) || (pickupMtimeRaw ? pickupMtimeRaw.slice(0, 16) : "unknown");
        let pickupAgeText = "?";
        if (Number.isFinite(Number(pickup.latest_file_age_seconds))) {{
            const age = Math.max(0, Number(pickup.latest_file_age_seconds));
            pickupAgeText = age < 3600 ? `${{Math.floor(age / 60)}}m` : `${{Math.floor(age / 3600)}}h`;
        }}
        let pickupLevel = "info";
        if (pickupStatus === "picked_up") pickupLevel = "ok";
        else if (pickupStatus === "export_seen_not_parsed" || pickupStatus === "stale") pickupLevel = "warn";
        const pickupLabel = pickupStatus || "unknown";
        let pickupLine = `📓 Pickup: ${{pickupLabel}} • ${{pickupFileName}} • mtime ${{pickupMtime}} • age ${{pickupAgeText}}`;
        if (pickupReason) pickupLine += ` • ${{pickupReason}}`;
        qaFreshnessState.diarium_pickup = pickupLevel;
        qaSetFreshnessLine("qa-fresh-diarium-pickup", pickupLine, pickupLevel);

        const meta = (snapshot.narrative_meta && typeof snapshot.narrative_meta === "object") ? snapshot.narrative_meta : {{}};
        const nState = String(meta.freshness_state || "").toLowerCase();
        const nSourceDate = String(meta.source_date || "").trim();
        const nGenerated = String(meta.generated_at || "").trim();
        const nSourceMax = String(meta.source_max_ts || "").trim();
        const nIncludesToday = meta.source_includes_today;
        const nGeneratedTs = nGenerated ? Date.parse(nGenerated) : NaN;
        const nSourceMaxTs = nSourceMax ? Date.parse(nSourceMax) : NaN;
        let narrativeLevel = "info";
        let narrativeLine = "ℹ️ Waiting for AI day narrative.";
        if (nState === "fresh") {{
            const when = qaFormatClockTime(nGenerated);
            narrativeLevel = "ok";
            narrativeLine = when ? `✅ What you did today is fresh (${{when}}).` : "✅ What you did today is fresh.";
        }} else if (nState === "stale") {{
            narrativeLevel = "warn";
            narrativeLine = "⚠️ Cached day narrative marked stale; fallback active.";
        }} else if (nSourceDate && effective && nSourceDate !== effective) {{
            narrativeLevel = "warn";
            narrativeLine = `⚠️ Cached day narrative source date mismatch (${{nSourceDate}}).`;
        }} else if (nIncludesToday === false) {{
            narrativeLevel = "warn";
            narrativeLine = "⚠️ Cached day narrative missing same-day sources.";
        }} else if (Number.isFinite(nGeneratedTs) && Number.isFinite(nSourceMaxTs) && nGeneratedTs < nSourceMaxTs) {{
            if ((new Date()).getHours() < 18) {{
                narrativeLevel = "info";
                narrativeLine = "🟡 Narrative refresh pending after recent updates.";
            }} else {{
                narrativeLevel = "warn";
                narrativeLine = "⚠️ Cached day narrative older than latest same-day source.";
            }}
        }} else if (nGenerated) {{
            const when = qaFormatClockTime(nGenerated);
            narrativeLevel = "info";
            narrativeLine = when ? `🟡 Narrative generated at ${{when}} — verifying freshness.` : "🟡 Narrative generated — verifying freshness.";
        }}
        qaFreshnessState.narrative = narrativeLevel;
        qaSetFreshnessLine("qa-fresh-narrative", narrativeLine, narrativeLevel);

        const updatesRaw = String(snapshot.diary_updates || "").trim();
        let updatesLevel = "info";
        let updatesLine = "ℹ️ No updates logged yet.";
        if (updatesRaw) {{
            const hasDump = /^(?:\\s*(?:📊\\s*)?Dashboard\\s*[-—:|])/im.test(updatesRaw)
                && (/\\n\\s*🌅\\s*Morning\\b/im.test(updatesRaw) || /\\n\\s*🌙\\s*Evening\\b/im.test(updatesRaw));
            const hasBullets = /(^[\\-\\*]|\\[\\s*[xX ]?\\s*\\]|\\d+\\.\\s)/m.test(updatesRaw);
            const isProse = updatesRaw.length > 150 && !hasBullets;
            if (hasDump) {{
                updatesLevel = "warn";
                updatesLine = "⚠️ Dashboard dump detected in updates and stripped automatically.";
            }} else if (isProse) {{
                updatesLevel = "info";
                updatesLine = "🟡 Long updates prose condensed automatically.";
            }} else {{
                updatesLevel = "ok";
                updatesLine = "✅ Updates feed looks clean.";
            }}
        }}
        qaFreshnessState.updates = updatesLevel;
        qaSetFreshnessLine("qa-fresh-updates", updatesLine, updatesLevel);

        const moodSlots = (snapshot.mood_slots && typeof snapshot.mood_slots === "object") ? snapshot.mood_slots : {{}};
        const morningSlot = String(moodSlots.morning || "").trim().toLowerCase() || "unknown";
        const eveningSlot = String(moodSlots.evening || "").trim().toLowerCase() || "unknown";
        const hourNow = (new Date()).getHours();
        let moodLevel = "info";
        let moodLine = "ℹ️ Mood slot status pending.";
        const moodCheckin = (snapshot.mood_checkin && typeof snapshot.mood_checkin === "object")
            ? snapshot.mood_checkin
            : {{}};
        const moodDone = Boolean(moodCheckin.done);
        if (!diariumFresh && !moodDone) {{
            moodLevel = "warn";
            moodLine = "⚠️ Mood slots unavailable while journal is stale. Add a manual mood check-in.";
        }} else if (morningSlot === "unknown") {{
            moodLevel = "warn";
            moodLine = "⚠️ Morning mood slot missing.";
        }} else if (eveningSlot === "unknown" && hourNow >= 23) {{
            moodLevel = "warn";
            moodLine = `⚠️ Evening mood slot still missing (morning: ${{morningSlot}}).`;
        }} else if (eveningSlot === "unknown") {{
            moodLevel = "info";
            moodLine = `🟡 Mood slots: morning ${{morningSlot}}, evening pending.`;
        }} else {{
            moodLevel = "ok";
            moodLine = `✅ Mood slots split: morning ${{morningSlot}}, evening ${{eveningSlot}}.`;
        }}
        qaFreshnessState.mood = moodLevel;
        qaSetFreshnessLine("qa-fresh-mood", moodLine, moodLevel);

        const aiPathStatus = (snapshot.ai_path_status && typeof snapshot.ai_path_status === "object")
            ? snapshot.ai_path_status
            : {{}};
        let aiPathRaw = String(aiPathStatus.last_path || "").trim();
        const aiTimestamp = String(aiPathStatus.last_timestamp || "").trim();
        const aiClock = qaFormatClockTime(aiTimestamp);
        let aiState = String(aiPathStatus.status || "").trim().toLowerCase();
        const aiRecentCount = Number(aiPathStatus.recent_count);
        if (!aiPathRaw) {{
            const aiInsights = (snapshot.ai_insights && typeof snapshot.ai_insights === "object") ? snapshot.ai_insights : {{}};
            const intervention = (aiInsights.intervention_selector && typeof aiInsights.intervention_selector === "object")
                ? aiInsights.intervention_selector
                : {{}};
            const schedule = (snapshot.schedule_analysis && typeof snapshot.schedule_analysis === "object")
                ? snapshot.schedule_analysis
                : {{}};
            const diariumAnalysis = (snapshot.diarium_analysis && typeof snapshot.diarium_analysis === "object")
                ? snapshot.diarium_analysis
                : {{}};
            const fallbackPairs = [
                ["ai_insights.generator_path", String(aiInsights.generator_path || "").trim()],
                ["ai_insights.intervention_selector.path", String(intervention.path || "").trim()],
                ["schedule_analysis.path", String(schedule.path || "").trim()],
                ["diarium.analysis_path", String(diariumAnalysis.analysis_path || "").trim()],
            ];
            for (const [label, candidate] of fallbackPairs) {{
                if (!candidate) continue;
                const key = candidate.toLowerCase();
                if (!(key.startsWith("ai_") || key.startsWith("heuristic") || key.startsWith("error"))) continue;
                aiPathRaw = candidate;
                aiState = "cached_fallback";
                break;
            }}
        }}
        let aiPathLevel = "info";
        let aiPathLine = "ℹ️ AI path telemetry unavailable.";
        if (aiPathRaw) {{
            const key = aiPathRaw.toLowerCase();
            let pathName = "Unknown";
            if (key.startsWith("ai_claude_cli")) {{
                pathName = "Claude CLI";
                aiPathLevel = "ok";
            }} else if (key.startsWith("ai_codex_cli")) {{
                pathName = "Codex CLI";
            }} else if (key.startsWith("ai_codex")) {{
                pathName = "Codex API";
            }} else if (key.startsWith("ai_claude_api")) {{
                pathName = "Claude API";
            }} else if (key.startsWith("heuristic")) {{
                pathName = "Heuristic fallback";
                aiPathLevel = "warn";
            }} else if (key.startsWith("error")) {{
                pathName = "Error fallback";
                aiPathLevel = "error";
            }}
            aiPathLine = `🤖 AI path last run: ${{pathName}}`;
            if (aiClock) aiPathLine += ` • ${{aiClock}}`;
            if (Number.isFinite(aiRecentCount) && aiRecentCount > 0) aiPathLine += ` • ${{aiRecentCount}} events`;
        }} else if (aiState === "empty") {{
            aiPathLine = "ℹ️ AI path telemetry ready (no calls yet this run).";
        }}
        qaSetFreshnessLine("qa-fresh-ai-path", aiPathLine, aiPathLevel);
        qaSetFreshnessLine("qa-fresh-ai-path-inline", aiPathLine, aiPathLevel);

        const updatedLine = document.getElementById("qa-fresh-updated");
        if (updatedLine) {{
            const now = new Date();
            const hh = String(now.getHours()).padStart(2, "0");
            const mm = String(now.getMinutes()).padStart(2, "0");
            updatedLine.textContent = `Auto-check updated ${{hh}}:${{mm}} • every 30s while this tab is open.`;
        }}

        qaRefreshFreshnessOverall();
    }}

    function qaUpdateFreshnessFromSystem(system) {{
        const payload = (system && typeof system === "object") ? system : null;
        if (!payload) return;
        const cacheAge = Number(payload.cache_age_minutes);
        let cacheLevel = "info";
        let cacheLine = "ℹ️ Cache age unknown.";
        if (Number.isFinite(cacheAge) && cacheAge <= 10) {{
            cacheLevel = "ok";
            cacheLine = `✅ Cache age healthy (${{cacheAge}}m).`;
        }} else if (Number.isFinite(cacheAge) && cacheAge <= 60) {{
            cacheLevel = "info";
            cacheLine = `🟡 Cache aging (${{cacheAge}}m) — watching.`;
        }} else if (Number.isFinite(cacheAge)) {{
            cacheLevel = "warn";
            cacheLine = `⚠️ Cache stale (${{cacheAge}}m) — refresh recommended.`;
        }}
        qaFreshnessState.cache = cacheLevel;
        qaSetFreshnessLine("qa-fresh-cache", cacheLine, cacheLevel);
        qaRefreshFreshnessOverall();
    }}

    function qaUpdateSystemStatus(system) {{
        if (!system || typeof system !== "object") return;
        const previous = (qaLastSystemStatus && typeof qaLastSystemStatus === "object") ? qaLastSystemStatus : {{}};
        const merged = Object.assign({{}}, previous, system);
        const incomingBeads = (system.beads && typeof system.beads === "object") ? system.beads : null;
        merged.beads = Object.assign({{}}, (previous.beads && typeof previous.beads === "object") ? previous.beads : {{}}, incomingBeads || {{}});
        if (system.daemon_ok === null || typeof system.daemon_ok === "undefined") {{
            merged.daemon_ok = Object.prototype.hasOwnProperty.call(previous, "daemon_ok") ? previous.daemon_ok : null;
        }}
        if (system.api_ok === null || typeof system.api_ok === "undefined") {{
            merged.api_ok = Object.prototype.hasOwnProperty.call(previous, "api_ok") ? previous.api_ok : null;
        }}
        if (!Number.isFinite(Number(system.cache_age_minutes)) && Number.isFinite(Number(previous.cache_age_minutes))) {{
            merged.cache_age_minutes = Number(previous.cache_age_minutes);
        }}
        qaLastSystemStatus = merged;
        const daemonBadge = document.getElementById("sys-daemon-badge");
        const apiBadge = document.getElementById("sys-api-badge");
        const cacheBadge = document.getElementById("sys-cache-badge");
        const beadsSummary = document.getElementById("sys-beads-summary");
        const checkedAt = document.getElementById("sys-checked-at");
        const cacheAge = Number(merged.cache_age_minutes);
        const degraded = (
            merged.daemon_ok === false ||
            merged.api_ok === false ||
            (Number.isFinite(cacheAge) && cacheAge > 60)
        );
        if (document && document.body && degraded) {{
            document.body.dataset.optionalPills = "on";
        }}

        if (daemonBadge) {{
            if (merged.daemon_ok === true) {{
                daemonBadge.textContent = "🟢 Daemon";
                daemonBadge.style.color = "#6ee7b7";
                daemonBadge.style.borderColor = "rgba(110,231,183,0.28)";
                daemonBadge.style.background = "rgba(6,95,70,0.22)";
            }} else if (merged.daemon_ok === false) {{
                daemonBadge.textContent = "🔴 Daemon";
                daemonBadge.style.color = "#fca5a5";
                daemonBadge.style.borderColor = "rgba(239,68,68,0.28)";
                daemonBadge.style.background = "rgba(127,29,29,0.22)";
            }} else {{
                daemonBadge.textContent = "🟡 Daemon";
                daemonBadge.style.color = "#fde68a";
                daemonBadge.style.borderColor = "rgba(251,191,36,0.28)";
                daemonBadge.style.background = "rgba(120,53,15,0.24)";
            }}
        }}
        if (apiBadge) {{
            if (merged.api_ok === true) {{
                apiBadge.textContent = "🟢 API";
                apiBadge.style.color = "#93c5fd";
                apiBadge.style.borderColor = "rgba(147,197,253,0.28)";
                apiBadge.style.background = "rgba(30,64,175,0.2)";
            }} else if (merged.api_ok === false) {{
                apiBadge.textContent = "🔴 API";
                apiBadge.style.color = "#fca5a5";
                apiBadge.style.borderColor = "rgba(239,68,68,0.28)";
                apiBadge.style.background = "rgba(127,29,29,0.22)";
            }} else {{
                apiBadge.textContent = "🟡 API";
                apiBadge.style.color = "#fde68a";
                apiBadge.style.borderColor = "rgba(251,191,36,0.28)";
                apiBadge.style.background = "rgba(120,53,15,0.24)";
            }}
        }}
        if (cacheBadge) {{
            const age = cacheAge;
            if (Number.isFinite(age)) {{
                if (age <= 10) {{
                    cacheBadge.textContent = `🟢 ${{age}}m`;
                    cacheBadge.style.color = "#a7f3d0";
                    cacheBadge.style.borderColor = "rgba(110,231,183,0.28)";
                    cacheBadge.style.background = "rgba(6,95,70,0.22)";
                }} else if (age <= 60) {{
                    cacheBadge.textContent = `🟡 ${{age}}m`;
                    cacheBadge.style.color = "#fde68a";
                    cacheBadge.style.borderColor = "rgba(251,191,36,0.28)";
                    cacheBadge.style.background = "rgba(120,53,15,0.24)";
                }} else {{
                    cacheBadge.textContent = `🔴 ${{age}}m`;
                    cacheBadge.style.color = "#fca5a5";
                    cacheBadge.style.borderColor = "rgba(239,68,68,0.28)";
                    cacheBadge.style.background = "rgba(127,29,29,0.22)";
                }}
            }} else {{
                cacheBadge.textContent = "🔴 Cache";
                cacheBadge.style.color = "#fca5a5";
                cacheBadge.style.borderColor = "rgba(239,68,68,0.28)";
                cacheBadge.style.background = "rgba(127,29,29,0.22)";
            }}
        }}
        if (beadsSummary) {{
            const beads = merged.beads || {{}};
            const parts = ["HEALTH", "WORK", "TODO"].map((name) => {{
                const value = beads[name];
                const prefix = name === "HEALTH" ? "H" : name === "WORK" ? "W" : "T";
                return Number.isFinite(Number(value)) ? `${{prefix}}:${{Number(value)}}` : `${{prefix}}:?`;
            }}).filter(Boolean);
            beadsSummary.textContent = parts.length ? parts.join(" • ") : "H:? • W:? • T:?";
        }}
        if (checkedAt) {{
            const checked = merged.checked_at ? String(merged.checked_at).slice(11, 16) : "";
            checkedAt.textContent = checked || "--:--";
        }}
        qaUpdateFreshnessFromSystem(merged);
    }}

    async function qaCompleteLoopText(text) {{
        const cleaned = String(text || "").trim();
        if (!cleaned) return null;
        const ui = await qaPostWithRetry("/v1/ui/actions/complete", {{ kind: "loop", text: cleaned }}, {{ retries: 1, label: "loop close" }});
        if (ui) return ui;
        return await qaPostWithRetry("/v1/actions/complete", {{ kind: "loop", text: cleaned }}, {{ retries: 1, label: "loop close" }});
    }}

    function qaTomorrowDateKey() {{
        const baseKey = qaEffectiveDateKey();
        const parsed = new Date(`${{baseKey}}T00:00:00`);
        if (Number.isNaN(parsed.getTime())) return "";
        parsed.setDate(parsed.getDate() + 1);
        const yyyy = String(parsed.getFullYear());
        const mm = String(parsed.getMonth() + 1).padStart(2, "0");
        const dd = String(parsed.getDate()).padStart(2, "0");
        return `${{yyyy}}-${{mm}}-${{dd}}`;
    }}

    async function qaCompleteTodoText(text) {{
        const cleaned = String(text || "").trim();
        if (!cleaned) return null;
        const ui = await qaPostWithRetry("/v1/ui/actions/complete", {{ kind: "todo", text: cleaned }}, {{ retries: 1, label: "todo close" }});
        if (ui) return ui;
        const direct = await qaPostWithRetry("/complete-todo", {{ text: cleaned }}, {{ retries: 1, label: "todo close" }});
        if (direct) return direct;
        return await qaPostWithRetry("/v1/actions/complete", {{ kind: "todo", text: cleaned }}, {{ retries: 1, label: "todo close" }});
    }}

    async function qaDeferTodoText(text, targetDate = "") {{
        const cleaned = String(text || "").trim();
        if (!cleaned) return null;
        const target = String(targetDate || qaTomorrowDateKey()).trim();
        const payload = {{
            text: cleaned,
            target_date: target,
            days: 1,
        }};
        const ui = await qaPostWithRetry("/v1/ui/actions/defer", payload, {{ retries: 1, label: "todo defer" }});
        if (ui) return ui;
        return await qaPostWithRetry("/v1/actions/defer", payload, {{ retries: 1, label: "todo defer" }});
    }}

    async function qaCompleteLoop() {{
        const input = document.getElementById("qa-loop-text");
        const text = (input && input.value ? input.value : "").trim();
        if (!text) return;
        const ok = await qaCompleteLoopText(text);
        if (ok) {{
            if (input) input.value = "";
        }}
    }}

    async function qaCompleteTodo() {{
        const input = document.getElementById("qa-todo-text");
        const text = (input && input.value ? input.value : "").trim();
        if (!text) return;
        const ok = await qaCompleteTodoText(text);
        if (ok) {{
            if (input) input.value = "";
        }}
    }}

    async function qaCompleteLoopFromButton(button) {{
        const text = ((button && button.dataset && button.dataset.text) || "").trim();
        if (!text) return;
        if (button) {{
            button.disabled = true;
            button.textContent = "Saving...";
        }}
        const ok = await qaCompleteLoopText(text);
        if (ok && button) {{
            qaRemovePendingCompletion("loop", text);
            qaSetLocalCompletion("loop", text, true);
            qaApplyLoopClosedUi(text);
        }} else if (button) {{
            qaAddPendingCompletion("loop", text);
            if (QA_IS_FILE_PROTOCOL) {{
                qaSetLocalCompletion("loop", text, true);
                qaApplyLoopClosedUi(text);
                const status = document.getElementById("qa-status");
                if (status) {{
                    status.textContent = "📶 Saved locally; loop close queued for sync when API is reachable.";
                    status.style.color = "#fbbf24";
                }}
                return;
            }}
            button.disabled = true;
            button.textContent = "📶 Queued";
            button.style.background = "rgba(120,53,15,0.35)";
            button.style.color = "#fde68a";
            button.style.borderColor = "rgba(251,191,36,0.35)";
            const row = button.closest("[data-qa-row='loop']");
            if (row) {{
                row.style.opacity = "0.75";
                let msg = row.querySelector(".qa-offline-msg");
                if (!msg) {{
                    msg = document.createElement("p");
                    msg.className = "qa-offline-msg text-xs mt-1";
                    msg.style.color = "#fde68a";
                    msg.textContent = "Queued — will sync when API is reachable.";
                    const flexOne = row.querySelector(".flex-1");
                    if (flexOne) flexOne.appendChild(msg);
                }}
            }}
        }}
    }}

    async function qaCompleteTodoFromButton(button) {{
        const text = ((button && button.dataset && button.dataset.text) || "").trim();
        if (!text) return;
        if (button) {{
            button.disabled = true;
            button.textContent = "Saving...";
        }}
        const ok = await qaCompleteTodoText(text);
        if (ok && button) {{
            qaRemovePendingCompletion("todo", text);
            qaSetLocalCompletion("todo", text, true);
            qaApplyTodoDoneUi(text);
        }} else if (button) {{
            qaAddPendingCompletion("todo", text);
            if (QA_IS_FILE_PROTOCOL) {{
                qaSetLocalCompletion("todo", text, true);
                qaApplyTodoDoneUi(text);
                const status = document.getElementById("qa-status");
                if (status) {{
                    status.textContent = "📶 Saved locally; action item completion queued for sync when API is reachable.";
                    status.style.color = "#fbbf24";
                }}
                return;
            }}
            button.disabled = true;
            button.textContent = "📶 Queued";
            button.style.background = "rgba(120,53,15,0.35)";
            button.style.color = "#fde68a";
            button.style.borderColor = "rgba(251,191,36,0.35)";
            const row = button.closest("[data-qa-row='todo']");
            if (row) {{
                row.style.opacity = "0.75";
                let msg = row.querySelector(".qa-offline-msg");
                if (!msg) {{
                    msg = document.createElement("p");
                    msg.className = "qa-offline-msg text-xs mt-1";
                    msg.style.color = "#fde68a";
                    msg.textContent = "Queued — will sync when API is reachable.";
                    const flexOne = row.querySelector(".flex-1");
                    if (flexOne) flexOne.appendChild(msg);
                }}
            }}
        }}
    }}

    async function qaDeferTodoFromButton(button) {{
        const text = ((button && button.dataset && button.dataset.text) || "").trim();
        if (!text) return;
        const targetDate = qaTomorrowDateKey();
        if (button) {{
            button.disabled = true;
            button.textContent = "Deferring...";
        }}
        const ok = await qaDeferTodoText(text, targetDate);
        if (ok) {{
            qaRemovePendingCompletion("todo_defer", text);
            qaSetLocalDeferred(text, targetDate);
            qaApplyTodoDeferredUi(text, targetDate, false);
            return;
        }}

        qaAddPendingCompletion("todo_defer", text, {{ target_date: targetDate }});
        if (QA_IS_FILE_PROTOCOL) {{
            qaSetLocalDeferred(text, targetDate);
            qaApplyTodoDeferredUi(text, targetDate, true);
            return;
        }}
        if (button) {{
            button.disabled = true;
            button.textContent = "📶 Queued";
            button.style.background = "rgba(120,53,15,0.35)";
            button.style.color = "#fde68a";
            button.style.borderColor = "rgba(251,191,36,0.35)";
        }}
    }}

    function qaStartOneThing(button) {{
        if (!button) return;
        button.disabled = true;
        button.textContent = "In progress";
        const text = ((button.dataset && button.dataset.text) || "").trim();
        const status = document.getElementById("qa-status");
        if (status && text) {{
            status.textContent = `▶️ Started: ${{text.slice(0, 120)}}`;
            status.style.color = "#93c5fd";
        }}
    }}

    function qaSetAnxietySaveState(kind) {{
        const badge = document.getElementById("qa-anxiety-save-state");
        if (!badge) return;
        const k = String(kind || "").toLowerCase();
        badge.hidden = false;
        if (k === "saving") {{
            badge.textContent = "saving...";
            badge.style.color = "#93c5fd";
            badge.style.borderColor = "rgba(147,197,253,0.35)";
            return;
        }}
        if (k === "retrying") {{
            badge.textContent = "retrying";
            badge.style.color = "#fbbf24";
            badge.style.borderColor = "rgba(251,191,36,0.35)";
            return;
        }}
        if (k === "error") {{
            badge.textContent = "save failed";
            badge.style.color = "#fca5a5";
            badge.style.borderColor = "rgba(248,113,113,0.4)";
            return;
        }}
        badge.hidden = true;
        badge.textContent = "synced";
        badge.style.color = "#6ee7b7";
        badge.style.borderColor = "rgba(110,231,183,0.4)";
    }}

    function qaOnAnxietyInput(input, immediate = false) {{
        const slider = input || document.getElementById("qa-anxiety-score");
        if (!slider) return;
        const valueLabel = document.getElementById("qa-anxiety-score-val");
        if (valueLabel) valueLabel.textContent = String(slider.value || "0");
        qaApplyAnxietyScore(Number(slider.value || "0"));
        qaSetAnxietySaveState("saving");
        if (qaAnxietySaveTimer) {{
            clearTimeout(qaAnxietySaveTimer);
            qaAnxietySaveTimer = null;
        }}
        qaAnxietySaveTimer = setTimeout(() => {{
            qaFlushAnxietyAutosave({{ immediate }});
        }}, immediate ? 0 : 450);
    }}

    async function qaFlushAnxietyAutosave(options = {{}}) {{
        const slider = document.getElementById("qa-anxiety-score");
        if (!slider) return;
        const score = Number(slider.value || "0");
        if (!Number.isFinite(score)) return;
        qaAnxietyPendingScore = score;
        if (qaAnxietySaveInFlight) return;
        qaAnxietySaveInFlight = true;
        const status = document.getElementById("qa-status");
        try {{
            while (qaAnxietyPendingScore !== null) {{
                const nextScore = Number(qaAnxietyPendingScore);
                qaAnxietyPendingScore = null;
                qaSetAnxietySaveState("saving");
                const result = await qaPostWithRetry("/v1/ui/interventions/rating", {{
                    score: nextScore,
                    date: qaEffectiveDateKey(),
                    source: "autosave",
                    client_ts: new Date().toISOString(),
                }}, {{ retries: 2, label: "anxiety score" }});
                if (!result) {{
                    qaSetAnxietySaveState("retrying");
                    qaAnxietyPendingScore = nextScore;
                    await qaDelay(900);
                    continue;
                }}
                const savedRaw = Number(result && result.score);
                const saved = Number.isFinite(savedRaw) ? savedRaw : nextScore;
                qaApplyAnxietyScore(saved);
                qaSetAnxietySaveState("synced");
                if (status) {{
                    status.textContent = `✅ Anxiety relief saved (${{saved}}/10)`;
                    status.style.color = "#6ee7b7";
                }}
            }}
        }} catch (_err) {{
            qaSetAnxietySaveState("error");
        }} finally {{
            qaAnxietySaveInFlight = false;
        }}
    }}

    async function qaRateAnxiety() {{
        await qaFlushAnxietyAutosave({{ immediate: true }});
    }}

    function qaApplyAnxietyScore(score) {{
        const slider = document.getElementById("qa-anxiety-score");
        const valueLabel = document.getElementById("qa-anxiety-score-val");
        const raw = Number(score);
        if (!Number.isFinite(raw)) return;
        const rounded = Math.max(0, Math.min(10, Math.round(raw)));
        if (slider) slider.value = String(rounded);
        if (valueLabel) valueLabel.textContent = String(rounded);
        const yogaAnxiety = document.getElementById("qa-wc-anxiety");
        if (yogaAnxiety && !String(yogaAnxiety.value || "").trim()) {{
            yogaAnxiety.value = String(rounded);
        }}
        qaCurrentAnxietyScore = rounded;
        qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
    }}

    function qaOpenWorkoutChecklist(scrollTo = false) {{
        const details = document.getElementById("qa-workout-checklist");
        if (!details) return;
        details.open = true;
        if (scrollTo && typeof details.scrollIntoView === "function") {{
            details.scrollIntoView({{ behavior: "smooth", block: "center" }});
        }}
    }}

    function qaWorkoutChecklistFeedbackState() {{
        const currentChecklist = (QA_WORKOUT_CHECKLIST_INITIAL && typeof QA_WORKOUT_CHECKLIST_INITIAL === "object")
            ? QA_WORKOUT_CHECKLIST_INITIAL
            : {{}};
        const fallbackFeedback = (currentChecklist.session_feedback && typeof currentChecklist.session_feedback === "object")
            ? currentChecklist.session_feedback
            : {{}};
        const parseIntInput = (id, min, max, fallbackValue = null) => {{
            const el = document.getElementById(id);
            const raw = (el ? String(el.value || "").trim() : String(fallbackValue || "").trim());
            if (!raw) return null;
            const n = Number(raw);
            if (!Number.isFinite(n)) return null;
            const rounded = Math.round(n);
            if (rounded < min || rounded > max) return null;
            return rounded;
        }};
        const parseChoice = (id, allowed, fallbackValue = "") => {{
            const el = document.getElementById(id);
            const raw = String((el ? el.value : fallbackValue) || "").trim().toLowerCase();
            return allowed.has(raw) ? raw : "";
        }};
        const noteEl = document.getElementById("qa-wc-note");
        const duration = parseIntInput("qa-wc-duration", 5, 240, fallbackFeedback.duration_minutes);
        const intensity = parseChoice("qa-wc-intensity", new Set(["easy", "moderate", "hard"]), fallbackFeedback.intensity);
        const sessionType = parseChoice("qa-wc-session-type", new Set(["somatic", "yin", "flow", "mobility", "restorative", "other"]), fallbackFeedback.session_type);
        const bodyFeel = parseChoice("qa-wc-body-feel", new Set(["relaxed", "neutral", "tight", "sore", "energised", "fatigued"]), fallbackFeedback.body_feel);
        const anxietyInput = parseIntInput("qa-wc-anxiety", 0, 10, fallbackFeedback.anxiety_reduction_score);
        const anxiety = Number.isFinite(qaCurrentAnxietyScore) ? qaCurrentAnxietyScore : anxietyInput;
        const sessionNoteRaw = String((noteEl ? noteEl.value : fallbackFeedback.session_note) || "").trim();
        return {{
            duration_minutes: duration,
            intensity,
            session_type: sessionType,
            body_feel: bodyFeel,
            anxiety_reduction_score: Number.isFinite(anxiety) ? anxiety : null,
            session_note: sessionNoteRaw ? sessionNoteRaw.slice(0, 280) : "",
        }};
    }}

    function qaMissingYogaFields(feedbackState) {{
        const safe = (feedbackState && typeof feedbackState === "object") ? feedbackState : {{}};
        const missing = [];
        if (!Number.isFinite(Number(safe.duration_minutes))) missing.push("duration");
        if (!String(safe.intensity || "").trim()) missing.push("intensity");
        if (!String(safe.session_type || "").trim()) missing.push("type");
        if (!String(safe.body_feel || "").trim()) missing.push("body feel");
        if (!Number.isFinite(Number(safe.anxiety_reduction_score))) missing.push("anxiety");
        return missing;
    }}

    function qaWeightsChecklistFeedbackState() {{
        const currentChecklist = (QA_WORKOUT_CHECKLIST_INITIAL && typeof QA_WORKOUT_CHECKLIST_INITIAL === "object")
            ? QA_WORKOUT_CHECKLIST_INITIAL
            : {{}};
        const fallbackPost = (currentChecklist.post_workout && typeof currentChecklist.post_workout === "object")
            ? currentChecklist.post_workout
            : {{}};
        const recoverySelect = document.getElementById("qa-wc-recovery");
        const recoveryGate = String((recoverySelect ? recoverySelect.value : currentChecklist.recovery_gate) || "unknown").trim().toLowerCase();
        const parseIntInput = (id, min, max, fallbackValue = null) => {{
            const el = document.getElementById(id);
            const raw = (el ? String(el.value || "").trim() : String(fallbackValue || "").trim());
            if (!raw) return null;
            const n = Number(raw);
            if (!Number.isFinite(n)) return null;
            const rounded = Math.round(n);
            if (rounded < min || rounded > max) return null;
            return rounded;
        }};
        return {{
            recovery_gate: recoveryGate,
            rpe: parseIntInput("qa-wc-rpe", 1, 10, fallbackPost.rpe),
            pain: parseIntInput("qa-wc-pain", 0, 10, fallbackPost.pain),
            energy_after: parseIntInput("qa-wc-energy", 1, 10, fallbackPost.energy_after),
        }};
    }}

    function qaMissingWeightsFields(weightsState, recoverySignal = "unknown") {{
        const safe = (weightsState && typeof weightsState === "object") ? weightsState : {{}};
        const missing = [];
        const recovery = String(safe.recovery_gate || "").trim().toLowerCase();
        const signal = String(recoverySignal || "unknown").trim().toLowerCase();
        const recoveryRequired = signal === "pass" || signal === "fail" || signal === "caution";
        if (recoveryRequired && !(recovery === "pass" || recovery === "fail")) missing.push("recovery gate");
        if (!Number.isFinite(Number(safe.rpe))) missing.push("RPE");
        if (!Number.isFinite(Number(safe.pain))) missing.push("pain");
        if (!Number.isFinite(Number(safe.energy_after))) missing.push("energy");
        return missing;
    }}

    function qaApplyYogaFeedbackPrompt(options = {{}}) {{
        const shouldAutoOpen = Boolean(options.autoOpen);
        const wrap = document.getElementById("qa-wc-yoga-feedback-wrap");
        if (wrap) {{
            wrap.style.display = qaCurrentWorkoutType === "yoga" ? "block" : "none";
        }}
        const nudge = document.getElementById("qa-yoga-feedback-nudge");
        const missingEl = document.getElementById("qa-yoga-feedback-missing");
        const titleEl = document.getElementById("qa-yoga-feedback-title");
        const hintEl = document.getElementById("qa-yoga-feedback-hint");
        if (!nudge) return;
        if (!qaCurrentWorkoutDone) {{
            nudge.style.display = "none";
            nudge.dataset.needed = "false";
            qaYogaPromptAutoOpened = false;
            return;
        }}
        let missing = [];
        let title = "";
        if (qaCurrentWorkoutType === "yoga") {{
            const feedbackState = qaWorkoutChecklistFeedbackState();
            missing = qaMissingYogaFields(feedbackState);
            title = "🧾 Add yoga details to unlock progression advice";
        }} else if (qaCurrentWorkoutType === "weights") {{
            const weightsState = qaWeightsChecklistFeedbackState();
            const recoverySignal = (qaCurrentWorkoutSignals && typeof qaCurrentWorkoutSignals === "object")
                ? String(qaCurrentWorkoutSignals.recovery_signal || "unknown")
                : "unknown";
            missing = qaMissingWeightsFields(weightsState, recoverySignal);
            title = "🧾 Add weights details to unlock progression advice";
        }} else {{
            missing = [];
        }}
        if (missing.length === 0) {{
            nudge.style.display = "none";
            nudge.dataset.needed = "false";
            qaYogaPromptAutoOpened = false;
            return;
        }}
        nudge.style.display = "block";
        nudge.dataset.needed = "true";
        if (titleEl) {{
            titleEl.textContent = title || "🧾 Add details to unlock progression advice";
        }}
        if (hintEl) {{
            hintEl.textContent = "What I need:";
        }}
        if (missingEl) {{
            missingEl.textContent = missing.join(", ");
        }}
        if (shouldAutoOpen && !qaYogaPromptAutoOpened) {{
            qaOpenWorkoutChecklist(true);
            qaYogaPromptAutoOpened = true;
        }}
    }}

    function qaRecoverySignalText(signals) {{
        const safe = (signals && typeof signals === "object") ? signals : {{}};
        const signal = String(safe.recovery_signal || "unknown").toLowerCase();
        const detail = String(safe.recovery_signal_detail || "No HRV/sleep gate signal yet.").trim();
        let badge = "⚪ Auto gate unavailable";
        if (signal === "pass") badge = "🟢 Auto gate suggests PASS";
        else if (signal === "fail") badge = "🟠 Auto gate suggests FAIL";
        else if (signal === "caution") badge = "🟡 Auto gate borderline";
        return `${{badge}} • ${{detail}}`;
    }}

    function qaApplyWorkoutChecklistSignals(signals) {{
        const safe = (signals && typeof signals === "object") ? signals : {{}};
        qaCurrentWorkoutSignals = safe;
        const applyCheck = (id, key) => {{
            const el = document.getElementById(id);
            if (el) el.checked = Boolean(safe[key]);
        }};
        applyCheck("qa-wc-sig-healthfit", "healthfit_export_today");
        applyCheck("qa-wc-sig-streaks", "streaks_export_today");
        applyCheck("qa-wc-sig-anxiety", "anxiety_saved_today");
        applyCheck("qa-wc-sig-reflection", "reflection_saved_today");

        const recovery = document.getElementById("qa-wc-recovery-signal");
        if (recovery) {{
            recovery.textContent = qaRecoverySignalText(safe);
        }}
    }}

    function qaWorkoutProgressionView(state) {{
        const safe = (state && typeof state === "object") ? state : {{}};
        const action = String(safe.action || "").trim();
        const labelRaw = String(safe.label || "").trim();
        const reason = String(safe.reason || "").trim();
        const confidence = String(safe.confidence || "").trim().toLowerCase();
        const label = labelRaw || "⚪ Progression signal not available yet.";
        let color = "#9ca3af";
        if (action === "increase_reps" || action === "increase_duration") color = "#6ee7b7";
        else if (action === "hold_reps" || action === "hold_or_deload" || action === "hold_duration" || action === "reduce_duration") color = "#fbbf24";
        else if (action === "build_base" || action === "capture_feedback") color = "#93c5fd";
        const confidenceText = ["low", "medium", "high"].includes(confidence) ? `Confidence: ${{confidence}}.` : "";
        const detail = [reason, confidenceText].filter(Boolean).join(" ").trim();
        return {{ label, color, detail }};
    }}

    function qaApplyWorkoutProgression(state) {{
        const view = qaWorkoutProgressionView(state);
        const topMeta = document.getElementById("qa-workout-progression-meta");
        if (topMeta) {{
            topMeta.textContent = view.label;
            topMeta.style.color = view.color;
        }}
        const topDetail = document.getElementById("qa-workout-progression-detail");
        if (topDetail) {{
            topDetail.textContent = view.detail;
        }}
        const checklistMeta = document.getElementById("qa-wc-progression-meta");
        if (checklistMeta) {{
            checklistMeta.textContent = view.label;
            checklistMeta.style.color = view.color;
        }}
        const checklistDetail = document.getElementById("qa-wc-progression-detail");
        if (checklistDetail) {{
            checklistDetail.textContent = view.detail;
        }}
    }}

    function qaApplyWeightsProgression(state) {{
        const view = qaWorkoutProgressionView(state);
        const weightsMeta = document.getElementById("qa-wc-weights-progression-meta");
        if (weightsMeta) {{
            weightsMeta.textContent = view.label;
            weightsMeta.style.color = view.color;
        }}
        const weightsDetail = document.getElementById("qa-wc-weights-progression-detail");
        if (weightsDetail) {{
            weightsDetail.textContent = view.detail;
        }}
    }}

    async function qaSyncTodayFromApi(options = {{}}) {{
        const force = Boolean(options.force);
        if (!force && qaIsLiveSyncPaused()) {{
            qaUpdateSyncPauseUi();
            return;
        }}
        if (!qaCanRunNetworkPoll({{ force }})) {{
            return;
        }}
        if (qaTodaySyncInFlight) return;
        qaTodaySyncInFlight = true;
        try {{
            const payload = await qaGet("/v1/ui/today", {{ coalesce: true }});
            const today = (payload && payload.today && typeof payload.today === "object") ? payload.today : null;
            if (!today) return;
            qaApplyLiveToday(today);
            if (qaLeaderModeEnabled() && qaIsPollLeader) {{
                qaBroadcastLive("today", today);
            }}
        }} finally {{
            qaTodaySyncInFlight = false;
        }}
    }}

    async function qaVerifyMindfulnessSaved(expectedDone, expectedMinutes) {{
        const payload = await qaGet("/v1/ui/today");
        const today = (payload && payload.today && typeof payload.today === "object") ? payload.today : null;
        if (!today || !today.mindfulness || typeof today.mindfulness !== "object") {{
            return {{ ok: false, state: null }};
        }}
        const updated = Object.assign({{}}, today.mindfulness);
        if (today.mental_health_progression && typeof today.mental_health_progression === "object") {{
            updated.progression = today.mental_health_progression;
        }}
        const savedDone = Boolean(updated.done);
        const minsRaw = Number(updated.minutes_done);
        const savedMinutes = Number.isFinite(minsRaw) ? minsRaw : 0;
        const targetMinutes = Number(expectedMinutes || 0);
        const minutesOk = !expectedDone || savedMinutes >= targetMinutes;
        return {{
            ok: savedDone === Boolean(expectedDone) && minutesOk,
            state: updated,
        }};
    }}

    function qaMindfulnessSummary(state) {{
        const safeState = (state && typeof state === "object") ? state : {{}};
        const done = Boolean(safeState.done);
        const autoDone = Boolean(safeState.auto_done);
        const manualDoneRaw = safeState.manual_done;
        const hasManualOverride = typeof manualDoneRaw === "boolean";
        const habit = String(safeState.habit || "").trim();
        const autoSourceRaw = String(safeState.auto_source || "").toLowerCase();
        const targetRaw = Number(safeState.minutes_target);
        const targetMinutes = Number.isFinite(targetRaw) && targetRaw > 0 ? targetRaw : QA_MINDFULNESS_TARGET;
        const minutesDoneRaw = Number(safeState.minutes_done);
        const minutesDone = Number.isFinite(minutesDoneRaw) && minutesDoneRaw > 0 ? minutesDoneRaw : (done ? targetMinutes : 0);
        const progression = (safeState.progression && typeof safeState.progression === "object") ? safeState.progression : {{}};
        const combinedRaw = Number(progression.combined_score);
        const adherenceRaw = Number(progression.seven_day_mindfulness_adherence_pct);
        let progressionText = "";
        if (Number.isFinite(combinedRaw)) {{
            progressionText = Number.isFinite(adherenceRaw)
                ? ` • progression ${{combinedRaw.toFixed(1)}}/10 • 7d ${{Math.round(adherenceRaw)}}%`
                : ` • progression ${{combinedRaw.toFixed(1)}}/10`;
        }}
        if (done) {{
            let sourceText = "manual";
            if (!hasManualOverride && autoDone && autoSourceRaw.includes("streaks")) {{
                sourceText = "auto from Streaks";
            }} else if (!hasManualOverride && autoDone && autoSourceRaw.includes("healthfit")) {{
                sourceText = "auto from HealthFit";
            }} else if (!hasManualOverride && autoDone && autoSourceRaw.includes("finch")) {{
                sourceText = "auto from Finch";
            }}
            return `✅ ${{minutesDone}}m logged (${{sourceText}})${{habit ? ` • ${{habit}}` : ""}}${{progressionText}}`;
        }}
        return `⬜ Target: ${{targetMinutes}}m today${{habit ? ` • ${{habit}}` : ""}}${{progressionText}}`;
    }}

    function qaApplyMindfulnessState(state) {{
        const safeState = (state && typeof state === "object") ? state : {{}};
        const checkbox = document.getElementById("qa-mindfulness-check");
        if (checkbox && typeof safeState.done === "boolean") {{
            checkbox.checked = Boolean(safeState.done);
        }}
        const quickCheckbox = document.getElementById("qa-quick-mindfulness-check");
        if (quickCheckbox && typeof safeState.done === "boolean") {{
            quickCheckbox.checked = Boolean(safeState.done);
        }}
        const meta = document.getElementById("qa-mindfulness-meta");
        if (meta) {{
            meta.textContent = qaMindfulnessSummary(safeState);
            meta.style.color = safeState.done ? "#6ee7b7" : "#9ca3af";
        }}
        qaUpdateQuickDoneMeta();
    }}

    async function qaToggleMindfulness(input) {{
        if (!input) return;
        if (qaMindfulnessSaving) {{
            input.checked = qaMindfulnessDesiredDone === null ? Boolean(input.checked) : Boolean(qaMindfulnessDesiredDone);
            return;
        }}
        const desired = Boolean(input && input.checked);
        qaMindfulnessSaving = true;
        qaMindfulnessDesiredDone = desired;
        input.disabled = true;

        const status = document.getElementById("qa-status");
        if (status) {{
            status.textContent = desired ? "⏳ Saving mindfulness..." : "⏳ Clearing mindfulness...";
            status.style.color = "#93c5fd";
        }}

        const payload = {{
            done: desired,
            minutes: QA_MINDFULNESS_TARGET,
            date: qaEffectiveDateKey(),
            source: "dashboard_manual",
        }};
        try {{
            let applied = false;
            let latestState = null;

            const first = await qaPost("/v1/ui/mindfulness/log", payload);
            if (first && first.mindfulness) {{
                latestState = Object.assign({{}}, first.mindfulness);
                if (first.mental_health_progression && typeof first.mental_health_progression === "object") {{
                    latestState.progression = first.mental_health_progression;
                }}
                applied = true;
            }}

            if (!applied) {{
                const verifyAfterFirst = await qaVerifyMindfulnessSaved(desired, desired ? QA_MINDFULNESS_TARGET : 0);
                if (verifyAfterFirst.ok && verifyAfterFirst.state) {{
                    latestState = verifyAfterFirst.state;
                    applied = true;
                }}
            }}

            if (!applied) {{
                const retryPayload = Object.assign({{}}, payload, {{ source: "dashboard_manual" }});
                const retry = await qaPost("/v1/ui/mindfulness/log", retryPayload);
                if (retry && retry.mindfulness) {{
                    latestState = Object.assign({{}}, retry.mindfulness);
                    if (retry.mental_health_progression && typeof retry.mental_health_progression === "object") {{
                        latestState.progression = retry.mental_health_progression;
                    }}
                    applied = true;
                }} else {{
                    const verifyAfterRetry = await qaVerifyMindfulnessSaved(desired, desired ? QA_MINDFULNESS_TARGET : 0);
                    if (verifyAfterRetry.ok && verifyAfterRetry.state) {{
                        latestState = verifyAfterRetry.state;
                        applied = true;
                    }}
                }}
            }}

            if (applied && latestState) {{
                qaApplyMindfulnessState(latestState);
                if (status) {{
                    const minutes = Number(latestState.minutes_done || QA_MINDFULNESS_TARGET);
                    if (desired) {{
                        status.textContent = `✅ Mindfulness saved (${{Math.max(0, Math.round(minutes))}}m)`;
                        status.style.color = "#6ee7b7";
                    }} else {{
                        status.textContent = "↩️ Mindfulness cleared";
                        status.style.color = "#9ca3af";
                    }}
                }}
            }} else {{
                input.checked = !desired;
                if (status) {{
                    status.textContent = "❌ Mindfulness save failed. Retry from http://127.0.0.1:8765/dashboard";
                    status.style.color = "#fca5a5";
                }}
            }}
        }} catch (err) {{
            input.checked = !desired;
            if (status) {{
                status.textContent = `❌ Mindfulness save failed: ${{(err && err.message) ? err.message : "unknown error"}}`;
                status.style.color = "#fca5a5";
            }}
        }} finally {{
            input.disabled = false;
            qaMindfulnessSaving = false;
            qaMindfulnessDesiredDone = null;
        }}
    }}

    async function qaQuickToggleMindfulness(input) {{
        if (!input) return;
        const main = document.getElementById("qa-mindfulness-check");
        if (main) {{
            main.checked = Boolean(input.checked);
            await qaToggleMindfulness(main);
            input.checked = Boolean(main.checked);
            return;
        }}
        await qaToggleMindfulness(input);
    }}

    function qaMoodSummary(state) {{
        const safe = (state && typeof state === "object") ? state : {{}};
        const done = Boolean(safe.done);
        const source = String(safe.source || "").toLowerCase();
        const habit = String(safe.habit || "").trim() || "Mood check-in";
        if (done) {{
            const sourceLabel = source.includes("streaks") ? "Streaks" : "manual";
            return `✅ Mood check-in done today (${{sourceLabel}}) • ${{habit}}`;
        }}
        const latest = String(safe.latest_completed || "").trim();
        if (latest) {{
            return `⬜ Mood check-in pending • last: ${{latest}} • ${{habit}}`;
        }}
        return `⬜ Mood check-in pending • ${{habit}}`;
    }}

    function qaSetMoodSaveState(kind) {{
        const badge = document.getElementById("qa-mood-save-state");
        if (!badge) return;
        const k = String(kind || "").toLowerCase();
        badge.hidden = false;
        if (k === "saving") {{
            badge.textContent = "saving...";
            badge.style.color = "#93c5fd";
            badge.style.borderColor = "rgba(147,197,253,0.35)";
            return;
        }}
        if (k === "retrying") {{
            badge.textContent = "retrying";
            badge.style.color = "#fbbf24";
            badge.style.borderColor = "rgba(251,191,36,0.35)";
            return;
        }}
        if (k === "error") {{
            badge.textContent = "save failed";
            badge.style.color = "#fca5a5";
            badge.style.borderColor = "rgba(248,113,113,0.4)";
            return;
        }}
        badge.hidden = true;
        badge.textContent = "synced";
        badge.style.color = "#6ee7b7";
        badge.style.borderColor = "rgba(110,231,183,0.4)";
    }}

    function qaApplyMoodState(state) {{
        const safe = (state && typeof state === "object") ? state : {{}};
        const done = Boolean(safe.done);
        const quickCheck = document.getElementById("qa-quick-mood-check");
        if (quickCheck) {{
            quickCheck.checked = done;
        }}
        const moodMeta = document.getElementById("qa-mood-meta");
        if (moodMeta) {{
            moodMeta.textContent = qaMoodSummary(safe);
            moodMeta.style.color = done ? "#6ee7b7" : "#9ca3af";
        }}
        qaUpdateQuickDoneMeta();
    }}

    async function qaVerifyMoodSaved(expectedDone) {{
        const payload = await qaGet("/v1/ui/today");
        const today = (payload && payload.today && typeof payload.today === "object") ? payload.today : null;
        if (!today || !today.mood_checkin || typeof today.mood_checkin !== "object") {{
            return {{ ok: false, state: null }};
        }}
        const state = Object.assign({{}}, today.mood_checkin);
        return {{
            ok: Boolean(state.done) === Boolean(expectedDone),
            state,
        }};
    }}

    async function qaToggleMoodQuick(input) {{
        if (!input) return;
        if (qaMoodSaving) return;
        qaMoodSaving = true;
        input.disabled = true;
        const desired = Boolean(input.checked);
        const status = document.getElementById("qa-status");
        qaSetMoodSaveState("saving");
        try {{
            const result = await qaPostWithRetry("/v1/ui/mood/log", {{
                done: desired,
                date: qaEffectiveDateKey(),
                source: "autosave",
            }}, {{ retries: 2, label: "mood check-in" }});
            if (result && result.mood_checkin) {{
                qaApplyMoodState(result.mood_checkin);
                qaSetMoodSaveState("synced");
                if (status) {{
                    status.textContent = desired ? "✅ Mood check-in saved" : "↩️ Mood check-in cleared";
                    status.style.color = desired ? "#6ee7b7" : "#9ca3af";
                }}
            }} else {{
                qaSetMoodSaveState("retrying");
                const verify = await qaVerifyMoodSaved(desired);
                if (verify.ok && verify.state) {{
                    qaApplyMoodState(verify.state);
                    qaSetMoodSaveState("synced");
                }} else {{
                    input.checked = !desired;
                    qaSetMoodSaveState("error");
                }}
            }}
        }} catch (err) {{
            input.checked = !desired;
            qaSetMoodSaveState("error");
            if (status) {{
                status.textContent = `❌ Mood save failed: ${{(err && err.message) ? err.message : "unknown error"}}`;
                status.style.color = "#fca5a5";
            }}
        }} finally {{
            input.disabled = false;
            qaMoodSaving = false;
        }}
    }}

    let _qaMoodCtx = 'general';
    function qaMoodCtx(btn) {{
        document.querySelectorAll('.mood-ctx').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _qaMoodCtx = btn.dataset.ctx;
    }}
    async function qaMoodSelect(btn) {{
        if (!btn || qaMoodEntrySaving) return;
        const nowMs = Date.now();
        if ((nowMs - qaMoodEntryLastAt) < 1200) return;
        qaMoodEntryLastAt = nowMs;

        const mood = btn.dataset.mood;
        const label = btn.dataset.label;
        if (!mood) return;
        qaMoodEntrySaving = true;
        const status = document.getElementById("qa-status");
        qaSetMoodSaveState("saving");
        const moodButtons = Array.from(document.querySelectorAll('.mood-btn'));
        moodButtons.forEach((b) => {{ b.disabled = true; }});
        btn.classList.add('selected');
        setTimeout(() => btn.classList.remove('selected'), 600);
        try {{
            if (status) {{
                status.textContent = "⏳ Saving mood...";
                status.style.color = "#93c5fd";
            }}
            const data = await qaPostWithRetry('/v1/ui/mood/entry', {{mood, label, context: _qaMoodCtx}}, {{ retries: 1, label: "mood entry" }});
            if (data && data.status === 'ok') {{
                const latest = (data.latest && typeof data.latest === "object") ? data.latest : {{}};
                const latestMood = String(latest.mood || mood).trim() || mood;
                const latestLabel = String(latest.label || label || "").trim() || label || "";
                const latestTime = String(latest.time || "").trim();
                const fallbackNow = new Date();
                const displayTime = latestTime || `${{fallbackNow.getHours().toString().padStart(2,'0')}}:${{fallbackNow.getMinutes().toString().padStart(2,'0')}}`;
                const pillText = `${{displayTime}} ${{latestMood}}`;

                // Add pill to timeline (dedupe exact same display token).
                let timeline = document.getElementById('qa-mood-timeline');
                const appendPill = () => {{
                    const pill = document.createElement('span');
                    pill.className = 'mood-pill';
                    pill.textContent = pillText;
                    return pill;
                }};
                if (timeline) {{
                    const existing = Array.from(timeline.querySelectorAll('.mood-pill')).map((p) => p.textContent || "");
                    if (!existing.includes(pillText)) {{
                        timeline.appendChild(document.createTextNode(' \u2192 '));
                        timeline.appendChild(appendPill());
                    }}
                }} else {{
                    const t = document.createElement('div');
                    t.className = 'mood-timeline';
                    t.id = 'qa-mood-timeline';
                    t.appendChild(appendPill());
                    const card = document.querySelector('.mood-card');
                    if (card) card.appendChild(t);
                }}
                // Update header context pill
                const headerPill = document.querySelector('[data-context-pill="mood"]');
                if (headerPill) headerPill.textContent = `${{latestMood}} ${{latestLabel}}`;
                const header = document.querySelector('.mood-current');
                if (header) header.textContent = `${{latestMood}} ${{latestLabel}}`;
                const moodCheckResult = await qaPostWithRetry("/v1/ui/mood/log", {{
                    done: true,
                    date: qaEffectiveDateKey(),
                    source: "autosave",
                }}, {{ retries: 1, label: "mood check-in" }});
                if (moodCheckResult && moodCheckResult.mood_checkin) {{
                    qaApplyMoodState(moodCheckResult.mood_checkin);
                }}
                qaSetMoodSaveState("synced");
                if (status) {{
                    status.textContent = data.deduped ? "✅ Mood saved (deduped tap)" : "✅ Mood saved";
                    status.style.color = "#6ee7b7";
                }}
            }} else if (status) {{
                qaSetMoodSaveState("error");
                status.textContent = "❌ Mood save failed";
                status.style.color = "#fca5a5";
            }}
        }} catch(err) {{
            qaSetMoodSaveState("error");
            if (status) {{
                status.textContent = `\u274c Mood save failed`;
                status.style.color = "#fca5a5";
            }}
        }} finally {{
            moodButtons.forEach((b) => {{ b.disabled = false; }});
            qaMoodEntrySaving = false;
        }}
    }}

    function qaUpdateQuickDoneMeta() {{
        const meta = document.getElementById("qa-quick-done-meta");
        if (!meta) return;
        const mind = document.getElementById("qa-quick-mindfulness-check");
        const workout = document.getElementById("qa-quick-workout-check");
        const mood = document.getElementById("qa-quick-mood-check");
        let total = 0;
        let done = 0;
        if (mind) {{
            total += 1;
            if (mind.checked) done += 1;
        }}
        if (workout) {{
            total += 1;
            if (workout.checked) done += 1;
        }}
        if (mood) {{
            total += 1;
            if (mood.checked) done += 1;
        }}
        meta.textContent = `${{done}}/${{total || 0}} check-ins done.`;
        meta.style.color = done >= Math.max(1, total) ? "#6ee7b7" : "#93c5fd";
    }}

    function qaApplyWorkoutState(done, workoutLabel) {{
        const checkbox = document.getElementById("qa-workout-check");
        if (checkbox) {{
            checkbox.checked = Boolean(done);
        }}
        const quickCheckbox = document.getElementById("qa-quick-workout-check");
        if (quickCheckbox) {{
            quickCheckbox.checked = Boolean(done);
        }}
        const meta = document.getElementById("qa-workout-meta");
        if (meta) {{
            const label = String(workoutLabel || "Workout").trim() || "Workout";
            if (done) {{
                meta.textContent = `✅ ${{label}} logged for today`;
                meta.style.color = "#6ee7b7";
            }} else {{
                meta.textContent = `⬜ ${{label}} not logged yet`;
                meta.style.color = "#9ca3af";
            }}
        }}
        const labelLower = String(workoutLabel || "").toLowerCase();
        if (labelLower.includes("yoga")) qaCurrentWorkoutType = "yoga";
        else if (labelLower.includes("workout")) qaCurrentWorkoutType = "weights";
        qaCurrentWorkoutDone = Boolean(done);
        qaUpdateQuickDoneMeta();
        qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
    }}

    async function qaToggleWorkout(input) {{
        if (!input) return;
        if (qaWorkoutSaving) return;
        qaWorkoutSaving = true;
        input.disabled = true;
        const desired = Boolean(input.checked);
        const workoutLabel = String((input.dataset && input.dataset.workout) || "").trim() || "Workout";
        const status = document.getElementById("qa-status");
        try {{
            if (status) {{
                status.textContent = desired ? `⏳ Logging ${{workoutLabel}}...` : `⏳ Clearing ${{workoutLabel}}...`;
                status.style.color = "#93c5fd";
            }}
            const resultWithRetry = await qaPostWithRetry("/v1/ui/workout/log", {{
                done: desired,
                workout: workoutLabel,
                date: qaEffectiveDateKey(),
                source: "dashboard",
            }}, {{ retries: 1, label: "workout log" }});
            if (resultWithRetry && resultWithRetry.workout) {{
                const savedDone = Boolean(resultWithRetry.workout.done);
                const savedWorkoutLabel = resultWithRetry.workout.workout || workoutLabel;
                qaApplyWorkoutState(savedDone, savedWorkoutLabel);
                const labelLower = String(savedWorkoutLabel || "").toLowerCase();
                if (labelLower.includes("yoga")) {{
                    qaCurrentWorkoutType = "yoga";
                }} else if (labelLower.includes("workout")) {{
                    qaCurrentWorkoutType = "weights";
                }}
                qaCurrentWorkoutDone = savedDone;
                qaApplyYogaFeedbackPrompt({{ autoOpen: savedDone && qaCurrentWorkoutType === "yoga" }});
                if (status) {{
                    status.textContent = desired ? `✅ ${{workoutLabel}} logged` : `↩️ ${{workoutLabel}} marked not done`;
                    status.style.color = desired ? "#6ee7b7" : "#9ca3af";
                }}
                // Refresh dynamic cards without forcing a full dashboard reload (prevents stale checkbox resets).
                setTimeout(() => {{ qaSyncTodayFromApi({{ force: true }}); }}, 350);
            }} else {{
                input.checked = !desired;
                if (status) {{
                    status.textContent = `❌ ${{workoutLabel}} save failed`;
                    status.style.color = "#fca5a5";
                }}
            }}
        }} catch (err) {{
            input.checked = !desired;
            if (status) {{
                status.textContent = `❌ ${{workoutLabel}} save failed: ${{(err && err.message) ? err.message : "unknown error"}}`;
                status.style.color = "#fca5a5";
            }}
        }} finally {{
            input.disabled = false;
            qaWorkoutSaving = false;
        }}
    }}

    async function qaQuickToggleWorkout(input) {{
        if (!input) return;
        const main = document.getElementById("qa-workout-check");
        if (main) {{
            main.checked = Boolean(input.checked);
            await qaToggleWorkout(main);
            input.checked = Boolean(main.checked);
            return;
        }}
        await qaToggleWorkout(input);
    }}

    function qaParseOptionalIntInput(inputId, minVal, maxVal) {{
        const input = document.getElementById(inputId);
        if (!input) return null;
        const raw = String(input.value || "").trim();
        if (!raw) return null;
        const num = Number(raw);
        if (!Number.isFinite(num)) return null;
        const rounded = Math.round(num);
        if (rounded < minVal || rounded > maxVal) return null;
        return rounded;
    }}

    function qaApplyWorkoutChecklistState(state) {{
        const safeState = (state && typeof state === "object") ? state : {{}};
        const recovery = String(safeState.recovery_gate || "unknown").toLowerCase();
        const recoverySelect = document.getElementById("qa-wc-recovery");
        if (recoverySelect) {{
            recoverySelect.value = ["pass", "fail", "unknown"].includes(recovery) ? recovery : "unknown";
        }}
        const calfCheck = document.getElementById("qa-wc-calf");
        if (calfCheck) {{
            calfCheck.checked = Boolean(safeState.calf_done);
        }}
        const post = (safeState.post_workout && typeof safeState.post_workout === "object") ? safeState.post_workout : {{}};
        const rpe = Number(post.rpe);
        const pain = Number(post.pain);
        const energy = Number(post.energy_after);
        const rpeInput = document.getElementById("qa-wc-rpe");
        const painInput = document.getElementById("qa-wc-pain");
        const energyInput = document.getElementById("qa-wc-energy");
        if (rpeInput) rpeInput.value = Number.isFinite(rpe) ? String(Math.max(1, Math.min(10, Math.round(rpe)))) : "";
        if (painInput) painInput.value = Number.isFinite(pain) ? String(Math.max(0, Math.min(10, Math.round(pain)))) : "";
        if (energyInput) energyInput.value = Number.isFinite(energy) ? String(Math.max(1, Math.min(10, Math.round(energy)))) : "";

        const feedback = (safeState.session_feedback && typeof safeState.session_feedback === "object") ? safeState.session_feedback : {{}};
        const durationInput = document.getElementById("qa-wc-duration");
        const intensityInput = document.getElementById("qa-wc-intensity");
        const typeInput = document.getElementById("qa-wc-session-type");
        const bodyFeelInput = document.getElementById("qa-wc-body-feel");
        const noteInput = document.getElementById("qa-wc-note");
        const anxietyInput = document.getElementById("qa-wc-anxiety");
        const durationVal = Number(feedback.duration_minutes);
        if (durationInput) durationInput.value = Number.isFinite(durationVal) ? String(Math.max(5, Math.min(240, Math.round(durationVal)))) : "";
        if (intensityInput) {{
            const intensityVal = String(feedback.intensity || "").toLowerCase();
            intensityInput.value = ["easy", "moderate", "hard"].includes(intensityVal) ? intensityVal : "";
        }}
        if (typeInput) {{
            const typeVal = String(feedback.session_type || "").toLowerCase();
            typeInput.value = ["somatic", "yin", "flow", "mobility", "restorative", "other"].includes(typeVal) ? typeVal : "";
        }}
        if (bodyFeelInput) {{
            const bodyFeelVal = String(feedback.body_feel || "").toLowerCase();
            bodyFeelInput.value = ["relaxed", "neutral", "tight", "sore", "energised", "fatigued"].includes(bodyFeelVal) ? bodyFeelVal : "";
        }}
        if (noteInput) noteInput.value = String(feedback.session_note || "").slice(0, 280);
        const anxietyVal = Number(feedback.anxiety_reduction_score);
        if (anxietyInput && Number.isFinite(anxietyVal) && !String(anxietyInput.value || "").trim()) {{
            anxietyInput.value = String(Math.max(0, Math.min(10, Math.round(anxietyVal))));
        }}
        qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
    }}

    let qaWorkoutChecklistSaving = false;
    async function qaSaveWorkoutChecklist(button) {{
        if (qaWorkoutChecklistSaving) return;
        qaWorkoutChecklistSaving = true;
        const recoverySelect = document.getElementById("qa-wc-recovery");
        const calfCheck = document.getElementById("qa-wc-calf");
        const status = document.getElementById("qa-wc-status");
        const baselineUpdatedAt = String((QA_WORKOUT_CHECKLIST_INITIAL && QA_WORKOUT_CHECKLIST_INITIAL.updated_at) || "").trim();
        if (status) {{
            status.textContent = "⏳ Saving checklist...";
            status.style.color = "#93c5fd";
        }}
        if (button) {{
            button.disabled = true;
            button.textContent = "Saving...";
        }}
        try {{
            const recoveryGate = recoverySelect ? String(recoverySelect.value || "unknown").toLowerCase() : "unknown";
            if (!["pass", "fail", "unknown"].includes(recoveryGate)) {{
                if (status) {{
                    status.textContent = "⚠️ Recovery gate must be pass/fail/unknown.";
                    status.style.color = "#fbbf24";
                }}
                return;
            }}
            const rpe = qaParseOptionalIntInput("qa-wc-rpe", 1, 10);
            const pain = qaParseOptionalIntInput("qa-wc-pain", 0, 10);
            const energyAfter = qaParseOptionalIntInput("qa-wc-energy", 1, 10);
            const durationMinutes = qaParseOptionalIntInput("qa-wc-duration", 5, 240);
            const anxietyScore = qaParseOptionalIntInput("qa-wc-anxiety", 0, 10);
            const intensitySelect = document.getElementById("qa-wc-intensity");
            const sessionTypeSelect = document.getElementById("qa-wc-session-type");
            const bodyFeelSelect = document.getElementById("qa-wc-body-feel");
            const noteInput = document.getElementById("qa-wc-note");
            const intensity = intensitySelect ? String(intensitySelect.value || "").trim().toLowerCase() : "";
            const sessionType = sessionTypeSelect ? String(sessionTypeSelect.value || "").trim().toLowerCase() : "";
            const bodyFeel = bodyFeelSelect ? String(bodyFeelSelect.value || "").trim().toLowerCase() : "";
            const sessionNote = noteInput ? String(noteInput.value || "").trim().slice(0, 280) : "";
            const expected = {{
                recovery_gate: recoveryGate,
                calf_done: Boolean(calfCheck && calfCheck.checked),
                rpe,
                pain,
                energy_after: energyAfter,
                duration_minutes: durationMinutes,
                intensity,
                session_type: sessionType,
                body_feel: bodyFeel,
                session_note: sessionNote,
            }};
            const payload = {{
                date: qaEffectiveDateKey(),
                recovery_gate: recoveryGate,
                calf_done: expected.calf_done,
                source: "dashboard",
            }};
            if (rpe !== null) payload.rpe = rpe;
            if (pain !== null) payload.pain = pain;
            if (energyAfter !== null) payload.energy_after = energyAfter;
            if (durationMinutes !== null) payload.duration_minutes = durationMinutes;
            if (intensity) payload.intensity = intensity;
            if (sessionType) payload.session_type = sessionType;
            if (bodyFeel) payload.body_feel = bodyFeel;
            payload.session_note = sessionNote;

            const checklistMatchesExpected = (state) => {{
                if (!state || typeof state !== "object") return false;
                const post = (state.post_workout && typeof state.post_workout === "object") ? state.post_workout : {{}};
                const feedback = (state.session_feedback && typeof state.session_feedback === "object") ? state.session_feedback : {{}};
                const stateRecovery = String(state.recovery_gate || "").toLowerCase();
                if (stateRecovery !== String(expected.recovery_gate || "").toLowerCase()) return false;
                if (Boolean(state.calf_done) !== Boolean(expected.calf_done)) return false;
                if (expected.rpe !== null && Number(post.rpe) !== Number(expected.rpe)) return false;
                if (expected.pain !== null && Number(post.pain) !== Number(expected.pain)) return false;
                if (expected.energy_after !== null && Number(post.energy_after) !== Number(expected.energy_after)) return false;
                if (expected.duration_minutes !== null && Number(feedback.duration_minutes) !== Number(expected.duration_minutes)) return false;
                if (expected.intensity && String(feedback.intensity || "").toLowerCase() !== expected.intensity) return false;
                if (expected.session_type && String(feedback.session_type || "").toLowerCase() !== expected.session_type) return false;
                if (expected.body_feel && String(feedback.body_feel || "").toLowerCase() !== expected.body_feel) return false;
                if (expected.session_note && String(feedback.session_note || "").trim() !== expected.session_note) return false;
                return true;
            }};

            const verifyChecklistSave = async () => {{
                for (let attempt = 0; attempt < 12; attempt += 1) {{
                    await qaDelay(450);
                    const verify = await qaGet("/v1/ui/today");
                    const today = (verify && verify.today && typeof verify.today === "object") ? verify.today : null;
                    const currentChecklist = (today && today.workout_checklist && typeof today.workout_checklist === "object") ? today.workout_checklist : null;
                    const currentUpdatedAt = String((currentChecklist && currentChecklist.updated_at) || "").trim();
                    if (!currentChecklist) continue;
                    const updated = !baselineUpdatedAt || (currentUpdatedAt && currentUpdatedAt !== baselineUpdatedAt);
                    if (updated && checklistMatchesExpected(currentChecklist)) {{
                        return {{
                            workout_checklist: currentChecklist,
                            workout_checklist_signals: (today.workout_checklist_signals && typeof today.workout_checklist_signals === "object") ? today.workout_checklist_signals : {{}},
                            workout_progression: (today.workout_progression && typeof today.workout_progression === "object") ? today.workout_progression : {{}},
                            workout_progression_weights: (today.workout_progression_weights && typeof today.workout_progression_weights === "object") ? today.workout_progression_weights : {{}},
                            anxiety_reduction_score: today.anxiety_reduction_score,
                            workout: (today.workout && typeof today.workout === "object") ? today.workout : null,
                        }};
                    }}
                }}
                return null;
            }};

            let result = null;
            let savedViaVerify = false;
            const postTask = (async () => {{
                try {{
                    return await qaPostWithRetry("/v1/ui/workout/checklist", payload, {{ retries: 1, label: "workout checklist" }});
                }} catch (_err) {{
                    return null;
                }}
            }})();
            const verifyTask = verifyChecklistSave();
            const winner = await Promise.race([
                postTask.then((data) => ({{ source: "post", data }})),
                verifyTask.then((data) => ({{ source: "verify", data }})),
                qaDelay(12000).then(() => ({{ source: "timeout", data: null }})),
            ]);

            if (winner && winner.data) {{
                result = winner.data;
                savedViaVerify = winner.source === "verify";
            }} else {{
                const verified = await Promise.race([
                    verifyTask,
                    qaDelay(2500).then(() => null),
                ]);
                if (verified) {{
                    result = verified;
                    savedViaVerify = true;
                }}
            }}

            let anxietySaved = false;
            if (anxietyScore !== null) {{
                const anxietyResult = await qaPostWithRetry("/v1/ui/interventions/rating", {{
                    score: anxietyScore,
                    date: qaEffectiveDateKey(),
                    source: "dashboard_manual",
                }}, {{ retries: 1, label: "anxiety score" }});
                if (anxietyResult && Number.isFinite(Number(anxietyResult.score))) {{
                    qaApplyAnxietyScore(Number(anxietyResult.score));
                    anxietySaved = true;
                }}
            }}

            if (result && result.workout_checklist) {{
                try {{
                    qaApplyWorkoutChecklistState(result.workout_checklist);
                    if (result.workout_checklist_signals && typeof result.workout_checklist_signals === "object") {{
                        qaApplyWorkoutChecklistSignals(result.workout_checklist_signals);
                    }}
                    if (result.workout_progression && typeof result.workout_progression === "object") {{
                        qaApplyWorkoutProgression(result.workout_progression);
                    }}
                    if (result.workout_progression_weights && typeof result.workout_progression_weights === "object") {{
                        qaApplyWeightsProgression(result.workout_progression_weights);
                    }}
                    if (result.workout && typeof result.workout === "object") {{
                        qaCurrentWorkoutType = String(result.workout.type || qaCurrentWorkoutType || "").toLowerCase();
                        qaCurrentWorkoutDone = Boolean(result.workout.done);
                    }}
                    if (anxietyScore !== null && !anxietySaved && Number.isFinite(Number(result.anxiety_reduction_score))) {{
                        qaApplyAnxietyScore(Number(result.anxiety_reduction_score));
                    }}
                    qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
                }} catch (_err) {{
                    // Keep status truthful even if DOM sync has an edge-case error.
                }}
                if (status) {{
                    status.textContent = savedViaVerify
                        ? (anxietySaved ? "✅ Checklist + anxiety saved (verified)" : "✅ Checklist saved (verified)")
                        : (anxietySaved ? "✅ Checklist + anxiety saved" : "✅ Checklist saved");
                    status.style.color = "#6ee7b7";
                }}
            }} else if (status) {{
                status.textContent = "⚠️ Saved may have succeeded. Reload once to confirm.";
                status.style.color = "#fbbf24";
            }}
        }} catch (err) {{
            if (status) {{
                const msg = (err && err.message) ? err.message : "Unexpected checklist error";
                status.textContent = "❌ " + msg;
                status.style.color = "#fca5a5";
            }}
        }} finally {{
            if (button) {{
                button.disabled = false;
                button.textContent = "Save checklist";
            }}
            qaWorkoutChecklistSaving = false;
        }}
    }}

    async function qaGenerateWeeklyDigest(button) {{
        const status = document.getElementById("qa-status");
        const badge = document.getElementById("qa-weekly-digest-status");
        const currentLink = document.getElementById("qa-weekly-digest-current-link");
        const latestLink = document.getElementById("qa-weekly-digest-latest-link");
        const meta = document.getElementById("qa-weekly-digest-meta");
        if (button) {{
            button.disabled = true;
            button.textContent = "Generating...";
        }}
        if (status) {{
            status.textContent = "⏳ Generating weekly report...";
            status.style.color = "#93c5fd";
        }}
        try {{
            const result = await qaPostWithRetry("/v1/ui/weekly-digest/generate", {{}}, {{ retries: 0, label: "weekly digest" }});
            if (result && result.path) {{
                const rawPath = String(result.path || "").trim();
                const fileName = rawPath ? rawPath.split("/").pop() : "weekly digest";
                let fileUrl = String(result.url || "").trim();
                if (!fileUrl && rawPath) {{
                    fileUrl = `file://${{rawPath}}`;
                }}
                if (currentLink) {{
                    currentLink.textContent = fileName;
                    if (fileUrl) currentLink.href = fileUrl;
                    currentLink.style.color = "#a7f3d0";
                }}
                if (latestLink) {{
                    latestLink.textContent = fileName;
                    if (fileUrl) latestLink.href = fileUrl;
                    latestLink.style.color = "#93c5fd";
                }}
                if (badge) {{
                    badge.textContent = "✅ Ready";
                    badge.style.color = "#6ee7b7";
                }}
                if (meta) {{
                    meta.textContent = "Weekly report generated and linked.";
                    meta.style.color = "#6b7280";
                }}
                if (status) {{
                    status.textContent = "✅ Weekly report generated";
                    status.style.color = "#6ee7b7";
                }}
                if (button) {{
                    button.textContent = "↻ Regenerate week report";
                }}
            }} else if (status) {{
                status.textContent = "⚠️ Weekly report generation may have failed";
                status.style.color = "#fbbf24";
            }}
        }} catch (err) {{
            if (status) {{
                status.textContent = `❌ Weekly report failed: ${{(err && err.message) ? err.message : "unknown error"}}`;
                status.style.color = "#fca5a5";
            }}
        }} finally {{
            if (button) button.disabled = false;
        }}
    }}

    async function qaRefreshData(button) {{
        if (button) {{
            button.disabled = true;
            button.textContent = "Refreshing...";
        }}
        const status = document.getElementById("qa-status");
        const SOFT_TIMEOUT_SECONDS = 120;
        const HARD_TIMEOUT_SECONDS = 360;
        const POLL_INTERVAL_MS = 3000;
        const resetButton = () => {{
            if (!button) return;
            button.disabled = false;
            button.textContent = "🔄 Refresh Data Now";
        }};
        const finish = (message, color, shouldReload = false, reloadDelayMs = 1800) => {{
            if (status) {{
                status.textContent = message;
                status.style.color = color;
            }}
            resetButton();
            if (shouldReload) {{
                setTimeout(() => window.location.reload(), Math.max(700, Number(reloadDelayMs) || 1800));
            }}
        }};
        try {{
            const trigger = await qaPostWithRetry('/v1/ui/refresh/trigger', {{}}, {{ retries: 1, label: "refresh trigger" }});
            if (trigger && (trigger.status === 'already_running' || trigger.status === 'started')) {{
                if (status) {{ status.textContent = "🔄 Refreshing..."; status.style.color = "#93c5fd"; }}
                const triggerRefresh = (trigger.refresh && typeof trigger.refresh === "object") ? trigger.refresh : {{}};
                const activeRunId = String(trigger.run_id || triggerRefresh.run_id || "").trim();
                const startedRaw = String(trigger.started_at || triggerRefresh.started_at || "").trim();
                const startedAtMs = Number.isFinite(Date.parse(startedRaw)) ? Date.parse(startedRaw) : Date.now();
                let warnedSlow = false;

                let pollTimer = null;
                const stopPolling = () => {{
                    if (pollTimer) {{
                        clearTimeout(pollTimer);
                        pollTimer = null;
                    }}
                }};
                const schedulePoll = () => {{
                    stopPolling();
                    pollTimer = setTimeout(() => {{
                        pollRefreshStatus();
                    }}, POLL_INTERVAL_MS);
                }};
                const pollRefreshStatus = async () => {{
                    const elapsed = Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000));
                    try {{
                        const d = await qaGet('/v1/ui/status', {{ coalesce: false }});
                        if (d && typeof d === "object") {{
                            const refresh = (d.refresh && typeof d.refresh === "object") ? d.refresh : {{}};
                            const refreshRunId = String(refresh.run_id || "").trim();
                            const sameRun = !activeRunId || !refreshRunId || activeRunId === refreshRunId;
                            const refreshStatus = String(refresh.status || "").toLowerCase();
                            const beforeStamp = String(refresh.last_cache_timestamp_before || "").trim();
                            const afterStamp = String(refresh.last_cache_timestamp_after || "").trim();
                            const cacheAdvanced = Boolean(beforeStamp && afterStamp && beforeStamp !== afterStamp);
                            const daemonRunning = Boolean(d.daemon_running);

                            if (sameRun && (refreshStatus === "ok" || cacheAdvanced || (!daemonRunning && refreshStatus !== "error" && refreshStatus !== "timeout"))) {{
                                stopPolling();
                                finish("✅ Refreshed — reload to see updates", "#6ee7b7", true, 1500);
                                return;
                            }}
                            if (sameRun && refreshStatus === "error") {{
                                stopPolling();
                                const errMsg = String(refresh.error || "refresh failed");
                                finish(`❌ Refresh failed: ${{errMsg}}`, "#fca5a5", false);
                                return;
                            }}
                            if (sameRun && refreshStatus === "timeout") {{
                                stopPolling();
                                finish("⚠️ Refresh timed out", "#fbbf24", false);
                                return;
                            }}
                        }}
                    }} catch (_err) {{
                        // Treat transient poll errors as still-running unless hard timeout reached.
                    }}

                    if (!warnedSlow && elapsed >= SOFT_TIMEOUT_SECONDS && status) {{
                        warnedSlow = true;
                        status.textContent = "⏳ Refresh still running…";
                        status.style.color = "#fbbf24";
                    }}
                    if (elapsed >= HARD_TIMEOUT_SECONDS) {{
                        stopPolling();
                        finish("⚠️ Refresh timed out", "#fbbf24", false);
                        return;
                    }}
                    schedulePoll();
                }};
                pollRefreshStatus();
            }} else {{
                const ok = await qaPostWithRetry("/v1/ui/refresh", {{}}, {{ retries: 1, label: "refresh" }});
                if (ok && status) {{
                    status.textContent = "✅ Refresh complete.";
                    status.style.color = "#6ee7b7";
                    setTimeout(() => window.location.reload(), 1500);
                }}
                resetButton();
            }}
        }} catch(err) {{
            finish("❌ Refresh failed", "#fca5a5", false);
        }}
    }}

    async function qaRunEndDay(button) {{
        const current = qaNormalizeEndDayState(qaEndDayState);
        if (current.done_today) {{
            qaApplyEndDayState(current);
            const status = document.getElementById("qa-status");
            if (status) {{
                status.textContent = "ℹ️ End Day already run today.";
                status.style.color = "#94a3b8";
            }}
            return;
        }}

        qaEndDayRunning = true;
        qaApplyEndDayState(qaEndDayState);
        try {{
            const result = await qaPostWithRetry("/v1/ui/end-day", {{
                date: qaEffectiveDateKey(),
            }}, {{ retries: 1, label: "end-day pipeline" }});

            if (result) {{
                const endDayState = (result.end_day && typeof result.end_day === "object")
                    ? result.end_day
                    : {{
                        done_today: true,
                        date: qaEffectiveDateKey(),
                        ran_at: new Date().toISOString(),
                        source: "dashboard_ui",
                    }};
                qaApplyEndDayState(endDayState);
                const status = document.getElementById("qa-status");
                if (status) {{
                    status.textContent = "✅ End-day pipeline complete. Marked done for today.";
                    status.style.color = "#6ee7b7";
                }}
                try {{
                    localStorage.setItem("dashboard.focus.mode.v1", "report");
                    localStorage.setItem("dashboard.focus.override.v1", JSON.stringify({{
                        date: qaEffectiveDateKey(),
                        mode: "report"
                    }}));
                }} catch (_err) {{}}
                setTimeout(() => {{ qaSyncTodayFromApi({{ force: true }}); }}, 300);
                setTimeout(() => window.location.reload(), 1700);
            }} else {{
                const status = document.getElementById("qa-status");
                if (status) {{
                    status.textContent = "❌ End-day pipeline failed";
                    status.style.color = "#fca5a5";
                }}
            }}
        }} finally {{
            qaEndDayRunning = false;
            qaApplyEndDayState(qaEndDayState);
        }}
    }}

    async function qaHealSystem(button) {{
        if (button) {{
            button.disabled = true;
            button.textContent = "Healing...";
        }}
        const ok = await qaPostWithRetry("/v1/ui/system/heal", {{ wait_seconds: 20 }}, {{ retries: 1, label: "self-heal" }});
        if (ok && ok.after) {{
            qaUpdateSystemStatus(ok.after);
            const status = document.getElementById("qa-status");
            if (status) {{
                status.textContent = "✅ Self-heal complete";
                status.style.color = "#6ee7b7";
            }}
        }}
        if (button) {{
            button.disabled = false;
            button.textContent = "🛠️ Heal";
        }}
    }}
    qaApplyMindfulnessState(QA_MINDFULNESS_INITIAL);
    qaApplyMoodState(QA_MOOD_INITIAL);
    qaSetMoodSaveState("synced");
    qaSetAnxietySaveState("synced");
    qaApplyWorkoutChecklistState(QA_WORKOUT_CHECKLIST_INITIAL);
    qaApplyWorkoutChecklistSignals(QA_WORKOUT_SIGNALS_INITIAL);
    qaApplyWorkoutProgression(QA_WORKOUT_PROGRESSION_INITIAL);
    qaApplyWeightsProgression(QA_WORKOUT_WEIGHTS_PROGRESSION_INITIAL);
    qaApplyEndDayState(QA_END_DAY_INITIAL);
    qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
    qaLoadSyncPauseState();
    qaUpdateSyncPauseUi();
    qaUpdateQuickDoneMeta();
    qaApplyLocalCompletionUi();
    qaStartLeaderCoordination();
    qaSyncTodayFromApi({{ force: true }});
    setTimeout(() => {{ qaRetryPendingCompletions(); }}, 2000);
    setTimeout(() => {{ qaRetryPendingScratch(); }}, 2200);
	    </script>
	    '''

    def _scratch_pad_html(section_id, label, today_str):
        storage_key = f"dashboard.scratch.{today_str}.{section_id}"
        sid = html.escape(section_id)
        return f'''<details class="mt-3">
        <summary class="text-xs cursor-pointer" style="color: #94a3b8; user-select: none">📝 {html.escape(label)} scratch pad</summary>
        <textarea id="qa-scratch-{sid}"
            rows="3" maxlength="500"
            data-storage-key="{html.escape(storage_key)}"
            data-section="{sid}"
            class="mt-1 w-full rounded px-2 py-1.5 text-xs"
            style="background: rgba(15,23,42,0.85); border: 1px solid rgba(148,163,184,0.24); color: #e5e7eb; resize: vertical; font-family: inherit;"
            placeholder="Quick notes..."
            oninput="qaSaveScratchPad(this)"></textarea>
        <div class="mt-1 flex items-center gap-2">
            <button id="qa-scratch-submit-{sid}"
                onclick="qaScratchSubmit('{sid}')"
                class="px-3 py-1 rounded text-xs"
                style="background: rgba(110,231,183,0.18); color: #6ee7b7; border: 1px solid rgba(110,231,183,0.3); cursor: pointer;">
                Save to journal
            </button>
            <span id="qa-scratch-status-{sid}" class="text-xs" style="color: #94a3b8;"></span>
        </div>
    </details>'''

    controls_open_attr = ""
    optional_pills_default = bool(weekly_needs_generation or qa_yoga_prompt_needed)
    optional_pills_attr = "on" if optional_pills_default else "off"
    utility_css = build_dashboard_utility_css()
    top_status_pills = []
    if not _diarium_is_fresh:
        stale_label = _truncate_sentence_safe(diarium_fresh_line, 74)
        top_status_pills.append(
            f'<span class="status-pill-mini">⚠️ {html.escape(stale_label)}</span>'
        )
    elif freshness_overall_level in {"warn", "error"}:
        freshness_label = _truncate_sentence_safe(freshness_overall_line, 74)
        top_status_pills.append(
            f'<span class="status-pill-mini">🧭 {html.escape(freshness_label)}</span>'
        )
    if bool(data.get("importantThingMissing", False)) and _diarium_is_fresh:
        top_status_pills.append('<span class="status-pill-mini">⚠️ Set important thing</span>')
    if weekly_needs_generation:
        top_status_pills.append('<span class="status-pill-mini">📅 Weekly digest due</span>')
    if system_needs_attention:
        top_status_pills.append('<span class="status-pill-mini">🧰 System attention</span>')
    top_status_pills_html = (
        f'<div class="top-status-row mt-3">{"".join(top_status_pills)}</div>'
        if top_status_pills else ""
    )
    weekly_nav_link_html = '<a href="#weekly">📅 Weekly</a>' if weekly_digest_html else ""

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Dashboard">
    <link rel="apple-touch-icon" href="/apple-touch-icon.png">
    <link rel="icon" href="/favicon.ico">
    <link rel="shortcut icon" href="/favicon.ico">
    <title>Daily Dashboard - {data.get("date", "")}</title>
    <style>
        {utility_css}
        :root {{
            --bg: #0b1020;
            --panel: rgba(15,23,42,0.74);
            --panel-border: rgba(148,163,184,0.25);
            --text: #e5e7eb;
            --muted: #94a3b8;
            --focus: #6ee7b7;
            --focus-soft: #cbefdf;
        }}
        * {{ box-sizing: border-box; }}
        html {{ font-size: 17px; }}
        body {{
            margin: 0;
            background:
                radial-gradient(circle at 85% -10%, rgba(14,116,144,0.24), transparent 34%),
                radial-gradient(circle at -10% 0%, rgba(131,24,67,0.2), transparent 30%),
                var(--bg);
            color: var(--text);
            font-family: "Aptos", "Segoe UI", "Trebuchet MS", "Verdana", sans-serif;
            line-height: 1.55;
            letter-spacing: 0.01em;
        }}
        a {{ color: inherit; text-decoration: none; }}
        a:hover {{ color: var(--focus); }}
        .dashboard-shell {{
            max-width: 1120px;
            margin: 0 auto;
            padding: 1rem 0.95rem 2.25rem;
        }}
        @media (min-width: 768px) {{
            .dashboard-shell {{ padding: 1.5rem 1.2rem 2.75rem; }}
        }}
        .card {{
            background: var(--panel);
            border: 1px solid var(--panel-border);
            border-radius: 0.9rem;
            padding: 1.1rem 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 10px 22px rgba(2,6,23,0.24);
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        .card:hover {{
            border-color: rgba(167,243,208,0.26);
            box-shadow: 0 12px 26px rgba(2,6,23,0.28);
        }}
        .top-status-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
        }}
        .status-pill-mini {{
            display: inline-flex;
            align-items: center;
            gap: 0.22rem;
            padding: 0.18rem 0.48rem;
            border-radius: 999px;
            border: 1px solid rgba(148,163,184,0.2);
            background: rgba(15,23,42,0.46);
            color: #cbd5e1;
            font-size: 0.72rem;
            line-height: 1.15;
            font-weight: 600;
        }}
        /* Mood emoji selector */
        .mood-emojis {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }}
        .mood-btn {{ font-size: 1.6rem; background: none; border: 2px solid transparent; border-radius: 8px; cursor: pointer; padding: 4px; transition: all 0.2s; }}
        .mood-btn:hover, .mood-btn.selected {{ border-color: var(--focus); background: rgba(110,231,183,0.08); transform: scale(1.15); }}
        .mood-context-btns {{ display: flex; gap: 6px; margin: 6px 0; }}
        .mood-ctx {{ font-size: 0.75rem; padding: 2px 10px; border-radius: 12px; border: 1px solid var(--panel-border); background: none; cursor: pointer; color: var(--muted); }}
        .mood-ctx.active {{ background: var(--focus); color: #0f172a; border-color: var(--focus); }}
        .mood-timeline {{ font-size: 0.8rem; color: var(--muted); margin-top: 6px; }}
        .mood-pill {{ background: var(--panel); border-radius: 10px; padding: 2px 6px; }}
        .mood-current {{ font-size: 0.9rem; margin-left: auto; }}
        body[data-optional-pills="off"] .optional-pill {{ display: none !important; }}
        body[data-optional-pills="off"] .mood-timeline {{ display: none !important; }}
        body[data-optional-pills="off"] .mood-pill {{ display: none !important; }}
        body[data-optional-pills="off"] #status-legend-wrap {{ display: none !important; }}

        .card h3 {{ line-height: 1.35; letter-spacing: 0.01em; }}
        .dashboard-section {{ margin-bottom: 0.9rem; }}
        .dashboard-section:empty {{ display: none; }}
        .dashboard-section[id] {{ scroll-margin-top: 4.6rem; }}
        .settings-stack {{
            margin: 0 0 0.82rem 0;
            display: grid;
            grid-template-columns: 1fr;
            gap: 0.34rem;
        }}
        .settings-toolbar-stack {{
            gap: 0.34rem;
        }}
        .settings-rail {{
            border-radius: 0.7rem;
            border: 1px solid rgba(148,163,184,0.2);
            background: rgba(15,23,42,0.5);
            padding: 0.22rem 0.38rem;
            min-height: 2.05rem;
            scrollbar-width: thin;
            -webkit-overflow-scrolling: touch;
        }}
        .settings-toolbar {{
            display: flex;
            flex-direction: column;
            gap: 0.34rem;
        }}
        .toolbar-row {{
            display: flex;
            align-items: center;
            gap: 0.22rem;
            min-width: 0;
        }}
        .toolbar-row-nav {{
            overflow-x: auto;
            white-space: nowrap;
        }}
        .dashboard-toolbar-controls {{
            display: block;
            min-width: 0;
        }}
        .toolbar-summary {{
            display: flex;
            align-items: center;
            gap: 0.22rem;
            min-width: 0;
            overflow-x: auto;
            white-space: nowrap;
            cursor: pointer;
            user-select: none;
        }}
        .toolbar-summary-pill {{
            flex: 0 0 auto;
        }}
        .toolbar-summary-spacer {{
            flex: 1 1 auto;
            min-width: 0;
        }}
        .toolbar-controls-panel {{
            display: grid;
            gap: 0.34rem;
            padding-top: 0.34rem;
            margin-top: 0.34rem;
            border-top: 1px solid rgba(148,163,184,0.16);
        }}
        .quick-nav {{
            display: flex;
            flex-wrap: nowrap;
            align-items: center;
            gap: 0.22rem;
            margin: 0;
            overflow-x: auto;
            white-space: nowrap;
            padding: 0;
            flex: 1 1 auto;
            min-width: 0;
        }}
        .focus-controls {{
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            gap: 0.22rem;
            overflow-x: auto;
            white-space: nowrap;
        }}
        .settings-inline-label,
        .focus-label {{
            color: #7dd3fc;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            display: inline-flex;
            align-items: center;
            flex: 0 0 auto;
            padding: 0.15rem 0.34rem;
            margin-right: 0.1rem;
            line-height: 1.14;
            border-radius: 0.5rem;
            border: 1px solid rgba(125,211,252,0.24);
            background: rgba(2,132,199,0.12);
        }}
        .quick-nav a,
        .focus-chip,
        .system-inline,
        .system-chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.15rem 0.34rem;
            font-size: 0.73rem;
            font-weight: 600;
            color: #cbd5e1;
            border-radius: 0.45rem;
            border: 1px solid rgba(148,163,184,0.2);
            background: rgba(15,23,42,0.34);
            line-height: 1.14;
            min-height: 1.56rem;
            white-space: nowrap;
            flex: 0 0 auto;
        }}
        .quick-nav a:hover,
        .focus-chip:hover {{
            color: #a7f3d0;
            border-color: rgba(167,243,208,0.32);
            background: rgba(6,95,70,0.16);
        }}
        .focus-chips {{
            display: flex;
            flex-wrap: nowrap;
            gap: 0.2rem;
            margin-top: 0;
            flex: 0 0 auto;
        }}
        .focus-chip {{
            cursor: pointer;
        }}
        .focus-chip.is-active {{
            background: rgba(6,95,70,0.45);
            color: #d1fae5;
            border-color: rgba(110,231,183,0.55);
            box-shadow: 0 0 0 1px rgba(110,231,183,0.2) inset;
        }}
        .focus-meta {{
            display: flex;
            flex-wrap: nowrap;
            gap: 0.2rem;
            margin-top: 0;
            flex: 0 0 auto;
        }}
        .backend-status-rail {{
            display: inline-flex;
            align-items: center;
            gap: 0.22rem;
            overflow-x: auto;
            white-space: nowrap;
            min-width: 0;
            flex: 0 1 auto;
        }}
        .backend-pill-row {{
            display: inline-flex;
            align-items: center;
            gap: 0.2rem;
            overflow-x: auto;
            white-space: nowrap;
            flex: 1 1 auto;
        }}
        .backend-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.15rem 0.34rem;
            font-size: 0.72rem;
            font-weight: 700;
            border-radius: 0.45rem;
            line-height: 1.14;
            min-height: 1.56rem;
            border: 1px solid rgba(148,163,184,0.2);
            color: #cbd5e1;
            background: rgba(15,23,42,0.34);
            flex: 0 0 auto;
        }}
        .backend-pill[data-level="ok"] {{
            color: #a7f3d0;
            border-color: rgba(110,231,183,0.34);
            background: rgba(6,95,70,0.2);
        }}
        .backend-pill[data-level="info"] {{
            color: #bfdbfe;
            border-color: rgba(147,197,253,0.32);
            background: rgba(30,64,175,0.18);
        }}
        .backend-pill[data-level="warn"] {{
            color: #fde68a;
            border-color: rgba(251,191,36,0.34);
            background: rgba(120,53,15,0.22);
        }}
        .backend-pill[data-level="error"] {{
            color: #fecaca;
            border-color: rgba(248,113,113,0.34);
            background: rgba(127,29,29,0.22);
        }}
        .backend-pill[hidden] {{
            display: none !important;
        }}
        .focus-note {{ display: none; }}
        .status-legend-wrap {{
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
        }}
        .status-legend-summary {{
            color: #7dd3fc;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            display: inline-flex;
            align-items: center;
            gap: 0.22rem;
            line-height: 1.14;
            cursor: pointer;
            user-select: none;
            border-radius: 0.5rem;
            padding: 0.15rem 0.24rem;
            border: 1px solid rgba(125,211,252,0.24);
            background: rgba(2,132,199,0.12);
        }}
        .status-caret {{
            color: #7dd3fc;
            display: inline-block;
            transform: rotate(0deg);
            transition: transform 0.15s ease;
        }}
        .dashboard-toolbar-controls[open] > .toolbar-summary .toolbar-summary-pill .status-caret {{
            transform: rotate(90deg);
        }}
        .status-legend-wrap[open] .status-caret {{
            transform: rotate(90deg);
        }}
        .status-legend-items {{
            display: flex;
            flex-wrap: nowrap;
            align-items: center;
            gap: 0.2rem;
            overflow-x: auto;
            white-space: nowrap;
            margin-top: 0.28rem;
        }}
        .status-chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.15rem 0.34rem;
            font-size: 0.72rem;
            font-weight: 600;
            border-radius: 0.45rem;
            line-height: 1.14;
            min-height: 1.56rem;
            border: 1px solid rgba(148,163,184,0.2);
            color: #d1d5db;
            background: rgba(15,23,42,0.34);
            flex: 0 0 auto;
        }}
        .status-chip.done {{
            color: #cbefdf;
            border-color: rgba(110,231,183,0.38);
            background: rgba(6,95,70,0.24);
        }}
        .status-chip.progress {{
            color: #bfdbfe;
            border-color: rgba(147,197,253,0.34);
            background: rgba(30,64,175,0.22);
        }}
        .status-chip.action {{
            color: #fde68a;
            border-color: rgba(251,191,36,0.34);
            background: rgba(120,53,15,0.22);
        }}
        .status-chip.parked {{
            color: #d8b4fe;
            border-color: rgba(192,132,252,0.34);
            background: rgba(88,28,135,0.2);
        }}
        .system-rail {{
            overflow-x: auto;
        }}
        .system-line {{
            display: flex;
            align-items: center;
            gap: 0.22rem;
            white-space: nowrap;
            min-height: 1.58rem;
        }}
        .system-inline {{
            color: #94a3b8;
        }}
        .system-chip {{
            font-weight: 700;
        }}
        .system-chip-action {{
            min-width: 2rem;
        }}
        .focus-hidden {{ display: none !important; }}
        .phase-morning .card {{ border-left: 3px solid rgba(110,231,183,0.32); }}
        .phase-day .card {{ border-left: 3px solid rgba(147,197,253,0.3); }}
        .phase-evening .card {{ border-left: 3px solid rgba(196,181,253,0.36); }}
        body[data-compact=\"on\"] .dashboard-shell {{
            padding-top: 0.75rem;
            padding-bottom: 1.45rem;
        }}
        body[data-compact=\"on\"] .dashboard-section {{
            margin-bottom: 0.45rem;
        }}
        body[data-compact=\"on\"] .card {{
            padding: 0.8rem 0.72rem;
            margin-bottom: 0.58rem;
        }}
        body[data-compact=\"on\"] .settings-stack {{
            gap: 0.24rem;
            margin-bottom: 0.5rem;
        }}
        body[data-compact=\"on\"] .settings-toolbar {{
            gap: 0.24rem;
        }}
        body[data-compact=\"on\"] .settings-rail {{
            padding: 0.18rem 0.24rem;
            min-height: 1.7rem;
        }}
        body[data-compact=\"on\"] .toolbar-controls-panel {{
            gap: 0.24rem;
            padding-top: 0.24rem;
            margin-top: 0.24rem;
        }}
        body[data-compact=\"on\"] .quick-nav a,
        body[data-compact=\"on\"] .focus-chip,
        body[data-compact=\"on\"] .system-inline,
        body[data-compact=\"on\"] .system-chip,
        body[data-compact=\"on\"] .backend-pill {{
            padding: 0.14rem 0.28rem;
            font-size: 0.69rem;
            min-height: 1.42rem;
        }}
        body[data-compact=\"on\"] .settings-inline-label,
        body[data-compact=\"on\"] .focus-label,
        body[data-compact=\"on\"] .status-legend-summary {{
            padding: 0.11rem 0.24rem;
            font-size: 0.67rem;
        }}
        body[data-compact=\"on\"] .status-chip {{
            padding: 0.14rem 0.28rem;
            font-size: 0.69rem;
            min-height: 1.42rem;
        }}
        body[data-compact=\"on\"] .system-line {{
            min-height: 1.44rem;
        }}
        body[data-compact=\"on\"] .text-xs {{
            font-size: 0.74rem !important;
            line-height: 1.08rem !important;
        }}
        body[data-compact=\"on\"] .text-sm {{
            font-size: 0.87rem !important;
            line-height: 1.22rem !important;
        }}
        body[data-compact=\"on\"] .text-lg {{
            font-size: 1.01rem !important;
            line-height: 1.26rem !important;
        }}
        body[data-compact=\"on\"] [data-qa-row] {{
            padding: 0.42rem 0.56rem !important;
            margin-bottom: 0.34rem !important;
        }}
        body[data-compact=\"on\"] button,
        body[data-compact=\"on\"] input[type=\"text\"],
        body[data-compact=\"on\"] select {{
            font-size: 0.86rem;
            min-height: 1.6rem;
        }}
        body[data-compact=\"on\"] input[type=\"range\"] {{
            min-height: 1.35rem;
        }}
        body[data-low-stim=\"on\"] {{
            background: #0f172a;
        }}
        body[data-low-stim=\"on\"] .card {{
            background: rgba(15,23,42,0.9);
            border-color: rgba(100,116,139,0.28);
            box-shadow: none;
        }}
        body[data-low-stim=\"on\"] .card:hover {{
            border-color: rgba(148,163,184,0.35);
            box-shadow: none;
        }}
        body[data-low-stim=\"on\"] .settings-rail {{
            background: rgba(15,23,42,0.9);
            border-color: rgba(100,116,139,0.35);
        }}
        body[data-low-stim=\"on\"] .quick-nav a,
        body[data-low-stim=\"on\"] .focus-chip,
        body[data-low-stim=\"on\"] .system-inline,
        body[data-low-stim=\"on\"] .system-chip,
        body[data-low-stim=\"on\"] .backend-pill,
        body[data-low-stim=\"on\"] .status-chip {{
            background: rgba(30,41,59,0.8);
            border-color: rgba(148,163,184,0.35);
            color: #cbd5e1;
        }}
        body[data-low-stim=\"on\"] .system-inline {{
            color: #94a3b8;
        }}
        body[data-low-stim=\"on\"] .status-legend-summary {{
            color: #93c5fd;
            border-color: rgba(147,197,253,0.3);
            background: rgba(30,64,175,0.14);
        }}
        body[data-low-stim=\"on\"] .phase-morning .card,
        body[data-low-stim=\"on\"] .phase-day .card,
        body[data-low-stim=\"on\"] .phase-evening .card {{
            border-left-color: rgba(148,163,184,0.38);
        }}
        body[data-low-stim=\"on\"] * {{
            transition: none !important;
        }}
        @media (prefers-reduced-motion: reduce) {{
            * {{
                transition: none !important;
                animation: none !important;
            }}
        }}
        a:focus-visible,
        button:focus-visible,
        input:focus-visible,
        select:focus-visible,
        summary:focus-visible {{
            outline: 2px solid var(--focus-soft);
            outline-offset: 2px;
            border-color: rgba(203,239,223,0.58) !important;
        }}
        .text-xs {{ font-size: 0.84rem !important; line-height: 1.28rem !important; }}
        .text-sm {{ font-size: 0.98rem !important; line-height: 1.5rem !important; }}
        .text-lg {{ font-size: 1.14rem !important; line-height: 1.45rem !important; }}
        button, input[type="text"], select {{ font-size: 0.95rem; }}
        button {{ min-height: 2rem; }}
        input[type="range"] {{ min-height: 1.8rem; }}
        p {{ margin: 0; }}
        li {{ line-height: 1.5; }}
        details > summary {{ list-style: none; }}
        details > summary::-webkit-details-marker {{ display: none; }}
        @media (max-width: 640px) {{
            html {{ font-size: 16px; }}
            .dashboard-shell {{ padding-top: 0.72rem; }}
            #diarium-header-image {{ width: 72px !important; height: 72px !important; }}
            .quick-nav a:nth-of-type(n+7) {{ display: none; }}
            .settings-stack {{ margin-bottom: 0.55rem; }}
            .settings-rail {{ padding: 0.18rem 0.28rem; }}
            .settings-toolbar {{ gap: 0.28rem; }}
            .toolbar-summary-spacer {{ display: none; }}
            .toolbar-summary,
            .toolbar-row-nav {{
                gap: 0.18rem;
            }}
            .top-status-row {{ gap: 0.28rem; }}
            .status-pill-mini {{ font-size: 0.68rem; padding: 0.16rem 0.42rem; }}
        }}
    </style>
</head>
<body data-optional-pills="{optional_pills_attr}">
    <main class="dashboard-shell">
    <!-- Header -->
    <div class="flex flex-wrap items-start gap-4 mb-5">
        {diarium_image_tag}
        <div class="flex-1">
            <h1 class="text-3xl font-bold" style="color: var(--focus-soft)">🌟 Daily Overview</h1>
            <p style="color: #9ca3af">{data.get("date", "")} • {data.get("time", "")}</p>
            {context_bar_html}
            {top_status_pills_html}
        </div>
        <div class="rounded-xl px-4 py-2 text-center flex-shrink-0" style="background: rgba(6,95,70,0.2); border: 1px solid rgba(110,231,183,0.15);">
            <p class="font-bold text-2xl" style="color: #6ee7b7">{data.get("sleepCalm", 0)}</p>
            <p class="text-sm" style="color: rgba(110,231,183,0.5)">calm days</p>
        </div>
    </div>

    <section class="settings-stack settings-toolbar-stack" aria-label="Dashboard settings">
        <div class="settings-rail settings-toolbar">
            <div class="toolbar-row toolbar-row-nav">
                <span class="settings-inline-label">Jump</span>
                <nav class="quick-nav" aria-label="Dashboard sections">
                    <a href="#actions">✅ Actions</a>
                    <a href="#morning">🌅 Morning</a>
                    <a href="#guidance">💡 Guidance</a>
                    <a href="#updates">📝 Updates</a>
                    <a href="#evening">🌙 Evening</a>
                    <a href="#review">💭 Review</a>
                    {weekly_nav_link_html}
                    <a href="#health">🏥 Health</a>
                    <a href="#film">🎬</a>
                    <a href="#jobs">💼 Jobs</a>
                    <a href="#system">🧰 System</a>
                </nav>
            </div>
            <details id="dashboard-controls-wrap" class="dashboard-toolbar-controls"{controls_open_attr}>
                <summary class="toolbar-summary">
                    <span class="status-legend-summary toolbar-summary-pill"><span class="status-caret">▸</span>⚙️ Controls</span>
                    <span class="toolbar-summary-spacer"></span>
                    <span class="backend-status-rail" aria-label="Live status">{backend_status_pills_html}</span>
                </summary>
                <div class="toolbar-controls-panel">
                    <div class="focus-controls" role="group" aria-label="Focus mode controls">
                        <span class="focus-label">⏳ Focus</span>
                        <div class="focus-chips">
                            <button type="button" class="focus-chip is-active" data-focus-btn="all">🌐 All</button>
                            <button type="button" class="focus-chip" data-focus-btn="morning">🌅 Morning</button>
                            <button type="button" class="focus-chip" data-focus-btn="day">📝 Day</button>
                            <button type="button" class="focus-chip" data-focus-btn="evening">🌙 Evening</button>
                            <button type="button" class="focus-chip" id="focus-report-chip" data-focus-btn="report"{daily_report_control_hidden_attr}>📖 Report</button>
                        </div>
                        <div class="focus-meta">
                            <button type="button" class="focus-chip" id="low-stim-toggle">🧘 Low: Off</button>
                            <button type="button" class="focus-chip" id="compact-toggle">📚 Compact: Off</button>
                        </div>
                        <p id="focus-mode-note" class="focus-note">All sections visible.</p>
                        <p id="focus-meta-note" class="focus-note">Style: Standard • Density: Standard.</p>
                    </div>
                    <details id="status-legend-wrap" class="status-legend-wrap">
                        <summary class="status-legend-summary"><span class="status-caret">▸</span>🧭 Status markers (optional)</summary>
                        <div class="status-legend-items" role="note" aria-label="Status marker legend">
                            <span class="status-chip done">✅ done</span>
                            <span class="status-chip progress">🔄 in progress</span>
                            <span class="status-chip action">⚠️ needs action</span>
                            <span class="status-chip parked">⏭️ parked</span>
                        </div>
                    </details>
                    {system_status_html}
                </div>
            </details>
        </div>
    </section>

    <!-- Action Items (TOP — the first thing to see) -->
    <section id="actions" class="dashboard-section phase-day" data-focus="always morning day evening">{action_items_html}</section>

    <!-- Mood selector — always visible, quick tap at any point in the day -->
    <section class="dashboard-section phase-day" data-focus="always morning day evening">{mood_tracking_html}</section>

    <!-- Freshness + journal warnings (moved below triage on mobile/desktop to reduce top-load) -->
    <section id="qa-status-cards-section" class="dashboard-section" data-focus="always" data-static-cards="{status_static_card_count}"{status_cards_section_hidden_attr}>
        {important_thing_warning_html}
        <div id="qa-freshness-watch-wrap"{freshness_watch_hidden_attr}>{freshness_watch_html}</div>
        {stale_notice_html}
        <div id="qa-ideas-status-wrap"{ideas_status_hidden_attr}>{ideas_status_html}</div>
        <div id="qa-section-freshness-wrap"{section_freshness_hidden_attr}>{section_freshness_html}</div>
    </section>

    <!-- Morning block: entries + AI analysis -->
    <section id="morning" class="dashboard-section phase-morning" data-focus="morning">
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #a7f3d0">🌅 Morning</h3>
        {morning_mood_pill_html}
        {morning_card_html}
    </div>
    {morning_insights_html}
    {_scratch_pad_html("morning", "Morning", effective_today)}
    </section>



    <!-- Updates (throughout-day notes) — still morning/day context -->
    <section id="updates" class="dashboard-section phase-day" data-focus="day">
        {updates_card_html}
        {updates_insights_html}
        {completed_updates_html}
        {_scratch_pad_html("updates", "Updates", effective_today)}
    </section>

    {(f'<section id="guidance" class="dashboard-section phase-day" data-focus="morning day evening">{guidance_section_html}</section>') if guidance_section_html else ''}

    {(f'<section class="dashboard-section phase-day" data-focus="morning day evening">{support_section_html}</section>') if support_section_html else ''}

    <!-- Evening block: entries + AI analysis + emotional synthesis + tomorrow -->
    <section id="evening" class="dashboard-section phase-evening" data-focus="evening">
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #c4b5fd">🌙 Evening</h3>
        {evening_mood_pill_html}
        {evening_card_html}
    </div>
    {evening_insights_html}
    {how_felt_html}
    {suggestions_html}
    {_scratch_pad_html("evening", "Evening", effective_today)}
    </section>

    {(f'<section id="daily-report" class="dashboard-section phase-evening" data-focus="report"{daily_report_control_hidden_attr}>{daily_report_html}</section>') if daily_report_html else ''}

    <!-- Calendar + Ta-Dah (with wins merged) -->
    <section id="review" class="dashboard-section phase-day" data-focus="day evening">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div class="card">
            <h3 class="text-lg font-semibold mb-4" style="color: #f9a8d4">📅 Today</h3>
            <div class="space-y-2" id="qa-calendar-body">{calendar_html}</div>
        </div>
        <div class="card">
            <h3 class="text-lg font-semibold mb-4"><a href="{journal_today}" style="color: #6ee7b7">✅ Ta-Dah ({len(tadah_flat)})</a></h3>
            <div class="space-y-1">{tadah_html}</div>
            {yesterday_tadah_html}
            {('<details class="mt-3"><summary class="text-xs cursor-pointer" style="color: #6b7280">Theme breakdown</summary><div class="mt-2">' + tadah_cat_html + '</div></details>') if tadah_cat_html else ''}
        </div>
    </div>
    </section>

    <!-- What you did today — full narrative card, always visible -->
    {(f'<section class="dashboard-section phase-day" data-focus="day evening">{_pieces_day_html}</section>') if _pieces_day_html else ''}

    <section id="weekly" class="dashboard-section phase-day" data-focus="day evening">{weekly_digest_html}</section>

    <!-- Fitness (HealthFit workouts + yoga goals) -->
    <section id="health" class="dashboard-section phase-day" data-focus="day evening">{workout_html}{fitness_html}</section>

    <!-- Mindfulness (Streaks auto + manual check) -->
    <section class="dashboard-section phase-day" data-focus="day evening">{mindfulness_html}</section>

    <!-- Finch Self-Care (collapsed — static aggregate, low daily signal) -->
    <section class="dashboard-section phase-day" data-focus="day evening">
        {('<details><summary class="text-sm cursor-pointer mb-2" style="color: #6b7280">🐦 Finch Self-Care</summary>' + finch_html + '</details>') if finch_html else ''}
    </section>

    <!-- Health (compact) + Habits -->
    <section class="dashboard-section phase-day" data-focus="day evening">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div class="card">
            <h3 class="text-lg font-semibold mb-4" style="color: #c4b5fd">🏥 Health</h3>
            {health_html if health_html else '<p class="text-sm" style="color: #6b7280">No health data</p>'}
        </div>
        <div class="card">
            <h3 class="text-lg font-semibold mb-4"><a href="{streaks_dir}" style="color: #fbbf24">🔥 Habits</a></h3>
            {habits_html if habits_html else '<p class="text-sm" style="color: #6b7280">No habit data</p>'}
        </div>
    </div>
    </section>

    <!-- Film -->
    <section id="film" class="dashboard-section" data-focus="day evening">{film_html}</section>

    <section class="dashboard-section phase-day" data-focus="day evening">{correlation_html}</section>

    <section class="dashboard-section phase-day" data-focus="day evening">{mood_correlation_html}</section>

    <!-- Digital Activity (Screen Time + ActivityWatch) -->
    <section class="dashboard-section phase-day" data-focus="day evening">
        {('<details class="card mb-4"><summary class="cursor-pointer text-lg font-semibold" style="color: #c4b5fd">' + html.escape(screentime_summary_label) + '</summary><div class="mt-3">' + screentime_html + '</div></details>') if screentime_html else ''}
        {('<details class="card"><summary class="cursor-pointer text-lg font-semibold" style="color: #fbbf24">' + html.escape(activitywatch_summary_label) + '</summary><div class="mt-3">' + activitywatch_html + '</div></details>') if activitywatch_html else ''}
    </section>

    <!-- Pieces Workstream -->
    <section id="pieces" class="dashboard-section phase-day" data-focus="day evening">{pieces_card_html if pieces_card_html else ''}</section>

    <!-- Therapy Notes (HEALTH only) -->
    <section class="dashboard-section phase-evening" data-focus="all">{therapy_notes_html}</section>

    <!-- Jobs {'(collapsed — WT day)' if is_wt_day else ''} -->
    <section id="jobs" class="dashboard-section phase-day" data-focus="all">
    {'<details class="card"><summary class="cursor-pointer"><span class="text-lg font-semibold" style="color: #f9a8d4">💼 ' + str(data.get("actualApps", 0)) + ' submitted · ' + str(data.get("jobAlerts", 0)) + ' alerts</span></summary><div class="mt-3">' if is_wt_day else '<div class="card">'}
        {'<h3 class="text-lg font-semibold mb-4"><a href="' + wins_file + '" style="color: #f9a8d4">💼 Job Search</a></h3>' if not is_wt_day else ''}
        <div class="flex gap-4 mb-4">
            <div class="flex-1 rounded-lg p-3 text-center" style="background: rgba(6,95,70,0.15)">
                <p class="text-3xl font-bold" style="color: #6ee7b7">{data.get("actualApps", 0)}</p>
                <p class="text-xs" style="color: #9ca3af">submitted</p>
            </div>
            <div class="flex-1 rounded-lg p-3 text-center" style="background: rgba(88,28,135,0.1)">
                <p class="text-xl font-semibold" style="color: #c4b5fd">{data.get("focus_label", "Remote £35k+ / local £40k+")}</p>
                <p class="text-xs" style="color: #9ca3af">focus</p>
            </div>
            <div class="flex-1 rounded-lg p-3 text-center" style="background: rgba(131,24,67,0.1)">
                <p class="text-xl font-semibold" style="color: #f9a8d4">{data.get("jobAlerts", 0)}</p>
                <p class="text-xs" style="color: #9ca3af">alerts</p>
            </div>
        </div>
        <div class="space-y-2">{jobs_html if jobs_html else '<p class="text-sm" style="color: #6b7280">No job alerts</p>'}</div>
    {'</div></details>' if is_wt_day else '</div>'}
    </section>

    <!-- Maintenance Tasks (beads) -->
    <section id="system" class="dashboard-section phase-day" data-focus="all">{backlog_html}</section>

    <div id="cmd-palette" class="focus-hidden" style="position: fixed; inset: 0; z-index: 1000; background: rgba(2,6,23,0.72);">
        <div style="max-width: 680px; margin: 8vh auto 0; padding: 0 1rem;">
            <div class="card" style="padding: 0.8rem; border: 1px solid rgba(147,197,253,0.28); background: rgba(15,23,42,0.96);">
                <p class="text-xs mb-2" style="color: #93c5fd">⌨️ Command Palette</p>
                <input id="cmd-input" type="text" placeholder="Type command... (focus day, open health, refresh, self-heal)" class="w-full rounded px-3 py-2 text-sm" style="background: rgba(15,23,42,0.85); border: 1px solid rgba(147,197,253,0.3); color: #e5e7eb;">
                <div id="cmd-list" class="mt-2 space-y-1"></div>
                <p class="text-xs mt-2" style="color: #6b7280">Enter to run • Esc to close • Cmd/Ctrl+K to open</p>
            </div>
        </div>
    </div>

    <script>
    (function () {{
        const STORAGE_KEY = "dashboard.focus.mode.v1";
        const FOCUS_OVERRIDE_KEY = "dashboard.focus.override.v1";
        const LOW_STIM_KEY = "dashboard.low.stim.v1";
        const COMPACT_KEY = "dashboard.compact.mode.v1";
        const STATUS_LEGEND_KEY = "dashboard.status.legend.v1";
        const MODES = {{
            all: "All",
            morning: "Morning",
            day: "Day",
            evening: "Evening",
            report: "Report"
        }};
        const MODE_BANDS = {{
            morning: "before 12:00",
            day: "12:00-17:59",
            evening: "18:00 onwards",
            report: "end of day"
        }};

        const sections = Array.from(document.querySelectorAll(".dashboard-section[data-focus]"));
        const buttons = Array.from(document.querySelectorAll("[data-focus-btn]"));
        const note = document.getElementById("focus-mode-note");
        const lowStimButton = document.getElementById("low-stim-toggle");
        const compactButton = document.getElementById("compact-toggle");
        const dashboardControlsWrap = document.getElementById("dashboard-controls-wrap");
        const statusLegendWrap = document.getElementById("status-legend-wrap");
        const focusMetaNote = document.getElementById("focus-meta-note");
        const cmdPalette = document.getElementById("cmd-palette");
        const cmdInput = document.getElementById("cmd-input");
        const cmdList = document.getElementById("cmd-list");
        const headerImage = document.getElementById("diarium-header-image");
        const settingsApiBase = (typeof QA_API_BASE !== "undefined" && QA_API_BASE ? QA_API_BASE : (() => {{
            if (typeof window !== "undefined" && window.location) {{
                const protocol = (window.location.protocol || "").toLowerCase();
                if (protocol === "http:" || protocol === "https:") {{
                    return window.location.origin;
                }}
            }}
            return "http://127.0.0.1:8765";
        }})());
        let commandOptions = [];

        if (headerImage) {{
            const protocol = (window.location.protocol || "").toLowerCase();
            const remoteSrc = headerImage.getAttribute("data-remote-src") || "";
            const fileSrc = headerImage.getAttribute("data-file-src") || "";
            if ((protocol === "http:" || protocol === "https:") && remoteSrc) {{
                headerImage.src = remoteSrc;
            }} else if (protocol === "file:" && fileSrc) {{
                headerImage.src = fileSrc;
            }}
        }}

        function getAutoModeForNow(now) {{
            const hour = now.getHours();
            if (hour < 12) return "morning";
            if (hour < 18) return "day";
            return "evening";
        }}

        function normalizeMode(raw) {{
            const mode = (raw || "").toLowerCase();
            if (mode === "report") {{
                const reportSection = document.getElementById("daily-report");
                if (!reportSection || reportSection.hidden) return "all";
            }}
            return Object.prototype.hasOwnProperty.call(MODES, mode) ? mode : "all";
        }}

        function isVisible(section, mode) {{
            const tags = String(section.dataset.focus || "").split(/\\s+/).filter(Boolean);
            if (mode === "report") {{
                return tags.includes("report");
            }}
            if (mode === "all") return true;
            if (!tags.length) return true;
            if (tags.includes("always")) return true;
            return tags.includes(mode);
        }}

        function setMode(mode, options = {{}}) {{
            const persist = options.persist !== false;
            const source = options.source || "manual";
            const safeMode = normalizeMode(mode);
            document.body.dataset.focusMode = safeMode;
            sections.forEach((section) => {{
                const visible = isVisible(section, safeMode);
                section.classList.toggle("focus-hidden", !visible);
                section.setAttribute("aria-hidden", visible ? "false" : "true");
            }});
            buttons.forEach((button) => {{
                button.classList.toggle("is-active", button.dataset.focusBtn === safeMode);
            }});

            if (note) {{
                let modeText = `${{MODES[safeMode] || MODES.all}} mode.`;
                if (source === "auto" && MODE_BANDS[safeMode]) {{
                    modeText = `Auto: ${{MODES[safeMode]}} (${{MODE_BANDS[safeMode]}}).`;
                }} else if (source === "override") {{
                    modeText = `Manual override today: ${{MODES[safeMode]}}.`;
                }} else if (source === "url") {{
                    modeText = `URL mode today: ${{MODES[safeMode]}}.`;
                }}
                note.textContent = modeText;
            }}
            if (persist) {{
                try {{
                    localStorage.setItem(STORAGE_KEY, safeMode);
                }} catch (_err) {{}}
            }}
            if (source === "manual" || source === "url") {{
                try {{
                    localStorage.setItem(FOCUS_OVERRIDE_KEY, JSON.stringify({{
                        date: getTodayKey(),
                        mode: safeMode
                    }}));
                }} catch (_err) {{}}
            }}
        }}

        function setLowStim(enabled, persist = true) {{
            const on = Boolean(enabled);
            document.body.dataset.lowStim = on ? "on" : "off";
            if (lowStimButton) {{
                lowStimButton.classList.toggle("is-active", on);
                lowStimButton.textContent = on ? "🧘 Low: On" : "🧘 Low: Off";
            }}
            updateFocusMeta();
            if (persist) {{
                try {{
                    localStorage.setItem(LOW_STIM_KEY, on ? "on" : "off");
                }} catch (_err) {{}}
            }}
        }}

        function setCompact(enabled, persist = true) {{
            const on = Boolean(enabled);
            document.body.dataset.compact = on ? "on" : "off";
            if (compactButton) {{
                compactButton.classList.toggle("is-active", on);
                compactButton.textContent = on ? "📚 Compact: On" : "📚 Compact: Off";
            }}
            updateFocusMeta();
            if (persist) {{
                try {{
                    localStorage.setItem(COMPACT_KEY, on ? "on" : "off");
                }} catch (_err) {{}}
            }}
        }}

        function setStatusLegendOpen(enabled, persist = true) {{
            if (!statusLegendWrap) return;
            const open = Boolean(enabled);
            if (open && dashboardControlsWrap) {{
                dashboardControlsWrap.setAttribute("open", "");
            }}
            if (open) {{
                statusLegendWrap.setAttribute("open", "");
            }} else {{
                statusLegendWrap.removeAttribute("open");
            }}
            if (persist) {{
                try {{
                    localStorage.setItem(STATUS_LEGEND_KEY, open ? "open" : "closed");
                }} catch (_err) {{}}
            }}
        }}

        function updateFocusMeta() {{
            if (!focusMetaNote) return;
            const lowStimOn = document.body.dataset.lowStim === "on";
            const compactOn = document.body.dataset.compact === "on";
            const styleText = lowStimOn ? "Low stimulation" : "Standard";
            const densityText = compactOn ? "Compact" : "Standard";
            focusMetaNote.textContent = `Style: ${{styleText}} • Density: ${{densityText}}.`;
        }}

        window.qaOpenReportFocus = function qaOpenReportFocus() {{
            setMode("report", {{ persist: true, source: "manual" }});
            jumpToSection("daily-report");
        }};

        window.qaExitReportFocus = function qaExitReportFocus() {{
            const fallbackMode = qaIsEveningUnlockOpen() ? "evening" : "all";
            setMode(fallbackMode, {{ persist: true, source: "manual" }});
            jumpToSection("evening");
        }};

        async function fetchSystemStatus() {{
            const previous = (qaLastSystemStatus && typeof qaLastSystemStatus === "object") ? qaLastSystemStatus : ((QA_SYSTEM_STATUS_INITIAL && typeof QA_SYSTEM_STATUS_INITIAL === "object") ? QA_SYSTEM_STATUS_INITIAL : null);
            // Use authenticated helper so remote dashboard requests don't 401.
            if (typeof qaGet === "function") {{
                const data = await qaGet("/v1/ui/system/status");
                if (data && typeof data === "object" && data.system && typeof data.system === "object") {{
                    qaSystemStatusFailureCount = 0;
                    return data.system;
                }}
                const health = await qaGet("/v1/health");
                if (health && typeof health === "object" && String(health.status || "").toLowerCase() === "ok") {{
                    qaSystemStatusFailureCount = 0;
                    return Object.assign({{}}, previous || {{}}, {{
                        checked_at: new Date().toISOString(),
                        api_ok: true,
                    }});
                }}
            }}
            qaSystemStatusFailureCount += 1;
            const degraded = qaSystemStatusFailureCount < 2;
            return Object.assign({{}}, previous || {{}}, {{
                checked_at: new Date().toISOString(),
                api_ok: degraded ? (previous && typeof previous.api_ok !== "undefined" ? previous.api_ok : null) : false,
            }});
        }}

        async function pollSystemStatus() {{
            if (!qaCanRunNetworkPoll()) return;
            if (qaSystemPollInFlight) return;
            qaSystemPollInFlight = true;
            try {{
                const system = await fetchSystemStatus();
                if (system && typeof qaUpdateSystemStatus === "function") {{
                    qaUpdateSystemStatus(system);
                    if (qaLeaderModeEnabled() && qaIsPollLeader) {{
                        qaBroadcastLive("system", system);
                    }}
                }}
            }} finally {{
                qaSystemPollInFlight = false;
            }}
        }}
        if (typeof window !== "undefined") {{
            window.pollSystemStatus = pollSystemStatus;
        }}

        function jumpToSection(id) {{
            const node = document.getElementById(id);
            if (node && typeof node.scrollIntoView === "function") {{
                node.scrollIntoView({{ behavior: "smooth", block: "start" }});
            }}
        }}

        let lastInteractionAt = Date.now();
        function markInteraction() {{
            lastInteractionAt = Date.now();
        }}
        function dashboardIsBusyForRefresh() {{
            if (Number(window.__qaPendingRequests || 0) > 0) return true;
            const active = document.activeElement;
            if (active && active.tagName) {{
                const tag = String(active.tagName).toUpperCase();
                if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
            }}
            // Small grace period after taps/drags to avoid interrupting interaction.
            if ((Date.now() - lastInteractionAt) < 6000) return true;
            return false;
        }}

        function closePalette() {{
            if (!cmdPalette) return;
            cmdPalette.classList.add("focus-hidden");
            if (cmdInput) cmdInput.value = "";
            if (cmdList) cmdList.innerHTML = "";
        }}

        function openPalette() {{
            if (!cmdPalette) return;
            cmdPalette.classList.remove("focus-hidden");
            renderCommandList("");
            if (cmdInput) {{
                cmdInput.value = "";
                cmdInput.focus();
            }}
        }}

        function renderCommandList(filterText) {{
            if (!cmdList) return;
            const query = String(filterText || "").toLowerCase().trim();
            const visible = commandOptions.filter((item) => item.label.toLowerCase().includes(query));
            const rows = visible.slice(0, 12).map((item, idx) => {{
                return `<button type="button" class="w-full text-left rounded px-2 py-1 text-xs" data-cmd-index="${{idx}}" style="background: rgba(15,23,42,0.72); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.22);">${{item.label}}</button>`;
            }});
            cmdList.innerHTML = rows.length ? rows.join("") : '<p class="text-xs" style="color: #6b7280">No matching command.</p>';
            const buttons = Array.from(cmdList.querySelectorAll("button[data-cmd-index]"));
            buttons.forEach((button) => {{
                button.addEventListener("click", () => {{
                    const index = Number(button.dataset.cmdIndex || "-1");
                    const item = visible[index];
                    if (!item || typeof item.run !== "function") return;
                    item.run();
                    closePalette();
                }});
            }});
        }}

        commandOptions = [
            {{ label: "Focus: All", run: () => setMode("all", {{ persist: true, source: "manual" }}) }},
            {{ label: "Focus: Morning", run: () => setMode("morning", {{ persist: true, source: "manual" }}) }},
            {{ label: "Focus: Day", run: () => setMode("day", {{ persist: true, source: "manual" }}) }},
            {{ label: "Focus: Evening", run: () => setMode("evening", {{ persist: true, source: "manual" }}) }},
            {qa_report_command_option}
            {{ label: "Toggle: Low stimulation", run: () => setLowStim(!(document.body.dataset.lowStim === "on"), true) }},
            {{ label: "Toggle: Compact", run: () => setCompact(!(document.body.dataset.compact === "on"), true) }},
            {{ label: "Toggle: Status legend", run: () => setStatusLegendOpen(!(statusLegendWrap && statusLegendWrap.open), true) }},
            {{ label: "Section: Actions", run: () => jumpToSection("actions") }},
            {{ label: "Section: Guidance", run: () => jumpToSection("guidance") }},
            {{ label: "Section: Updates", run: () => jumpToSection("updates") }},
            {{ label: "Section: Evening", run: () => jumpToSection("evening") }},
            {{ label: "Section: Health", run: () => jumpToSection("health") }},
            {{ label: "Action: Pause live sync (10m)", run: () => qaSetSyncPause(10) }},
            {{ label: "Action: Pause live sync (30m)", run: () => qaSetSyncPause(30) }},
            {{ label: "Action: Resume live sync", run: () => qaSetSyncPause(0) }},
            {qa_end_day_command_option}
            {{ label: "Action: Refresh data now", run: () => {{ if (typeof qaRefreshData === "function") qaRefreshData(document.getElementById("qa-refresh-btn")); }} }},
            {{ label: "Action: Self-heal system", run: () => {{ if (typeof qaHealSystem === "function") qaHealSystem(document.getElementById("sys-heal-btn")); }} }},
        ];

        if (cmdInput) {{
            cmdInput.addEventListener("input", () => renderCommandList(cmdInput.value || ""));
            cmdInput.addEventListener("keydown", (event) => {{
                if (event.key === "Enter") {{
                    event.preventDefault();
                    const first = commandOptions.filter((item) => item.label.toLowerCase().includes(String(cmdInput.value || "").toLowerCase().trim()))[0];
                    if (first && typeof first.run === "function") {{
                        first.run();
                    }}
                    closePalette();
                }}
                if (event.key === "Escape") {{
                    event.preventDefault();
                    closePalette();
                }}
            }});
        }}
        if (cmdPalette) {{
            cmdPalette.addEventListener("click", (event) => {{
                if (event.target === cmdPalette) closePalette();
            }});
        }}

        buttons.forEach((button) => {{
            button.addEventListener("click", () => setMode(button.dataset.focusBtn || "all", {{ persist: true, source: "manual" }}));
        }});
        if (lowStimButton) {{
            lowStimButton.addEventListener("click", () => {{
                const isOn = document.body.dataset.lowStim === "on";
                setLowStim(!isOn, true);
            }});
        }}
        if (compactButton) {{
            compactButton.addEventListener("click", () => {{
                const isOn = document.body.dataset.compact === "on";
                setCompact(!isOn, true);
            }});
        }}
        if (statusLegendWrap) {{
            statusLegendWrap.addEventListener("toggle", () => {{
                try {{
                    localStorage.setItem(STATUS_LEGEND_KEY, statusLegendWrap.open ? "open" : "closed");
                }} catch (_err) {{}}
            }});
        }}

        const hotkeys = {{ "1": "all", "2": "morning", "3": "day", "4": "evening" }};
        document.addEventListener("keydown", (event) => {{
            markInteraction();
            if ((event.metaKey || event.ctrlKey) && !event.altKey && String(event.key || "").toLowerCase() === "k") {{
                event.preventDefault();
                if (cmdPalette && !cmdPalette.classList.contains("focus-hidden")) {{
                    closePalette();
                }} else {{
                    openPalette();
                }}
                return;
            }}
            if (String(event.key || "") === "Escape" && cmdPalette && !cmdPalette.classList.contains("focus-hidden")) {{
                event.preventDefault();
                closePalette();
                return;
            }}
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            const target = event.target;
            const tag = target && target.tagName ? target.tagName.toUpperCase() : "";
            if (tag === "INPUT" || tag === "TEXTAREA" || (target && target.isContentEditable)) return;
            if (event.key === "5") {{
                event.preventDefault();
                const compactOn = document.body.dataset.compact === "on";
                setCompact(!compactOn, true);
                return;
            }}
            const mode = hotkeys[event.key];
            if (!mode) return;
            event.preventDefault();
            setMode(mode, {{ persist: true, source: "manual" }});
        }});
        document.addEventListener("pointerdown", markInteraction, true);
        document.addEventListener("input", markInteraction, true);
        document.addEventListener("change", markInteraction, true);

        let initialLowStim = false;
        try {{
            initialLowStim = localStorage.getItem(LOW_STIM_KEY) === "on";
        }} catch (_err) {{
            initialLowStim = false;
        }}
        let initialCompact = false;
        try {{
            initialCompact = localStorage.getItem(COMPACT_KEY) === "on";
        }} catch (_err) {{
            initialCompact = false;
        }}
        let initialStatusLegend = false;
        try {{
            initialStatusLegend = localStorage.getItem(STATUS_LEGEND_KEY) === "open";
        }} catch (_err) {{
            initialStatusLegend = false;
        }}
        const urlParams = new URLSearchParams(window.location.search);
        const urlFocusRaw = (urlParams.get("focus") || "").toLowerCase();
        const urlLowStimRaw = (urlParams.get("lowStim") || "").toLowerCase();
        const urlCompactRaw = (urlParams.get("compact") || "").toLowerCase();
        const urlStatusLegendRaw = (urlParams.get("statusLegend") || "").toLowerCase();
        if (urlLowStimRaw === "1" || urlLowStimRaw === "true" || urlLowStimRaw === "on") {{
            initialLowStim = true;
        }}
        if (urlLowStimRaw === "0" || urlLowStimRaw === "false" || urlLowStimRaw === "off") {{
            initialLowStim = false;
        }}
        if (urlCompactRaw === "1" || urlCompactRaw === "true" || urlCompactRaw === "on") {{
            initialCompact = true;
        }}
        if (urlCompactRaw === "0" || urlCompactRaw === "false" || urlCompactRaw === "off") {{
            initialCompact = false;
        }}
        if (urlStatusLegendRaw === "1" || urlStatusLegendRaw === "true" || urlStatusLegendRaw === "on" || urlStatusLegendRaw === "open") {{
            initialStatusLegend = true;
        }}
        if (urlStatusLegendRaw === "0" || urlStatusLegendRaw === "false" || urlStatusLegendRaw === "off" || urlStatusLegendRaw === "closed") {{
            initialStatusLegend = false;
        }}
        setLowStim(initialLowStim, false);
        setCompact(initialCompact, false);
        setStatusLegendOpen(initialStatusLegend, false);

        let modeApplied = false;
        if (Object.prototype.hasOwnProperty.call(MODES, urlFocusRaw)) {{
            setMode(urlFocusRaw, {{ persist: true, source: "url" }});
            modeApplied = true;
        }}
        if (!modeApplied) {{
            const todayKey = getTodayKey();
            let override = null;
            try {{
                const raw = localStorage.getItem(FOCUS_OVERRIDE_KEY) || "";
                override = raw ? JSON.parse(raw) : null;
            }} catch (_err) {{
                override = null;
            }}
            if (
                override &&
                typeof override === "object" &&
                override.date === todayKey &&
                Object.prototype.hasOwnProperty.call(MODES, String(override.mode || "").toLowerCase())
            ) {{
                setMode(override.mode, {{ persist: false, source: "override" }});
                modeApplied = true;
            }}
        }}
        if (!modeApplied) {{
            let legacyModeRaw = "";
            try {{
                legacyModeRaw = (localStorage.getItem(STORAGE_KEY) || "").toLowerCase().trim();
            }} catch (_err) {{
                legacyModeRaw = "";
            }}
            if (legacyModeRaw && Object.prototype.hasOwnProperty.call(MODES, legacyModeRaw)) {{
                setMode(legacyModeRaw, {{ persist: true, source: "manual" }});
                modeApplied = true;
            }}
        }}
        if (!modeApplied) {{
            const autoMode = getAutoModeForNow(new Date());
            setMode(autoMode, {{ persist: false, source: "auto" }});
        }}

        qaPrimeFreshnessStateFromDom();
        qaSyncEveningUnlockVisibility();
        window.addEventListener("resize", qaApplyBackendPillVisibility);

        // Keep status/data live, with optional reading-mode pause.
        if (!qaIsLiveSyncPaused()) {{
            pollSystemStatus();
            qaSyncTodayFromApi({{ force: true }});
            qaSyncRenderStatus();
        }} else {{
            qaUpdateSyncPauseUi();
        }}
        window.setInterval(() => {{
            if (document.hidden) return;
            if (!qaIsLiveSyncPaused() && !dashboardIsBusyForRefresh()) {{
                pollSystemStatus();
            }}
        }}, 30000);
        window.setTimeout(() => {{
            window.setInterval(() => {{
                if (document.hidden) return;
                if (!qaIsLiveSyncPaused() && !dashboardIsBusyForRefresh()) {{
                    qaSyncTodayFromApi({{ force: true }});
                    qaSyncRenderStatus();
                }} else {{
                    qaUpdateSyncPauseUi();
                }}
            }}, 30000);
        }}, 15000);
        window.setInterval(() => {{
            if (document.hidden) return;
            qaUpdateSyncPauseUi();
            qaSyncEveningUnlockVisibility();
        }}, 15000);
        document.addEventListener("visibilitychange", () => {{
            if (!document.hidden && !qaIsLiveSyncPaused() && !dashboardIsBusyForRefresh()) {{
                pollSystemStatus();
                qaSyncTodayFromApi({{ force: true }});
                qaSyncRenderStatus();
            }}
            if (!document.hidden) {{
                qaSyncEveningUnlockVisibility();
            }}
        }});
    }})();
    </script>
    </main>
</body>
</html>'''


def _get_evening_data(diarium, ai_day=None):
    """Get evening data from diarium cache. Returns whatever is available."""
    updates_text = str(diarium.get("updates", "") or "").strip()
    if not updates_text:
        updates_text = _parse_updates_from_journal(get_effective_date())

    tomorrow_text = str(diarium.get("tomorrow", "") or "").strip()
    remember_text = str(diarium.get("remember_tomorrow", "") or "").strip()

    return {
        "three_things": diarium.get("three_things", []),
        "tomorrow": tomorrow_text,
        "updates": updates_text,
        "brave": diarium.get("brave", ""),
        "evening_reflections": diarium.get("evening_reflections", ""),
        "remember_tomorrow": remember_text,
        "mood_tag": str(diarium.get("mood_tag_evening", "")).strip(),
    }


def main():
    now = datetime.now()

    # Load directly from daemon cache
    cache = load_daemon_cache()

    # Extract data from cache
    diarium = cache.get("diarium", {})
    calendar_data = cache.get("calendar", {})
    akiflow_raw = cache.get("akiflow_tasks", {})
    open_loops = cache.get("open_loops", {})
    streaks = cache.get("streaks", {})
    finch = cache.get("finch", {})
    linkedin = cache.get("linkedin_jobs", {})
    apple_health = cache.get("apple_health", {})
    mh_correlation = cache.get("mental_health_correlation", {})
    context = cache.get("context_digest", {})
    effective_today = get_effective_date()
    ai_cache = normalize_ai_cache_for_date(cache.get("ai_insights", {}), effective_today)
    diarium_source_date = cache.get("diarium_source_date") or cache.get("date", "")
    diarium_fresh_flag = cache.get("diarium_fresh")
    if isinstance(diarium_fresh_flag, bool):
        diarium_fresh = diarium_fresh_flag
    else:
        diarium_fresh = diarium_source_date == effective_today if diarium_source_date else True
    diarium_fresh_reason = cache.get("diarium_fresh_reason", "")
    ai_cache, ai_diarium_guard = _apply_diarium_alignment_guard(ai_cache, cache, effective_today)
    ai_today = get_ai_day(ai_cache, effective_today)
    diarium_display = diarium if diarium_fresh else {}
    diarium_images = []
    if diarium_fresh:
        diarium_images = (
            get_diarium_images(now.strftime("%Y-%m-%d"))
            or get_diarium_images((now - timedelta(days=1)).strftime("%Y-%m-%d"))
        )

    runtime_status = {
        "daemon_ok": _runtime_daemon_running(),
        "api_ok": _runtime_api_health(),
        "cache_age_minutes": _runtime_cache_age_minutes(DAEMON_CACHE),
        "beads": _runtime_open_bead_counts(),
        "checked_at": now.strftime("%H:%M"),
        "remote_access": _runtime_remote_access(),
    }
    anxiety_correlation = _compute_anxiety_correlation(cache, ai_cache, effective_today, days=14)
    iso_year, iso_week, iso_weekday = now.isocalendar()
    weekly_current_file = SHARED_DIR / f"weekly-digest-{iso_year}-W{iso_week:02d}.md"
    weekly_files = []
    try:
        weekly_files = sorted(
            SHARED_DIR.glob("weekly-digest-*-W*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        weekly_files = []
    weekly_latest_file = weekly_files[0] if weekly_files else None
    weekly_digest_payload = {
        "current_week_label": f"{iso_year}-W{iso_week:02d}",
        "is_end_of_week": iso_weekday >= 6,
        "is_sunday": iso_weekday == 7,
        "current_exists": weekly_current_file.exists(),
        "current_path": str(weekly_current_file),
        "current_url": f"file://{weekly_current_file}",
        "latest_path": str(weekly_latest_file) if weekly_latest_file else "",
        "latest_url": f"file://{weekly_latest_file}" if weekly_latest_file else "",
        "latest_name": weekly_latest_file.name if weekly_latest_file else "",
        "needs_generation": bool(iso_weekday == 7 and not weekly_current_file.exists()),
    }

    mood_log_payload = cache.get("moodLog", {}) if isinstance(cache.get("moodLog", {}), dict) else {}
    mood_log_entries = _sanitize_mood_entries_for_today(
        mood_log_payload.get("entries", []),
        now_dt=now,
        allow_diarium_source=bool(diarium_fresh),
    )

    def _latest_diarium_context_mood(context_name):
        for entry in reversed(mood_log_entries):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("source", "")).strip().lower() != "diarium":
                continue
            if str(entry.get("context", "")).strip().lower() != context_name:
                continue
            label = str(entry.get("label", "")).strip()
            if label:
                return label
        return ""

    def _latest_diarium_mood_any_context():
        for entry in reversed(mood_log_entries):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("source", "")).strip().lower() != "diarium":
                continue
            label = str(entry.get("label", "")).strip()
            if label:
                return label
        return ""

    diarium_slots = diarium_display.get("mood_slots", {}) if isinstance(diarium_display.get("mood_slots", {}), dict) else {}
    ai_mood_slots = ai_today.get("mood_slots", {}) if isinstance(ai_today.get("mood_slots", {}), dict) else {}
    if not diarium_fresh:
        ai_mood_slots = {}
        diarium_slots = {}

    def _slot_value(*candidates):
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value and value.lower() != "unknown":
                return value
        return ""

    allow_unscoped_morning_fallback = now.hour < 20
    latest_diarium_any_mood = _latest_diarium_mood_any_context()
    morning_mood_tag = _slot_value(
        ai_mood_slots.get("morning", ""),
        diarium_slots.get("morning", ""),
        diarium_display.get("mood_tag_morning", ""),
        _latest_diarium_context_mood("morning"),
        (_latest_diarium_context_mood("diarium") if allow_unscoped_morning_fallback else ""),
        (latest_diarium_any_mood if allow_unscoped_morning_fallback else ""),
        (ai_mood_slots.get("unscoped", "") if allow_unscoped_morning_fallback else ""),
        (diarium_slots.get("unscoped", "") if allow_unscoped_morning_fallback else ""),
        (diarium_display.get("mood_tag", "") if allow_unscoped_morning_fallback else ""),
    )
    evening_mood_tag = _slot_value(
        ai_mood_slots.get("evening", ""),
        diarium_slots.get("evening", ""),
        diarium_display.get("mood_tag_evening", ""),
        _latest_diarium_context_mood("evening"),
    )
    if not morning_mood_tag:
        for _entry in reversed(mood_log_entries):
            if not isinstance(_entry, dict):
                continue
            _label = str(_entry.get("label", "") or _entry.get("mood", "")).strip()
            _context = str(_entry.get("context", "")).strip().lower()
            if not _label:
                continue
            if _context in {"morning", "general", ""}:
                morning_mood_tag = _label
                break
    if not evening_mood_tag:
        for _entry in reversed(mood_log_entries):
            if not isinstance(_entry, dict):
                continue
            _label = str(_entry.get("label", "") or _entry.get("mood", "")).strip()
            _context = str(_entry.get("context", "")).strip().lower()
            if not _label:
                continue
            if _context == "evening":
                evening_mood_tag = _label
                break
    if not morning_mood_tag:
        morning_mood_tag = "unknown"
    if not evening_mood_tag:
        evening_mood_tag = "unknown"
    work_strategy = cache.get("work_strategy", {}) if isinstance(cache.get("work_strategy", {}), dict) else {}
    work_focus_label = str(work_strategy.get("focus_label", "Remote £35k+ / local £40k+")).strip() or "Remote £35k+ / local £40k+"

    # Build dashboard data
    data = {
        "date": now.strftime("%d %b %Y"),
        "time": now.strftime("%H:%M"),
        "cacheTimestamp": str(cache.get("timestamp", "")).strip(),
        "feature_flags": cache.get("feature_flags", {}) if isinstance(cache.get("feature_flags", {}), dict) else {},
        "morning": {
            "grateful": ai_today.get("diarium_interpreted", {}).get("grateful_core") or diarium_display.get("grateful", ""),
            "intent": ai_today.get("diarium_interpreted", {}).get("intent_core") or diarium_display.get("intent", ""),
            "affirmation": ai_today.get("diarium_interpreted", {}).get("affirmation_core") or diarium_display.get("daily_affirmation", ""),
            "emotional_summary": next((e.get("emotional_summary", "") for e in ai_today.get("entries", []) if e.get("source") == "morning"), ""),
            "body_check": diarium_display.get("body_check", ""),
            "letting_go": diarium_display.get("letting_go", ""),
            "mood_tag": morning_mood_tag,
        },
        "evening": {**_get_evening_data(diarium_display, ai_today), "mood_tag": evening_mood_tag},
        "calendar": [],
        "tadah": get_tadah(),
        "healthData": [],
        "habits": [],
        "sleepCalm": 0,
        "actualApps": 0,
        "jobAlerts": 0,
        "openLoops": open_loops.get("count", 0) if open_loops.get("status") == "found" else 0,
        "openLoopItems": open_loops.get("items", []) if open_loops.get("status") == "found" else [],
        "calendar_raw": calendar_data.get("events", []),
        "calendarStatus": calendar_data if isinstance(calendar_data, dict) else {},
        "mentalHealthFlags": diarium_display.get("keyword_detections", [])[:3],
        "engagementHints": cache.get("engagement_hints", []),
        "aiInsights": ai_cache,
        "diariumAnalysis": diarium_display.get("analysis_context", {}),
        "diarium_images": diarium_images,
        "entryMeta": {
            "weather": str(diarium_display.get("weather", "")).strip(),
            "location": str(diarium_display.get("location", "")).strip(),
            "locations_detected": diarium_display.get("locations_detected", []) if isinstance(diarium_display.get("locations_detected", []), list) else [],
            "photo_count": len(diarium_images),
            "source_date": diarium_source_date,
        },
        "totalApps": 0,
        "focus_label": work_focus_label,
        "topJobs": [],
        "wins": [],
        "screentime": cache.get("screentime", {}),
        "activitywatch": cache.get("activitywatch", {}),
        "film_data": cache.get("film_data", {}) if isinstance(cache.get("film_data", {}), dict) else {},
        "jobBoards": cache.get("job_boards", {}) if isinstance(cache.get("job_boards", {}), dict) else {},
        "linkedinJobs": linkedin if isinstance(linkedin, dict) else {},
        "applications": cache.get("applications", {}) if isinstance(cache.get("applications", {}), dict) else {},
        "healthfit": cache.get("healthfit", {}) if isinstance(cache.get("healthfit", {}), dict) else {},
        "streaks": streaks if isinstance(streaks, dict) else {},
        "appleHealth": apple_health if isinstance(apple_health, dict) else {},
        "autosleep": cache.get("autosleep", {}) if isinstance(cache.get("autosleep", {}), dict) else {},
        "taDahCategorised": cache.get("ta_dah_categorised", {}),
        "diariumTodos": diarium_display.get("todos_extracted", []),
        "appleNotesTodos": cache.get("apple_notes_todos", []) if isinstance(cache.get("apple_notes_todos", []), list) else [],
        "appleNotesCompletedTodos": cache.get("apple_notes_completed_todos", []) if isinstance(cache.get("apple_notes_completed_todos", []), list) else [],
        "appleNotesTodoEntries": cache.get("apple_notes_todo_entries", []) if isinstance(cache.get("apple_notes_todo_entries", []), list) else [],
        "appleNotesIdeas": cache.get("apple_notes_ideas", {}) if isinstance(cache.get("apple_notes_ideas", {}), dict) else {},
        "diariumTaDah": diarium_display.get("ta_dah", []) if isinstance(diarium_display.get("ta_dah", []), list) else [],
        "akiflow_tasks": akiflow_raw if isinstance(akiflow_raw, dict) else {},
        "schedule_analysis": cache.get("schedule_analysis", {}),
        "pieces_activity": cache.get("pieces_activity", {}),
        "day_state_summary": cache.get("day_state_summary", {}) if isinstance(cache.get("day_state_summary", {}), dict) else {},
        "diariumDataDate": diarium_source_date,
        "diariumFresh": diarium_fresh,
        "diariumFreshReason": diarium_fresh_reason,
        "diariumPickupStatus": cache.get("diarium_pickup_status", {}) if isinstance(cache.get("diarium_pickup_status", {}), dict) else {},
        "importantThing": str(diarium_display.get("important_thing", "")).strip(),
        "importantThingMissing": bool(diarium_display.get("important_thing_missing", False)) if diarium_fresh else False,
        "healthfitWorkouts": cache.get("healthfit", {}).get("workouts", []) if cache.get("healthfit", {}).get("status") == "success" else [],
        "mindfulness": (lambda _d: _d.get("mindfulness_completion", {}) if isinstance(_d, dict) else {})(get_ai_day(ai_cache, get_effective_date()) if isinstance(ai_cache, dict) else {}),
        "moodTracking": (lambda _m: {
            "done_today": bool(_m.get("done")),
            "manual_done_today": _m.get("source") == "dashboard_manual",
            "streaks_done_today": bool(_m.get("done")) and _m.get("source") != "dashboard_manual",
            "source": _m.get("source", ""),
            "manual_source": _m.get("source", "") if _m.get("source") == "dashboard_manual" else "",
            "habit": _m.get("habit", ""),
            "latest_completed": _m.get("latest_completed", ""),
            "updated_at": _m.get("updated_at", ""),
        })((get_ai_day(ai_cache, get_effective_date()) if isinstance(ai_cache, dict) else {}).get("mood_checkin", {})),
        "moodLog": {
            "date": mood_log_payload.get("date", ""),
            "entries": mood_log_entries,
        },
        "moodCorrelation": cache.get("mood_correlation", {}),
        "workoutChecklist": {},
        "workoutChecklistSignals": {},
        "workoutProgression": {},
        "workoutProgressionWeights": {},
        "workoutShortcutEndpoint": "",
        "finch": finch,
        "runtimeStatus": runtime_status,
        "remoteAccess": runtime_status.get("remote_access", {}),
        "aiPathStatus": cache.get("ai_path_status", {}) if isinstance(cache.get("ai_path_status", {}), dict) else {},
        "aiDiariumGuard": ai_diarium_guard if isinstance(ai_diarium_guard, dict) else {},
        "anxietyCorrelation": anxiety_correlation,
        "weeklyDigest": weekly_digest_payload,
        "_raw_cache": cache,
    }

    # Strict date guard: never render stale day_state_summary from another date.
    dss = data.get("day_state_summary", {}) if isinstance(data.get("day_state_summary", {}), dict) else {}
    if str(dss.get("date", "")).strip() != effective_today:
        data["day_state_summary"] = {}

    # Parse calendar events — STRICT filter: only show events that fall on TODAY
    _today_date_str = get_effective_date()
    if calendar_data.get("status") == "success":
        for event in calendar_data.get("events", []):
            summary = event.get("summary", "")
            start = event.get("start", "")
            cal_name = event.get("calendar", "")

            # Strict date filter: only keep events where today is within [start, end)
            # Calendar APIs use exclusive end dates (all-day on Feb 12 -> end=Feb 13)
            _evt_start_date = start[:10] if start else ""
            if not _evt_start_date:
                continue  # No start date, skip
            if _evt_start_date > _today_date_str:
                continue  # Future event somehow in cache, skip
            if _evt_start_date != _today_date_str:
                # Event started before today — only keep if it's multi-day spanning today
                _evt_end_date = (event.get("end", "") or "")[:10]
                if not _evt_end_date or _evt_end_date <= _today_date_str:
                    continue  # Ended on or before today (exclusive end), skip

            if 'T' not in start:
                time_str = "All day"
            else:
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    time_str = start_dt.strftime("%H:%M")
                except Exception:
                    time_str = "TBD"

            event_type = "work" if "WT" in cal_name else "event" if cal_name == "Events" else "task"
            data["calendar"].append({
                "time": time_str,
                "event": summary,
                "type": event_type
            })

    # Parse health data — prefer HealthFit (auto-synced Google Sheets) over Apple Health (manual export)
    healthfit = cache.get("healthfit", {})
    health_source_used = False

    if healthfit.get("status") == "success" and healthfit.get("daily_metrics"):
        hf_metrics = healthfit.get("daily_metrics", [])[:7]
        # HealthFit dates are DD/MM/YYYY — sort chronologically
        def _hf_sort_key(m):
            try:
                return datetime.strptime(m.get("date", ""), "%d/%m/%Y")
            except (ValueError, TypeError):
                return datetime.min
        hf_sorted = sorted(hf_metrics, key=_hf_sort_key)
        for m in hf_sorted:
            date_str = m.get("date", "")
            # Extract day number from DD/MM/YYYY
            day_label = date_str[:2] if date_str else ""
            data["healthData"].append({
                "day": day_label,
                "steps": m.get("steps", 0) or 0,
                "exercise": m.get("exercise_minutes", 0) or 0
            })

        try:
            hf_dates = [datetime.strptime(m.get("date", ""), "%d/%m/%Y") for m in hf_metrics if m.get("date")]
            if hf_dates:
                most_recent = max(hf_dates)
                days_old = (now - most_recent).days
                data["healthDataStale"] = days_old > 3
                data["healthDataAge"] = days_old
                health_source_used = True
        except Exception:
            pass

    # Fall back to Apple Health export if HealthFit unavailable
    if not health_source_used and apple_health.get("status") == "success":
        metrics = apple_health.get("daily_metrics", [])[-7:]
        metrics_sorted = sorted(metrics, key=lambda m: m.get("date", ""))
        for m in metrics_sorted:
            date_str = m.get("date", "")
            day_label = date_str[-2:] if date_str else ""
            data["healthData"].append({
                "day": day_label,
                "steps": m.get("steps", 0),
                "exercise": m.get("exercise_minutes", 0)
            })

        try:
            most_recent = max(m.get("date", "") for m in metrics if m.get("date"))
            days_old = (now - datetime.strptime(most_recent, "%Y-%m-%d")).days
            data["healthDataStale"] = days_old > 3
            data["healthDataAge"] = days_old
        except Exception:
            data["healthDataStale"] = False
            data["healthDataAge"] = 0

    # Calculate calm days from mental health correlations
    if mh_correlation.get("status") == "success":
        correlations = mh_correlation.get("data", {}).get("correlations", [])
        calm_count = sum(1 for c in correlations if c.get("severity") == "positive")
        data["sleepCalm"] = calm_count

    # Parse habits from streaks (cumulative rates — not daily, so less prone to staleness)
    if streaks.get("status") == "success":
        for h in streaks.get("habits", []):
            data["habits"].append({
                "name": h.get("habit", ""),
                "rate": h.get("rate", 0)
            })
        # Note: Streaks data is cumulative (completion rates over time), not daily.
        # It's refreshed each daemon cycle from the Streaks backup file.

    # Mindfulness state: manual override (ai_insights) + auto detection (Streaks/HealthFit).
    ai_mindfulness = ai_today.get("mindfulness_completion", {}) if isinstance(ai_today.get("mindfulness_completion"), dict) else {}
    streaks_mindfulness = streaks.get("mindfulness_habit", {}) if isinstance(streaks.get("mindfulness_habit"), dict) else {}

    manual_done_raw = ai_mindfulness.get("manual_done")
    manual_done = manual_done_raw if isinstance(manual_done_raw, bool) else None

    auto_done = bool(streaks_mindfulness.get("completed_today"))
    auto_source = "streaks_auto" if auto_done else ""
    habit_name = str(streaks_mindfulness.get("habit", "")).strip()
    latest_completed = str(streaks_mindfulness.get("latest_completed", "")).strip()

    if not auto_done and healthfit.get("status") == "success":
        for entry in healthfit.get("mindfulness", []):
            if not isinstance(entry, dict):
                continue
            entry_date = str(entry.get("date", "")).strip()
            if not entry_date:
                continue
            try:
                entry_day = datetime.strptime(entry_date, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                continue
            if entry_day != effective_today:
                continue
            auto_done = True
            auto_source = "healthfit_auto"
            latest_completed = effective_today
            if not habit_name:
                habit_name = str(entry.get("data_source") or "Mindfulness").strip()
            break

    done = manual_done if manual_done is not None else auto_done
    minutes_target_raw = ai_mindfulness.get("minutes_target", 20)
    try:
        minutes_target = int(minutes_target_raw)
    except Exception:
        minutes_target = 20
    if minutes_target <= 0:
        minutes_target = 20

    minutes_done_raw = ai_mindfulness.get("minutes_done", minutes_target if done else 0)
    try:
        minutes_done = int(minutes_done_raw)
    except Exception:
        minutes_done = minutes_target if done else 0
    if done and minutes_done <= 0:
        minutes_done = minutes_target

    data["mindfulness"] = {
        "done": bool(done),
        "manual_done": manual_done,
        "auto_done": auto_done,
        "auto_source": auto_source or str(ai_mindfulness.get("auto_source", "")).strip(),
        "source": str(ai_mindfulness.get("source", "")).strip() or ("manual" if manual_done is not None else (auto_source or "none")),
        "habit": habit_name or str(ai_mindfulness.get("habit", "")).strip(),
        "minutes_target": minutes_target,
        "minutes_done": minutes_done,
        "latest_completed": latest_completed or str(ai_mindfulness.get("latest_completed", "")).strip(),
        "progression": ai_today.get("mental_health_progression", {}) if isinstance(ai_today.get("mental_health_progression"), dict) else {},
    }

    # Mood tracking: Streaks mood check-in + Finch mood trend (if available).
    streaks_mood = streaks.get("mood_habit", {}) if isinstance(streaks.get("mood_habit"), dict) else {}
    mood_habit_name = str(streaks_mood.get("habit", "")).strip()
    mood_done_streaks = bool(streaks_mood.get("completed_today"))
    mood_latest_completed = str(streaks_mood.get("latest_completed", "")).strip()
    ai_mood = ai_today.get("mood_checkin", {}) if isinstance(ai_today.get("mood_checkin"), dict) else {}
    mood_done_manual = bool(ai_mood.get("done"))
    mood_manual_source = str(ai_mood.get("source", "")).strip()
    mood_done_today = bool(mood_done_streaks or mood_done_manual)
    mood_source = "streaks" if mood_done_streaks else ("manual" if mood_done_manual else "none")
    if not mood_latest_completed:
        mood_latest_completed = str(ai_mood.get("latest_completed", "")).strip()

    finch_mood = finch.get("mood", {}) if isinstance(finch.get("mood"), dict) else {}
    finch_summary = finch.get("summary", {}) if isinstance(finch.get("summary"), dict) else {}
    finch_mood_entries = finch_mood.get("entries", []) if isinstance(finch_mood.get("entries"), list) else []
    latest_finch_entry = finch_mood_entries[-1] if finch_mood_entries else {}

    data["moodTracking"] = {
        "habit": mood_habit_name,
        "done_today": mood_done_today,
        "streaks_done_today": mood_done_streaks,
        "manual_done_today": mood_done_manual,
        "latest_completed": mood_latest_completed,
        "source": mood_source,
        "manual_source": mood_manual_source,
        "updated_at": str(ai_mood.get("updated_at", "")).strip(),
        "finch_average": finch_mood.get("average", finch_summary.get("mood_average")),
        "finch_trend": str(finch_mood.get("trend") or finch_summary.get("mood_trend") or "").strip(),
        "finch_latest_date": str(latest_finch_entry.get("date", "")).strip(),
        "finch_latest_value": latest_finch_entry.get("mood"),
        "finch_entries_count": len(finch_mood_entries),
    }

    # Workout checklist state (manual dashboard checklist + auto readiness signals)
    ai_workout_checklist = ai_today.get("workout_checklist", {}) if isinstance(ai_today.get("workout_checklist"), dict) else {}
    ai_workout_post = ai_workout_checklist.get("post_workout", {}) if isinstance(ai_workout_checklist.get("post_workout"), dict) else {}
    ai_workout_feedback = ai_workout_checklist.get("session_feedback", {}) if isinstance(ai_workout_checklist.get("session_feedback"), dict) else {}

    recovery_gate = str(ai_workout_checklist.get("recovery_gate", "unknown")).strip().lower()
    if recovery_gate not in {"pass", "fail", "unknown"}:
        recovery_gate = "unknown"

    data["workoutChecklist"] = {
        "recovery_gate": recovery_gate,
        "calf_done": bool(ai_workout_checklist.get("calf_done", False)),
        "post_workout": {
            "rpe": coerce_optional_int(ai_workout_post.get("rpe"), 1, 10),
            "pain": coerce_optional_int(ai_workout_post.get("pain"), 0, 10),
            "energy_after": coerce_optional_int(ai_workout_post.get("energy_after"), 1, 10),
        },
        "session_feedback": {
            "duration_minutes": coerce_optional_int(ai_workout_feedback.get("duration_minutes"), 5, 240),
            "intensity": coerce_choice(ai_workout_feedback.get("intensity"), {"easy", "moderate", "hard"}),
            "session_type": coerce_choice(ai_workout_feedback.get("session_type"), {"somatic", "yin", "flow", "mobility", "restorative", "other"}),
            "body_feel": coerce_choice(ai_workout_feedback.get("body_feel"), {"relaxed", "neutral", "tight", "sore", "energised", "fatigued"}),
            "session_note": str(ai_workout_feedback.get("session_note", "")).strip()[:280] or None,
            "anxiety_reduction_score": _to_float(ai_workout_feedback.get("anxiety_reduction_score")),
        },
        "source": str(ai_workout_checklist.get("source", "")).strip(),
        "updated_at": str(ai_workout_checklist.get("updated_at", "")).strip(),
    }

    # Data freshness checks
    healthfit_export_today = is_healthfit_export_today(healthfit, effective_today)
    streaks_export_today = is_streaks_export_today(streaks, effective_today)
    anxiety_saved_today = isinstance(ai_today.get("anxiety_reduction_score"), (int, float))
    # Reflect as done if evening_reflections written OR meaningful day diary exists
    # (Diarium docx export may predate when the evening section is written)
    _ev_refl = bool(str(diarium_display.get("evening_reflections", "")).strip())
    _has_tadah = bool(diarium_display.get("ta_dah") or data.get("diarium", {}).get("ta_dah"))
    _has_tomorrow = bool(str(diarium_display.get("remember_tomorrow", "")).strip() or str(diarium_display.get("tomorrow", "")).strip())
    reflection_saved_today = _ev_refl or _has_tadah or _has_tomorrow

    # Recovery gate signal from latest HRV + sleep (if available)
    recovery_signal = "unknown"
    recovery_signal_detail = "No HRV/sleep gate signal yet."
    hrv_latest_raw = healthfit.get("hrv_latest")
    hrv_latest = coerce_optional_int(hrv_latest_raw, 1, 200)
    sleep_hours = extract_healthfit_sleep_hours(healthfit, effective_today)

    if isinstance(hrv_latest, int) and isinstance(sleep_hours, (int, float)):
        if hrv_latest <= 35 or float(sleep_hours) < 6.5:
            recovery_signal = "fail"
            recovery_signal_detail = f"Suggest FAIL gate: HRV {hrv_latest}, sleep {sleep_hours:.1f}h"
        elif hrv_latest >= 40 and float(sleep_hours) >= 6.5:
            recovery_signal = "pass"
            recovery_signal_detail = f"Suggest PASS gate: HRV {hrv_latest}, sleep {sleep_hours:.1f}h"
        else:
            recovery_signal = "caution"
            recovery_signal_detail = f"Borderline gate: HRV {hrv_latest}, sleep {sleep_hours:.1f}h"

    data["workoutChecklistSignals"] = {
        "healthfit_export_today": healthfit_export_today,
        "streaks_export_today": streaks_export_today,
        "anxiety_saved_today": anxiety_saved_today,
        "reflection_saved_today": reflection_saved_today,
        "recovery_signal": recovery_signal,
        "recovery_signal_detail": recovery_signal_detail,
    }

    existing_workout_progression = ai_today.get("workout_progression", {}) if isinstance(ai_today.get("workout_progression"), dict) else {}
    workout_type_for_progression = str(get_todays_workout().get("type", "")).strip().lower()
    anxiety_score_today = _to_float(ai_today.get("anxiety_reduction_score"))
    workout_progression = derive_workout_progression(
        data["workoutChecklist"],
        date_key=effective_today,
        fitness=cache.get("fitness", {}) if isinstance(cache.get("fitness", {}), dict) else {},
        signals=data["workoutChecklistSignals"],
        workout_type=workout_type_for_progression,
        anxiety_score=anxiety_score_today,
    )
    weights_progression = derive_workout_progression(
        data["workoutChecklist"],
        date_key=effective_today,
        fitness=cache.get("fitness", {}) if isinstance(cache.get("fitness", {}), dict) else {},
        signals=data["workoutChecklistSignals"],
        workout_type="weights",
        anxiety_score=anxiety_score_today,
    )
    if existing_workout_progression.get("updated_at") and not workout_progression.get("updated_at"):
        workout_progression["updated_at"] = existing_workout_progression.get("updated_at")
    data["workoutProgression"] = workout_progression
    data["workoutProgressionWeights"] = weights_progression

    # Shortcut hybrid endpoint: prefer remote URL for iPhone, fall back to local API.
    remote_access = data.get("remoteAccess", {}) if isinstance(data.get("remoteAccess"), dict) else {}
    shortcut_base = str(remote_access.get("tailscale_url", "")).strip() or str(remote_access.get("cloudflare_url", "")).strip()
    if not shortcut_base:
        shortcut_base = "http://127.0.0.1:8765"
    data["workoutShortcutEndpoint"] = shortcut_base.rstrip("/") + "/v1/workout/log"

    # Parse LinkedIn jobs
    if linkedin.get("status") == "success":
        data["jobAlerts"] = linkedin.get("count", 0)
        for job in linkedin.get("jobs", [])[:5]:
            data["topJobs"].append({
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "score": job.get("score", 0)
            })

    # Get ACTUAL application count
    wins_data = context.get("wins", {}).get("digest", {})
    data["actualApps"] = wins_data.get("total_apps", 0)
    data["totalApps"] = data["actualApps"]

    # Parse wins
    if WINS_FILE.exists():
        data["wins"] = parse_wins(WINS_FILE.read_text())

    # Generate HTML
    html = generate_html(data)
    OUTPUT_FILE.write_text(html)
    print(f"✅ Dashboard generated: {OUTPUT_FILE}")
    print(f"📊 Data from cache: {cache.get('timestamp', 'unknown')}")

    # Open browser UNLESS --no-open flag is passed
    if "--no-open" not in sys.argv:
        webbrowser.open(f"file://{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
