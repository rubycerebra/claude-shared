"""Shared daily-report helpers for dashboard + standalone daily report."""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dashboard_day_narrative import (
    collect_day_narrative_lines,
    polish_day_narrative_text,
)

DAEMON_CACHE = Path.home() / ".claude" / "cache" / "session-data.json"
SHARED_ROOT = Path.home() / "Documents" / "Claude Projects" / "claude-shared"
JOURNAL_DIR = SHARED_ROOT / "journal"
DAILY_REPORT_FILE = SHARED_ROOT / "daily-report.html"


def load_cache(cache_path: Path = DAEMON_CACHE) -> dict:
    try:
        return json.loads(cache_path.read_text())
    except Exception:
        return {}


def _read_markdown_section(text: str, header: str) -> str:
    if not text:
        return ""
    match = re.search(rf"(?ms)^##\s+{re.escape(header)}\s*\n(.*?)(?=^##\s+|\Z)", text)
    return match.group(1) if match else ""


def _clean_journal_lines(raw_block: str, *, limit: int = 8, stop_on_tadah: bool = False) -> str:
    if not raw_block:
        return ""
    lines: list[str] = []
    for raw in raw_block.splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        if re.match(r"^\*\[\d{1,2}:\d{2}\s+via dashboard\]\*$", line, re.IGNORECASE):
            continue
        if stop_on_tadah and re.match(r"^\*\*Ta-?Dah list:\*\*$", line, re.IGNORECASE):
            break
        if re.match(r"^\*Auto-generated from Pieces", line, re.IGNORECASE):
            break
        if re.match(r"^###\s+", line):
            continue
        line = re.sub(r"^[\-\*\u2022]+\s*", "", line).strip()
        if not line:
            continue
        lines.append(line)
    if not lines:
        return ""
    return "\n".join(lines[-max(1, int(limit)) :]).strip()


def parse_journal(date_str: str, journal_dir: Path = JOURNAL_DIR) -> dict:
    path = journal_dir / f"{date_str}.md"
    if not path.exists():
        return {}
    try:
        text = path.read_text()
    except Exception:
        return {}
    out: dict[str, Any] = {}
    for field, pattern in [
        ("grateful", r"\*\*Grateful for:\*\*\s*(.+?)(?=\n\*\*|\n##|\Z)"),
        ("intent", r"\*\*Intent:\*\*\s*(.+?)(?=\n\*\*|\n##|\Z)"),
        ("carrying", r"\*\*Carrying forward:\*\*\s*(.+?)(?=\n\*\*|\n##|\Z)"),
    ]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            value = match.group(1).strip()
            if value and value.lower() not in {"", "not specified"}:
                out[field] = value
    match = re.search(r"\*\*Ta-Dah list:\*\*\s*\n((?:\s*-\s+.+\n?)+)", text)
    if match:
        out["ta_dah"] = [item.strip() for item in re.findall(r"-\s+(.+)", match.group(1)) if item.strip()]

    morning_block = _read_markdown_section(text, "Morning")
    notes_block = _read_markdown_section(text, "Notes")
    evening_block = _read_markdown_section(text, "Evening")
    out["morning_note"] = _clean_journal_lines(morning_block, limit=4)
    out["updates_note"] = _clean_journal_lines(notes_block, limit=10)
    out["evening_note"] = _clean_journal_lines(evening_block, limit=6, stop_on_tadah=True)
    return out


