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
import hashlib
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


# Paths
DAEMON_CACHE = Path.home() / ".claude" / "cache" / "session-data.json"
SHARED_DIR = Path.home() / "Documents" / "Claude Projects" / "claude-shared"
WINS_FILE = SHARED_DIR / "wins.md"
JOURNAL_DIR = SHARED_DIR / "journal"  # Used only for hyperlinks, not for reading raw text
OUTPUT_FILE = SHARED_DIR / "dashboard.html"
COMPLETED_TODOS_FILE = Path.home() / ".claude" / "cache" / "completed-todos.json"


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

        kept_lines.append(line)

    return "\n".join(kept_lines).strip()


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


def _sanitize_mood_entries_for_today(entries, now_dt=None):
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
        merged = " • ".join(fallback_bits).strip()
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


def get_tadah():
    """Get ta-dah list from daemon cache (AI-cleaned).
    Supports categorised format with emoji headers and plain bullet lists.
    Strict daily reset for today's list; yesterday is shown separately."""
    today = get_effective_date()
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    today_tadah = []
    yesterday_tadah = []

    # Try daemon cache FIRST — has AI-cleaned text
    if DAEMON_CACHE.exists():
        try:
            with open(DAEMON_CACHE) as f:
                cache = json.load(f)
            source_date = str(cache.get("diarium_source_date", "")).strip()
            if source_date == today:
                cache_tadah = cache.get("diarium", {}).get("ta_dah", [])
                if cache_tadah and isinstance(cache_tadah, list) and len(cache_tadah) >= 1:
                    today_tadah = cache_tadah
        except Exception:
            pass

    # Yesterday remains explicit context only (never merged into today's list)
    try:
        yesterday_tadah = _parse_tadah_from_journal(yesterday)
    except Exception:
        yesterday_tadah = []

    return {"categories": {}, "flat": today_tadah, "yesterday": yesterday_tadah}


