"""Heuristics for watchlist suggestions inside the dashboard film card."""

from __future__ import annotations

import re
from datetime import datetime


GENTLE_TITLE_TOKENS = {
    "heart", "home", "love", "faith", "garden", "spring", "summer", "autumn",
    "winter", "quiet", "soft", "song", "moon", "star", "day", "night", "light",
}
CURIOUS_TITLE_TOKENS = {
    "mystery", "secret", "strange", "weird", "phantom", "dream", "ghost", "fairy",
    "mirror", "unknown", "night", "moves", "country", "project", "planet", "space",
}
INTENSE_TITLE_TOKENS = {
    "revenge", "kill", "killer", "blood", "war", "attack", "hunt", "dark", "hell",
    "silent", "storm", "terror", "dead", "crime", "violent", "wrath", "rage",
}

LOW_ENERGY_MARKERS = (
    "tired", "resigned", "stressed", "stress", "scam", "achy", "ache", "sore",
    "sensitive", "cramp", "victim", "hospital", "overdo", "limitations", "let go",
)
HIGH_ENERGY_MARKERS = (
    "ready", "fresh", "focused", "momentum", "energ", "excited", "curious", "interested",
)


def _tokenise(raw_text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", str(raw_text or "").lower()) if token}


def _safe_year(raw_value) -> int | None:
    try:
        year = int(str(raw_value).strip())
    except Exception:
        return None
    if 1888 <= year <= 2100:
        return year
    return None


def _collect_context_text(data: dict) -> str:
    day_state = data.get("day_state_summary", {}) if isinstance(data.get("day_state_summary", {}), dict) else {}
    morning = data.get("morning", {}) if isinstance(data.get("morning", {}), dict) else {}
    evening = data.get("evening", {}) if isinstance(data.get("evening", {}), dict) else {}
    parts = [
        str(morning.get("mood_tag", "")).strip(),
        str(evening.get("mood_tag", "")).strip(),
        str(morning.get("body_check", "")).strip(),
        str(data.get("importantThing", "")).strip(),
        " ".join(str(line).strip() for line in day_state.get("morning", []) if str(line).strip()),
        " ".join(str(line).strip() for line in day_state.get("day", []) if str(line).strip()),
        " ".join(str(line).strip() for line in day_state.get("evening", []) if str(line).strip()),
    ]
    return " ".join(part for part in parts if part)


def derive_viewing_profile(data: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    morning = data.get("morning", {}) if isinstance(data.get("morning", {}), dict) else {}
    evening = data.get("evening", {}) if isinstance(data.get("evening", {}), dict) else {}
    body_text = str(morning.get("body_check", "")).strip().lower()
    mood_text = " ".join(
        part for part in [
            str(morning.get("mood_tag", "")).strip().lower(),
            str(evening.get("mood_tag", "")).strip().lower(),
        ]
        if part
    )
    context_text = _collect_context_text(data)
    context_lower = context_text.lower()

    low_hits = sum(1 for marker in LOW_ENERGY_MARKERS if marker in context_lower)
    high_hits = sum(1 for marker in HIGH_ENERGY_MARKERS if marker in context_lower)
    strong_low_hits = sum(
        1
        for marker in ("sore", "achy", "cramp", "tired", "exhaust", "sensitive", "resigned", "stress")
        if marker in body_text or marker in mood_text
    )
    if strong_low_hits:
        low_hits += 2 + strong_low_hits
    if now.hour >= 22:
        low_hits += 1

    energy = "medium"
    if strong_low_hits or low_hits >= max(2, high_hits + 1):
        energy = "low"
    elif high_hits >= low_hits + 3:
        energy = "high"
    if data.get("diariumFresh") is False and energy == "high":
        energy = "medium"

    tone = "curious"
    if energy == "low":
        tone = "gentle"
    elif any(word in context_lower for word in ("stress", "victim", "hospital", "scam", "resigned")):
        tone = "grounded"
    elif any(word in context_lower for word in ("focus", "curious", "build", "project", "research")):
        tone = "curious"
    if data.get("diariumFresh") is False and tone == "curious":
        tone = "grounded"

    window = "later"
    if now.hour >= 22:
        window = "late"
    elif now.hour >= 19:
        window = "evening"
    elif now.hour >= 16:
        window = "plan_tonight"

    if energy == "low":
        headline = "Low-bandwidth evening — bias toward an easy watchlist pick."
    elif energy == "high":
        headline = "You look able to handle something more involving tonight."
    else:
        headline = "Decision cost matters more than hunting for the perfect film tonight."
    if data.get("diariumFresh") is False and energy != "low":
        headline = "No fresh diary yet — keep tonight's pick easy and low-decision."

    reason_bits: list[str] = []
    if any(word in context_lower for word in ("sore", "achy", "cramp", "tired")):
        reason_bits.append("body looks taxed")
    if any(word in context_lower for word in ("stress", "scam", "victim", "hospital")):
        reason_bits.append("emotional load is higher than usual")
    if now.hour >= 22:
        reason_bits.append("it is already late")
    elif now.hour >= 19:
        reason_bits.append("tonight is in wind-down territory")
    if data.get("diariumFresh") is False:
        reason_bits.append("journal context is fallback-only")

    return {
        "energy": energy,
        "tone": tone,
        "window": window,
        "headline": headline,
        "reason_text": " · ".join(reason_bits),
    }


def _build_recommendation_reason(item: dict, profile: dict, recent_rank: int | None) -> str:
    title = str(item.get("title", "")).strip()
    tokens = _tokenise(title)
    year = _safe_year(item.get("year"))
    notes: list[str] = []
    if recent_rank is not None:
        notes.append("recent watchlist add")
    if profile.get("energy") == "low":
        if year and year <= 2005:
            notes.append("older/steadier fit")
        elif tokens & GENTLE_TITLE_TOKENS:
            notes.append("title reads gentler")
        else:
            notes.append("easy-decision pick")
    elif profile.get("energy") == "high":
        if tokens & INTENSE_TITLE_TOKENS:
            notes.append("title reads more propulsive")
        else:
            notes.append("good for a fuller-energy evening")
    else:
        if tokens & CURIOUS_TITLE_TOKENS:
            notes.append("title reads curious")
        else:
            notes.append("balanced tonight pick")
    return " · ".join(notes[:2])


def _score_candidate(
    item: dict,
    *,
    profile: dict,
    recent_rank: int | None,
    recent_watched_tokens: set[str],
) -> tuple[float, str]:
    title = str(item.get("title", "")).strip()
    tokens = _tokenise(title)
    year = _safe_year(item.get("year"))
    score = 0.0

    if recent_rank is not None:
        score += max(0, 6 - recent_rank)
    if recent_watched_tokens & tokens:
        score -= 2.5

    if profile.get("energy") == "low":
        if year and year <= 2005:
            score += 1.6
        if tokens & GENTLE_TITLE_TOKENS:
            score += 1.4
        if tokens & INTENSE_TITLE_TOKENS:
            score -= 1.2
    elif profile.get("energy") == "high":
        if year and year >= 2010:
            score += 0.7
        if tokens & INTENSE_TITLE_TOKENS:
            score += 1.6
    else:
        if tokens & CURIOUS_TITLE_TOKENS:
            score += 1.5
        if year and 1970 <= year <= 2015:
            score += 0.5

    if profile.get("tone") == "grounded" and year and year <= 2000:
        score += 0.7
    if profile.get("window") == "late" and recent_rank is not None:
        score += 0.5

    return score, _build_recommendation_reason(item, profile, recent_rank)


def build_recent_watch_note(recent_watched: list[dict]) -> str:
    if not recent_watched:
        return ""
    rated = [item for item in recent_watched if item.get("rating") not in (None, "", 0, 0.0)]
    year_values = [_safe_year(item.get("year")) for item in recent_watched]
    year_values = [year for year in year_values if year is not None]

    notes: list[str] = []
    if rated:
        best = max(rated, key=lambda item: float(item.get("rating") or 0))
        try:
            rating_label = f"★{float(best.get('rating')):g}"
        except Exception:
            rating_label = ""
        if rating_label:
            notes.append(f"Recent high point: {best.get('title', 'Unknown')} {rating_label}")
    if len(year_values) >= 2 and (max(year_values) - min(year_values)) >= 20:
        notes.append(f"Wide decade spread lately ({min(year_values)}–{max(year_values)})")
    if len(recent_watched) >= 2 and str(recent_watched[0].get("date", "")).strip() == str(recent_watched[1].get("date", "")).strip():
        notes.append(f"{recent_watched[0].get('date', '')}: multi-film day")
    return " · ".join(notes[:2])


def build_watch_recommendations(film_data: dict, data: dict, now: datetime | None = None) -> dict:
    profile = derive_viewing_profile(data, now=now)
    recent_watchlist = film_data.get("recent_watchlist", []) if isinstance(film_data.get("recent_watchlist", []), list) else []
    full_watchlist = film_data.get("full_watchlist", []) if isinstance(film_data.get("full_watchlist", []), list) else []
    recent_watched = film_data.get("recent_watched", []) if isinstance(film_data.get("recent_watched", []), list) else []
    pool = list(recent_watchlist[:12])
    if len(pool) < 8:
        pool.extend(full_watchlist[: max(0, 24 - len(pool))])

    recent_rank_by_key = {}
    for idx, item in enumerate(recent_watchlist[:20]):
        key = str(item.get("id") or item.get("url") or item.get("title", "")).strip()
        if key and key not in recent_rank_by_key:
            recent_rank_by_key[key] = idx

    recent_watched_tokens = set()
    for item in recent_watched[:4]:
        recent_watched_tokens |= _tokenise(item.get("title", ""))

    scored: list[dict] = []
    seen_keys: set[str] = set()
    for item in pool:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        key = str(item.get("id") or item.get("url") or title).strip().lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        score, reason = _score_candidate(
            item,
            profile=profile,
            recent_rank=recent_rank_by_key.get(str(item.get("id") or item.get("url") or "").strip()),
            recent_watched_tokens=recent_watched_tokens,
        )
        scored.append({
            "title": title,
            "year": str(item.get("year", "")).strip(),
            "url": str(item.get("url", "")).strip(),
            "reason": reason,
            "score": score,
        })

    scored.sort(key=lambda item: (-float(item.get("score", 0)), item.get("title", "").lower()))
    primary = scored[0] if scored else {}
    alternates = scored[1:3]
    return {
        "profile": profile,
        "primary": primary,
        "alternates": alternates,
        "recent_watch_note": build_recent_watch_note(recent_watched),
    }
