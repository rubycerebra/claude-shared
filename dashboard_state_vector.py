"""Daily state vector helpers for dashboard/API compounding insights."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List

from shared.cache_dates import get_ai_day, normalize_ai_cache_for_date


_POSITIVE_MOOD_SCORES = {
    "calm": 78,
    "content": 76,
    "attentive": 72,
    "ready": 68,
    "steady": 66,
    "aware": 62,
    "neutral": 56,
}
_NEGATIVE_MOOD_SCORES = {
    "resigned": 36,
    "tired": 42,
    "depleted": 32,
    "anxious": 30,
    "overwhelmed": 24,
    "stressed": 34,
    "frustrated": 38,
    "low": 35,
}


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _avg(values: Iterable[float]) -> float | None:
    cleaned = [float(v) for v in values if isinstance(v, (int, float))]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _parse_ymd(raw: str) -> datetime | None:
    try:
        return datetime.strptime(str(raw or "").strip(), "%Y-%m-%d")
    except Exception:
        return None


def _parse_dmy(raw: str) -> datetime | None:
    try:
        return datetime.strptime(str(raw or "").strip(), "%d/%m/%Y")
    except Exception:
        return None


def _parse_hours(raw: Any) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text.endswith("h"):
        try:
            return float(text[:-1])
        except Exception:
            return None
    match = re.match(r"^\s*(\d+)\s*h[: ](\d+)\s*m?\s*$", text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        return hours + (minutes / 60.0)
    return None


def _trend_from_history(values: List[float]) -> str:
    if len(values) < 3:
        return "live"
    recent = _avg(values[:3])
    prior = _avg(values[3:6])
    if recent is None or prior is None:
        return "live"
    delta = recent - prior
    if delta >= 5:
        return "up"
    if delta <= -5:
        return "down"
    return "steady"


def _score_mood_label(label: str) -> float | None:
    cleaned = str(label or "").strip().lower()
    if not cleaned or cleaned == "unknown":
        return None
    for key, score in _POSITIVE_MOOD_SCORES.items():
        if key in cleaned:
            return float(score)
    for key, score in _NEGATIVE_MOOD_SCORES.items():
        if key in cleaned:
            return float(score)
    return 58.0


def _dimension_state(score: float) -> str:
    if score >= 74:
        return "strong"
    if score >= 58:
        return "workable"
    if score >= 44:
        return "mixed"
    return "watch"


def _state_palette(state: str) -> Dict[str, str]:
    palettes = {
        "strong": {
            "text": "#6ee7b7",
            "border": "rgba(110,231,183,0.35)",
            "bg": "rgba(6,95,70,0.22)",
        },
        "workable": {
            "text": "#93c5fd",
            "border": "rgba(147,197,253,0.34)",
            "bg": "rgba(30,64,175,0.18)",
        },
        "mixed": {
            "text": "#fde68a",
            "border": "rgba(253,230,138,0.34)",
            "bg": "rgba(120,53,15,0.18)",
        },
        "watch": {
            "text": "#fca5a5",
            "border": "rgba(252,165,165,0.34)",
            "bg": "rgba(127,29,29,0.18)",
        },
    }
    return palettes.get(state, palettes["mixed"])


def _dimension(label: str, score: float, summary: str, evidence: List[str], trend: str, emoji: str) -> Dict[str, Any]:
    score = round(_clamp(score))
    return {
        "label": label,
        "emoji": emoji,
        "score": score,
        "state": _dimension_state(score),
        "summary": summary.strip(),
        "evidence": [str(item).strip() for item in evidence if str(item).strip()][:3],
        "trend": trend,
    }


def _recent_ai_days(ai_cache: Dict[str, Any], today: str, limit: int = 7) -> List[Dict[str, Any]]:
    by_date = ai_cache.get("by_date", {}) if isinstance(ai_cache.get("by_date", {}), dict) else {}
    ordered = sorted(
        [key for key in by_date.keys() if _parse_ymd(key)],
        reverse=True,
    )
    if today not in ordered:
        ordered.insert(0, today)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for date_key in ordered:
        if date_key in seen:
            continue
        seen.add(date_key)
        rows.append(get_ai_day(ai_cache, date_key))
        if len(rows) >= limit:
            break
    return rows


def _healthfit_steps_history(healthfit: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = healthfit.get("daily_metrics", []) if isinstance(healthfit.get("daily_metrics", []), list) else []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dt = _parse_dmy(str(row.get("date", "")))
        if not dt:
            continue
        cleaned.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "steps": float(row.get("steps") or 0),
                "hrv": float(row.get("hrv") or 0) if row.get("hrv") not in (None, "") else None,
                "exercise_minutes": float(row.get("exercise_minutes") or 0),
            }
        )
    cleaned.sort(key=lambda item: item["date"], reverse=True)
    return cleaned


def _healthfit_sleep_history(healthfit: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = healthfit.get("sleep", []) if isinstance(healthfit.get("sleep", []), list) else []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dt = _parse_dmy(str(row.get("date", "")))
        if not dt:
            continue
        asleep_hours = _parse_hours(row.get("asleep"))
        if asleep_hours is None:
            continue
        cleaned.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "asleep_hours": asleep_hours,
            }
        )
    cleaned.sort(key=lambda item: item["date"], reverse=True)
    return cleaned


def _latest_sleep_hours(cache: Dict[str, Any]) -> float | None:
    healthfit = cache.get("healthfit", {}) if isinstance(cache.get("healthfit", {}), dict) else {}
    sleep_history = _healthfit_sleep_history(healthfit)
    if sleep_history:
        return sleep_history[0].get("asleep_hours")
    autosleep = cache.get("autosleep", {}) if isinstance(cache.get("autosleep", {}), dict) else {}
    return _parse_hours((autosleep.get("last_night", {}) if isinstance(autosleep.get("last_night", {}), dict) else {}).get("asleep"))


def _body_check_penalty(body_check: str) -> float:
    text = str(body_check or "").strip().lower()
    if not text:
        return 0.0
    penalty = 0.0
    if any(token in text for token in ("hurt", "pain", "ache", "cramp", "stiff", "toe", "hyperextension", "sore")):
        penalty -= 10.0
    if any(token in text for token in ("feel better", "steady", "ready", "good", "energ")):
        penalty += 6.0
    return penalty


def _recent_anxiety_scores(ai_days: List[Dict[str, Any]]) -> List[float]:
    scores: List[float] = []
    for row in ai_days:
        if not isinstance(row, dict):
            continue
        score = row.get("anxiety_reduction_score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    return scores


def _intervention_signal(day: Dict[str, Any]) -> str:
    selector = day.get("intervention_selector", {}) if isinstance(day.get("intervention_selector", {}), dict) else {}
    weekly_rank = selector.get("weekly_rank", []) if isinstance(selector.get("weekly_rank", []), list) else []
    if not weekly_rank:
        return ""
    best = weekly_rank[0] if isinstance(weekly_rank[0], dict) else {}
    technique = str(best.get("technique", "")).strip()
    avg_relief = best.get("avg_relief")
    evidence_days = best.get("evidence_days")
    if not technique:
        return ""
    if isinstance(avg_relief, (int, float)) and isinstance(evidence_days, int) and evidence_days > 0:
        return f"{technique} is your strongest recent relief ({float(avg_relief):.1f}/10 across {evidence_days} day{'s' if evidence_days != 1 else ''})."
    return f"{technique} is the strongest repeated intervention in the current evidence."


def _mindfulness_signal(ai_days: List[Dict[str, Any]]) -> str:
    with_mindfulness: List[float] = []
    without_mindfulness: List[float] = []
    for row in ai_days:
        if not isinstance(row, dict):
            continue
        score = row.get("anxiety_reduction_score")
        if not isinstance(score, (int, float)):
            continue
        progression = row.get("mental_health_progression", {}) if isinstance(row.get("mental_health_progression", {}), dict) else {}
        if bool(progression.get("mindfulness_done")):
            with_mindfulness.append(float(score))
        else:
            without_mindfulness.append(float(score))
    avg_with = _avg(with_mindfulness)
    avg_without = _avg(without_mindfulness)
    if avg_with is None:
        return ""
    if avg_without is None:
        return f"Mindfulness is showing up on {len(with_mindfulness)} recent scored day{'s' if len(with_mindfulness) != 1 else ''}, with {avg_with:.1f}/10 average relief."
    delta = avg_with - avg_without
    if abs(delta) < 0.6:
        return f"Mindfulness is present on {len(with_mindfulness)} recent scored day{'s' if len(with_mindfulness) != 1 else ''}, with {avg_with:.1f}/10 average relief."
    direction = "higher" if delta > 0 else "lower"
    return f"Mindfulness days are trending {direction} relief ({avg_with:.1f}/10 vs {avg_without:.1f}/10)."


def _sleep_signal(ai_days: List[Dict[str, Any]], sleep_history: List[Dict[str, Any]]) -> str:
    if not sleep_history:
        return ""
    anxiety_by_date = {
        str(row.get("date", "")).strip(): float(row.get("anxiety_reduction_score"))
        for row in ai_days
        if isinstance(row, dict) and isinstance(row.get("anxiety_reduction_score"), (int, float))
    }
    rested: List[float] = []
    short: List[float] = []
    for row in sleep_history[:7]:
        date_key = str(row.get("date", "")).strip()
        if date_key not in anxiety_by_date:
            continue
        score = anxiety_by_date[date_key]
        asleep_hours = row.get("asleep_hours")
        if not isinstance(asleep_hours, (int, float)):
            continue
        if float(asleep_hours) >= 6.5:
            rested.append(score)
        else:
            short.append(score)
    avg_rested = _avg(rested)
    avg_short = _avg(short)
    if avg_rested is None and avg_short is None:
        return ""
    if len(rested) >= 2 and len(short) >= 2 and avg_rested is not None and avg_short is not None and (avg_rested - avg_short) >= 0.6:
        return f"Sleep ≥6.5h is lining up with better evening relief ({avg_rested:.1f}/10 vs {avg_short:.1f}/10)."
    latest_hours = sleep_history[0].get("asleep_hours")
    if isinstance(latest_hours, (int, float)):
        if float(latest_hours) < 6.5:
            return f"Latest sleep was {latest_hours:.1f}h, so protect pace before treating good activation as surplus energy."
        return f"Latest sleep was {latest_hours:.1f}h, which supports a steadier recovery base than the short-night days."
    return ""


def _mood_shift_signal(mood_slots: Dict[str, str], ai_days: List[Dict[str, Any]]) -> str:
    morning = str((mood_slots or {}).get("morning", "")).strip()
    if not morning or morning.lower() == "unknown":
        return ""
    current_score = _score_mood_label(morning)
    if current_score is None:
        return ""
    if len(ai_days) < 2:
        return ""
    prior = ai_days[1] if isinstance(ai_days[1], dict) else {}
    prior_slots = prior.get("mood_slots", {}) if isinstance(prior.get("mood_slots", {}), dict) else {}
    prior_evening = str(prior_slots.get("evening", "") or prior_slots.get("unscoped", "")).strip()
    prior_score = _score_mood_label(prior_evening)
    if prior_score is None:
        return ""
    delta = current_score - prior_score
    if delta >= 10:
        return f"Morning mood has lifted from yesterday evening ({prior_evening} → {morning}), which is usable momentum."
    if delta <= -10:
        return f"Morning mood is softer than yesterday evening ({prior_evening} → {morning}), so start with pacing before pushing."
    return f"Mood is broadly continuous with yesterday ({prior_evening} → {morning}); steady routines should carry best."


def build_daily_state_vector(
    cache: Dict[str, Any],
    *,
    today: str,
    mood_slots: Dict[str, Any] | None = None,
    action_items: List[Dict[str, Any]] | None = None,
    future_action_items: List[Dict[str, Any]] | None = None,
    completed_action_items: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    ai_cache = normalize_ai_cache_for_date(
        cache.get("ai_insights", {}) if isinstance(cache.get("ai_insights", {}), dict) else {},
        today,
    )
    day = get_ai_day(ai_cache, today)
    ai_days = _recent_ai_days(ai_cache, today, limit=7)
    diarium = cache.get("diarium", {}) if isinstance(cache.get("diarium", {}), dict) else {}
    healthfit = cache.get("healthfit", {}) if isinstance(cache.get("healthfit", {}), dict) else {}
    activitywatch = cache.get("activitywatch", {}) if isinstance(cache.get("activitywatch", {}), dict) else {}
    pieces = cache.get("pieces_activity", {}) if isinstance(cache.get("pieces_activity", {}), dict) else {}
    schedule = cache.get("schedule_analysis", {}) if isinstance(cache.get("schedule_analysis", {}), dict) else {}
    streaks = cache.get("streaks", {}) if isinstance(cache.get("streaks", {}), dict) else {}
    mood_tracking = day.get("mood_checkin", {}) if isinstance(day.get("mood_checkin", {}), dict) else {}
    mindfulness = day.get("mindfulness_completion", {}) if isinstance(day.get("mindfulness_completion", {}), dict) else {}
    progression = day.get("mental_health_progression", {}) if isinstance(day.get("mental_health_progression", {}), dict) else {}
    mental_corr = cache.get("mental_health_correlation", {}) if isinstance(cache.get("mental_health_correlation", {}), dict) else {}

    mood_slots = mood_slots if isinstance(mood_slots, dict) else {}
    action_items = action_items if isinstance(action_items, list) else []
    future_action_items = future_action_items if isinstance(future_action_items, list) else []
    completed_action_items = completed_action_items if isinstance(completed_action_items, list) else []

    sleep_history = _healthfit_sleep_history(healthfit)
    steps_history = _healthfit_steps_history(healthfit)
    latest_steps = steps_history[0] if steps_history else {}
    latest_sleep_hours = _latest_sleep_hours(cache)
    latest_hrv = latest_steps.get("hrv") if isinstance(latest_steps, dict) else None
    latest_steps_count = latest_steps.get("steps") if isinstance(latest_steps, dict) else None
    latest_exercise = latest_steps.get("exercise_minutes") if isinstance(latest_steps, dict) else None
    body_check = str(diarium.get("body_check", "") or "").strip()
    summary_text = str(day.get("latest_summary", "") or "").strip().lower()
    focus_patterns = activitywatch.get("focus_patterns", {}) if isinstance(activitywatch.get("focus_patterns", {}), dict) else {}
    focus_state = str(focus_patterns.get("focus_state", "")).strip().lower()
    productive_minutes = float(activitywatch.get("productive_minutes") or 0)
    pieces_count = int(pieces.get("count") or 0)
    updates_done = len(day.get("updates_completed_today", [])) if isinstance(day.get("updates_completed_today", []), list) else 0
    ta_dah_items = cache.get("ta_dah_categorised", {}) if isinstance(cache.get("ta_dah_categorised", {}), dict) else {}
    ta_dah_total = 0
    for value in ta_dah_items.values():
        if isinstance(value, list):
            ta_dah_total += len(value)
    anxiety_scores = _recent_anxiety_scores(ai_days)

    recovery_score = 52.0
    recovery_evidence: List[str] = []
    if isinstance(latest_sleep_hours, (int, float)):
        if latest_sleep_hours >= 7.5:
            recovery_score += 18
        elif latest_sleep_hours >= 6.5:
            recovery_score += 10
        elif latest_sleep_hours >= 6.0:
            recovery_score += 2
        else:
            recovery_score -= 12
        recovery_evidence.append(f"Sleep {latest_sleep_hours:.1f}h")
    if isinstance(latest_hrv, (int, float)):
        if latest_hrv >= 40:
            recovery_score += 12
        elif latest_hrv >= 35:
            recovery_score += 6
        elif latest_hrv < 30:
            recovery_score -= 12
        elif latest_hrv < 33:
            recovery_score -= 6
        recovery_evidence.append(f"HRV {int(latest_hrv)}")
    if bool(progression.get("mindfulness_done")) or bool(mindfulness.get("done")):
        recovery_score += 8
        recovery_evidence.append("Mindfulness logged")
    recent_recovery_history = []
    for idx, sleep_row in enumerate(sleep_history[:6]):
        row_score = 50.0
        asleep_hours = sleep_row.get("asleep_hours")
        if isinstance(asleep_hours, (int, float)):
            if asleep_hours >= 7.5:
                row_score += 18
            elif asleep_hours >= 6.5:
                row_score += 10
            elif asleep_hours >= 6.0:
                row_score += 2
            else:
                row_score -= 12
        if idx < len(steps_history):
            row_hrv = steps_history[idx].get("hrv")
            if isinstance(row_hrv, (int, float)):
                if row_hrv >= 40:
                    row_score += 12
                elif row_hrv >= 35:
                    row_score += 6
                elif row_hrv < 30:
                    row_score -= 12
                elif row_hrv < 33:
                    row_score -= 6
        recent_recovery_history.append(row_score)
    recovery_summary_bits = []
    if isinstance(latest_sleep_hours, (int, float)):
        recovery_summary_bits.append(f"{latest_sleep_hours:.1f}h sleep")
    if isinstance(latest_hrv, (int, float)):
        recovery_summary_bits.append(f"HRV {int(latest_hrv)}")
    recovery_summary = " + ".join(recovery_summary_bits) if recovery_summary_bits else "Sleep / HRV data still sparse"

    physical_score = 55.0
    physical_evidence: List[str] = []
    if isinstance(latest_steps_count, (int, float)):
        if latest_steps_count >= 12000:
            physical_score += 10
        elif latest_steps_count >= 8000:
            physical_score += 5
        elif latest_steps_count < 5000:
            physical_score -= 8
        physical_evidence.append(f"{int(latest_steps_count):,} steps")
    if isinstance(latest_exercise, (int, float)):
        if latest_exercise >= 90:
            physical_score += 12
        elif latest_exercise >= 45:
            physical_score += 8
        elif latest_exercise < 20:
            physical_score -= 5
        physical_evidence.append(f"{int(latest_exercise)}m exercise")
    physical_score += _body_check_penalty(body_check)
    if body_check:
        physical_evidence.append("Body check noted")
    physical_summary = ", ".join(physical_evidence[:2]) if physical_evidence else "Movement data limited"
    physical_history = []
    for row in steps_history[:6]:
        row_score = 55.0
        steps = row.get("steps")
        exercise = row.get("exercise_minutes")
        if isinstance(steps, (int, float)):
            if steps >= 12000:
                row_score += 10
            elif steps >= 8000:
                row_score += 5
            elif steps < 5000:
                row_score -= 8
        if isinstance(exercise, (int, float)):
            if exercise >= 90:
                row_score += 12
            elif exercise >= 45:
                row_score += 8
            elif exercise < 20:
                row_score -= 5
        physical_history.append(row_score)

    emotional_base = _score_mood_label(str(mood_slots.get("morning", "") or mood_slots.get("unscoped", ""))) or 54.0
    emotional_score = emotional_base
    emotional_evidence: List[str] = []
    morning_mood = str(mood_slots.get("morning", "") or "").strip()
    if morning_mood and morning_mood.lower() != "unknown":
        emotional_evidence.append(f"Morning mood {morning_mood}")
    latest_anxiety = anxiety_scores[0] if anxiety_scores else None
    if isinstance(latest_anxiety, (int, float)):
        if latest_anxiety >= 7:
            emotional_score += 10
        elif latest_anxiety >= 5:
            emotional_score += 5
        elif latest_anxiety < 4:
            emotional_score -= 8
        emotional_evidence.append(f"Recent relief {float(latest_anxiety):.1f}/10")
    if "calm" in summary_text or "activating" in summary_text or "focused" in summary_text:
        emotional_score += 6
    if any(token in summary_text for token in ("anxious", "depleted", "worn", "resigned", "miserable", "tension")):
        emotional_score -= 8
    correlations = mental_corr.get("data", {}).get("correlations", []) if isinstance(mental_corr.get("data", {}), dict) else []
    recent_negative_corr = 0
    for row in correlations[:5]:
        if not isinstance(row, dict):
            continue
        severity = str(row.get("severity", "")).strip().lower()
        if severity in {"high", "medium"}:
            recent_negative_corr += 1
    if recent_negative_corr >= 2:
        emotional_score -= 6
        emotional_evidence.append("Recent stress correlations present")
    emotional_summary = ", ".join(emotional_evidence[:2]) if emotional_evidence else "Mood + anxiety signal still building"
    emotional_history = []
    for row in ai_days[:6]:
        row_slots = row.get("mood_slots", {}) if isinstance(row.get("mood_slots", {}), dict) else {}
        row_score = _score_mood_label(str(row_slots.get("morning", "") or row_slots.get("unscoped", ""))) or 54.0
        row_anxiety = row.get("anxiety_reduction_score")
        if isinstance(row_anxiety, (int, float)):
            if row_anxiety >= 7:
                row_score += 10
            elif row_anxiety >= 5:
                row_score += 5
            elif row_anxiety < 4:
                row_score -= 8
        emotional_history.append(row_score)

    focus_score = 54.0
    focus_evidence: List[str] = []
    if productive_minutes >= 120:
        focus_score += 15
    elif productive_minutes >= 60:
        focus_score += 8
    elif productive_minutes < 30:
        focus_score -= 8
    if productive_minutes:
        focus_evidence.append(f"{int(round(productive_minutes))}m productive")
    if focus_state == "focused":
        focus_score += 12
    elif focus_state == "balanced":
        focus_score += 6
    elif focus_state == "scattered":
        focus_score -= 4
    if focus_state:
        focus_evidence.append(f"Focus {focus_state}")
    if pieces_count >= 10:
        focus_score += 10
    elif pieces_count >= 4:
        focus_score += 5
    if pieces_count:
        focus_evidence.append(f"{pieces_count} Pieces sessions")
    if updates_done >= 2:
        focus_score += 8
    elif updates_done == 1:
        focus_score += 4
    if updates_done:
        focus_evidence.append(f"{updates_done} update win{'s' if updates_done != 1 else ''}")
    focus_summary = ", ".join(focus_evidence[:3]) if focus_evidence else "Execution signal still warming up"
    focus_history = []
    for row in ai_days[:6]:
        row_score = 54.0
        done_count = len(row.get("updates_completed_today", [])) if isinstance(row.get("updates_completed_today", []), list) else 0
        if done_count >= 2:
            row_score += 8
        elif done_count == 1:
            row_score += 4
        if str(row.get("day_activity_narrative", "")).strip():
            row_score += 5
        focus_history.append(row_score)

    load_score = 64.0
    load_evidence: List[str] = []
    schedule_density = str(schedule.get("schedule_density", "")).strip().lower()
    burnout_risk = str(schedule.get("burnout_risk", "")).strip().lower()
    if schedule_density == "light":
        load_score += 10
    elif schedule_density in {"busy", "packed", "heavy"}:
        load_score -= 12
    elif schedule_density == "moderate":
        load_score -= 2
    if schedule_density:
        load_evidence.append(f"Schedule {schedule_density}")
    if burnout_risk == "high":
        load_score -= 14
    elif burnout_risk == "medium":
        load_score -= 6
    elif burnout_risk == "low":
        load_score += 4
    if burnout_risk:
        load_evidence.append(f"Burnout risk {burnout_risk}")
    open_loops = cache.get("open_loops", {}) if isinstance(cache.get("open_loops", {}), dict) else {}
    open_loop_count = int(open_loops.get("count") or 0) if str(open_loops.get("status", "")).strip().lower() == "found" else 0
    load_score -= min(len(action_items), 8) * 3
    load_score -= min(len(future_action_items), 4) * 4
    load_score -= min(open_loop_count, 4) * 4
    load_evidence.append(f"{len(action_items)} live tasks")
    if future_action_items:
        load_evidence.append(f"{len(future_action_items)} queued later")
    if open_loop_count:
        load_evidence.append(f"{open_loop_count} open loops")
    load_summary = ", ".join(load_evidence[:3]) if load_evidence else "Task load still resolving"

    momentum_score = 50.0
    momentum_evidence: List[str] = []
    if isinstance(latest_anxiety, (int, float)) and latest_anxiety >= 6:
        momentum_score += 6
    if morning_mood and morning_mood.lower() in {"attentive", "ready", "calm", "content", "steady"}:
        momentum_score += 8
        momentum_evidence.append(f"{morning_mood.title()} start")
    if ta_dah_total >= 3:
        momentum_score += 10
        momentum_evidence.append(f"{ta_dah_total} ta-dahs")
    elif ta_dah_total:
        momentum_score += 4
        momentum_evidence.append(f"{ta_dah_total} ta-dah")
    elif updates_done:
        momentum_score += 4
        momentum_evidence.append(f"{updates_done} update win{'s' if updates_done != 1 else ''}")
    if bool(mindfulness.get("done")) or bool(progression.get("mindfulness_done")):
        momentum_score += 5
        momentum_evidence.append("Mindfulness on board")
    if bool(mood_tracking.get("done")):
        momentum_score += 4
        momentum_evidence.append("Mood tracked")
    selector = day.get("intervention_selector", {}) if isinstance(day.get("intervention_selector", {}), dict) else {}
    weekly_rank = selector.get("weekly_rank", []) if isinstance(selector.get("weekly_rank", []), list) else []
    if weekly_rank and isinstance(weekly_rank[0], dict):
        top_relief = weekly_rank[0].get("avg_relief")
        evidence_days = weekly_rank[0].get("evidence_days")
        if isinstance(top_relief, (int, float)) and float(top_relief) >= 7 and isinstance(evidence_days, int) and evidence_days >= 3:
            momentum_score += 8
            momentum_evidence.append("Intervention evidence building")
    if "activating" in summary_text or "forward" in summary_text or "focused" in summary_text:
        momentum_score += 6
    if "depleted" in summary_text or "resigned" in summary_text:
        momentum_score -= 6
    momentum_summary = ", ".join(momentum_evidence[:3]) if momentum_evidence else "Momentum is mostly being inferred from the live day"
    momentum_history = []
    for row in ai_days[:6]:
        row_score = 50.0
        row_progression = row.get("mental_health_progression", {}) if isinstance(row.get("mental_health_progression", {}), dict) else {}
        combined = row_progression.get("combined_score")
        if isinstance(combined, (int, float)):
            row_score += float(combined) * 4
        elif isinstance(row.get("anxiety_reduction_score"), (int, float)):
            row_score += float(row.get("anxiety_reduction_score")) * 4
        momentum_history.append(row_score)

    dimensions = [
        _dimension("Recovery", recovery_score, recovery_summary, recovery_evidence, _trend_from_history(recent_recovery_history), "🌿"),
        _dimension("Physical", physical_score, physical_summary, physical_evidence, _trend_from_history(physical_history), "💪"),
        _dimension("Emotional", emotional_score, emotional_summary, emotional_evidence, _trend_from_history(emotional_history), "🫀"),
        _dimension("Focus", focus_score, focus_summary, focus_evidence, _trend_from_history(focus_history), "🎯"),
        _dimension("Load", load_score, load_summary, load_evidence, "live", "📦"),
        _dimension("Momentum", momentum_score, momentum_summary, momentum_evidence, _trend_from_history(momentum_history), "🚀"),
    ]

    overall_score = round(_avg([row["score"] for row in dimensions]) or 0)
    overall_state = _dimension_state(overall_score)
    strongest = sorted(dimensions, key=lambda row: row["score"], reverse=True)[:2]
    weakest = sorted(dimensions, key=lambda row: row["score"])[0]
    if weakest["score"] >= 60:
        headline = f"{strongest[0]['label']} is strongest and the day looks workable overall."
    else:
        headline = f"{strongest[0]['label']} and {strongest[1]['label']} can carry the day, but {weakest['label'].lower()} needs pacing."

    compounding_signals = [
        _intervention_signal(day),
        _mindfulness_signal(ai_days),
        _sleep_signal(ai_days, sleep_history),
        _mood_shift_signal(mood_slots, ai_days),
    ]
    compounding_signals = [item for item in compounding_signals if item][:3]
    if not compounding_signals:
        compounding_signals = [weakest["summary"]]

    primary_constraint = weakest["label"].lower()
    best_now = selector.get("best_now", {}) if isinstance(selector.get("best_now", {}), dict) else {}
    best_technique = str(best_now.get("technique", "")).strip()
    best_steps = best_now.get("steps", []) if isinstance(best_now.get("steps", []), list) else []

    if primary_constraint == "recovery":
        support_steps = [
            {"label": "1m", "text": "Loosen jaw/shoulders, drink water, and stop treating activation as spare capacity."},
            {"label": "10m", "text": (str(best_steps[0]).strip() if best_steps else "Take a short walk or gentle stretch before the next hard task.")},
            {"label": "30m", "text": "Do one low-friction block only, then reassess energy instead of chaining tasks."},
        ]
    elif primary_constraint == "emotional":
        support_steps = [
            {"label": "1m", "text": "Name the feeling, then do three physiological sighs."},
            {"label": "10m", "text": (str(best_steps[0]).strip() if best_steps else "Take a grounding walk and avoid making the next decision in the spike.")},
            {"label": "30m", "text": "Externalise three worries, choose one controllable action, and ignore the rest for now."},
        ]
    elif primary_constraint == "load":
        support_steps = [
            {"label": "1m", "text": "Write the top 3 true-today tasks only."},
            {"label": "10m", "text": "Defer or park one non-today item so the day stops competing with tomorrow."},
            {"label": "30m", "text": "Finish one concrete admin/errand block and declare that enough before adding more."},
        ]
    else:
        support_steps = [
            {"label": "1m", "text": "Pick the next task and make the first tiny move now."},
            {"label": "10m", "text": (str(best_steps[0]).strip() if best_steps else f"Run a starter sprint using {best_technique} if friction appears." if best_technique else "Run a 10-minute starter sprint on the clearest task." )},
            {"label": "30m", "text": "Protect one uninterrupted block while the current momentum is available."},
        ]

    return {
        "date": today,
        "headline": headline,
        "overall_score": overall_score,
        "overall_state": overall_state,
        "dimensions": dimensions,
        "compounding_signals": compounding_signals,
        "support_steps": support_steps,
        "primary_constraint": weakest["label"],
        "primary_strength": strongest[0]["label"] if strongest else "",
    }


def build_state_vector_html(vector: Dict[str, Any]) -> str:
    if not isinstance(vector, dict) or not vector.get("dimensions"):
        return ""

    overall_state = str(vector.get("overall_state", "mixed")).strip().lower()
    overall_palette = _state_palette(overall_state)
    dimensions = vector.get("dimensions", []) if isinstance(vector.get("dimensions"), list) else []
    pills_html = ""
    detail_rows_html = ""
    trend_map = {"up": "↗", "steady": "→", "down": "↘", "live": "•"}
    for row in dimensions:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", "")).strip()
        if not label:
            continue
        state = str(row.get("state", "mixed")).strip().lower()
        palette = _state_palette(state)
        trend = trend_map.get(str(row.get("trend", "live")).strip().lower(), "•")
        pills_html += (
            f'<span class="optional-pill text-xs rounded px-2 py-1" '
            f'style="border:1px solid {palette["border"]};background:{palette["bg"]};color:{palette["text"]};">'
            f'{html.escape(str(row.get("emoji", "•")))} {html.escape(label)} {int(row.get("score", 0))} {trend}'
            '</span>'
        )
        evidence_items = "".join(
            f'<li class="text-xs mb-1" style="color:#cbd5e1;line-height:1.45;">{html.escape(item)}</li>'
            for item in (row.get("evidence", []) if isinstance(row.get("evidence", []), list) else [])[:3]
        )
        _ul_block = f'<ul style="margin:0;padding-left:1rem;">{evidence_items}</ul>' if evidence_items else ""
        detail_rows_html += (
            f'<div class="rounded-lg p-3" style="background:rgba(15,23,42,0.46);border:1px solid rgba(148,163,184,0.14);">'
            f'<div class="flex items-center justify-between gap-2 mb-1">'
            f'<p class="text-sm font-semibold" style="color:{palette["text"]};">{html.escape(str(row.get("emoji", "•")))} {html.escape(label)}</p>'
            f'<span class="text-xs rounded px-2 py-0.5" style="border:1px solid {palette["border"]};color:{palette["text"]};">{int(row.get("score", 0))}</span>'
            f'</div>'
            f'<p class="text-xs mb-2" style="color:#e5e7eb;line-height:1.5;">{html.escape(str(row.get("summary", "")))}</p>'
            f'{_ul_block}'
            '</div>'
        )

    compounding_html = "".join(
        f'<li class="text-sm mb-1" style="color:#dbeafe;line-height:1.5;">{html.escape(str(item))}</li>'
        for item in (vector.get("compounding_signals", []) if isinstance(vector.get("compounding_signals", []), list) else [])[:3]
        if str(item).strip()
    )
    support_steps_html = "".join(
        f'<div class="rounded-lg px-3 py-2" style="background:rgba(15,23,42,0.48);border:1px solid rgba(148,163,184,0.16);">'
        f'<p class="text-xs font-semibold mb-1" style="color:#bae6fd">{html.escape(str(step.get("label", "")))}</p>'
        f'<p class="text-sm" style="color:#e5e7eb;line-height:1.45;">{html.escape(str(step.get("text", "")))}</p>'
        '</div>'
        for step in (vector.get("support_steps", []) if isinstance(vector.get("support_steps", []), list) else [])[:3]
        if isinstance(step, dict)
    )

    return f'''
        <div class="card rounded-xl p-5 mb-4" style="background:rgba(15,23,42,0.72);border:1px solid rgba(125,211,252,0.16);">
            <div class="flex items-start justify-between gap-3 mb-2">
                <div>
                    <h3 class="text-lg font-semibold" style="color:#bae6fd">🧭 Daily State Vector</h3>
                    <p class="text-sm mt-1" style="color:#e2e8f0;line-height:1.5;">{html.escape(str(vector.get("headline", "")))}</p>
                </div>
                <span class="text-xs rounded px-2 py-1" style="border:1px solid {overall_palette["border"]};background:{overall_palette["bg"]};color:{overall_palette["text"]};">
                    {html.escape(str(vector.get("overall_score", 0)))} · {html.escape(overall_state)}
                </span>
            </div>
            <div class="flex flex-wrap gap-2 mb-3">{pills_html}</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                    <p class="text-xs font-semibold mb-2" style="color:#93c5fd">Compounding signals</p>
                    <ul style="margin:0;padding-left:1rem;">{compounding_html}</ul>
                </div>
                <div>
                    <p class="text-xs font-semibold mb-2" style="color:#93c5fd">Progressive support</p>
                    <div class="grid grid-cols-1 gap-2">{support_steps_html}</div>
                </div>
            </div>
            <details class="mt-3">
                <summary class="text-xs cursor-pointer" style="color:#94a3b8">Why this state</summary>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">{detail_rows_html}</div>
            </details>
        </div>
    '''