def parse_wins(content):
    """Parse wins.md - extract most recent week's accomplishments only"""
    # Split by week headers to get the latest week
    weeks = re.split(r'^## (Week \d+.*?)$', content, flags=re.MULTILINE)
    if len(weeks) < 3:
        return []
    last_content = weeks[-1]

    wins = []
    skip_prefixes = [
        '- Evidence:', '- Status:', '- Note:', '- Reason:', '- Decision:',
        '- Reflection:', '- Contract:', '- Salary negotiation',
    ]
    for line in last_content.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('###') or line.startswith('**Target') or line.startswith('**Actual'):
            continue
        if any(line.startswith(p) for p in skip_prefixes):
            continue
        if '❌' in line:
            continue
        # Capture 🎉/✅ lines and normal bullet wins
        if '🎉' in line or '✅' in line:
            clean = re.sub(r'^\d+\.\s*', '', line).strip('- ').replace('**', '')
            wins.append(clean)
        elif line.startswith('- ') and len(line) > 10:
            clean = line.lstrip('- ').strip().replace('**', '')
            if len(clean) < 80:
                wins.append(clean)
    return wins[:4]


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
    yesterday_tadah = tadah_data.get("yesterday", []) if isinstance(tadah_data, dict) else []

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

        def _render_tadah_item(item_text, category):
            color = _category_colors.get(category, "#d1d5db")
            content_emoji = _pick_content_emoji(item_text)
            return f'<div class="flex items-start gap-2 text-sm" style="margin-left: 4px;"><span style="color: {color}; font-size: 1.2em; line-height: 1;">●</span><span style="color: #d1d5db; line-height: 1.4;">{html.escape(str(item_text))} {content_emoji}</span></div>'

        # Sort ta-dah items by category before rendering
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

        tadah_sorted = sorted(tadah_flat, key=_get_sort_key)

        # Render with category headers (bigger, more spacing)
        last_category = None
        for i, item in enumerate(tadah_sorted[:8]):
            current_category = _get_category(item)
            if current_category != last_category:
                tadah_html += f'<div style="color: #6ee7b7; font-size: 0.85rem; font-weight: 700; margin-top: {12 if i > 0 else 0}px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.08em;">{_category_labels.get(current_category, "Other")}</div>'
                last_category = current_category
            tadah_html += _render_tadah_item(item, current_category)

        if len(tadah_sorted) > 8:
            extra_html = ""
            last_category_extra = last_category
            for item in tadah_sorted[8:]:
                current_category = _get_category(item)
                if current_category != last_category_extra:
                    extra_html += f'<div style="color: #6ee7b7; font-size: 0.85rem; font-weight: 700; margin-top: 12px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.08em;">{_category_labels.get(current_category, "Other")}</div>'
                    last_category_extra = current_category
                extra_html += _render_tadah_item(item, current_category)
            tadah_html += f'<details class="mt-2"><summary style="color: #6ee7b7; font-size: 0.75rem; cursor: pointer;">+{len(tadah_sorted) - 8} more</summary><div class="mt-1 space-y-1">{extra_html}</div></details>'

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

    # === Action Items Section — categorised by quick_win / maintenance / standard ===
    # Matches embed-dashboard-in-notes.py action items section
    ai_insights = data.get("aiInsights", {})
    ai_today = get_ai_day(ai_insights, get_effective_date())
    weekly_digest_for_actions = data.get("weeklyDigest", {}) if isinstance(data.get("weeklyDigest"), dict) else {}
    weekly_report_due = bool(weekly_digest_for_actions.get("needs_generation"))
    action_items_list_html = '<p class="text-sm" style="color: #9ca3af">No action items right now.</p>'
    display_action_items = []

    # Date-gate: only show action items from today's data
    _effective_today = get_effective_date()
    _ai_is_today = ai_today.get("status") == "success"
    _completed_hashes_today = set()
    _completed_text_keys_today = []
    _completed_labels_today = []
    try:
        if COMPLETED_TODOS_FILE.exists():
            completed_payload = json.loads(COMPLETED_TODOS_FILE.read_text(encoding="utf-8", errors="replace"))
            if (
                isinstance(completed_payload, dict)
                and str(completed_payload.get("date", "")).strip() == _effective_today
                and isinstance(completed_payload.get("completed"), list)
            ):
                _completed_hashes_today = {
                    str(item).strip().lower()
                    for item in completed_payload.get("completed", [])
                    if str(item).strip()
                }
                if isinstance(completed_payload.get("completed_texts"), list):
                    _completed_text_keys_today = [
                        re.sub(r"\s+", " ", str(item).strip().lower())
                        for item in completed_payload.get("completed_texts", [])
                        if str(item).strip()
                    ]
                if isinstance(completed_payload.get("completed_labels"), list):
                    _completed_labels_today = [
                        str(item).strip()
                        for item in completed_payload.get("completed_labels", [])
                        if str(item).strip()
                    ]
                if not _completed_labels_today and isinstance(completed_payload.get("completed_texts"), list):
                    _completed_labels_today = [
                        str(item).strip().capitalize()
                        for item in completed_payload.get("completed_texts", [])
                        if str(item).strip()
                    ]
    except Exception:
        _completed_hashes_today = set()
        _completed_text_keys_today = []
        _completed_labels_today = []

    # Collect action items from multiple sources (only if data is from today)
    diarium_data = data.get("diariumTodos", []) if data.get("diariumDataDate") == _effective_today else []
    notes_todos = data.get("appleNotesTodos", []) if isinstance(data.get("appleNotesTodos", []), list) else []
    diarium_tadah = data.get("diariumTaDah", []) if data.get("diariumDataDate") == _effective_today else []
    ai_todos = ai_today.get("genuine_todos", []) if _ai_is_today else []

    # --- Akiflow today tasks (non-routine, for action items injection) ---
    _akiflow_raw_sa = data.get("akiflow_tasks", {})
    _akiflow_routine_lower = {"weights", "yoga", "walk dog", "walk the dog", "get ready", "meditation", "stretch"}
    _akiflow_today_items = []
    if isinstance(_akiflow_raw_sa, dict) and _akiflow_raw_sa.get("status") == "ok":
        for _t in _akiflow_raw_sa.get("tasks", []):
            if _t.get("days_from_now") != 0:
                continue
            _summary = _t.get("summary", "").strip()
            if not _summary or _summary.lower() in _akiflow_routine_lower:
                continue
            _time_est = "30m"
            try:
                from datetime import datetime as _dt_sa
                _s = _dt_sa.fromisoformat(_t["start"].replace("Z", "+00:00"))
                _e = _dt_sa.fromisoformat(_t["end"].replace("Z", "+00:00"))
                _mins = int((_e - _s).total_seconds() / 60)
                if _mins > 0:
                    _time_est = (f"{_mins}m" if _mins < 60
                                 else f"{_mins//60}h{_mins%60}m" if _mins % 60
                                 else f"{_mins//60}h")
            except Exception:
                pass
            _akiflow_today_items.append({"summary": _summary, "time_est": _time_est})

    # --- Schedule analysis extraction (feasibility_map populated after _task_match_key) ---
    _sa = data.get("schedule_analysis", {})
    _sa_today = isinstance(_sa, dict) and _sa.get("date") == _effective_today
    _burnout_risk = _sa.get("burnout_risk", "") if _sa_today else ""
    _schedule_density = _sa.get("schedule_density", "") if _sa_today else ""
    _schedule_insight = _sa.get("schedule_insight", "") if _sa_today else ""
    _feasibility_map = {}  # populated after _task_match_key is defined below

    def _task_match_key(raw_text):
        """Normalize task/loop text so small punctuation differences do not duplicate rows."""
        text = re.sub(r"\s+", " ", str(raw_text or "").strip().lower())
        text = re.sub(r"[^a-z0-9\s]", "", text)
        return text

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

    def _task_completion_hash(raw_text):
        key = _task_match_key(raw_text) or str(raw_text or "").strip().lower()
        if not key:
            return ""
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def _task_completion_hash_legacy(raw_text):
        seed = str(raw_text or "").strip().lower()
        if not seed:
            return ""
        return hashlib.md5(seed.encode()).hexdigest()[:12]

    _task_action_stems = {
        "apply", "assemble", "book", "buy", "call", "cancel", "change", "check",
        "clean", "collect", "complete", "contact", "create", "do", "email", "file",
        "fill", "find", "finish", "fix", "follow", "get", "give", "install", "log",
        "look", "make", "message", "move", "pack", "pay", "pick", "plan", "post",
        "prepare", "print", "read", "register", "repair", "replace", "reply",
        "request", "research", "review", "schedule", "send", "set", "sign", "sort",
        "submit", "tidy", "unpack", "update", "vacuum", "wash", "write",
    }
    _task_object_stopwords = {
        "the", "and", "this", "that", "with", "from", "into", "onto", "for", "to",
        "after", "before", "right", "left", "one", "some", "any", "just", "then",
        "today", "tonight", "tomorrow", "morning", "afternoon", "evening", "now",
    }

    def _task_matches_completed_text(raw_text):
        candidate_key = _task_match_key(raw_text)
        if not candidate_key or not _completed_text_keys_today:
            return False
        candidate_tokens = {t for t in candidate_key.split() if t}
        candidate_object_tokens = {
            t for t in candidate_tokens
            if t not in _task_action_stems and t not in _task_object_stopwords and not t.isdigit() and len(t) > 2
        }
        for done_raw in _completed_text_keys_today:
            done_key = _task_match_key(done_raw)
            if not done_key:
                continue
            if candidate_key == done_key:
                return True
            if len(candidate_key) >= 10 and candidate_key in done_key:
                return True
            if len(done_key) >= 10 and done_key in candidate_key:
                return True
            done_tokens = {t for t in done_key.split() if t}
            done_object_tokens = {
                t for t in done_tokens
                if t not in _task_action_stems and t not in _task_object_stopwords and not t.isdigit() and len(t) > 2
            }
            if done_object_tokens and candidate_object_tokens:
                obj_overlap = done_object_tokens & candidate_object_tokens
                min_obj = min(len(done_object_tokens), len(candidate_object_tokens))
                if len(obj_overlap) >= 2:
                    return True
                if min_obj >= 3 and len(obj_overlap) / max(min_obj, 1) >= 0.75:
                    return True
            overlap = len(candidate_tokens & done_tokens)
            union = len(candidate_tokens | done_tokens)
            if overlap >= 2 and union and (overlap / union) >= 0.66:
                return True
        return False

    def _task_object_tokens(raw_text):
        key = _task_match_key(raw_text)
        tokens = {t for t in key.split() if t}
        return {
            t for t in tokens
            if t not in _task_action_stems and t not in _task_object_stopwords and not t.isdigit() and len(t) > 2
        }

    def _tasks_equivalent(left_text, right_text):
        left_key = _task_match_key(left_text)
        right_key = _task_match_key(right_text)
        if not left_key or not right_key:
            return False
        if left_key == right_key:
            return True
        if len(left_key) >= 10 and left_key in right_key:
            return True
        if len(right_key) >= 10 and right_key in left_key:
            return True
        left_obj = _task_object_tokens(left_text)
        right_obj = _task_object_tokens(right_text)
        if left_obj and right_obj:
            obj_overlap = left_obj & right_obj
            min_obj = min(len(left_obj), len(right_obj))
            if len(obj_overlap) >= 2:
                return True
            if min_obj >= 3 and len(obj_overlap) / max(min_obj, 1) >= 0.75:
                return True
        left_tokens = set(left_key.split())
        right_tokens = set(right_key.split())
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return bool(overlap >= 2 and union and (overlap / union) >= 0.66)

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

    _task_action_verbs = {
        "apply", "assemble", "book", "buy", "call", "cancel", "change", "check",
        "clean", "collect", "complete", "contact", "create", "do", "email", "file",
        "fill", "finish", "fix", "follow", "get", "give", "install", "log", "make",
        "message", "move", "pack", "pay", "pick", "plan", "post", "prepare", "print",
        "read", "register", "repair", "replace", "reply", "request", "research",
        "review", "schedule", "send", "set", "sign", "sort", "submit", "tidy",
        "unpack", "update", "vacuum", "wash", "write",
    }
    _task_vague_object_tokens = {
        "that", "this", "it", "thing", "things", "stuff", "something", "anything",
        "everything", "whatever", "whenever", "sometime", "someday",
    }

    def _is_actionable_task(raw_text):
        text = re.sub(r"\s+", " ", str(raw_text or "").strip())
        if len(text) < 10 or len(text) > 220:
            return False
        lower = text.lower()
        if "tomorrow" in lower and re.search(r"\bpay(?:ing)?\b", lower):
            concrete_targets = ("rent", "invoice", "bill", "tax", "credit card", "subscription", "council")
            if not any(token in lower for token in concrete_targets):
                return False
        if any(tok in lower for tok in ("payment", "paid")):
            if lower.startswith(("get paid", "be paid", "receive payment", "check if", "check whether", "check that", "wait for", "waiting for")):
                return False
            if any(tok in lower for tok in ("tomorrow", "by noon", "by midday", "arrive", "arrives", "arrived", "land", "lands", "come through")):
                return False
        if re.match(r"^(and|or|but|so|because|me|him|her|them|us|it|that|which)\b", lower):
            return False
        if re.match(r"^(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower):
            return False
        if lower.startswith("make sure"):
            return False
        if any(phrase in lower for phrase in ("can wait", "could wait", "should wait", "wait for later", "wait until later", "at some point", "eventually")):
            return False
        if any(marker in lower for marker in ("i'm a terrible person", "denigrate", "feel bad about", "childish")):
            return False
        candidate = re.sub(
            r"^(?:i need to|i have to|i must|i'm going to|i will|need to|must|to)\s+",
            "",
            lower,
        ).strip()
        words = re.findall(r"[a-z']+", candidate)
        if len(words) < 2:
            return False
        if words[0] not in _task_action_verbs:
            return False
        if words[0] in {"do", "get", "make"} and words[1] in _task_vague_object_tokens:
            return False
        object_tokens = [
            token for token in words[1:]
            if token not in {"up", "out", "off", "on", "in", "to", "for", "with", "and", "or", "then", "now"}
        ]
        if object_tokens and all(token in _task_vague_object_tokens for token in object_tokens):
            return False
        return True

    def _compact_task_text(raw_text, max_len=140):
        """Shorten long AI task text so rows stay scannable."""
        text = re.sub(r"\s+", " ", str(raw_text or "").strip())
        if len(text) <= max_len:
            return text
        first_clause = re.split(r"(?<=[\.\!\?])\s+| — | - |; ", text, maxsplit=1)[0].strip()
        if 24 <= len(first_clause) <= max_len:
            return first_clause.rstrip(".!?:;,- ") + "..."
        return text[: max_len - 3].rstrip() + "..."

    all_action_items = []
    action_item_index = {}

    def _append_action_item(task, priority="Medium", time_est="30m", source="daemon", category="standard"):
        task_text = str(task or "").strip()
        if not task_text:
            return
        if not _is_actionable_task(task_text):
            return
        task_key = _task_match_key(task_text)
        if not task_key:
            return
        done_today = _is_task_completed_today(task_text)
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
            return
        action_item_index[task_key] = len(all_action_items)
        all_action_items.append({
            "task": task_text,
            "priority": priority,
            "time": time_est,
            "source": source,
            "category": category,
            "done": done_today,
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
        if not done_text:
            continue
        if not _is_task_completed_today(done_text):
            continue
        _append_action_item(done_text, priority="Medium", time_est="", source="ta_dah", category="maintenance")

    # Fallback: if ta_dah sync lags, still render completed labels from completion cache.
    for done_label in (_completed_labels_today or []):
        done_text = str(done_label or "").strip()
        if not done_text:
            continue
        _append_action_item(done_text, priority="Medium", time_est="", source="completed", category="maintenance")

    for todo in (ai_todos or []):
        text = todo.get("text", "") if isinstance(todo, dict) else str(todo)
        category = todo.get("category", "standard") if isinstance(todo, dict) else "standard"
        _append_action_item(text, priority="Medium", time_est="15m", source="ai", category=category)

    if weekly_report_due:
        _append_action_item(
            "Generate weekly report and review it on the dashboard weekly section.",
            priority="Medium",
            time_est="10m",
            source="system",
            category="maintenance",
        )

    # Also pull todo-type from all_insights that aren't already captured (date-gated)
    if _ai_is_today:
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

    # Akiflow time-blocked tasks (non-routine) → action items
    for _ak in _akiflow_today_items:
        _append_action_item(
            _ak["summary"],
            priority="High",
            time_est=_ak["time_est"],
            source="akiflow",
            category="standard",
        )

    if all_action_items:
        # Group by category: quick_win, maintenance, standard, system (claude)
        quick_items = []
        maintenance_items = []
        standard_items = []
        system_items = []
        completed_items = []
        system_keywords = ["daemon", "dashboard", "claude", "script", "config", "cache", "verify"]

        current_hour_for_filter = datetime.now().hour
        for item in all_action_items:
            # Skip items with empty task text
            if not item.get("task", "").strip():
                continue
            # Skip "set tomorrow's plans" before 18:00 — Jim sets these in the evening
            if current_hour_for_filter < 18 and "tomorrow" in item.get("task", "").lower() and "plan" in item.get("task", "").lower():
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
                button_html = f'<button onclick="qaCompleteTodoFromButton(this)" data-text="{html.escape(task, quote=True)}" data-task-hash="{html.escape(task_hash, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(131,24,67,0.35); color: #fbcfe8; border: 1px solid rgba(249,168,212,0.35);">☐ Done</button>'
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

        if items_html:
            action_items_list_html = items_html

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
        entries = []
    anxiety_today_raw = ai_today.get("anxiety_reduction_score") if isinstance(ai_today, dict) else None
    try:
        anxiety_today_value = float(anxiety_today_raw)
    except Exception:
        anxiety_today_value = None
    workout_signals_for_stale = data.get("workoutChecklistSignals", {}) if isinstance(data.get("workoutChecklistSignals"), dict) else {}
    anxiety_saved_signal = bool(workout_signals_for_stale.get("anxiety_saved_today"))
    has_anxiety_logged_today = anxiety_today_value is not None or anxiety_saved_signal

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

    if entries:
        # Entries are already today-scoped; only split by source
        morning_entries = [e for e in entries if e.get("source") == "morning"]
        evening_payload = data.get("evening", {}) if isinstance(data.get("evening"), dict) else {}
        has_real_updates_text = bool(_strip_updates_metadata(evening_payload.get("updates", "")))
        updates_entries = [e for e in entries if e.get("source") == "updates"] if has_real_updates_text else []
        evening_entries = [e for e in entries if e.get("source") == "evening"]
        # Fallback: daemon_evening (heuristic) when no API-based evening insights exist
        if not evening_entries:
            evening_entries = [e for e in entries if e.get("source") == "daemon_evening"]

        # Synthesised insights — split by source
        daily_guidance = ai_today.get("daily_guidance")

        # Morning synthesis (morning data only)
        # daily_guidance contains AI-generated prescriptive analysis of morning diary entries
        # (grateful, intent, body check, letting go, affirmation) — this IS Morning Insights content
        morning_synthesis = synthesise_top_insights(
            morning_entries, [],  # No evening data for morning synthesis
            data.get("engagementHints", []),
            data.get("mentalHealthFlags", []),
            {"status": "found", "items": data.get("openLoopItems", [])} if data.get("openLoopItems") else {},
            data.get("aiInsights", {}).get("therapy_homework", []),
            max_length=500,
            daily_guidance=daily_guidance  # AI morning diary analysis goes here
        )
        morning_synthesis = [line for line in morning_synthesis if not _is_stale_missing_reflection_signal(line)]

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
        evening_synthesis = [line for line in evening_synthesis if not _is_stale_missing_reflection_signal(line)]

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
                    synthesis_items_html += f'''
                        <div class="mb-4{'  pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);' if idx > 0 else '"'}>
                            <p class="text-base font-medium leading-relaxed" style="color: #f3f4f6; line-height: 1.8;">{emoji} {lead}</p>
                            <p class="text-sm mt-2 ml-6 leading-relaxed" style="color: #b0b5bd; line-height: 1.7;">{rest}</p>
                        </div>'''
                else:
                    synthesis_items_html += f'''
                        <div class="mb-4{'  pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);' if idx > 0 else '"'}>
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
                all_morning_insights.extend(entry.get("insights", []))
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
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #a7f3d0">🌅 Morning Insights (tap to expand)</summary>
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
                if summary and not _is_stale_missing_reflection_signal(summary):
                    update_summaries.append(summary)
                all_updates_insights.extend(entry.get("insights", []))

            if update_summaries:
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

        if updates_sections:
            updates_insights_html = f'''
            <div class="card rounded-xl p-5 mb-4" style="background: linear-gradient(135deg, rgba(30,64,175,0.18), rgba(6,95,70,0.08)); border: 1px solid rgba(147,197,253,0.2);">
                <details>
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #93c5fd">📝 Update Insights (tap to expand)</summary>
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
                    synthesis_items_html += f'''
                        <div class="mb-4{'  pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);' if idx > 0 else '"'}>
                            <p class="text-base font-medium leading-relaxed" style="color: #f3f4f6; line-height: 1.8;">{emoji} {lead}</p>
                            <p class="text-sm mt-2 ml-6 leading-relaxed" style="color: #b0b5bd; line-height: 1.7;">{rest}</p>
                        </div>'''
                else:
                    synthesis_items_html += f'''
                        <div class="mb-4{'  pt-3" style="border-top: 1px solid rgba(196,181,253,0.08);' if idx > 0 else '"'}>
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
                all_evening_insights.extend(entry.get("insights", []))
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
                    <summary class="text-lg font-semibold cursor-pointer" style="color: #c4b5fd">🌙 Evening Insights (tap to expand)</summary>
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
            weekly_rank = selector.get("weekly_rank", []) if isinstance(selector.get("weekly_rank", []), list) else []

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

            ranking_html = ""
            for row in weekly_rank[:5]:
                if not isinstance(row, dict):
                    continue
                row_name = str(row.get("technique", "")).strip()
                if not row_name:
                    continue
                row_avg = row.get("avg_relief")
                row_days = row.get("evidence_days")
                row_note = str(row.get("note", "")).strip()
                avg_text = f"{float(row_avg):.1f}/10" if isinstance(row_avg, (int, float)) else "n/a"
                days_text = f"{int(row_days)}d" if isinstance(row_days, (int, float)) else "0d"
                ranking_html += f'''
                <div class="flex items-center justify-between gap-2 text-xs mb-1.5">
                    <span style="color: #dbeafe">{html.escape(row_name)}</span>
                    <span style="color: #93c5fd">{avg_text} • {days_text}</span>
                </div>'''
                if row_note:
                    ranking_html += f'<p class="text-xs mb-1.5" style="color: #64748b">{html.escape(row_note)}</p>'

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
                {f'<div class="mt-3 pt-2" style="border-top: 1px solid rgba(125,211,252,0.22);"><p class="text-xs mb-2" style="color: #93c5fd; font-weight: 600;">Weekly effectiveness rank</p>{ranking_html}</div>' if ranking_html else ''}
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

    def _input_num(value, min_v, max_v):
        try:
            if value is None or value == "":
                return ""
            n = float(value)
        except Exception:
            return ""
        if n < float(min_v) or n > float(max_v):
            return ""
        if float(n).is_integer():
            return str(int(n))
        return str(round(float(n), 1))

    def _input_choice(value, allowed):
        raw = str(value or "").strip().lower()
        return raw if raw in allowed else ""

    wc_recovery = str(workout_checklist.get("recovery_gate", "unknown")).strip().lower()
    if wc_recovery not in {"pass", "fail", "unknown"}:
        wc_recovery = "unknown"
    wc_calf_checked = "checked" if bool(workout_checklist.get("calf_done")) else ""
    wc_rpe_value = _input_num(workout_checklist_post.get("rpe"), 1, 10)
    wc_pain_value = _input_num(workout_checklist_post.get("pain"), 0, 10)
    wc_energy_value = _input_num(workout_checklist_post.get("energy_after"), 1, 10)
    wc_feedback = workout_checklist.get("session_feedback", {}) if isinstance(workout_checklist.get("session_feedback"), dict) else {}
    wc_duration_value = _input_num(wc_feedback.get("duration_minutes"), 5, 240)
    wc_intensity_value = _input_choice(wc_feedback.get("intensity"), {"easy", "moderate", "hard"})
    wc_session_type_value = _input_choice(wc_feedback.get("session_type"), {"somatic", "yin", "flow", "mobility", "restorative", "other"})
    wc_body_feel_value = _input_choice(wc_feedback.get("body_feel"), {"relaxed", "neutral", "tight", "sore", "energised", "fatigued"})
    wc_note_value = str(wc_feedback.get("session_note", "")).strip()
    wc_yoga_anxiety_source = wc_feedback.get("anxiety_reduction_score")
    if wc_yoga_anxiety_source in {None, ""}:
        wc_yoga_anxiety_source = get_ai_day(data.get("aiInsights", {}) if isinstance(data.get("aiInsights", {}), dict) else {}, get_effective_date()).get("anxiety_reduction_score")
    wc_yoga_anxiety_value = _input_num(wc_yoga_anxiety_source, 0, 10)
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
                <summary class="text-xs font-semibold cursor-pointer" style="color: #9ca3af">🧾 Workout checklist (tap to expand)</summary>
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
    if corr.get("status") == "ok" and corr.get("count", 0) >= 5:
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
    weekly_status_label = "✅ Ready" if weekly_current_exists else ("⚠️ Due this weekend" if weekly_needs_generation else "⏳ Waiting for week end")
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
        "End-of-week reminder: generate this on Saturday/Sunday so the review is ready."
        if weekly_end_of_week and not weekly_current_exists
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
        </div>'''
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
    updates_text = _strip_updates_metadata(evening.get("updates", ""))
    updates_card_html = ""
    completed_updates_html = ""
    if updates_text:
        updates_emoji = _pick_content_emoji(updates_text)
        updates_card_html = f'''
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #93c5fd">📝 Updates</h3>
        <div class="rounded-lg p-3" style="background: rgba(30,64,175,0.12); border-left: 3px solid #60a5fa">
            <p class="text-sm" style="color: #e5e7eb">{updates_emoji} {updates_text}</p>
        </div>
    </div>'''

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
    evening_reflections_text = evening.get("evening_reflections", "")
    if evening_reflections_text:
        evening_raw_html += f'''
            <div class="rounded-lg p-3 mb-2" style="background: rgba(88,28,135,0.08); border-left: 3px solid rgba(196,181,253,0.5)">
                <p class="text-xs mb-1" style="color: rgba(196,181,253,0.7)">🌙 Evening reflections</p>
                <p class="text-sm" style="color: #e5e7eb">{evening_reflections_text}</p>
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

    # Build Pieces "What I worked on today" block for evening card
    _pieces_day_html = ""
    _p_digest2 = _pieces_digest_text if isinstance(_pieces_d, dict) else ""
    _p_digest2_source = _pieces_digest_source if isinstance(_pieces_d, dict) else ""
    _p_summaries2 = _pieces_d.get("summaries", []) if isinstance(_pieces_d, dict) else []
    if _pieces_d.get("status") == "ok" and (_p_digest2 or _p_summaries2):
        _day_parts = _build_pieces_shared_parts(
            _pieces_d,
            _p_digest2,
            _p_digest2_source,
            body_color="#e5e7eb",
            muted_color="#9ca3af",
            details_class="mt-1",
        )
        if _day_parts:
            _pieces_day_html = (
                '<div class="rounded-lg p-3 mb-2" style="background:rgba(88,28,135,0.1);border-left:3px solid rgba(196,181,253,0.4);">'
                '<p class="text-xs font-semibold mb-2" style="color:#c4b5fd">🛠️ What you worked on today</p>'
                + "".join(_day_parts)
                + '</div>'
            )

    # Build final evening card with clear section headers
    # TIME-OF-DAY AWARENESS: keep evening entries hidden until evening close window
    evening_card_html = ""
    if not is_evening:
        if evening_arc_html:
            evening_card_html += evening_arc_html
        # Still show Pieces day digest during the day (not gated by evening hour)
        if _pieces_day_html:
            evening_card_html += _pieces_day_html
        if not evening_card_html:
            evening_card_html = '<p class="text-sm" style="color: #6b7280">Evening entries appear after 18:00</p>'
    else:
        if evening_arc_html:
            evening_card_html += evening_arc_html
        if evening_raw_html:
            evening_card_html += f'''
                <p class="text-xs font-semibold mb-2" style="color: #9ca3af">📝 Your entries</p>
                {evening_raw_html}'''
        if _pieces_day_html:
            evening_card_html += _pieces_day_html
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
            tomorrow_lines_for_display = _build_tomorrow_reframe_lines(
                jim_tomorrow,
                jim_remember,
                weekend_mode=tomorrow_is_weekend,
            )

        # If only one AI line survived, top up with reframed lines.
        if (jim_tomorrow or jim_remember) and len(tomorrow_lines_for_display) < 2:
            extras = _build_tomorrow_reframe_lines(
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
                tomorrow_subnote = "Reframed from tonight&apos;s notes + current patterns."
                if tomorrow_is_weekend:
                    tomorrow_subnote = "Weekend mode active: recovery/family guidance prioritised."
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
        if summary and not _looks_like_weekly_digest_summary(summary):
            eve_felt_summary = summary
            eve_felt_entry = entry
            break
    if eve_felt_entry is None and eve_felt_entries:
        eve_felt_entry = eve_felt_entries[-1]
    eve_felt_insights = eve_felt_entry.get("insights", []) if isinstance(eve_felt_entry, dict) else []
    eve_patterns = [i for i in eve_felt_insights if i.get("type") == "pattern"]
    eve_signals = [
        i for i in eve_felt_insights
        if i.get("type") == "signal"
        and not _is_stale_missing_reflection_signal(i.get("text", ""))
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
        # Get beads data from HEALTH project
        health_path = Path.home() / "Documents/Claude Projects/HEALTH"
        result = subprocess.run(
            ["bd", "list", "--status=open", "--json"],
            cwd=health_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            beads = json.loads(result.stdout)
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
    except Exception as e:
        print(f"Warning: Beads section failed: {e}", file=sys.stderr)

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

            initial_url = file_url or remote_url
            if initial_url:
                diarium_image_tag = (
                    f'<img id="diarium-header-image" src="{html.escape(initial_url, quote=True)}" '
                    f'data-file-src="{html.escape(file_url, quote=True)}" '
                    f'data-remote-src="{html.escape(remote_url, quote=True)}" '
                    'alt="Today" class="rounded-2xl object-cover flex-shrink-0" '
                    'style="width: 100px; height: 100px; border: 2px solid rgba(249,168,212,0.3);"/>'
                )

    system_status_html = ""
    system_needs_attention = False
    runtime = data.get("runtimeStatus", {}) if isinstance(data.get("runtimeStatus", {}), dict) else {}
    if runtime:
        daemon_ok = bool(runtime.get("daemon_ok"))
        api_ok = bool(runtime.get("api_ok"))
        cache_age = runtime.get("cache_age_minutes")
        checked_at = str(runtime.get("checked_at", "")).strip()
        beads_counts = runtime.get("beads", {}) if isinstance(runtime.get("beads", {}), dict) else {}
        remote_access = runtime.get("remote_access", {}) if isinstance(runtime.get("remote_access", {}), dict) else {}

        daemon_label = "🟢 Daemon" if daemon_ok else "🔴 Daemon"
        daemon_style = "color: #6ee7b7; border: 1px solid rgba(110,231,183,0.28); background: rgba(6,95,70,0.22);" if daemon_ok else "color: #fca5a5; border: 1px solid rgba(239,68,68,0.28); background: rgba(127,29,29,0.22);"
        api_label = "🟢 API" if api_ok else "🔴 API"
        api_style = "color: #93c5fd; border: 1px solid rgba(147,197,253,0.28); background: rgba(30,64,175,0.2);" if api_ok else "color: #fca5a5; border: 1px solid rgba(239,68,68,0.28); background: rgba(127,29,29,0.22);"

        if isinstance(cache_age, int):
            if cache_age <= 10:
                cache_label = f"🟢 {cache_age}m"
                cache_style = "color: #a7f3d0; border: 1px solid rgba(110,231,183,0.28); background: rgba(6,95,70,0.22);"
            elif cache_age <= 60:
                cache_label = f"🟡 {cache_age}m"
                cache_style = "color: #fde68a; border: 1px solid rgba(251,191,36,0.28); background: rgba(120,53,15,0.24);"
            else:
                cache_label = f"🔴 {cache_age}m"
                cache_style = "color: #fca5a5; border: 1px solid rgba(239,68,68,0.28); background: rgba(127,29,29,0.22);"
        else:
            cache_label = "🔴 Cache"
            cache_style = "color: #fca5a5; border: 1px solid rgba(239,68,68,0.28); background: rgba(127,29,29,0.22);"

        system_needs_attention = (
            runtime.get("daemon_ok") is False
            or runtime.get("api_ok") is False
            or (isinstance(cache_age, int) and cache_age > 60)
        )

        beads_h = beads_counts.get("HEALTH")
        beads_w = beads_counts.get("WORK")
        beads_t = beads_counts.get("TODO")
        beads_summary = f"H:{beads_h if isinstance(beads_h, int) else '?'} • W:{beads_w if isinstance(beads_w, int) else '?'} • T:{beads_t if isinstance(beads_t, int) else '?'}"
        checked_text = checked_at if checked_at else "--:--"

        tailscale_url = str(remote_access.get("tailscale_url", "")).strip()
        tailscale_state = str(remote_access.get("tailscale_state", "unknown")).strip()
        cloudflare_url = str(remote_access.get("cloudflare_url", "")).strip()
        cloudflare_state = str(remote_access.get("cloudflare_state", "missing")).strip()
        cloudflare_age = remote_access.get("cloudflare_age_minutes")

        if tailscale_url:
            ts_label = "🟢 TS" if tailscale_state == "serve" else "🔵 TS"
            tailscale_html = f'<a href="{html.escape(tailscale_url + "/dashboard", quote=True)}" class="system-inline" target="_blank" rel="noopener">{ts_label}</a>'
        else:
            tailscale_html = '<span class="system-inline">⚪ TS</span>'

        # Hide Cloudflare status badge when Tailscale is available to reduce visual noise.
        # Cloudflare can still be used as backend fallback.
        if tailscale_url:
            cloudflare_html = ""
        else:
            if cloudflare_url:
                if isinstance(cloudflare_age, int):
                    cf_age_text = f"{cloudflare_age}m"
                else:
                    cf_age_text = "?"
                cf_label = "🟢 CF" if cloudflare_state == "fresh" else "🟠 CF"
                cloudflare_html = f'<a href="{html.escape(cloudflare_url + "/dashboard", quote=True)}" class="system-inline" target="_blank" rel="noopener">{cf_label} {cf_age_text}</a>'
            else:
                cloudflare_html = '<span class="system-inline">⚪ CF</span>'

        system_status_html = f'''
    <section class="settings-rail system-rail" aria-label="System status">
        <div class="system-line">
            <span class="settings-inline-label">🧩 System</span>
            <button id="sys-heal-btn" onclick="qaHealSystem(this)" class="system-chip system-chip-action" style="background: rgba(6,95,70,0.28); color: #a7f3d0; border: 1px solid rgba(110,231,183,0.3);">🛠️</button>
            <span id="sys-daemon-badge" class="system-chip" style="{daemon_style}">{daemon_label}</span>
            <span id="sys-api-badge" class="system-chip" style="{api_style}">{api_label}</span>
            <span id="sys-cache-badge" class="system-chip" style="{cache_style}">{cache_label}</span>
            <span id="sys-beads-summary" class="system-inline">{beads_summary}</span>
            <span id="sys-checked-at" class="system-inline">{checked_text}</span>
            {tailscale_html}
            {cloudflare_html}
        </div>
    </section>'''

    stale_notice_html = ""
    if not data.get("diariumFresh", True):
        source_date = data.get("diariumDataDate") or "unknown"
        reason = data.get("diariumFreshReason") or "Latest Diarium export does not match today's effective date."
        stale_notice_html = f'''
    <div class="card" style="border: 1px solid rgba(251,191,36,0.35); background: rgba(120,53,15,0.18);">
        <p class="text-sm font-semibold" style="color: #fde68a">⚠️ Diarium data is stale</p>
        <p class="text-xs mt-1" style="color: #fcd34d">Source date: {source_date} • {reason}</p>
        <p class="text-xs mt-1" style="color: #9ca3af">Morning/Evening journal sections are hidden until a fresh export is detected.</p>
    </div>'''

    important_thing_warning_html = ""
    if data.get("diariumFresh", True) and data.get("importantThingMissing", False):
        important_thing_warning_html = '''
    <div class="card mt-2" style="border: 1px solid rgba(251,191,36,0.35); background: rgba(120,53,15,0.16);">
        <p class="text-sm font-semibold" style="color: #fde68a">⚠️ Missing “important thing” in morning transcription</p>
        <p class="text-xs mt-1" style="color: #fcd34d">Add one priority action in morning pages so today’s focus can be extracted cleanly.</p>
    </div>'''

    ideas_status_html = ""
    ideas_payload = data.get("appleNotesIdeas", {}) if isinstance(data.get("appleNotesIdeas", {}), dict) else {}
    if ideas_payload:
        ideas_status = str(ideas_payload.get("status", "") or "").strip().lower() or "unknown"
        ideas_counts = ideas_payload.get("counts", {}) if isinstance(ideas_payload.get("counts", {}), dict) else {}
        ideas_new = int(ideas_counts.get("new_items", ideas_payload.get("new_items_count", 0)) or 0)
        ideas_created = int(ideas_counts.get("beads_created", 0) or 0)
        ideas_failed = int(ideas_counts.get("beads_failed", 0) or 0)
        ideas_retried = int(ideas_counts.get("retried", 0) or 0)
        ideas_retry_queue = int(ideas_payload.get("retry_queue_count", 0) or 0)
        ideas_last_run = str(ideas_payload.get("last_run", "") or "").strip()
        ideas_preview = ideas_payload.get("latest_items_preview", []) if isinstance(ideas_payload.get("latest_items_preview", []), list) else []
        ideas_failures = ideas_payload.get("failures", []) if isinstance(ideas_payload.get("failures", []), list) else []
        ideas_fail_summary = ""
        if ideas_failures:
            first_fail = ideas_failures[0] if isinstance(ideas_failures[0], dict) else {}
            fail_reason = str(first_fail.get("reason", "")).strip() if isinstance(first_fail, dict) else ""
            if fail_reason:
                ideas_fail_summary = f'<p class="text-xs mt-1" style="color: #fecaca">Latest failure: {html.escape(fail_reason[:140])}</p>'
        ideas_preview_html = ""
        if ideas_preview:
            preview_items = "".join(
                f'<li style="color: #cbd5e1;">{html.escape(str(item).strip())}</li>'
                for item in ideas_preview[:3]
                if str(item).strip()
            )
            if preview_items:
                ideas_preview_html = f'<ul class="text-xs mt-2 space-y-1">{preview_items}</ul>'

        status_colour = "#86efac" if ideas_status == "success" else ("#fca5a5" if ideas_status == "error" else "#fde68a")
        ideas_status_html = f'''
    <div class="card mt-2" style="border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.58);">
        <p class="text-sm font-semibold" style="color: #a7f3d0">💡 Ideas pickup</p>
        <p class="text-xs mt-1" style="color: {status_colour};">Status: {html.escape(ideas_status)} • new {ideas_new} • beads {ideas_created} • failed {ideas_failed} • retried {ideas_retried} • queue {ideas_retry_queue}</p>
        {f'<p class="text-xs mt-1" style="color: #94a3b8">Last run: {html.escape(ideas_last_run)}</p>' if ideas_last_run else ''}
        {ideas_fail_summary}
        {ideas_preview_html}
    </div>'''

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

    def _qa_input_num(value, min_v, max_v):
        try:
            if value is None or value == "":
                return None
            n = int(value)
        except Exception:
            return None
        if n < min_v or n > max_v:
            return None
        return n

    qa_workout_checklist_state = {
        "recovery_gate": str(qa_workout_checklist.get("recovery_gate", "unknown")).strip().lower(),
        "calf_done": bool(qa_workout_checklist.get("calf_done", False)),
        "post_workout": {
            "rpe": _qa_input_num(qa_workout_post.get("rpe"), 1, 10),
            "pain": _qa_input_num(qa_workout_post.get("pain"), 0, 10),
            "energy_after": _qa_input_num(qa_workout_post.get("energy_after"), 1, 10),
        },
        "session_feedback": {
            "duration_minutes": _qa_input_num(qa_workout_feedback.get("duration_minutes"), 5, 240),
            "intensity": str(qa_workout_feedback.get("intensity", "")).strip().lower(),
            "session_type": str(qa_workout_feedback.get("session_type", "")).strip().lower(),
            "body_feel": str(qa_workout_feedback.get("body_feel", "")).strip().lower(),
            "session_note": str(qa_workout_feedback.get("session_note", "")).strip()[:280],
            "anxiety_reduction_score": _qa_input_num(qa_workout_feedback.get("anxiety_reduction_score"), 0, 10),
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

    def _qa_end_day_status_text(state):
        if not isinstance(state, dict) or not bool(state.get("done_today")):
            return "⬜ End Day not run yet."
        ran_at = str(state.get("ran_at", "")).strip()
        if ran_at:
            try:
                return f"✅ End Day already run at {datetime.fromisoformat(ran_at).strftime('%H:%M')}."
            except Exception:
                pass
        return "✅ End Day already run today."

    qa_end_day_done_today = bool(qa_end_day_state.get("done_today"))
    qa_end_day_status_text = _qa_end_day_status_text(qa_end_day_state)
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
        one_text = qa_todo_options[0]
        one_hash = _task_completion_hash(one_text)
        one_emoji = _pick_content_emoji(one_text)
        one_compact = _compact_task_text(one_text, max_len=155)
        qa_one_thing_html = f'''
        <div class="rounded-lg px-3 py-3 mb-3" style="background: rgba(6,95,70,0.2); border: 1px solid rgba(110,231,183,0.26);">
            <p class="text-xs font-semibold mb-1" style="color: #a7f3d0">🎯 One Thing Now</p>
            <p class="text-sm mb-2" title="{html.escape(one_text, quote=True)}" style="color: #d1fae5; line-height: 1.45;">{one_emoji} {html.escape(one_compact)}</p>
            <div class="flex flex-wrap items-center gap-2">
                <button onclick="qaStartOneThing(this)" data-text="{html.escape(one_text, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(30,64,175,0.32); color: #bfdbfe; border: 1px solid rgba(147,197,253,0.35);">Start</button>
                <button onclick="qaCompleteTodoFromButton(this)" data-text="{html.escape(one_text, quote=True)}" data-task-hash="{html.escape(one_hash, quote=True)}" class="rounded px-2 py-1 text-xs font-semibold" style="min-width: 72px; min-height: 34px; touch-action: manipulation; background: rgba(131,24,67,0.35); color: #fbcfe8; border: 1px solid rgba(249,168,212,0.35);">☐ Done</button>
            </div>
        </div>
        '''

    def _qa_missing_yoga_feedback(checklist_state, anxiety_score):
        state = checklist_state if isinstance(checklist_state, dict) else {}
        feedback = state.get("session_feedback", {}) if isinstance(state.get("session_feedback"), dict) else {}
        missing = []
        if _qa_input_num(feedback.get("duration_minutes"), 5, 240) is None:
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

    def _qa_missing_weights_feedback(checklist_state):
        state = checklist_state if isinstance(checklist_state, dict) else {}
        post = state.get("post_workout", {}) if isinstance(state.get("post_workout"), dict) else {}
        missing = []
        recovery = str(state.get("recovery_gate", "")).strip().lower()
        if recovery not in {"pass", "fail"}:
            missing.append("recovery gate")
        if _qa_input_num(post.get("rpe"), 1, 10) is None:
            missing.append("RPE")
        if _qa_input_num(post.get("pain"), 0, 10) is None:
            missing.append("pain")
        if _qa_input_num(post.get("energy_after"), 1, 10) is None:
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
        qa_prompt_missing_fields = _qa_missing_weights_feedback(qa_workout_checklist_state)
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
    qa_quick_meta = f"{qa_quick_done_count}/{qa_quick_done_total} core daily check-ins done."
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

    if is_evening:
        qa_anxiety_relief_html = f'''
        <div class="mt-4 pt-4" style="border-top: 1px solid rgba(251,191,36,0.16);">
            <label class="text-xs block mb-1" style="color: #fbbf24">📉 Rate today's anxiety relief (0-10)</label>
            <div class="flex items-center gap-3">
                <input id="qa-anxiety-score" type="range" min="0" max="10" step="1" value="{qa_slider_value}" class="flex-1" oninput="document.getElementById('qa-anxiety-score-val').textContent=this.value">
                <span id="qa-anxiety-score-val" class="text-sm font-semibold" style="color: #fcd34d">{qa_slider_value}</span>
                <button onclick="qaRateAnxiety()" class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(120,53,15,0.35); color: #fcd34d; border: 1px solid rgba(251,191,36,0.35);">Save</button>
            </div>
            {qa_yoga_evening_hint_html}
            {qa_week_summary_html}
        </div>
        '''
    else:
        qa_anxiety_relief_html = f'''
        <div class="mt-4 pt-4" style="border-top: 1px solid rgba(251,191,36,0.16);">
            <p class="text-xs font-semibold mb-1" style="color: #fbbf24">📉 Anxiety relief rating unlocks at 18:00</p>
            <p class="text-xs" style="color: #9ca3af">Score this after evening reflection for a true end-of-day read.</p>
            {qa_yoga_evening_hint_html}
            <details class="mt-2">
                <summary class="text-xs font-semibold cursor-pointer" style="color: #94a3b8">📊 Weekly trend</summary>
                {qa_week_summary_html}
            </details>
        </div>
        '''

    if is_evening:
        qa_end_day_label = "✅ End Day done" if qa_end_day_done_today else "🌙 End Day (after diary)"
        qa_end_day_disabled = "disabled" if qa_end_day_done_today else ""
        qa_end_day_opacity = "0.72" if qa_end_day_done_today else "1"
        qa_end_day_controls_html = f'''
            <div class="flex items-center gap-2 flex-wrap">
                <button id="qa-end-day-btn" onclick="qaRunEndDay(this)" {qa_end_day_disabled} class="rounded px-3 py-2 text-sm font-semibold" style="background: rgba(120,53,15,0.35); color: #fde68a; border: 1px solid rgba(251,191,36,0.35); opacity: {qa_end_day_opacity};">{qa_end_day_label}</button>
                <span class="text-xs" style="color: #94a3b8">Runs end-day pipeline: refresh → dashboard → Apple Notes → commit/push.</span>
            </div>
            <p id="qa-end-day-status" class="text-xs mt-1" style="color: {qa_end_day_status_color}">{html.escape(qa_end_day_status_text)}</p>
        '''
        qa_end_day_command_option = '{ label: "Action: End day (after diary)", run: () => { if (typeof qaRunEndDay === "function") qaRunEndDay(document.getElementById("qa-end-day-btn")); } },'
    else:
        qa_end_day_controls_html = f'''
            <div class="flex items-center gap-2 flex-wrap">
                <p class="text-xs font-semibold" style="color: #fbbf24">🌙 End Day unlocks at 18:00</p>
                <span class="text-xs" style="color: #94a3b8">Use after evening diary so signals + summary are complete.</span>
            </div>
            <p id="qa-end-day-status" class="text-xs mt-1" style="color: {qa_end_day_status_color}">{html.escape(qa_end_day_status_text)}</p>
        '''
        qa_end_day_command_option = ""

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

    action_items_html = f'''
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
            <summary class="text-xs font-semibold cursor-pointer" style="color: #94a3b8">Manual close (only if an item is missing)</summary>
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
            <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs font-semibold" style="color: #a7f3d0">📖 Reading mode</span>
                <button id="qa-sync-pause-10" onclick="qaSetSyncPause(10)" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(30,41,59,0.62); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.25);">Pause 10m</button>
                <button id="qa-sync-pause-30" onclick="qaSetSyncPause(30)" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(30,41,59,0.62); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.25);">Pause 30m</button>
                <button id="qa-sync-resume" onclick="qaSetSyncPause(0)" class="rounded px-2 py-1 text-xs font-semibold" style="background: rgba(6,95,70,0.32); color: #6ee7b7; border: 1px solid rgba(110,231,183,0.3);">Resume</button>
                <span id="qa-sync-pause-meta" class="text-xs" style="color: #94a3b8">Live sync active</span>
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
    const QA_API_BASE = (() => {{
        if (typeof window !== "undefined" && window.location) {{
            const protocol = (window.location.protocol || "").toLowerCase();
            if (protocol === "http:" || protocol === "https:") {{
                return window.location.origin;
            }}
            // file:// — iPhone via iCloud or Mac local. Use LAN IP if available.
            if (typeof QA_LOCAL_IP !== "undefined" && QA_LOCAL_IP && QA_LOCAL_IP !== "127.0.0.1") {{
                return `http://${{QA_LOCAL_IP}}:8765`;
            }}
        }}
        return "http://127.0.0.1:8765";
    }})();
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
    const QA_SYNC_PAUSE_KEY = "dashboard.live.sync.pause.until.v1";
    let qaMindfulnessSaving = false;
    let qaMindfulnessDesiredDone = null;
    let qaMoodSaving = false;
    let qaMoodEntrySaving = false;
    let qaMoodEntryLastAt = 0;
    let qaWorkoutSaving = false;
    let qaCurrentWorkoutType = String(QA_WORKOUT_TYPE_INITIAL || "").toLowerCase();
    let qaCurrentWorkoutDone = Boolean(QA_WORKOUT_DONE_INITIAL);
    const qaAnxietySeed = Number(QA_ANXIETY_SCORE_INITIAL);
    let qaCurrentAnxietyScore = Number.isFinite(qaAnxietySeed) ? qaAnxietySeed : null;
    let qaYogaPromptAutoOpened = false;
    let qaLiveSyncPausedUntil = 0;
    let qaEndDayState = (QA_END_DAY_INITIAL && typeof QA_END_DAY_INITIAL === "object") ? QA_END_DAY_INITIAL : {{ done_today: false, date: "", ran_at: "", source: "" }};
    let qaEndDayRunning = false;
    let qaSystemStatusFailureCount = 0;
    let qaSystemPollInFlight = false;
    let qaTodaySyncInFlight = false;
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

    function qaApplyLiveToday(today) {{
        const snapshot = (today && typeof today === "object") ? today : null;
        if (!snapshot) return;
        if (snapshot.end_day && typeof snapshot.end_day === "object") {{
            qaApplyEndDayState(snapshot.end_day);
        }}
        const liveScore = Number(snapshot.anxiety_reduction_score);
        if (Number.isFinite(liveScore)) {{
            qaApplyAnxietyScore(liveScore);
        }} else {{
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
        }}
        qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
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

    function qaEffectiveDateKey() {{
        const key = getTodayKey();
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

    function qaUpdateSystemStatus(system) {{
        if (!system || typeof system !== "object") return;
        const controlsWrap = document.getElementById("dashboard-controls-wrap");
        const daemonBadge = document.getElementById("sys-daemon-badge");
        const apiBadge = document.getElementById("sys-api-badge");
        const cacheBadge = document.getElementById("sys-cache-badge");
        const beadsSummary = document.getElementById("sys-beads-summary");
        const checkedAt = document.getElementById("sys-checked-at");
        const cacheAge = Number(system.cache_age_minutes);
        const degraded = (
            system.daemon_ok === false ||
            system.api_ok === false ||
            (Number.isFinite(cacheAge) && cacheAge > 60)
        );
        if (document && document.body && degraded) {{
            document.body.dataset.optionalPills = "on";
        }}
        if (controlsWrap && degraded) {{
            controlsWrap.setAttribute("open", "");
        }}

        if (daemonBadge) {{
            if (system.daemon_ok === true) {{
                daemonBadge.textContent = "🟢 Daemon";
                daemonBadge.style.color = "#6ee7b7";
                daemonBadge.style.borderColor = "rgba(110,231,183,0.28)";
                daemonBadge.style.background = "rgba(6,95,70,0.22)";
            }} else if (system.daemon_ok === false) {{
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
            if (system.api_ok === true) {{
                apiBadge.textContent = "🟢 API";
                apiBadge.style.color = "#93c5fd";
                apiBadge.style.borderColor = "rgba(147,197,253,0.28)";
                apiBadge.style.background = "rgba(30,64,175,0.2)";
            }} else if (system.api_ok === false) {{
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
            const beads = system.beads || {{}};
            const parts = ["HEALTH", "WORK", "TODO"].map((name) => {{
                const value = beads[name];
                const prefix = name === "HEALTH" ? "H" : name === "WORK" ? "W" : "T";
                return Number.isFinite(Number(value)) ? `${{prefix}}:${{Number(value)}}` : `${{prefix}}:?`;
            }}).filter(Boolean);
            beadsSummary.textContent = parts.length ? parts.join(" • ") : "H:? • W:? • T:?";
        }}
        if (checkedAt) {{
            const checked = system.checked_at ? String(system.checked_at).slice(11, 16) : "";
            checkedAt.textContent = checked || "--:--";
        }}
    }}

    async function qaCompleteLoopText(text) {{
        const cleaned = String(text || "").trim();
        if (!cleaned) return null;
        const ui = await qaPostWithRetry("/v1/ui/actions/complete", {{ kind: "loop", text: cleaned }}, {{ retries: 1, label: "loop close" }});
        if (ui) return ui;
        return await qaPostWithRetry("/v1/actions/complete", {{ kind: "loop", text: cleaned }}, {{ retries: 1, label: "loop close" }});
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
        const prevText = button ? button.textContent : "";
        if (button) {{
            button.disabled = true;
            button.textContent = "Saving...";
        }}
        const ok = await qaCompleteLoopText(text);
        if (ok && button) {{
            button.disabled = true;
            button.textContent = "Closed";
            const row = button.closest("[data-qa-row='loop']");
            if (row) row.style.opacity = "0.55";
        }} else if (button) {{
            button.disabled = false;
            button.textContent = prevText || "Retry";
        }}
    }}

    async function qaCompleteTodoFromButton(button) {{
        const text = ((button && button.dataset && button.dataset.text) || "").trim();
        if (!text) return;
        const prevText = button ? button.textContent : "";
        if (button) {{
            button.disabled = true;
            button.textContent = "Saving...";
        }}
        const ok = await qaCompleteTodoText(text);
        if (ok && button) {{
            button.disabled = true;
            button.textContent = "☑ Done";
            const row = button.closest("[data-qa-row='todo']");
            if (row) {{
                row.style.opacity = "0.55";
                const taskLine = row.querySelector("p");
                if (taskLine) {{
                    taskLine.style.textDecoration = "line-through";
                    taskLine.style.textDecorationThickness = "1.5px";
                    taskLine.style.textDecorationColor = "rgba(148,163,184,0.85)";
                    taskLine.style.color = "#cbd5e1";
                }}
            }}
        }} else if (button) {{
            button.disabled = false;
            button.textContent = prevText || "Retry";
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

    async function qaRateAnxiety() {{
        const scoreEl = document.getElementById("qa-anxiety-score");
        const score = Number(scoreEl.value || "0");
        const result = await qaPostWithRetry("/v1/ui/interventions/rating", {{ score }}, {{ retries: 1, label: "anxiety score" }});
        if (result) {{
            const status = document.getElementById("qa-status");
            const savedRaw = Number(result && result.score);
            const saved = Number.isFinite(savedRaw) ? savedRaw : score;
            qaApplyAnxietyScore(saved);
            if (status) {{
                status.textContent = `✅ Anxiety relief saved (${{saved}}/10)`;
                status.style.color = "#6ee7b7";
            }}
        }}
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

    function qaMissingWeightsFields(weightsState) {{
        const safe = (weightsState && typeof weightsState === "object") ? weightsState : {{}};
        const missing = [];
        const recovery = String(safe.recovery_gate || "").trim().toLowerCase();
        if (!(recovery === "pass" || recovery === "fail")) missing.push("recovery gate");
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
            missing = qaMissingWeightsFields(weightsState);
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
        try {{
            const result = await qaPostWithRetry("/v1/ui/mood/log", {{
                done: desired,
                date: qaEffectiveDateKey(),
                source: "dashboard_manual",
            }}, {{ retries: 1, label: "mood check-in" }});
            if (result && result.mood_checkin) {{
                qaApplyMoodState(result.mood_checkin);
                if (status) {{
                    status.textContent = desired ? "✅ Mood check-in saved" : "↩️ Mood check-in cleared";
                    status.style.color = desired ? "#6ee7b7" : "#9ca3af";
                }}
            }} else {{
                const verify = await qaVerifyMoodSaved(desired);
                if (verify.ok && verify.state) {{
                    qaApplyMoodState(verify.state);
                }} else {{
                    input.checked = !desired;
                }}
            }}
        }} catch (err) {{
            input.checked = !desired;
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
                if (status) {{
                    status.textContent = data.deduped ? "✅ Mood saved (deduped tap)" : "✅ Mood saved";
                    status.style.color = "#6ee7b7";
                }}
            }} else if (status) {{
                status.textContent = "❌ Mood save failed";
                status.style.color = "#fca5a5";
            }}
        }} catch(err) {{
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
        meta.textContent = `${{done}}/${{total || 0}} core daily check-ins done.`;
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
    qaApplyWorkoutChecklistState(QA_WORKOUT_CHECKLIST_INITIAL);
    qaApplyWorkoutChecklistSignals(QA_WORKOUT_SIGNALS_INITIAL);
    qaApplyWorkoutProgression(QA_WORKOUT_PROGRESSION_INITIAL);
    qaApplyWeightsProgression(QA_WORKOUT_WEIGHTS_PROGRESSION_INITIAL);
    qaApplyEndDayState(QA_END_DAY_INITIAL);
    qaApplyYogaFeedbackPrompt({{ autoOpen: false }});
    qaLoadSyncPauseState();
    qaUpdateSyncPauseUi();
    qaUpdateQuickDoneMeta();
    qaStartLeaderCoordination();
    qaSyncTodayFromApi({{ force: !qaLeaderModeEnabled() || qaIsPollLeader }});
	    </script>
	    '''

    controls_open_attr = " open" if system_needs_attention else ""
    optional_pills_default = bool(system_needs_attention or weekly_needs_generation or qa_yoga_prompt_needed)
    optional_pills_attr = "on" if optional_pills_default else "off"

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
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
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
        .settings-rail {{
            border-radius: 0.7rem;
            border: 1px solid rgba(148,163,184,0.2);
            background: rgba(15,23,42,0.5);
            padding: 0.22rem 0.38rem;
            min-height: 2.05rem;
            scrollbar-width: thin;
            -webkit-overflow-scrolling: touch;
        }}
        /* Keep settings rails stacked for clearer scan order and less visual clash. */
        .quick-nav {{
            display: flex;
            flex-wrap: nowrap;
            align-items: center;
            gap: 0.22rem;
            margin: 0;
            overflow-x: auto;
            white-space: nowrap;
            padding: 0;
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
        .dashboard-controls-wrap[open] > .status-legend-summary .status-caret {{
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
        body[data-compact=\"on\"] .settings-rail {{
            padding: 0.18rem 0.24rem;
            min-height: 1.7rem;
        }}
        body[data-compact=\"on\"] .quick-nav a,
        body[data-compact=\"on\"] .focus-chip,
        body[data-compact=\"on\"] .system-inline,
        body[data-compact=\"on\"] .system-chip {{
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
        </div>
        <div class="rounded-xl px-4 py-2 text-center flex-shrink-0" style="background: rgba(6,95,70,0.2); border: 1px solid rgba(110,231,183,0.15);">
            <p class="font-bold text-2xl" style="color: #6ee7b7">{data.get("sleepCalm", 0)}</p>
            <p class="text-sm" style="color: rgba(110,231,183,0.5)">calm days</p>
        </div>
    </div>

    <section class="settings-stack" aria-label="Dashboard settings">
        <nav class="settings-rail quick-nav" aria-label="Dashboard sections">
            <span class="settings-inline-label">Jump</span>
            <a href="#actions">✅ Actions</a>
            <a href="#morning">🌅 Morning</a>
            <a href="#guidance">💡 Guidance</a>
            <a href="#updates">📝 Updates</a>
            <a href="#evening">🌙 Evening</a>
            <a href="#review">💭 Review</a>
            <a href="#weekly">📅 Weekly</a>
            <a href="#health">🏥 Health</a>
            <a href="#jobs">💼 Jobs</a>
            <a href="#system">🧰 System</a>
        </nav>
        <details id="dashboard-controls-wrap" class="settings-rail dashboard-controls-wrap"{controls_open_attr}>
            <summary class="status-legend-summary"><span class="status-caret">▸</span>⚙️ Controls</summary>
            <div class="focus-controls mt-2" role="group" aria-label="Focus mode controls">
                <span class="focus-label">⏳ Focus</span>
                <div class="focus-chips">
                    <button type="button" class="focus-chip is-active" data-focus-btn="all">🌐 All</button>
                    <button type="button" class="focus-chip" data-focus-btn="morning">🌅 Morning</button>
                    <button type="button" class="focus-chip" data-focus-btn="day">📝 Day</button>
                    <button type="button" class="focus-chip" data-focus-btn="evening">🌙 Evening</button>
                </div>
                <div class="focus-meta">
                    <button type="button" class="focus-chip" id="low-stim-toggle">🧘 Low: Off</button>
                    <button type="button" class="focus-chip" id="compact-toggle">📚 Compact: Off</button>
                </div>
                <p id="focus-mode-note" class="focus-note">All sections visible. Keys: 1-5.</p>
                <p id="focus-meta-note" class="focus-note">Style: Standard • Density: Standard.</p>
            </div>
            <details id="status-legend-wrap" class="status-legend-wrap mt-2">
                <summary class="status-legend-summary"><span class="status-caret">▸</span>🧭 Status markers (optional)</summary>
                <div class="status-legend-items" role="note" aria-label="Status marker legend">
                    <span class="status-chip done">✅ done</span>
                    <span class="status-chip progress">🔄 in progress</span>
                    <span class="status-chip action">⚠️ needs action</span>
                    <span class="status-chip parked">⏭️ parked</span>
                </div>
            </details>
            {system_status_html}
        </details>
    </section>

    <!-- Stale Diarium Warning -->
    <section class="dashboard-section" data-focus="always">
        {stale_notice_html}
        {important_thing_warning_html}
        {ideas_status_html}
    </section>

    <!-- Action Items (TOP — the first thing to see) -->
    <section id="actions" class="dashboard-section phase-day" data-focus="always morning day evening">{action_items_html}</section>

    <!-- Mood selector — always visible, quick tap at any point in the day -->
    <section class="dashboard-section phase-day" data-focus="always morning day evening">{mood_tracking_html}</section>

    <!-- Morning block: entries + AI analysis -->
    <section id="morning" class="dashboard-section phase-morning" data-focus="morning">
    <div class="card mb-4">
        <h3 class="text-lg font-semibold mb-3" style="color: #a7f3d0">🌅 Morning</h3>
        {morning_mood_pill_html}
        {morning_card_html}
    </div>
    {morning_insights_html}
    </section>



    <!-- Updates (throughout-day notes) — still morning/day context -->
    <section id="updates" class="dashboard-section phase-day" data-focus="day">
        {updates_card_html}
        {updates_insights_html}
        {completed_updates_html}
    </section>

    <!-- Guidance: AI daily tips (day/evening) + fallback when no AI data -->
    <section id="guidance" class="dashboard-section phase-day" data-focus="morning day evening">
        {todays_guidance_html}
        {insights_fallback_html}
    </section>



    <!-- Regulation & Support (overwhelm techniques + personalised intervention) -->
    <section class="dashboard-section phase-day" data-focus="morning day evening">
        {support_html}
        {intervention_html}
    </section>

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
    </section>

    <!-- Calendar + Ta-Dah (with wins merged) -->
    <section id="review" class="dashboard-section phase-day" data-focus="day evening">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div class="card">
            <h3 class="text-lg font-semibold mb-4" style="color: #f9a8d4">📅 Today</h3>
            <div class="space-y-2">{calendar_html}</div>
        </div>
        <div class="card">
            <h3 class="text-lg font-semibold mb-4"><a href="{journal_today}" style="color: #6ee7b7">✅ Ta-Dah ({len(tadah_flat)})</a></h3>
            <div class="space-y-1">{tadah_html}</div>
            {yesterday_tadah_html}
            {('<details class="mt-3"><summary class="text-xs cursor-pointer" style="color: #6b7280">Theme breakdown</summary><div class="mt-2">' + tadah_cat_html + '</div></details>') if tadah_cat_html else ''}
        </div>
    </div>
    </section>

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

    <p class="text-center text-sm mt-6" style="color: #4b5563">
        Data from daemon cache • Generated {data.get("time", "")} • Live status sync every 30s (no auto page jump)
    </p>
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
            evening: "Evening"
        }};
        const MODE_BANDS = {{
            morning: "before 12:00",
            day: "12:00-17:59",
            evening: "18:00 onwards"
        }};
        const MODE_SHORTCUTS = "Keys: 1-5.";

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
            return Object.prototype.hasOwnProperty.call(MODES, mode) ? mode : "all";
        }}

        function isVisible(section, mode) {{
            if (mode === "all") return true;
            const tags = String(section.dataset.focus || "").split(/\\s+/).filter(Boolean);
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
                let modeText = `${{MODES[safeMode] || MODES.all}} mode. ${{MODE_SHORTCUTS}}`;
                if (source === "auto" && MODE_BANDS[safeMode]) {{
                    modeText = `Auto: ${{MODES[safeMode]}} (${{MODE_BANDS[safeMode]}}). ${{MODE_SHORTCUTS}}`;
                }} else if (source === "override") {{
                    modeText = `Manual override today: ${{MODES[safeMode]}}. ${{MODE_SHORTCUTS}}`;
                }} else if (source === "url") {{
                    modeText = `URL mode today: ${{MODES[safeMode]}}. ${{MODE_SHORTCUTS}}`;
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

        async function fetchSystemStatus() {{
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
                    return {{
                        checked_at: new Date().toISOString(),
                        daemon_ok: null,
                        api_ok: true,
                        cache_age_minutes: null,
                        beads: {{}},
                    }};
                }}
            }}
            qaSystemStatusFailureCount += 1;
            const degraded = qaSystemStatusFailureCount < 2;
            return {{
                checked_at: new Date().toISOString(),
                daemon_ok: null,
                api_ok: degraded ? null : false,
                cache_age_minutes: null,
                beads: {{}},
            }};
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

        // Keep status/data live, with optional reading-mode pause.
        if (!qaIsLiveSyncPaused()) {{
            pollSystemStatus();
            qaSyncTodayFromApi();
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
                    qaSyncTodayFromApi();
                }} else {{
                    qaUpdateSyncPauseUi();
                }}
            }}, 30000);
        }}, 15000);
        window.setInterval(() => {{
            if (document.hidden) return;
            qaUpdateSyncPauseUi();
        }}, 15000);
        document.addEventListener("visibilitychange", () => {{
            if (!document.hidden && !qaIsLiveSyncPaused() && !dashboardIsBusyForRefresh()) {{
                pollSystemStatus();
                qaSyncTodayFromApi();
            }}
        }});
    }})();
    </script>
    </main>
</body>
</html>'''


def _get_evening_data(diarium):
    """Get evening data from diarium cache. Returns whatever is available."""
    return {
        "three_things": diarium.get("three_things", []),
        "tomorrow": diarium.get("tomorrow", ""),
        "updates": diarium.get("updates", ""),
        "brave": diarium.get("brave", ""),
        "evening_reflections": diarium.get("evening_reflections", ""),
        "remember_tomorrow": diarium.get("remember_tomorrow", ""),
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
    ai_today = get_ai_day(ai_cache, effective_today)
    diarium_source_date = cache.get("diarium_source_date") or cache.get("date", "")
    diarium_fresh_flag = cache.get("diarium_fresh")
    if isinstance(diarium_fresh_flag, bool):
        diarium_fresh = diarium_fresh_flag
    else:
        diarium_fresh = diarium_source_date == effective_today if diarium_source_date else True
    diarium_fresh_reason = cache.get("diarium_fresh_reason", "")
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
        "current_exists": weekly_current_file.exists(),
        "current_path": str(weekly_current_file),
        "current_url": f"file://{weekly_current_file}",
        "latest_path": str(weekly_latest_file) if weekly_latest_file else "",
        "latest_url": f"file://{weekly_latest_file}" if weekly_latest_file else "",
        "latest_name": weekly_latest_file.name if weekly_latest_file else "",
        "needs_generation": bool(iso_weekday >= 6 and not weekly_current_file.exists()),
    }

    mood_log_payload = cache.get("moodLog", {}) if isinstance(cache.get("moodLog", {}), dict) else {}
    mood_log_entries = _sanitize_mood_entries_for_today(
        mood_log_payload.get("entries", []),
        now_dt=now,
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

    morning_mood_tag = str(
        diarium_display.get("mood_tag_morning", "")
        or diarium_display.get("mood_tag", "")
        or _latest_diarium_context_mood("morning")
    ).strip()
    evening_mood_tag = str(
        diarium_display.get("mood_tag_evening", "")
        or _latest_diarium_context_mood("evening")
    ).strip()
    work_strategy = cache.get("work_strategy", {}) if isinstance(cache.get("work_strategy", {}), dict) else {}
    work_focus_label = str(work_strategy.get("focus_label", "Remote £35k+ / local £40k+")).strip() or "Remote £35k+ / local £40k+"

    # Build dashboard data
    data = {
        "date": now.strftime("%d %b %Y"),
        "time": now.strftime("%H:%M"),
        "morning": {
            "grateful": ai_today.get("diarium_interpreted", {}).get("grateful_core") or diarium_display.get("grateful", ""),
            "intent": ai_today.get("diarium_interpreted", {}).get("intent_core") or diarium_display.get("intent", ""),
            "affirmation": ai_today.get("diarium_interpreted", {}).get("affirmation_core") or diarium_display.get("daily_affirmation", ""),
            "emotional_summary": next((e.get("emotional_summary", "") for e in ai_today.get("entries", []) if e.get("source") == "morning"), ""),
            "body_check": diarium_display.get("body_check", ""),
            "letting_go": diarium_display.get("letting_go", ""),
            "mood_tag": morning_mood_tag,
        },
        "evening": {**_get_evening_data(diarium_display), "mood_tag": evening_mood_tag},
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
        "importantThing": str(diarium_display.get("important_thing", "")).strip(),
        "importantThingMissing": bool(diarium_display.get("important_thing_missing", False)) if diarium_fresh else False,
        "healthfitWorkouts": cache.get("healthfit", {}).get("workouts", []) if cache.get("healthfit", {}).get("status") == "success" else [],
        "mindfulness": {},
        "moodTracking": {},
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
        "anxietyCorrelation": anxiety_correlation,
        "weeklyDigest": weekly_digest_payload,
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

    def _coerce_optional_int(value, min_val, max_val):
        try:
            if value is None or value == "":
                return None
            n = int(value)
        except Exception:
            return None
        if n < min_val or n > max_val:
            return None
        return n

    def _coerce_choice(value, allowed):
        raw = str(value or "").strip().lower()
        return raw if raw in allowed else None

    recovery_gate = str(ai_workout_checklist.get("recovery_gate", "unknown")).strip().lower()
    if recovery_gate not in {"pass", "fail", "unknown"}:
        recovery_gate = "unknown"

    data["workoutChecklist"] = {
        "recovery_gate": recovery_gate,
        "calf_done": bool(ai_workout_checklist.get("calf_done", False)),
        "post_workout": {
            "rpe": _coerce_optional_int(ai_workout_post.get("rpe"), 1, 10),
            "pain": _coerce_optional_int(ai_workout_post.get("pain"), 0, 10),
            "energy_after": _coerce_optional_int(ai_workout_post.get("energy_after"), 1, 10),
        },
        "session_feedback": {
            "duration_minutes": _coerce_optional_int(ai_workout_feedback.get("duration_minutes"), 5, 240),
            "intensity": _coerce_choice(ai_workout_feedback.get("intensity"), {"easy", "moderate", "hard"}),
            "session_type": _coerce_choice(ai_workout_feedback.get("session_type"), {"somatic", "yin", "flow", "mobility", "restorative", "other"}),
            "body_feel": _coerce_choice(ai_workout_feedback.get("body_feel"), {"relaxed", "neutral", "tight", "sore", "energised", "fatigued"}),
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
    hrv_latest = _coerce_optional_int(hrv_latest_raw, 1, 200)
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
