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


_AI_PROMPT_ARTIFACTS = (
    "ready to help",
    "please provide",
    "transcription error",
    "british english",
    "journal text",
    "you'd like me to fix",
    "you'd like me to",
    "i'm here to help",
    "how can i assist",
    "i can help you",
    "as an ai",
    "as a language model",
)


def is_ai_prompt_artifact(text: str) -> bool:
    """Return True if text looks like a leaked Claude system/prompt response."""
    low = str(text or "").lower().strip()
    return any(frag in low for frag in _AI_PROMPT_ARTIFACTS)


def is_noise_day_narrative_line(line: str) -> bool:
    low = str(line or "").strip().lower()
    if not low:
        return True
    if is_ai_prompt_artifact(low):
        return True
    if re.search(r"test[-_ ]?(?:item|entry|does|abc|stub|dummy)|doesnotexist|abc123|~{2,}", low):
        return True
    if re.search(r"\[[a-f0-9]{6,}\]$", low):
        return True
    if re.search(r"internalised\s+\d+\s+item\(s\)", low):
        return True
    if re.search(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[—-]\s*internalised", low):
        return True
    if re.search(r"here is your full formatted entry|ready to paste into diarium|formatted entry ready to paste", low):
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


def polish_day_narrative_text(narrative: str) -> str:
    text = str(narrative or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*#{1,6}\s+[^\n]+\n*", "", text, flags=re.MULTILINE).strip()

    raw_paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not raw_paras:
        raw_paras = [text]

    polished = []
    for para in raw_paras:
        line = str(para).strip()
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r";\s+", ", ", line)
        line = re.sub(r"\bDuring the day, you noticed that you\b", "During the day, you noticed you", line, flags=re.IGNORECASE)
        line = re.sub(r"\bYou also noticed that you\b", "You also noticed you", line, flags=re.IGNORECASE)
        line = re.sub(r"\bAlongside that,\b", "Along the way,", line, flags=re.IGNORECASE)
        line = re.sub(r"\bOn the laptop side,\b", "On the work side,", line, flags=re.IGNORECASE)
        line = re.sub(r"\bYou moved through the day by\b", "You spent part of the day", line, flags=re.IGNORECASE)
        line = re.sub(
            r"(which can happen with autism masking) but you still felt",
            r"\1. Even so, you felt",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(r"\s+", " ", line).strip()
        if line and line[-1] not in ".!?":
            line += "."
        polished.append(line)

    return "\n\n".join(polished).strip()


def split_day_narrative_paragraphs(narrative: str) -> list[str]:
    polished = polish_day_narrative_text(str(narrative or ""))
    parts = [p.strip() for p in re.split(r"\n\n+|\n(?=[A-Z])", polished) if p.strip()]
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
    # Narrative freshness metadata is the canonical contract for the cached
    # day narrative itself. Do not let later unrelated same-day AI entries
    # (for example daemon_evening / tomorrow suggestions) outvote it and mark
    # the narrative stale when the narrative cache explicitly says it is fresh.
    if meta_source_max_ts > 0:
        latest_source_iso = meta_source_max_iso
        latest_source_ts = meta_source_max_ts
    else:
        latest_source_iso = source_max_iso
        latest_source_ts = source_max_ts
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
        narrative = polish_day_narrative_text(clean_cached or cached)
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

    def _normalise_clause(bit: str) -> str:
        text = re.sub(r"\s+", " ", str(bit or "")).strip(" \t\r\n;:,.")
        if not text:
            return ""
        # Remove leading connectors that read awkwardly mid-sentence.
        text = re.sub(r"^(?:because|and|but)\s+", "", text, flags=re.IGNORECASE)
        # Normalize perspective so fallback narrative stays in second person.
        text = re.sub(r"\bI['’]m\b", "you're", text, flags=re.IGNORECASE)
        text = re.sub(r"\bI['’]ve\b", "you've", text, flags=re.IGNORECASE)
        text = re.sub(r"\bI am\b", "you are", text, flags=re.IGNORECASE)
        text = re.sub(r"\bI was\b", "you were", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmy\b", "your", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmyself\b", "yourself", text, flags=re.IGNORECASE)
        text = re.sub(r"\bme\b", "you", text, flags=re.IGNORECASE)
        text = re.sub(r"\bI\b", "you", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*they bring you joy", "supporting them brings you joy", text, flags=re.IGNORECASE)
        if re.fullmatch(r"your girls", text, flags=re.IGNORECASE):
            text = "supporting your girls"

        imperative_starts = (
            ("turn up ", "turning up "),
            ("be ", "being "),
            ("get ", "getting "),
        )
        lowered = text.lower()
        for start, replacement in imperative_starts:
            if lowered.startswith(start):
                text = replacement + text[len(start):]
                lowered = text.lower()
                break

        if re.match(r"^(went|felt|thought|noticed|managed|fixed|built|completed|deferred|showered|tidied|made|added)\b", text, flags=re.IGNORECASE):
            text = f"you {text[0].lower()}{text[1:]}"
        text = re.sub(r",\s*be\s+", ", being ", text, flags=re.IGNORECASE)
        text = re.sub(r"\band\s+show\b", "and showing", text, flags=re.IGNORECASE)
        text = re.sub(r"\band\s+tidy\b", "and tidying", text, flags=re.IGNORECASE)
        text = re.sub(r"\bself conscious\b", "self-conscious", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbut that comes with\b", "which can come with", text, flags=re.IGNORECASE)
        text = re.sub(r"\byou felt pretty self-conscious talking too much\b", "you felt self-conscious about talking too much", text, flags=re.IGNORECASE)
        text = re.sub(r"being overly confident which can come with autism masking", "worrying about sounding overly confident, which can happen with autism masking", text, flags=re.IGNORECASE)
        text = re.sub(r"and you don['’]t think you did a bad job", "but you still felt you handled it well", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" ;:,.")
        if not text:
            return ""
        return text

    def _narrative_join(bits):
        def _token_signature(value: str) -> set[str]:
            return {
                token
                for token in re.findall(r"[a-z0-9']+", str(value or "").lower())
                if len(token) > 2
            }

        clean_bits = []
        seen_keys = set()
        seen_token_sets = []
        for bit in bits:
            clean = _normalise_clause(str(bit or ""))
            if not clean:
                continue
            key = day_narrative_line_key(clean)
            if not key or key in seen_keys:
                continue
            token_set = _token_signature(clean)
            if token_set:
                is_near_duplicate = False
                for prior in seen_token_sets:
                    overlap = len(token_set & prior) / max(1, min(len(token_set), len(prior)))
                    if overlap >= 0.62:
                        is_near_duplicate = True
                        break
                if is_near_duplicate:
                    continue
            seen_keys.add(key)
            clean_bits.append(clean)
            if token_set:
                seen_token_sets.append(token_set)
        if not clean_bits:
            return ""
        if len(clean_bits) == 1:
            return clean_bits[0]
        if len(clean_bits) == 2:
            if clean_bits[1].lower().startswith("supporting your girls"):
                return f"{clean_bits[0]}, while {clean_bits[1]}"
            return f"{clean_bits[0]}, and {clean_bits[1]}"
        return f"{clean_bits[0]}, {clean_bits[1]}, and {clean_bits[2]}"

    def _narrative_sentence(starter, bits, max_len, *, use_colon=True):
        body = _narrative_join(bits)
        if not body:
            return ""
        if use_colon:
            sentence = f"{starter}: {body}".strip()
        else:
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
        max_items=2,
        split_sentences=True,
    )
    morning_sentence = _narrative_sentence(
        "You opened the day focused on",
        morning_bits,
        max_len=520,
        use_colon=False,
    )
    if morning_sentence:
        parts.append(morning_sentence)

    updates_lines = collect_day_narrative_lines([updates_text], max_items=2, split_sentences=True)
    updates_lines = [line for line in updates_lines if not is_updates_verification_noise_text(line)]
    def _is_system_navigation_noise(text: str) -> bool:
        """Filter Pieces/IDE/system activity that isn't a real personal accomplishment."""
        low = str(text or "").strip().lower()
        noise_phrases = [
            "find settings", "integrations menu", "locate tadah",
            "sync or export option", "open settings", "navigate to",
            "click on", "select the", "go to settings", "check the menu",
            "look for the", "search for the", "open the dashboard",
            "refresh the page", "close the tab", "scroll to",
            "sign in", "log in", "open claude app", "open the app",
            "open app on phone", "install the", "download the",
        ]
        # Developer/system activity keywords — these are Pieces session summaries, not personal wins
        dev_keywords = [
            "bug fix", "bug in", "resolved a", "implemented a", "refactor",
            "dashboard", "daemon", "hookmark", "axidentifier",
            "polling loop", "cache", "stale flag", "api endpoint",
            "script", "debug", "integration bug", "integration error",
            "deduplication", "code review", "pull request", "commit",
            "merge", "session summary", "focused laptop session",
            "ui color", "ui layout", "ux improvement", "apple notes integration",
            "calendar integration", "todoist integration",
            "fixing the", "improving the", "updating the",
            "layout across", "sections", "time parsing",
            "token", "css", "html", "python", "json",
        ]
        if any(phrase in low for phrase in noise_phrases):
            return True
        if any(phrase in low for phrase in dev_keywords):
            return True
        # Short imperative phrases that are UI actions
        if len(low) < 40 and re.match(r"^(open|close|find|locate|check|click|tap|scroll|browse|navigate)\b", low):
            return True
        # Pieces-style session summaries with markdown formatting artifacts
        if "**" in text or "`" in text:
            return True
        return False

    done_source = [item for item in tadah_flat if not looks_like_test_noise(item) and not _is_system_navigation_noise(item)]
    done_lines = collect_day_narrative_lines(done_source, max_items=4, split_sentences=False)

    def _as_progress_fragment(raw_line: str) -> str:
        fragment = _normalise_clause(raw_line)
        fragment = re.sub(r"^you\s+", "", fragment, flags=re.IGNORECASE).strip()
        fragment = re.sub(r"^added\b", "adding", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^improved\b", "improving", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^made\b", "making", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^fixed\b", "fixing", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^built\b", "building", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^completed\b", "completing", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^got\b", "getting", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^get\b", "getting", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^tidied\b", "tidying", fragment, flags=re.IGNORECASE)
        return fragment[:1].lower() + fragment[1:] if fragment else ""

    def _as_observation_fragment(raw_line: str) -> str:
        fragment = _normalise_clause(raw_line)
        fragment = str(fragment or "").strip()
        if not fragment:
            return ""
        if re.match(r"^you\b", fragment, flags=re.IGNORECASE):
            return fragment[:1].lower() + fragment[1:]
        if re.match(r"^(went|felt|thought|noticed|managed|fixed|built|completed|deferred|showered|tidied|made|added|improved)\b", fragment, flags=re.IGNORECASE):
            return f"you {fragment[0].lower()}{fragment[1:]}"
        return fragment[:1].lower() + fragment[1:]

    day_observation = ""
    if updates_lines:
        update_fragments = [_as_observation_fragment(item) for item in updates_lines[:2]]
        update_fragments = [item for item in update_fragments if item]
        if update_fragments:
            if len(update_fragments) == 1:
                day_observation = truncate_sentence_safe(
                    f"During the day, you noticed that {update_fragments[0]}.",
                    max_len=560,
                )
            else:
                day_observation = truncate_sentence_safe(
                    f"During the day, you noticed that {update_fragments[0]}. You also noticed that {update_fragments[1]}.",
                    max_len=620,
                )
    if day_observation:
        parts.append(day_observation)

    day_activity_sentences = []
    if done_lines:
        done_fragments = [_as_progress_fragment(item) for item in done_lines[:2]]
        done_fragments = [item for item in done_fragments if item]
        line = _narrative_sentence(
            "Alongside that, you moved a few things forward",
            done_fragments,
            max_len=480,
            use_colon=True,
        )
        if line:
            day_activity_sentences.append(line)

    walk = any("walk" in str(t).lower() or "coco" in str(t).lower() for t in tadah_flat)
    if steps_val > 10000:
        day_activity_sentences.append(f"You kept moving, with {steps_val:,} steps logged.")
    elif steps_val > 5000 or walk:
        day_activity_sentences.append("You kept moving and got out for a walk.")

    if session_type and str(session_type).lower() not in ("none", ""):
        workout_label = str(session_type).replace("_", " ").lower()
        dur = f" for {session_dur} minutes" if session_dur else ""
        day_activity_sentences.append(f"You logged a {workout_label} workout session{dur}.")

    if day_activity_sentences:
        parts.append(" ".join(str(s).strip() for s in day_activity_sentences if str(s).strip()))

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
        parts.append(f"You also put in {pieces_count} focused laptop session{'s' if pieces_count != 1 else ''}.")

    fallback_text = "\n\n".join([p.strip() for p in parts if str(p).strip()]) if parts else ""
    fallback_text = polish_day_narrative_text(fallback_text)
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