def build_daily_report_context(cache: dict, journal: dict, date_str: str) -> dict:
    cache = cache if isinstance(cache, dict) else {}
    journal = journal if isinstance(journal, dict) else {}
    diarium_raw = cache.get("diarium", {}) if isinstance(cache.get("diarium", {}), dict) else {}
    ai_by_date = cache.get("ai_insights", {}).get("by_date", {}) if isinstance(cache.get("ai_insights", {}), dict) else {}
    ai_day = ai_by_date.get(date_str, {}) if isinstance(ai_by_date.get(date_str, {}), dict) else {}
    hf = cache.get("healthfit", {}).get("latest", {}) if isinstance(cache.get("healthfit", {}), dict) else {}
    mood_ml = cache.get("moodLog", {}) if isinstance(cache.get("moodLog", {}), dict) else {}

    diarium_source_date = str(cache.get("diarium_source_date") or cache.get("date") or "").strip()
    diarium_fresh_flag = cache.get("diarium_fresh")
    diarium_same_day = bool(diarium_source_date and diarium_source_date == date_str)
    if isinstance(diarium_fresh_flag, bool):
        diarium_is_current = diarium_fresh_flag and (diarium_same_day or not diarium_source_date)
    else:
        diarium_is_current = diarium_same_day
    diarium = diarium_raw if diarium_is_current else {}

    intent = diarium.get("intent", "") or journal.get("intent", "")
    grateful = diarium.get("grateful", "") or journal.get("grateful", "")
    bullet_re = re.compile(r"^[\u2219\u2022\u00b7\u22c5\u2219\-\*\t\s∙•·\u2705]+")
    raw_tadah = diarium.get("ta_dah", []) or journal.get("ta_dah", [])

    _TADAH_NOISE = {
        "to-dos", "todos", "to dos", "action points", "ta-dah list",
        "other", "notes", "updates", "summary",
    }
    _TADAH_NOISE_PAT = re.compile(r"^ta-?dah\s*\(\d+\s*items?\)", re.IGNORECASE)

    def _parse_tadah_text(raw: object) -> str:
        text = str(raw).strip()
        if text.startswith("{") and "'text'" in text:
            try:
                import ast as _ast
                obj = _ast.literal_eval(text)
                if isinstance(obj, dict) and obj.get("text"):
                    return str(obj["text"]).strip()
            except Exception:
                pass
        return text

    def _is_noise(text: str) -> bool:
        lower = re.sub(r"^[\U00010000-\U0010ffff\u2600-\u27bf\u2700-\u27bf]+\s*", "", text.lower())
        if lower in _TADAH_NOISE or not lower:
            return True
        if _TADAH_NOISE_PAT.match(lower):
            return True
        future_starters = (
            "get ", "do ", "sort ", "check ", "make sure ", "try to ", "need to ",
            "set a ", "write a ", "plan ", "look at ", "start ", "stop ",
            "figure out ", "decide ", "think about ", "remember to ",
            "prepare ", "finish ", "complete ", "tidy ",
        )
        if any(lower.startswith(s) for s in future_starters):
            return True
        routine = {"breakfast", "lunch", "dinner", "coffee", "get ready", "walk dog", "tidy", "relax"}
        if lower in routine:
            return True
        if len(lower.split()) <= 2 and not any(w in lower for w in ("fixed", "done", "finished", "sent", "built", "walked")):
            return True
        return False

    _seen_td: set[str] = set()
    ta_dah: list[str] = []
    for _raw in raw_tadah:
        _t = bullet_re.sub("", _parse_tadah_text(_raw)).strip()
        if not _t or _t.lower() in {"", "list"}:
            continue
        if _is_noise(_t):
            continue
        _k = re.sub(r"[^a-z0-9]+", "", _t.lower())[:60]
        if _k in _seen_td:
            continue
        _seen_td.add(_k)
        ta_dah.append(_t)
    carrying = str(diarium.get("remember_tomorrow", "") or journal.get("carrying", "")).strip()
    updates_note = str(diarium.get("updates", "") or journal.get("updates_note", "")).strip()
    morning_note = str(
        diarium.get("morning_pages", "")
        or diarium.get("morning_reflections", "")
        or journal.get("morning_note", "")
    ).strip()
    evening_note = str(
        diarium.get("evening_reflections", "")
        or diarium.get("how_to_improve", "")
        or journal.get("evening_note", "")
    ).strip()
    three_things = diarium.get("three_things", [])
    if not isinstance(three_things, list):
        three_things = []
    three_things = [str(item).strip() for item in three_things if str(item).strip()]
    tomorrow_plan = re.sub(r'\s+##\s+.*', '', str(diarium.get("tomorrow", "") or ""), flags=re.DOTALL).strip()
    brave_note = str(diarium.get("brave", "") or "").strip()
    summary = str(ai_day.get("latest_summary", "") or "").strip()
    score = ai_day.get("anxiety_reduction_score")
    narrative = polish_day_narrative_text(ai_day.get("day_activity_narrative", ""))
    wc = ai_day.get("workout_checklist", {}) if isinstance(ai_day.get("workout_checklist", {}), dict) else {}
    sf = wc.get("session_feedback", {}) if isinstance(wc.get("session_feedback", {}), dict) else {}
    workout = sf.get("session_type", "") or ""
    workout_dur = sf.get("duration_minutes")
    workout_feel = sf.get("body_feel", "") or ""

    mood_entries = []
    if str(mood_ml.get("date", "")).strip() == date_str:
        mood_entries = [f"{entry.get('label', '?')} at {entry.get('time', '?')}" for entry in mood_ml.get("entries", []) if isinstance(entry, dict)]

    hrv = hf.get("hrv")
    sleep = None
    autosleep = cache.get("autosleep", {}) if isinstance(cache.get("autosleep", {}), dict) else {}
    for row in autosleep.get("daily_metrics", []):
        if isinstance(row, dict) and row.get("date") == date_str:
            sleep = row.get("asleep_hours")
            break
    hf_date_raw = str(hf.get("date", "") or "").strip()
    # HealthFit exports dates as DD/MM/YYYY — normalise to YYYY-MM-DD for comparison
    try:
        from datetime import datetime as _dt
        if "/" in hf_date_raw:
            hf_date_norm = _dt.strptime(hf_date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
        else:
            hf_date_norm = hf_date_raw
    except Exception:
        hf_date_norm = hf_date_raw
    steps = hf.get("steps") if hf_date_norm == date_str else None

    return {
        "date_str": date_str,
        "intent": intent,
        "grateful": grateful,
        "ta_dah": ta_dah,
        "carrying": carrying,
        "summary": summary,
        "score": score,
        "mood_entries": mood_entries,
        "hrv": hrv,
        "sleep": sleep,
        "steps": steps,
        "narrative": narrative,
        "workout": workout,
        "workout_dur": workout_dur,
        "workout_feel": workout_feel,
        "morning_note": morning_note,
        "updates_note": updates_note,
        "evening_note": evening_note,
        "three_things": three_things,
        "tomorrow_plan": tomorrow_plan,
        "brave_note": brave_note,
        "cache_timestamp": str(cache.get("timestamp", "") or "").strip(),
        "diarium_source_date": diarium_source_date,
        "diarium_current": diarium_is_current,
    }


def _sentence_safe_clip(raw_text: str, max_len: int = 340) -> str:
    text = re.sub(r"\s+", " ", str(raw_text or "")).strip()
    if not text or len(text) <= max_len:
        return text
    cut = max(text.rfind(". ", 0, max_len), text.rfind("! ", 0, max_len), text.rfind("? ", 0, max_len))
    if cut >= int(max_len * 0.6):
        return text[: cut + 1].strip()
    return text[:max_len].rstrip(" ,;:-") + "…"




def _compose_sentence(prefix: str, lines: list[str], *, max_len: int = 420) -> str:
    cleaned = [re.sub(r"[.!?]+$", "", str(line or "").strip()) for line in lines if str(line or "").strip()]
    cleaned = [line for line in cleaned if line]
    if not cleaned:
        return ""
    return _sentence_safe_clip(f"{prefix}: {'; '.join(cleaned)}.", max_len=max_len)


def compose_today_fallback(ctx: dict, *, now_hour: int | None = None, unlock_hour: int = 13) -> str:
    ctx = ctx if isinstance(ctx, dict) else {}
    lines: list[str] = []
    updates = str(ctx.get("updates_note", "") or "").strip()
    evening = str(ctx.get("evening_note", "") or "").strip()
    ta_dah = ctx.get("ta_dah", []) if isinstance(ctx.get("ta_dah", []), list) else []
    three_things = ctx.get("three_things", []) if isinstance(ctx.get("three_things", []), list) else []
    summary = str(ctx.get("summary", "") or "").strip()
    narrative = polish_day_narrative_text(ctx.get("narrative", ""))
    hour = datetime.now().hour if now_hour is None else int(now_hour)
    midday_unlocked = hour >= unlock_hour

    if midday_unlocked:
        day_chunks: list[str] = []
        updates_bits = collect_day_narrative_lines([updates], max_items=3, split_sentences=True)
        if updates_bits:
            sentence = _compose_sentence("Day updates", updates_bits, max_len=520)
            if sentence:
                day_chunks.append(sentence)

        done_bits = collect_day_narrative_lines([str(item) for item in ta_dah], max_items=4, split_sentences=False)
        if done_bits:
            sentence = _compose_sentence("Completed", done_bits[:3], max_len=420)
            if sentence:
                day_chunks.append(sentence)
        if day_chunks:
            lines.append(" ".join(day_chunks))

    evening_sources: list[Any] = [evening]
    if three_things:
        evening_sources.extend(three_things[:3])
    evening_bits = collect_day_narrative_lines(evening_sources, max_items=3, split_sentences=True)
    if evening_bits:
        sentence = _compose_sentence("Evening reflection", evening_bits, max_len=460)
        if sentence:
            lines.append(sentence)

    if summary:
        tone_line = _compose_sentence("Tone check", [summary], max_len=260)
        if tone_line:
            lines.append(tone_line)

    fallback = "\n\n".join(line for line in lines if line).strip()
    if fallback:
        return fallback
    if narrative:
        return narrative
    return "No AI narrative available yet."


def compose_tomorrow_fallback(ctx: dict, *, now_hour: int | None = None, unlock_hour: int = 18) -> str:
    ctx = ctx if isinstance(ctx, dict) else {}
    tomorrow = str(ctx.get("tomorrow_plan", "") or "").strip()
    carrying = str(ctx.get("carrying", "") or "").strip()
    sleep = ctx.get("sleep")
    hrv = ctx.get("hrv")
    hour = datetime.now().hour if now_hour is None else int(now_hour)

    energy_bits: list[str] = []
    if isinstance(sleep, (int, float)):
        energy_bits.append(f"sleep {sleep:.1f}h")
    if isinstance(hrv, (int, float)):
        energy_bits.append(f"HRV {int(hrv)}")

    if tomorrow:
        suffix = f" Keep it realistic and paced ({', '.join(energy_bits)})." if energy_bits else " Keep it realistic and paced."
        _tomorrow_clean = re.sub(r'\s+', ' ', tomorrow).rstrip(' ,;:-')
        return f"Tomorrow, focus on: {_tomorrow_clean}.{suffix}"
    if carrying:
        _carrying_clean = re.sub(r'\s+', ' ', carrying).rstrip(' ,;:-')
        return f"Tomorrow, pick up: {_carrying_clean}. Start with one clear first step."
    if hour < unlock_hour:
        return ""
    if energy_bits:
        return f"Tomorrow, keep the plan light and specific. Use {', '.join(energy_bits)} as a pacing check and start with one meaningful task."
    return "Tomorrow, keep the plan light and specific: one meaningful task first, then reassess your energy."


def parse_saved_report_html(path: Path = DAILY_REPORT_FILE) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    def _attr(name: str) -> str:
        match = re.search(rf'data-{re.escape(name)}="([^"]*)"', text)
        return match.group(1).strip() if match else ""

    section_map: dict[str, str] = {}
    for match in re.finditer(
        r'<div class="card[^"]*">\s*<h2[^>]*>(.*?)</h2>\s*<div class="prose">(.*?)</div>\s*</div>',
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        heading_raw = re.sub(r"<[^>]+>", "", match.group(1))
        heading = html_lib.unescape(re.sub(r"\s+", " ", heading_raw).strip())
        blocks = re.findall(r'<div class="prose-block[^>]*>(.*?)</div>', match.group(2), re.IGNORECASE | re.DOTALL)
        rows = []
        for block in blocks:
            cleaned = re.sub(r"<[^>]+>", "", block)
            cleaned = html_lib.unescape(re.sub(r"\s+", " ", cleaned).strip())
            if cleaned:
                rows.append(cleaned)
        if not rows:
            cleaned = re.sub(r"<[^>]+>", "", match.group(2))
            cleaned = html_lib.unescape(re.sub(r"\s+", " ", cleaned).strip())
            if cleaned:
                rows.append(cleaned)
        if heading and rows:
            section_map[heading] = "\n\n".join(rows).strip()

    return {
        "date": _attr("date"),
        "cache_timestamp": _attr("cache-timestamp"),
        "generated_at": _attr("generated-at"),
        "today_story": section_map.get("📖 Today's Story", ""),
        "tomorrow_text": section_map.get("🌅 Tomorrow", ""),
        "path": str(path),
    }


def _parse_iso(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def report_lag_minutes(report: dict, cache_timestamp: str) -> int | None:
    report_cache = _parse_iso(str((report or {}).get("cache_timestamp", "")))
    cache_dt = _parse_iso(cache_timestamp)
    if report_cache is None or cache_dt is None:
        return None
    return max(0, int(round((cache_dt - report_cache).total_seconds() / 60)))


def report_is_evening_ready(report: dict, *, expected_date: str, cache_timestamp: str, unlock_hour: int = 18, max_lag_minutes: int = 45) -> bool:
    report = report if isinstance(report, dict) else {}
    if str(report.get("date", "")).strip() != str(expected_date or "").strip():
        return False
    if not str(report.get("today_story", "")).strip():
        return False
    generated = _parse_iso(str(report.get("generated_at", "")))
    if generated is None or generated.hour < unlock_hour:
        return False
    lag = report_lag_minutes(report, cache_timestamp)
    if lag is not None and lag > max_lag_minutes:
        return False
    return True
