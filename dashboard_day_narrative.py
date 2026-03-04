"""Helpers for building and rendering the day narrative section."""

from __future__ import annotations

import re
from typing import Callable, Iterable


def clean_day_narrative_line(raw: str) -> str:
    line = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not line:
        return ""
    if re.match(r"^\*\[\d{1,2}:\d{2}\s+via dashboard\]\*$", line, re.IGNORECASE):
        return ""
    line = re.sub(r"^[\-\*\u2022]+\s*", "", line).strip()
    line = re.sub(r"^\*\*Ta-?Dah list:\*\*$", "", line, flags=re.IGNORECASE).strip()
    line = re.sub(r"^\*Auto-generated from Pieces.*$", "", line, flags=re.IGNORECASE).strip()
    return line


def is_noise_day_narrative_line(line: str) -> bool:
    low = str(line or "").strip().lower()
    if not low:
        return True
    if re.search(r"test[-_ ]?(?:item|entry|does|abc|stub|dummy)|doesnotexist|abc123|~{2,}", low):
        return True
    if re.search(r"\[[a-f0-9]{6,}\]$", low):
        return True
    if re.search(r"internalised\s+\d+\s+item\(s\)", low):
        return True
    if re.search(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[—-]\s*internalised", low):
        return True
    return False


def day_narrative_line_key(line: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(line or "").lower()).strip()


def collect_day_narrative_lines(
    values: Iterable[str],
    *,
    max_items: int = 3,
    split_sentences: bool = False,
) -> list[str]:
    seen = set()
    rows = []
    for value in values:
        chunks = (
            re.split(r"(?<=[.!?])\s+|\n+", str(value or ""))
            if split_sentences
            else str(value or "").splitlines()
        )
        for raw_chunk in chunks:
            line = clean_day_narrative_line(raw_chunk)
            if not line or len(line) < 4 or is_noise_day_narrative_line(line):
                continue
            key = day_narrative_line_key(line)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(line.rstrip("."))
            if len(rows) >= max_items:
                return rows
    return rows


def compose_day_narrative_sentence(
    prefix: str,
    values: list[str],
    *,
    truncate_fn: Callable[[str], str],
    max_len: int = 430,
) -> str:
    if not values:
        return ""
    text = f"{prefix}: {'; '.join(values)}."
    return truncate_fn(text, max_len=max_len)


def split_day_narrative_paragraphs(narrative: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\n+|\n(?=[A-Z])", str(narrative or "")) if p.strip()]
    return parts if parts else ([str(narrative or "").strip()] if str(narrative or "").strip() else [])


def evaluate_cached_narrative(
    today_ai: dict,
    *,
    effective_today_key: str,
    current_hour: int,
    iso_to_ts: Callable[[str], float],
    clock_hhmm: Callable[[str], str],
    contradiction_reason_fn: Callable[[str], str],
) -> tuple[str, dict]:
    cached = str((today_ai or {}).get("day_activity_narrative", "") or "").strip() if isinstance(today_ai, dict) else ""
    if not cached:
        return "", {
            "status": "missing",
            "level": "info",
            "line": "ℹ️ Waiting for AI day narrative.",
        }

    entries = (today_ai or {}).get("entries", []) if isinstance((today_ai or {}).get("entries", []), list) else []
    source_max_iso = ""
    source_max_ts = 0.0
    source_includes_today = False
    morning_generated_iso = ""
    morning_generated_ts = 0.0
    for row in entries:
        if not isinstance(row, dict):
            continue
        row_date = str(row.get("date", "")).strip()
        if row_date == effective_today_key:
            source_includes_today = True
        row_generated = str(row.get("generated_at", "")).strip()
        row_ts = iso_to_ts(row_generated)
        if row_ts > source_max_ts:
            source_max_ts = row_ts
            source_max_iso = row_generated
        if str(row.get("source", "")).strip() == "morning" and row_ts > morning_generated_ts:
            morning_generated_ts = row_ts
            morning_generated_iso = row_generated

    meta = (today_ai or {}).get("narrative_meta", {}) if isinstance((today_ai or {}).get("narrative_meta"), dict) else {}
    meta_source_date = str(meta.get("source_date", "")).strip()
    meta_generated_iso = str(meta.get("generated_at", "")).strip()
    meta_source_max_iso = str(meta.get("source_max_ts", "")).strip()
    meta_source_includes_today = meta.get("source_includes_today")
    generated_iso = meta_generated_iso or morning_generated_iso
    generated_ts = iso_to_ts(generated_iso)
    meta_source_max_ts = iso_to_ts(meta_source_max_iso)
    if source_max_ts >= meta_source_max_ts:
        latest_source_iso = source_max_iso
        latest_source_ts = source_max_ts
    else:
        latest_source_iso = meta_source_max_iso
        latest_source_ts = meta_source_max_ts
    if isinstance(meta_source_includes_today, bool):
        source_includes_today = bool(meta_source_includes_today)

    reasons = []
    if meta_source_date and meta_source_date != effective_today_key:
        reasons.append(f"source date {meta_source_date} ≠ {effective_today_key}")
    if not source_includes_today:
        reasons.append("same-day sources missing")
    if generated_ts <= 0:
        reasons.append("generated_at missing")
    if latest_source_ts > 0 and generated_ts > 0 and generated_ts < latest_source_ts:
        reasons.append("older than latest same-day source")

    if not reasons:
        clean_cached = re.sub(r"^\s*#{1,6}\s+[^\n]+\n*", "", cached, count=1).strip()
        narrative = clean_cached or cached
        contradiction = contradiction_reason_fn(narrative)
        if contradiction:
            return "", {
                "status": "stale",
                "level": "warn",
                "line": f"⚠️ Cached day narrative invalid ({contradiction}); fallback active.",
                "generated_at": generated_iso,
                "source_max_ts": latest_source_iso,
            }
        if narrative:
            when = clock_hhmm(generated_iso)
            line = "✅ What you did today is fresh."
            if when:
                line = f"✅ What you did today is fresh ({when})."
            return narrative, {
                "status": "fresh",
                "level": "ok",
                "line": line,
                "generated_at": generated_iso,
                "source_max_ts": latest_source_iso,
            }

    if reasons == ["older than latest same-day source"] and current_hour < 18:
        return "", {
            "status": "pending_refresh",
            "level": "info",
            "line": "🟡 Cached day narrative waiting for refresh after recent updates.",
            "generated_at": generated_iso,
            "source_max_ts": latest_source_iso,
        }

    reason_text = reasons[0] if reasons else "cache mismatch"
    return "", {
        "status": "stale",
        "level": "warn",
        "line": f"⚠️ Cached day narrative stale ({reason_text}); fallback active.",
        "generated_at": generated_iso,
        "source_max_ts": latest_source_iso,
    }


def compose_day_narrative(
    *,
    today_ai: dict,
    data: dict,
    updates_text: str,
    tadah_flat: list,
    steps_val: int,
    session_type: str,
    session_dur,
    pieces_count: int,
    current_hour: int,
    effective_today_key: str,
    iso_to_ts: Callable[[str], float],
    clock_hhmm: Callable[[str], str],
    truncate_sentence_safe: Callable[[str], str],
    contradiction_reason_fn: Callable[[str], str],
    is_updates_verification_noise_text: Callable[[str], bool],
    looks_like_test_noise: Callable[[str], bool],
) -> tuple[str, dict]:
    cached_narrative, cached_state = evaluate_cached_narrative(
        today_ai,
        effective_today_key=effective_today_key,
        current_hour=current_hour,
        iso_to_ts=iso_to_ts,
        clock_hhmm=clock_hhmm,
        contradiction_reason_fn=contradiction_reason_fn,
    )
    if cached_narrative:
        return cached_narrative, cached_state

    parts = []
    morning_data = data.get("morning", {}) if isinstance(data.get("morning"), dict) else {}
    evening_data = data.get("evening", {}) if isinstance(data.get("evening"), dict) else {}

    def _narrative_join(bits):
        clean_bits = []
        for bit in bits:
            clean = str(bit or "").strip().rstrip(" .")
            if clean:
                clean_bits.append(clean)
        if not clean_bits:
            return ""
        if len(clean_bits) == 1:
            return clean_bits[0]
        if len(clean_bits) == 2:
            return f"{clean_bits[0]} and {clean_bits[1]}"
        return f"{clean_bits[0]}, {clean_bits[1]}, and {clean_bits[2]}"

    def _narrative_sentence(starter, bits, max_len):
        body = _narrative_join(bits)
        if not body:
            return ""
        sentence = f"{starter} {body}".strip()
        if sentence and sentence[-1] not in ".!?":
            sentence += "."
        return truncate_sentence_safe(sentence, max_len=max_len)

    morning_bits = collect_day_narrative_lines(
        [
            morning_data.get("intent", ""),
            morning_data.get("important_thing", ""),
            morning_data.get("grateful", ""),
            morning_data.get("affirmation", ""),
            morning_data.get("body_check", ""),
            morning_data.get("morning_pages", ""),
            morning_data.get("morning_reflections", ""),
        ],
        max_items=3,
        split_sentences=True,
    )
    morning_sentence = _narrative_sentence("You started the day focusing on", morning_bits, max_len=520)
    if morning_sentence:
        parts.append(morning_sentence)

    updates_lines = collect_day_narrative_lines([updates_text], max_items=3, split_sentences=True)
    updates_lines = [line for line in updates_lines if not is_updates_verification_noise_text(line)]
    done_source = [item for item in tadah_flat if not looks_like_test_noise(item)]
    done_lines = collect_day_narrative_lines(done_source, max_items=4, split_sentences=False)
    day_sentences = []
    if updates_lines:
        line = _narrative_sentence("During the day, you noted", updates_lines, max_len=560)
        if line:
            day_sentences.append(line)
    if done_lines:
        line = _narrative_sentence("You also got through", done_lines[:3], max_len=480)
        if line:
            day_sentences.append(line)

    walk = any("walk" in str(t).lower() or "coco" in str(t).lower() for t in tadah_flat)
    if steps_val > 10000:
        day_sentences.append(f"You kept moving with {steps_val:,} steps logged.")
    elif steps_val > 5000 or walk:
        day_sentences.append("You kept moving and got out for a walk.")

    if session_type and str(session_type).lower() not in ("none", ""):
        workout_label = str(session_type).replace("_", " ").lower()
        dur = f" for {session_dur} minutes" if session_dur else ""
        day_sentences.append(f"You logged a {workout_label} workout session{dur}.")

    if day_sentences:
        parts.append(" ".join(truncate_sentence_safe(str(s), max_len=380) for s in day_sentences if str(s).strip()))

    evening_values = []
    three = evening_data.get("three_things", [])
    if isinstance(three, list):
        evening_values.extend(three)
    evening_values.extend(
        [
            evening_data.get("brave", ""),
            evening_data.get("evening_reflections", ""),
            evening_data.get("remember_tomorrow", ""),
            evening_data.get("tomorrow", ""),
        ]
    )
    evening_bits = collect_day_narrative_lines(evening_values, max_items=3, split_sentences=True)
    evening_sentence = _narrative_sentence("By evening, you captured", evening_bits, max_len=520)
    if evening_sentence:
        parts.append(evening_sentence)

    if pieces_count > 0:
        parts.append(f"On the laptop side, you logged {pieces_count} dev session{'s' if pieces_count != 1 else ''}.")

    fallback_text = "\n\n".join([p.strip() for p in parts if str(p).strip()]) if parts else ""
    if fallback_text:
        if cached_state.get("status") == "stale":
            return fallback_text, {
                **cached_state,
                "status": "fallback",
                "level": "warn",
                "line": str(cached_state.get("line", "")).strip() or "⚠️ Cached day narrative stale; fallback active.",
            }
        return fallback_text, {
            "status": "fallback",
            "level": "info",
            "line": "🟡 Using structured fallback narrative until AI rewrite lands.",
        }
    return "", cached_state
