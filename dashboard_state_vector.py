"""Daily state vector helpers for dashboard/API compounding insights."""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List

from shared.cache_dates import get_ai_day, normalize_ai_cache_for_date


_HEALTH_LIVE_PATH = Path.home() / ".claude" / "cache" / "health-live.json"
_DASH_HISTORY_PATH = Path.home() / ".claude" / "cache" / "dashboard-history.json"
_health_live_raw_cache: Dict[str, Any] = {"mtime": 0.0, "data": {}}


def _get_health_live_metrics() -> Dict[str, list]:
    """Return health-live.json metrics keyed by name, mtime-cached. Returns {} if stale or missing."""
    try:
        mtime = _HEALTH_LIVE_PATH.stat().st_mtime
        if (time.time() - mtime) / 3600 >= 12:
            return {}
        if mtime == _health_live_raw_cache["mtime"]:
            return _health_live_raw_cache["data"]  # type: ignore[return-value]
        raw = json.loads(_HEALTH_LIVE_PATH.read_text(encoding="utf-8"))
        metrics_list = raw.get("data", {}).get("metrics", []) if isinstance(raw.get("data"), dict) else []
        result: Dict[str, list] = {}
        for m in metrics_list:
            if isinstance(m, dict) and m.get("name") and isinstance(m.get("data"), list):
                result[m["name"]] = m["data"]
        _health_live_raw_cache["mtime"] = mtime
        _health_live_raw_cache["data"] = result  # type: ignore[assignment]
        return result
    except Exception:
        return {}


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

DASHBOARD_HISTORY_FILE = Path.home() / ".claude" / "cache" / "dashboard-history.json"
KNOWLEDGE_STATE_FILE = Path.home() / ".claude" / "cache" / "knowledge-state.json"

# Minimum sample size before we trust personalised baselines over fixed thresholds
_BASELINE_MIN_N = 7

_DOMAIN_KEYWORDS = {
    "health": ("walk", "weights", "yoga", "stretch", "exercise", "workout", "sleep", "bath", "therapy", "health", "mindfulness"),
    "home": ("dishwasher", "coffee", "tablets", "bathroom", "bath", "caulk", "clean", "tidy", "laundry", "garden", "shopping", "house"),
    "admin": ("post office", "email", "call", "calendar", "schedule", "plan", "invoice", "pay", "review", "sort"),
    "system": ("dashboard", "qmd", "claude", "script", "cache", "bead", "bd ", "weekly report", "analysis", "sync", "daemon", "api"),
    "work": ("job", "cv", "application", "remote", "client", "freelance", "sony", "role", "outreach"),
}
_STRATEGIC_KEYWORDS = (
    "qmd", "dashboard", "memory", "pattern", "analysis", "report", "system",
    "workflow", "cv", "job", "application", "weekly", "integration",
)
_MAINTENANCE_KEYWORDS = (
    "coffee", "dishwasher", "tablets", "laundry", "cat food", "bins", "bathroom",
    "clean", "tidy", "shopping", "restock", "top up", "supplies",
)
_UNLOCK_KEYWORDS = (
    "fix", "verify", "generate", "review", "sync", "install", "integrate",
    "set up", "repair", "close", "export",
)


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _load_baselines() -> Dict[str, Any]:
    """Load personalised baselines from knowledge-state.json, or empty dict on failure."""
    try:
        if KNOWLEDGE_STATE_FILE.exists():
            raw = json.loads(KNOWLEDGE_STATE_FILE.read_text(encoding="utf-8"))
            return raw.get("baselines", {}) if isinstance(raw, dict) else {}
    except Exception:
        pass
    return {}


def _personalised_score(
    value: float,
    baselines: Dict[str, Any],
    mean_key: str,
    std_key: str,
    n_key: str,
    fixed_thresholds: List[tuple],
    higher_is_better: bool = True,
) -> float:
    """Score a metric using personal baselines when available, fixed thresholds otherwise.

    fixed_thresholds: [(threshold, score_delta), ...] ordered from highest to lowest threshold.
    Returns the score delta to add to base score.
    """
    mean = baselines.get(mean_key)
    std = baselines.get(std_key)
    n = baselines.get(n_key, 0) or 0
    if isinstance(mean, (int, float)) and isinstance(std, (int, float)) and std > 0 and n >= _BASELINE_MIN_N:
        z = (value - mean) / std
        if higher_is_better:
            if z >= 0.5:
                return 12
            elif z >= -0.5:
                return 6
            elif z < -1.0:
                return -12
            else:
                return -6
        else:
            if z <= -0.5:
                return 12
            elif z <= 0.5:
                return 6
            elif z > 1.0:
                return -12
            else:
                return -6
    # Fallback to fixed thresholds
    for threshold, delta in fixed_thresholds:
        if higher_is_better and value >= threshold:
            return delta
        if not higher_is_better and value <= threshold:
            return delta
    # Last entry in fixed_thresholds is the "else" case — return its delta
    return fixed_thresholds[-1][1] if fixed_thresholds else 0


def _avg(values: Iterable[float]) -> float | None:
    cleaned = [float(v) for v in values if isinstance(v, (int, float))]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _to_float(raw: Any) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except Exception:
        return None


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        return int(float(raw))
    except Exception:
        return default


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


def load_dashboard_history(history_file: Path | None = None) -> Dict[str, Any]:
    target = history_file or DASHBOARD_HISTORY_FILE
    try:
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, dict):
                payload.setdefault("by_date", {})
                return payload
    except Exception:
        pass
    return {"by_date": {}, "updated_at": ""}


def save_dashboard_history_snapshot(snapshot: Dict[str, Any], history_file: Path | None = None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    date_key = str(snapshot.get("date", "")).strip()
    if not date_key:
        return False
    target = history_file or DASHBOARD_HISTORY_FILE
    try:
        payload = load_dashboard_history(target)
        by_date = payload.get("by_date", {}) if isinstance(payload.get("by_date", {}), dict) else {}
        by_date[date_key] = snapshot
        payload["by_date"] = dict(sorted(by_date.items()))
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
        return True
    except Exception:
        return False


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


def _dimension(label: str, score: float, summary: str, evidence: List[str], trend: str, emoji: str, trajectory_7d: List[float] | None = None) -> Dict[str, Any]:
    score = round(_clamp(score))
    return {
        "label": label,
        "emoji": emoji,
        "score": score,
        "state": _dimension_state(score),
        "summary": summary.strip(),
        "evidence": [str(item).strip() for item in evidence if str(item).strip()][:3],
        "trend": trend,
        "trajectory_7d": [round(float(v), 1) for v in (trajectory_7d or [])][:7],
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
    # All sources date-guarded: sleep dates = wake date. Only today's data is valid.
    # Priority: health-live.json (file) → sleep_fallback → health_live (cache) → AutoSleep → HealthFit
    _today = datetime.now()
    _today_str = _today.strftime("%Y-%m-%d")
    _today_dmy = _today.strftime("%d/%m/%Y")

    # 0. health-live.json file — freshest source (shared mtime-cached read)
    _hl_metrics = _get_health_live_metrics()
    for _e in sorted(_hl_metrics.get("sleep_analysis", []), key=lambda x: str(x.get("date", "")), reverse=True):
        if isinstance(_e, dict) and str(_e.get("date", ""))[:10] == _today_str:
            _asleep = _to_float(_e.get("asleep")) or _to_float(_e.get("totalSleep"))
            if _asleep and _asleep > 0:
                return round(_asleep, 1)
            break

    # 1. sleep_fallback — daemon's fallback chain (date-guarded)
    raw = cache.get("sleep_fallback")
    fallback = raw if isinstance(raw, dict) else {}
    if fallback.get("source") and fallback.get("fresh"):
        if str(fallback.get("date", "")).strip()[:10] == _today_str:
            val = _to_float(fallback.get("sleep_hours"))
            if val is not None:
                return val

    # 2. health_live cache — daemon-normalised key (date-guarded)
    raw = cache.get("health_live")
    health_live = raw if isinstance(raw, dict) else {}
    _hl_sleep = health_live.get("sleep")
    if isinstance(_hl_sleep, dict):
        # Daemon cache omits 'date' from sleep dict — use sleep_end (wake time) then sleep_start
        _sleep_date = str(
            _hl_sleep.get("date") or _hl_sleep.get("sleep_end") or _hl_sleep.get("sleep_start") or ""
        ).strip()[:10]
        if _sleep_date == _today_str:
            val = _to_float(_hl_sleep.get("asleep_hours"))
            if val and val > 0:
                return val
    hl_sleep = _to_float(health_live.get("sleep_hours"))
    hl_date = str(health_live.get("date", "") or "").strip()[:10]
    if hl_sleep is not None and hl_sleep > 0 and hl_date == _today_str:
        return hl_sleep

    # 3. AutoSleep daily_metrics (date-guarded)
    raw = cache.get("autosleep")
    autosleep = raw if isinstance(raw, dict) else {}
    metrics = autosleep.get("daily_metrics", [])
    if not isinstance(metrics, list):
        metrics = []
    if metrics:
        latest = metrics[0]
        if isinstance(latest, dict) and str(latest.get("date", "")).strip()[:10] == _today_str:
            val = _to_float(latest.get("asleep_hours"))
            if val is not None:
                return val

    # 4. AutoSleep last_night (date-guarded)
    last_night = autosleep.get("last_night", {})
    last_night = last_night if isinstance(last_night, dict) else {}
    if str(last_night.get("date", "")).strip()[:10] == _today_str:
        parsed = _parse_hours(last_night.get("asleep"))
        if parsed is not None:
            return parsed

    # 5. HealthFit — last resort (date-guarded)
    raw = cache.get("healthfit")
    healthfit = raw if isinstance(raw, dict) else {}
    sleep_history = _healthfit_sleep_history(healthfit)
    if sleep_history:
        first = sleep_history[0]
        if isinstance(first, dict):
            _hf_date = str(first.get("date", "")).strip()
            if _hf_date == _today_str or _hf_date == _today_dmy:
                return _to_float(first.get("asleep_hours"))

    return None


def _latest_hrv(cache: Dict[str, Any], steps_history: list) -> float | None:
    """Get freshest HRV: health-live.json → health_live cache → HealthFit steps (date-guarded)."""
    _today = datetime.now()
    _today_str = _today.strftime("%Y-%m-%d")
    _today_dmy = _today.strftime("%d/%m/%Y")

    # 1. health-live.json file (shared mtime-cached read) — latest HRV reading today
    _hl_metrics = _get_health_live_metrics()
    _hrv_entries = _hl_metrics.get("heart_rate_variability", [])
    _today_pts = [e for e in _hrv_entries if isinstance(e, dict) and str(e.get("date", ""))[:10] == _today_str]
    if _today_pts:
        _latest = max(_today_pts, key=lambda x: str(x.get("date", "")))
        val = _to_float(_latest.get("qty"))
        if val and val > 0:
            return round(val)

    # 2. health_live cache — daemon-normalised
    hl = cache.get("health_live", {})
    hl = hl if isinstance(hl, dict) else {}
    hl_hrv = _to_float(hl.get("hrv_latest"))
    if hl_hrv and hl_hrv > 0:
        return round(hl_hrv)

    # 3. HealthFit steps history (date-guarded)
    if steps_history:
        latest = steps_history[0] if isinstance(steps_history[0], dict) else {}
        _date = str(latest.get("date", "")).strip()
        if _date == _today_str or _date == _today_dmy:
            val = _to_float(latest.get("hrv"))
            if val and val > 0:
                return round(val)

    return None


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


def _sleep_signal(ai_days: List[Dict[str, Any]], sleep_history: List[Dict[str, Any]], *, latest_override: float | None = None) -> str:
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
    latest_hours = latest_override if latest_override is not None else sleep_history[0].get("asleep_hours")
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


def _health_delta_signal() -> str:
    """Compare this week vs previous week recovery/focus/sleep/steps. Returns signal string when change ≥10%."""
    try:
        raw = json.loads(_DASH_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    by_date = raw.get("by_date", {}) if isinstance(raw.get("by_date", {}), dict) else {}
    today = datetime.now().strftime("%Y-%m-%d")
    # This week = last 7 days; prev week = 7-14 days ago
    this_week_keys = [(datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    prev_week_keys = [(datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7, 14)]

    def _avg_field(keys: list, field: str) -> float | None:
        vals = [float(by_date[k][field]) for k in keys if k in by_date and isinstance(by_date[k].get(field), (int, float))]
        return sum(vals) / len(vals) if vals else None

    this_recovery = _avg_field(this_week_keys, "recovery")
    prev_recovery = _avg_field(prev_week_keys, "recovery")
    this_focus = _avg_field(this_week_keys, "focus")
    prev_focus = _avg_field(prev_week_keys, "focus")

    # Also check steps from health-live.json — aggregate per-minute samples into daily totals
    metrics = _get_health_live_metrics()
    step_entries = metrics.get("step_count", [])
    def _avg_steps(keys: list) -> float | None:
        daily: dict[str, float] = {k: 0.0 for k in keys}
        for e in step_entries:
            day = str(e.get("date", ""))[:10]
            if day in daily and isinstance(e.get("qty"), (int, float)):
                daily[day] += float(e["qty"])  # type: ignore[arg-type]
        vals = [v for v in daily.values() if v > 0]
        return sum(vals) / len(vals) if vals else None

    this_steps = _avg_steps(this_week_keys)
    prev_steps = _avg_steps(prev_week_keys)

    # Surface the largest meaningful delta (≥10%)
    signals: list[tuple[float, str]] = []
    if this_recovery is not None and prev_recovery is not None and prev_recovery > 0:
        pct = (this_recovery - prev_recovery) / prev_recovery * 100
        if abs(pct) >= 10:
            arrow = "↑" if pct > 0 else "↓"
            label = "up" if pct > 0 else "down"
            signals.append((abs(pct), f"Recovery is {arrow}{abs(pct):.0f}% vs last week ({this_recovery:.0f} vs {prev_recovery:.0f}) — {label} trend."))
    if this_focus is not None and prev_focus is not None and prev_focus > 0:
        pct = (this_focus - prev_focus) / prev_focus * 100
        if abs(pct) >= 10:
            arrow = "↑" if pct > 0 else "↓"
            signals.append((abs(pct), f"Focus score is {arrow}{abs(pct):.0f}% vs last week ({this_focus:.0f} vs {prev_focus:.0f})."))
    if this_steps is not None and prev_steps is not None and prev_steps > 0:
        pct = (this_steps - prev_steps) / prev_steps * 100
        if abs(pct) >= 10:
            arrow = "↑" if pct > 0 else "↓"
            label = "strong momentum" if pct > 0 else "pace today"
            signals.append((abs(pct), f"Daily steps {arrow}{abs(pct):.0f}% vs last week ({int(this_steps):,} vs {int(prev_steps):,}) — {label}."))

    if not signals:
        return ""
    # Return the strongest signal
    signals.sort(key=lambda x: x[0], reverse=True)
    return signals[0][1]


def _recent_history_rows(history_payload: Dict[str, Any], today: str, limit: int = 30) -> List[Dict[str, Any]]:
    by_date = history_payload.get("by_date", {}) if isinstance(history_payload.get("by_date", {}), dict) else {}
    ordered = sorted([key for key in by_date.keys() if _parse_ymd(key)], reverse=True)
    if today in by_date and today not in ordered:
        ordered.insert(0, today)
    return [by_date[key] for key in ordered[:limit] if isinstance(by_date.get(key), dict)]


def _task_domain(task_text: str) -> str:
    text = str(task_text or "").strip().lower()
    if not text:
        return "admin"
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return domain
    return "admin"


def _domain_counts(task_texts: Iterable[str]) -> Dict[str, int]:
    counts = {key: 0 for key in _DOMAIN_KEYWORDS.keys()}
    for text in task_texts:
        counts[_task_domain(str(text))] += 1
    return counts


def _snapshot_metric(snapshot: Dict[str, Any], *path: str) -> float | None:
    current: Any = snapshot
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _to_float(current)


def _window_average(rows: List[Dict[str, Any]], *path: str) -> float | None:
    values = []
    for row in rows:
        value = _snapshot_metric(row, *path)
        if value is not None:
            values.append(value)
    return _avg(values)


def _window_domain_average(rows: List[Dict[str, Any]], domain: str) -> float:
    values = []
    for row in rows:
        value = _snapshot_metric(row, "throughput_by_domain", domain)
        if value is not None:
            values.append(value)
    return round(_avg(values) or 0.0, 1)


def _count_task_recurrence(task_key: str, history_rows: List[Dict[str, Any]]) -> int:
    if not task_key:
        return 0
    count = 0
    for row in history_rows:
        inputs = row.get("priority_inputs", {}) if isinstance(row.get("priority_inputs", {}), dict) else {}
        task_keys = inputs.get("open_task_keys", []) if isinstance(inputs.get("open_task_keys", []), list) else []
        if task_key in task_keys:
            count += 1
    return count


_WORKOUT_KINDS = [
    {"kind": "yoga", "task_keywords": ["yoga", "stretch", "mobility"], "schedule_keywords": ["yoga"]},
    {"kind": "weights", "task_keywords": ["weights", "workout a", "workout b", "lifting", "gym"], "schedule_keywords": ["workout", "weight"]},
]


def _is_off_schedule_workout(task_lower: str, today_workout_type: str) -> bool:
    """Return True if task is a workout-specific item for a workout NOT scheduled today."""
    if not today_workout_type:
        return False
    twt = today_workout_type.lower()
    for wk in _WORKOUT_KINDS:
        if any(kw in task_lower for kw in wk["task_keywords"]):
            if not any(sk in twt for sk in wk["schedule_keywords"]):
                return True
    return False


def _build_priority_candidates(
    action_items: List[Dict[str, Any]],
    *,
    history_rows: List[Dict[str, Any]],
    now_hour: int,
    primary_constraint: str,
    today_workout_type: str = "",
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    constraint_lower = primary_constraint.lower()
    for item in action_items:
        if not isinstance(item, dict) or bool(item.get("done")):
            continue
        task = str(item.get("task", "")).strip()
        if not task:
            continue
        task_key = re.sub(r"\s+", " ", task.lower()).strip()
        # Skip workout-specific items when that workout isn't scheduled today
        if _is_off_schedule_workout(task_key, today_workout_type):
            continue
        recurrence = _count_task_recurrence(task_key, history_rows)
        domain = _task_domain(task)
        strategic_value = 3 if any(keyword in task_key for keyword in _STRATEGIC_KEYWORDS) else (2 if domain in {"system", "work"} else 0)
        maintenance_risk = 3 if any(keyword in task_key for keyword in _MAINTENANCE_KEYWORDS) else (2 if str(item.get("category", "")).lower() == "maintenance" else 0)
        if recurrence >= 3 and maintenance_risk:
            maintenance_risk += 1
        dependency_unlock = 2 if any(keyword in task_key for keyword in _UNLOCK_KEYWORDS) else 0
        prior_completion = 1 if _window_domain_average(history_rows[:7], domain) >= 1 else 0
        if now_hour >= 20:
            energy_fit = 2 if domain in {"home", "admin", "health"} else 0
        elif constraint_lower in {"recovery", "load"}:
            energy_fit = 2 if domain in {"admin", "home"} else (1 if domain == "health" else 0)
        else:
            energy_fit = 2 if domain in {"system", "work"} else 1
        score = (recurrence * 1.6) + strategic_value + maintenance_risk + dependency_unlock + prior_completion + energy_fit
        reasons: List[str] = []
        if recurrence:
            reasons.append(f"seen {recurrence + 1} day{'s' if recurrence + 1 != 1 else ''}")
        if strategic_value:
            reasons.append("builds leverage")
        if maintenance_risk:
            reasons.append("prevents decay")
        if dependency_unlock:
            reasons.append("unlocks follow-on work")
        if prior_completion:
            reasons.append(f"{domain} is a domain with recent follow-through")
        candidates.append(
            {
                "task": task,
                "task_key": task_key,
                "domain": domain,
                "score": round(score, 1),
                "reasons": reasons[:3],
                "source": str(item.get("source", "")).strip(),
                "category": str(item.get("category", "")).strip(),
            }
        )
    candidates.sort(key=lambda row: (-float(row.get("score", 0)), row.get("task", "").lower()))
    return candidates[:5]


def _report_status_payload(
    *,
    today: str,
    diarium_fresh: bool,
    weekly_context: Dict[str, Any],
    history_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    weekly_ready = bool(weekly_context.get("current_exists"))
    weekly_placeholder = bool(weekly_context.get("needs_regeneration"))
    month_prefix = today[:7]
    month_rows = [row for row in history_rows if str(row.get("date", "")).startswith(month_prefix)]
    monthly_confidence = round(min(len(month_rows) / 20.0, 1.0), 2)
    return {
        "daily": {"status": "fresh" if diarium_fresh else "stale", "confidence": 0.9 if diarium_fresh else 0.45},
        "weekly": {
            "status": "needs_regeneration" if weekly_placeholder else ("ready" if weekly_ready else "waiting"),
            "confidence": 0.45 if weekly_placeholder else (0.9 if weekly_ready else 0.35),
        },
        "monthly": {
            "status": "building" if month_rows else "sparse",
            "confidence": monthly_confidence,
        },
    }


def _support_mode_snapshot(cache: Dict[str, Any]) -> Dict[str, Any]:
    raw = cache.get("support_mode_meta")
    sm = raw if isinstance(raw, dict) else {}
    return {"mode": str(sm.get("mode", "")), "ease_score": _safe_int(sm.get("ease_score")), "progress_score": _safe_int(sm.get("progress_score"))}


def _build_snapshot(
    *,
    today: str,
    cache: Dict[str, Any],
    day: Dict[str, Any],
    dimensions: List[Dict[str, Any]],
    compounding_signals: List[str],
    action_items: List[Dict[str, Any]],
    completed_action_items: List[Dict[str, Any]],
    future_action_items: List[Dict[str, Any]],
    throughput_by_domain: Dict[str, int],
    priority_candidates: List[Dict[str, Any]],
    report_status: Dict[str, Any],
    latest_sleep_hours: float | None = None,
    latest_hrv: float | None = None,
) -> Dict[str, Any]:
    diarium = cache.get("diarium", {}) if isinstance(cache.get("diarium", {}), dict) else {}
    healthfit = cache.get("healthfit", {}) if isinstance(cache.get("healthfit", {}), dict) else {}
    open_loops = cache.get("open_loops", {}) if isinstance(cache.get("open_loops", {}), dict) else {}
    _aw = cache.get("activitywatch", {}) if isinstance(cache.get("activitywatch", {}), dict) else {}
    _aw_fp = _aw.get("focus_patterns", {}) if isinstance(_aw.get("focus_patterns"), dict) else {}
    steps_history = _healthfit_steps_history(healthfit)
    latest_steps = steps_history[0] if steps_history else {}
    wins_count = len([item for item in (day.get("all_insights", []) if isinstance(day.get("all_insights", []), list) else []) if isinstance(item, dict) and item.get("type") == "win"])
    signal_count = len([item for item in (day.get("all_insights", []) if isinstance(day.get("all_insights", []), list) else []) if isinstance(item, dict) and item.get("type") == "signal"])
    completed_texts = [
        str(item.get("task", "")).strip()
        for item in completed_action_items
        if isinstance(item, dict) and str(item.get("task", "")).strip()
    ]
    maintenance_completed = sum(1 for text in completed_texts if _task_domain(text) in {"home", "admin", "health"})
    maintenance_open = sum(
        1
        for item in action_items
        if isinstance(item, dict)
        and not bool(item.get("done"))
        and (
            str(item.get("category", "")).strip().lower() == "maintenance"
            or _task_domain(str(item.get("task", ""))) in {"home", "admin", "health"}
        )
    )
    strategic_progress = sum(1 for text in completed_texts if any(keyword in text.lower() for keyword in _STRATEGIC_KEYWORDS))
    recovery_dim = next((row for row in dimensions if row.get("label") == "Recovery"), {})
    physical_dim = next((row for row in dimensions if row.get("label") == "Physical"), {})
    load_dim = next((row for row in dimensions if row.get("label") == "Load"), {})
    momentum_dim = next((row for row in dimensions if row.get("label") == "Momentum"), {})
    emotional_dim = next((row for row in dimensions if row.get("label") == "Emotional"), {})
    focus_dim = next((row for row in dimensions if row.get("label") == "Focus"), {})
    top_loops = open_loops.get("items", []) if isinstance(open_loops.get("items", []), list) else []
    return {
        "date": today,
        "coverage": {
            "diarium": "fresh" if bool(cache.get("diarium_fresh", True)) else "stale",
            "ai_insights": "fresh" if str(day.get("status", "")).strip().lower() in {"ok", ""} else "stale",
            "pieces": "fresh" if str((cache.get("pieces_activity", {}) if isinstance(cache.get("pieces_activity", {}), dict) else {}).get("status", "")).strip().lower() == "ok" else "stale",
            "weekly": report_status.get("weekly", {}).get("status", "waiting"),
        },
        "throughput": {
            "throughput_total": sum(int(v) for v in throughput_by_domain.values()),
            "ta_dah_count": len(diarium.get("ta_dah", []) if isinstance(diarium.get("ta_dah", []), list) else []),
            "completed_action_count": len(completed_texts),
            "wins_count": wins_count,
            "maintenance_completed": maintenance_completed,
            "maintenance_open": maintenance_open,
            "strategic_progress_count": strategic_progress,
        },
        "throughput_by_domain": throughput_by_domain,
        "health": {
            "steps": _safe_int(latest_steps.get("steps")),
            "exercise_minutes": _safe_int(latest_steps.get("exercise_minutes")),
            "hrv": latest_hrv,
            "sleep_hours": latest_sleep_hours,
            "sleep_efficiency": _to_float((cache.get("autosleep", {}) if isinstance(cache.get("autosleep", {}), dict) else {}).get("last_night", {}).get("efficiency")),
            "screen_time_hours": _to_float(_parse_hours((cache.get("screentime", {}) if isinstance(cache.get("screentime", {}), dict) else {}).get("today_total"))),
        },
        "activitywatch": {
            "productive_minutes": _to_float(_aw.get("productive_minutes")),
            "focus_state": str(_aw_fp.get("focus_state", "")).strip(),
            "context_switches": _safe_int(_aw_fp.get("context_switches")),
            "total_tracked_minutes": _to_float(_aw.get("total_tracked_minutes")),
        },
        "regulation": {
            "mood_morning": str((day.get("mood_slots", {}) if isinstance(day.get("mood_slots", {}), dict) else {}).get("morning", "")).strip(),
            "mood_evening": str((day.get("mood_slots", {}) if isinstance(day.get("mood_slots", {}), dict) else {}).get("evening", "")).strip(),
            "anxiety_reduction_score": _to_float(day.get("anxiety_reduction_score")),
            "intervention_count": len((day.get("daily_guidance", {}) if isinstance(day.get("daily_guidance", {}), dict) else {}).get("lines", [])),
            "wins_count": wins_count,
            "signals_count": signal_count,
            "feedback_count": 1 if isinstance(day.get("anxiety_reduction_score"), (int, float)) else 0,
        },
        "state_vector": {
            "energy": round((float(recovery_dim.get("score", 0)) + float(physical_dim.get("score", 0))) / 2.0, 1) if recovery_dim and physical_dim else None,
            "strain": round(100.0 - float(load_dim.get("score", 0)), 1) if load_dim else None,
            "momentum": _to_float(momentum_dim.get("score")),
            "recovery": _to_float(recovery_dim.get("score")),
            "emotional": _to_float(emotional_dim.get("score")),
            "focus": _to_float(focus_dim.get("score")),
            "compounding_signals": compounding_signals[:3],
        },
        "support_mode": _support_mode_snapshot(cache),
        "top_open_loops": [str(item).strip() for item in top_loops[:5] if str(item).strip()],
        "priority_inputs": {
            "time_of_day": "evening" if datetime.now().hour >= 18 else "day",
            "open_tasks": [
                str(item.get("task", "")).strip()
                for item in action_items
                if isinstance(item, dict) and not bool(item.get("done")) and str(item.get("task", "")).strip()
            ][:12],
            "open_task_keys": [
                re.sub(r"\s+", " ", str(item.get("task", "")).strip().lower())
                for item in action_items
                if isinstance(item, dict) and not bool(item.get("done")) and str(item.get("task", "")).strip()
            ][:12],
            "future_queue_count": len(future_action_items),
            "top_candidates": priority_candidates[:3],
        },
        "report_status": report_status,
    }


def build_daily_state_vector(
    cache: Dict[str, Any],
    *,
    today: str,
    mood_slots: Dict[str, Any] | None = None,
    action_items: List[Dict[str, Any]] | None = None,
    future_action_items: List[Dict[str, Any]] | None = None,
    completed_action_items: List[Dict[str, Any]] | None = None,
    history_payload: Dict[str, Any] | None = None,
    report_context: Dict[str, Any] | None = None,
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
    screentime = cache.get("screentime", {}) if isinstance(cache.get("screentime", {}), dict) else {}
    screentime_today_hours = _parse_hours(screentime.get("today_total"))
    pieces = cache.get("pieces_activity", {}) if isinstance(cache.get("pieces_activity", {}), dict) else {}
    schedule = cache.get("schedule_analysis", {}) if isinstance(cache.get("schedule_analysis", {}), dict) else {}
    finch_raw = cache.get("finch", {}) if isinstance(cache.get("finch", {}), dict) else {}
    finch_activities = finch_raw.get("activities", {}).get("activities", {}) if isinstance(finch_raw.get("activities", {}), dict) else {}
    finch_today_count = sum(1 for _ in finch_activities)
    mood_tracking = day.get("mood_checkin", {}) if isinstance(day.get("mood_checkin", {}), dict) else {}
    mindfulness = day.get("mindfulness_completion", {}) if isinstance(day.get("mindfulness_completion", {}), dict) else {}
    progression = day.get("mental_health_progression", {}) if isinstance(day.get("mental_health_progression", {}), dict) else {}
    mental_corr = cache.get("mental_health_correlation", {}) if isinstance(cache.get("mental_health_correlation", {}), dict) else {}

    mood_slots = mood_slots if isinstance(mood_slots, dict) else {}
    action_items = action_items if isinstance(action_items, list) else []
    future_action_items = future_action_items if isinstance(future_action_items, list) else []
    completed_action_items = completed_action_items if isinstance(completed_action_items, list) else []
    history_payload = history_payload if isinstance(history_payload, dict) else load_dashboard_history()
    report_context = report_context if isinstance(report_context, dict) else {}
    history_rows = _recent_history_rows(history_payload, today, limit=30)
    prior_history_rows = [row for row in history_rows if str(row.get("date", "")).strip() != today]

    sleep_history = _healthfit_sleep_history(healthfit)
    steps_history = _healthfit_steps_history(healthfit)
    latest_steps = steps_history[0] if steps_history else {}
    latest_sleep_hours = _latest_sleep_hours(cache)
    latest_hrv = _latest_hrv(cache, steps_history)
    latest_steps_count = latest_steps.get("steps") if isinstance(latest_steps, dict) else None
    latest_exercise = latest_steps.get("exercise_minutes") if isinstance(latest_steps, dict) else None
    body_check = str(diarium.get("body_check", "") or "").strip()
    keyword_flags = diarium.get("keyword_detections", []) if isinstance(diarium.get("keyword_detections", []), list) else []
    keyword_flag_count = len(keyword_flags)
    diarium_emotional_tone = str(diarium.get("emotional_tone", "") or "").strip().lower()
    summary_text = str(day.get("latest_summary", "") or "").strip().lower()
    focus_patterns = activitywatch.get("focus_patterns", {}) if isinstance(activitywatch.get("focus_patterns", {}), dict) else {}
    focus_state = str(focus_patterns.get("focus_state", "")).strip().lower()
    context_switches = int(focus_patterns.get("context_switches") or 0)
    scattered_ratio = float(focus_patterns.get("scattered_ratio") or 0)
    productive_minutes = float(activitywatch.get("productive_minutes") or 0)
    pieces_count = int(pieces.get("count") or 0)
    updates_done = len(day.get("updates_completed_today", [])) if isinstance(day.get("updates_completed_today", []), list) else 0
    ta_dah_items = cache.get("ta_dah_categorised", {}) if isinstance(cache.get("ta_dah_categorised", {}), dict) else {}
    ta_dah_total = 0
    for value in ta_dah_items.values():
        if isinstance(value, list):
            ta_dah_total += len(value)
    anxiety_scores = _recent_anxiety_scores(ai_days)
    baselines = _load_baselines()
    mental_health = cache.get("mental_health", {}) if isinstance(cache.get("mental_health", {}), dict) else {}
    homework_items = mental_health.get("homework_items", []) if isinstance(mental_health.get("homework_items", []), list) else []
    homework_count = len(homework_items)

    recovery_score = 52.0
    recovery_evidence: List[str] = []
    if isinstance(latest_sleep_hours, (int, float)):
        recovery_score += _personalised_score(
            latest_sleep_hours, baselines, "sleep_mean_hours", "sleep_std", "sleep_n",
            [(7.5, 18), (6.5, 10), (6.0, 2), (0, -12)],
        )
        recovery_evidence.append(f"Sleep {latest_sleep_hours:.1f}h")
    if isinstance(latest_hrv, (int, float)):
        recovery_score += _personalised_score(
            latest_hrv, baselines, "hrv_mean", "hrv_std", "hrv_n",
            [(40, 12), (35, 6), (33, 0), (30, -6), (0, -12)],
        )
        recovery_evidence.append(f"HRV {int(latest_hrv)}")
    if bool(progression.get("mindfulness_done")) or bool(mindfulness.get("done")):
        recovery_score += 8
        recovery_evidence.append("Mindfulness logged")
    recent_recovery_history = []
    for idx, sleep_row in enumerate(sleep_history[:6]):
        row_score = 50.0
        asleep_hours = sleep_row.get("asleep_hours")
        if isinstance(asleep_hours, (int, float)):
            row_score += _personalised_score(
                asleep_hours, baselines, "sleep_mean_hours", "sleep_std", "sleep_n",
                [(7.5, 18), (6.5, 10), (6.0, 2), (0, -12)],
            )
        if idx < len(steps_history):
            row_hrv = steps_history[idx].get("hrv")
            if isinstance(row_hrv, (int, float)):
                row_score += _personalised_score(
                    row_hrv, baselines, "hrv_mean", "hrv_std", "hrv_n",
                    [(40, 12), (35, 6), (33, 0), (30, -6), (0, -12)],
                )
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
        physical_score += _personalised_score(
            latest_steps_count, baselines, "steps_mean", "steps_std", "steps_n",
            [(12000, 10), (8000, 5), (5000, 0), (0, -8)],
        )
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
            row_score += _personalised_score(
                steps, baselines, "steps_mean", "steps_std", "steps_n",
                [(12000, 10), (8000, 5), (5000, 0), (0, -8)],
            )
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
    # Diarium keyword flags (anxious/overwhelmed/worried language detected in journal)
    if keyword_flag_count >= 5:
        emotional_score -= 8
        emotional_evidence.append(f"{keyword_flag_count} distress flags in journal")
    elif keyword_flag_count >= 3:
        emotional_score -= 4
        emotional_evidence.append(f"{keyword_flag_count} distress flags in journal")
    elif keyword_flag_count == 0 and diarium:
        emotional_score += 3
    # Diarium emotional tone field
    if diarium_emotional_tone in {"anxious", "overwhelmed", "stressed", "depleted", "low"}:
        emotional_score = max(emotional_score - 5, 20.0)
    elif diarium_emotional_tone in {"calm", "content", "positive", "energised"}:
        emotional_score = min(emotional_score + 4, 95.0)
    # Therapy homework engagement — active homework signals self-regulation investment
    engagement_hints = cache.get("engagement_hints", []) if isinstance(cache.get("engagement_hints", []), list) else []
    homework_surfaced_today = any(
        isinstance(h, dict) and h.get("type") == "therapy_homework_context"
        for h in engagement_hints
    )
    if homework_surfaced_today:
        emotional_score += 4
        emotional_evidence.append("Therapy homework active today")
    elif homework_count >= 3 and not homework_surfaced_today:
        emotional_score += 2
        emotional_evidence.append(f"{homework_count} homework items tracked")
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
    dashboard_bell = cache.get("dashboard_bell", {}) if isinstance(cache.get("dashboard_bell", {}), dict) else {}
    dashboard_bell_items = dashboard_bell.get("items", []) if isinstance(dashboard_bell.get("items", []), list) else []
    dashboard_bell_count = sum(
        1
        for item in dashboard_bell_items
        if isinstance(item, dict)
        and str(item.get("item_id", "")).strip()
        and str(item.get("sync_state", "")).strip().lower() != "auto_resolved"
    )
    load_score -= min(len(action_items), 8) * 3
    load_score -= min(len(future_action_items), 4) * 4
    load_score -= min(open_loop_count, 4) * 4
    load_score -= min(dashboard_bell_count, 4) * 3
    load_evidence.append(f"{len(action_items)} live tasks")
    if future_action_items:
        load_evidence.append(f"{len(future_action_items)} queued later")
    if open_loop_count:
        load_evidence.append(f"{open_loop_count} open loops")
    if dashboard_bell_count:
        load_evidence.append(f"{dashboard_bell_count} check-ins")
    # Context switch penalty — high app-switching signals fragmented cognitive load
    if context_switches >= 200:
        load_score -= 10
        load_evidence.append(f"{context_switches} context switches (high fragmentation)")
    elif context_switches >= 100:
        load_score -= 5
        load_evidence.append(f"{context_switches} context switches")
    elif context_switches >= 50 and scattered_ratio >= 0.8:
        load_score -= 3
        load_evidence.append(f"Scattered focus ({int(scattered_ratio * 100)}%)")
    # Screen time → Load penalty (personalised baseline or fixed thresholds)
    if isinstance(screentime_today_hours, (int, float)):
        _st_delta = _personalised_score(
            screentime_today_hours, baselines,
            "screen_time_mean", "screen_time_std", "screen_time_n",
            [(8.0, -8), (6.0, -4), (4.0, 0), (0, 2)],
            higher_is_better=False,
        )
        load_score += _st_delta
        if _st_delta <= -4:
            load_evidence.append(f"Screen time {screentime_today_hours:.1f}h (high)")
        elif _st_delta < 0:
            load_evidence.append(f"Screen time {screentime_today_hours:.1f}h")
    # Hyperfocus session penalty (sustained single-app focus outside productive context)
    hyperfocus_sessions = int(focus_patterns.get("hyperfocus_sessions") or 0)
    if hyperfocus_sessions >= 2:
        load_score -= 5
        load_evidence.append(f"{hyperfocus_sessions} hyperfocus sessions")
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
    if homework_surfaced_today:
        momentum_score += 3
        momentum_evidence.append("Therapy homework engaged")
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
    # Finch self-care activity signal
    if finch_today_count >= 5:
        momentum_score += 5
        momentum_evidence.append("Self-care routine done")
    elif finch_today_count == 0:
        momentum_evidence.append("No Finch activity recorded")
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
        _dimension("Recovery", recovery_score, recovery_summary, recovery_evidence, _trend_from_history(recent_recovery_history), "🌿", trajectory_7d=recent_recovery_history[:7]),
        _dimension("Physical", physical_score, physical_summary, physical_evidence, _trend_from_history(physical_history), "💪", trajectory_7d=physical_history[:7]),
        _dimension("Emotional", emotional_score, emotional_summary, emotional_evidence, _trend_from_history(emotional_history), "🫀", trajectory_7d=emotional_history[:7]),
        _dimension("Focus", focus_score, focus_summary, focus_evidence, _trend_from_history(focus_history), "🎯", trajectory_7d=focus_history[:7]),
        _dimension("Load", load_score, load_summary, load_evidence, "live", "📦"),
        _dimension("Momentum", momentum_score, momentum_summary, momentum_evidence, _trend_from_history(momentum_history), "🚀", trajectory_7d=momentum_history[:7]),
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
        _sleep_signal(ai_days, sleep_history, latest_override=latest_sleep_hours),
        _mood_shift_signal(mood_slots, ai_days),
    ]
    # Ensure _health_delta_signal is always included when available (place it last, keep up to 4 total)
    delta_sig = _health_delta_signal()
    non_delta = [item for item in compounding_signals[:-1] if item][:3]
    compounding_signals = (non_delta + [delta_sig]) if delta_sig else non_delta[:3]
    # Compound risk: surface when multiple dimensions simultaneously in "watch"
    watch_count = sum(1 for d in dimensions if d.get("state") == "watch")
    if watch_count >= 2:
        watch_labels = ", ".join(d["label"] for d in dimensions if d.get("state") == "watch")
        compound_msg = f"Compound risk: {watch_count} dimensions in watch state ({watch_labels}) — reduce commitments today."
        compounding_signals.insert(0, compound_msg)
        compounding_signals = compounding_signals[:4]
    if not compounding_signals:
        compounding_signals = [weakest["summary"]]

    completed_task_texts = [
        str(item.get("task", "")).strip()
        for item in completed_action_items
        if isinstance(item, dict) and str(item.get("task", "")).strip()
    ]
    ta_dah_list = diarium.get("ta_dah", []) if isinstance(diarium.get("ta_dah", []), list) else []
    throughput_task_texts = completed_task_texts + [str(item).strip() for item in ta_dah_list if str(item).strip()]
    throughput_by_domain = _domain_counts(throughput_task_texts)
    # Derive today's workout type for schedule-aware filtering
    _fitness_raw = cache.get("fitness", {})
    _fitness = _fitness_raw if isinstance(_fitness_raw, dict) else {}
    _session_raw = _fitness.get("next_session", {})
    _next_session = _session_raw if isinstance(_session_raw, dict) else {}
    _today_workout_type = str(_next_session.get("type", "")).strip()
    priority_candidates = _build_priority_candidates(
        action_items,
        history_rows=prior_history_rows[:14],
        now_hour=datetime.now().hour,
        primary_constraint=weakest["label"],
        today_workout_type=_today_workout_type,
    )
    report_status = _report_status_payload(
        today=today,
        diarium_fresh=bool(cache.get("diarium_fresh", True)),
        weekly_context=report_context,
        history_rows=history_rows,
    )
    current_snapshot = _build_snapshot(
        today=today,
        cache=cache,
        day=day,
        dimensions=dimensions,
        compounding_signals=compounding_signals,
        action_items=action_items,
        completed_action_items=completed_action_items,
        future_action_items=future_action_items,
        throughput_by_domain=throughput_by_domain,
        priority_candidates=priority_candidates,
        report_status=report_status,
        latest_sleep_hours=latest_sleep_hours,
        latest_hrv=latest_hrv,
    )
    window_7 = [current_snapshot] + prior_history_rows[:6]
    window_30 = [current_snapshot] + prior_history_rows[:29]
    day_throughput_total = sum(throughput_by_domain.values())
    avg_7 = _window_average(window_7, "throughput", "throughput_total") or 0.0
    avg_30 = _window_average(window_30, "throughput", "throughput_total") or 0.0
    momentum_delta = {
        "vs_7d": round(float(momentum_score) - float(_window_average(window_7[1:], "state_vector", "momentum") or momentum_score), 1),
        "vs_30d": round(float(momentum_score) - float(_window_average(window_30[1:], "state_vector", "momentum") or momentum_score), 1),
    }
    trend_windows = {
        "day": {
            "throughput_total": day_throughput_total,
            "completed_action_count": len(completed_task_texts),
            "momentum": round(float(momentum_score), 1),
        },
        "7d": {
            "throughput_avg": round(avg_7, 1),
            "momentum_avg": round(float(_window_average(window_7, "state_vector", "momentum") or momentum_score), 1),
        },
        "30d": {
            "throughput_avg": round(avg_30, 1),
            "momentum_avg": round(float(_window_average(window_30, "state_vector", "momentum") or momentum_score), 1),
        },
    }
    increasing_lines: List[str] = []
    stalling_lines: List[str] = []
    priority_lines: List[str] = []
    if avg_7:
        if day_throughput_total > avg_7:
            increasing_lines.append(f"Today throughput is above the 7-day average ({day_throughput_total:g} vs {avg_7:.1f}).")
        elif abs(day_throughput_total - avg_7) < 0.1:
            increasing_lines.append(f"Today throughput is holding level with the 7-day average ({day_throughput_total:g}).")
    if float(momentum_score) >= float(_window_average(window_7, 'state_vector', 'momentum') or momentum_score):
        increasing_lines.append("Momentum is holding above the recent baseline.")
    strongest_domain = max(throughput_by_domain.items(), key=lambda item: item[1])[0] if any(throughput_by_domain.values()) else ""
    if strongest_domain and throughput_by_domain.get(strongest_domain, 0):
        increasing_lines.append(f"{strongest_domain.title()} is the strongest completed domain today.")
    recurring_candidates = [row for row in priority_candidates if any("seen " in reason for reason in row.get("reasons", []))]
    if recurring_candidates:
        stalling_lines.append(f"{recurring_candidates[0]['task']} keeps resurfacing and needs a real close-loop move.")
    maintenance_open = _safe_int(current_snapshot.get("throughput", {}).get("maintenance_open"))
    maintenance_done_avg = _window_average(window_7, "throughput", "maintenance_completed") or 0.0
    if maintenance_open > max(1.0, maintenance_done_avg):
        stalling_lines.append("Maintenance drag is building faster than it is being closed.")
    if report_status.get("weekly", {}).get("status") == "needs_regeneration":
        stalling_lines.append("Weekly deep analysis exists but is still a placeholder and needs regeneration.")
    for candidate in priority_candidates[:3]:
        reasons = ", ".join(candidate.get("reasons", [])[:2]) or "highest compounding score"
        priority_lines.append(f"{candidate.get('task', '')} — {reasons}.")
    if not increasing_lines:
        increasing_lines.append("The compounding layer is online, but it still needs a few more days of snapshots for stronger trend claims.")
    if not stalling_lines:
        stalling_lines.append("No major repeating stall surfaced beyond the live task load.")
    if not priority_lines:
        priority_lines.append("No compounding priority candidates yet — fall back to the clearest single next task.")

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
        "trend_windows": trend_windows,
        "throughput_by_domain": throughput_by_domain,
        "momentum_delta": momentum_delta,
        "compounding_priority_candidates": priority_candidates,
        "report_status": report_status,
        "built_from_prior_data": {
            "increasing": increasing_lines[:3],
            "stalling": stalling_lines[:3],
            "priority": priority_lines[:3],
        },
        "history_snapshot": current_snapshot,
        "conversation_context": priority_lines[:2] + stalling_lines[:1],
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
    trend_windows = vector.get("trend_windows", {}) if isinstance(vector.get("trend_windows", {}), dict) else {}
    day_window = trend_windows.get("day", {}) if isinstance(trend_windows.get("day", {}), dict) else {}
    week_window = trend_windows.get("7d", {}) if isinstance(trend_windows.get("7d", {}), dict) else {}
    month_window = trend_windows.get("30d", {}) if isinstance(trend_windows.get("30d", {}), dict) else {}
    momentum_delta = vector.get("momentum_delta", {}) if isinstance(vector.get("momentum_delta", {}), dict) else {}
    throughput_by_domain = vector.get("throughput_by_domain", {}) if isinstance(vector.get("throughput_by_domain", {}), dict) else {}
    report_status = vector.get("report_status", {}) if isinstance(vector.get("report_status", {}), dict) else {}
    prior_data = vector.get("built_from_prior_data", {}) if isinstance(vector.get("built_from_prior_data", {}), dict) else {}
    candidates = vector.get("compounding_priority_candidates", []) if isinstance(vector.get("compounding_priority_candidates", []), list) else []
    domain_mix_html = "".join(
        f'<span class="optional-pill text-xs rounded px-2 py-1" style="border:1px solid rgba(148,163,184,0.16);background:rgba(15,23,42,0.42);color:#dbeafe;">{html.escape(domain.title())} {int(count)}</span>'
        for domain, count in sorted(throughput_by_domain.items(), key=lambda item: (-int(item[1]), item[0]))
        if int(count) > 0
    ) or '<span class="text-xs" style="color:#94a3b8">No completed-domain signal yet today.</span>'
    report_status_html = "".join(
        f'<span class="optional-pill text-xs rounded px-2 py-1" style="border:1px solid rgba(148,163,184,0.16);background:rgba(15,23,42,0.42);color:#cbd5e1;">{html.escape(label.title())} {html.escape(str((row if isinstance(row, dict) else {}).get("status", "unknown")))} · {int(round(float((row if isinstance(row, dict) else {}).get("confidence", 0)) * 100))}%</span>'
        for label, row in report_status.items()
        if isinstance(row, dict)
    )
    candidate_html = "".join(
        f'<li class="text-sm mb-1" style="color:#e5e7eb;line-height:1.5;">{html.escape(str(item.get("task", "")))}'
        f'<span style="color:#93c5fd"> — {html.escape(", ".join(item.get("reasons", [])[:2]))}</span></li>'
        for item in candidates[:3]
        if isinstance(item, dict) and str(item.get("task", "")).strip()
    )
    increasing_html = "".join(
        f'<li class="text-sm mb-1" style="color:#d1fae5;line-height:1.5;">{html.escape(str(item))}</li>'
        for item in (prior_data.get("increasing", []) if isinstance(prior_data.get("increasing", []), list) else [])[:3]
        if str(item).strip()
    )
    stalling_html = "".join(
        f'<li class="text-sm mb-1" style="color:#fde68a;line-height:1.5;">{html.escape(str(item))}</li>'
        for item in (prior_data.get("stalling", []) if isinstance(prior_data.get("stalling", []), list) else [])[:3]
        if str(item).strip()
    )
    priority_html = "".join(
        f'<li class="text-sm mb-1" style="color:#dbeafe;line-height:1.5;">{html.escape(str(item))}</li>'
        for item in (prior_data.get("priority", []) if isinstance(prior_data.get("priority", []), list) else [])[:3]
        if str(item).strip()
    )
    delta_7 = float(momentum_delta.get("vs_7d", 0) or 0)
    delta_30 = float(momentum_delta.get("vs_30d", 0) or 0)
    def _delta_text(value: float) -> str:
        if value > 1:
            return f"↑ {value:.1f}"
        if value < -1:
            return f"↓ {abs(value):.1f}"
        return f"→ {abs(value):.1f}"

    return f'''
        <div class="card rounded-xl p-5 mb-4" style="background:rgba(15,23,42,0.72);border:1px solid rgba(125,211,252,0.16);">
            <div class="flex items-start justify-between gap-3 mb-2">
                <div>
                    <p class="text-sm" style="color:#e2e8f0;line-height:1.55;">{html.escape(str(vector.get("headline", "")))}</p>
                </div>
                <span class="text-xs rounded px-2 py-1 flex-shrink-0" style="border:1px solid {overall_palette["border"]};background:{overall_palette["bg"]};color:{overall_palette["text"]};">
                    {html.escape(str(vector.get("overall_score", 0)))} · {html.escape(overall_state)}
                </span>
            </div>
            <div class="flex flex-wrap gap-2 mb-3">{pills_html}</div>
            <details>
                <summary class="text-xs cursor-pointer" style="color:#93c5fd;user-select:none;">Signals &amp; support</summary>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                    <div>
                        <p class="text-xs font-semibold mb-2" style="color:#93c5fd">Compounding signals</p>
                        <ul style="margin:0;padding-left:1rem;">{compounding_html}</ul>
                    </div>
                    <div>
                        <p class="text-xs font-semibold mb-2" style="color:#93c5fd">Progressive support</p>
                        <div class="grid grid-cols-1 gap-2">{support_steps_html}</div>
                    </div>
                </div>
            </details>
            <details class="mt-2">
                <summary class="text-xs cursor-pointer" style="color:#93c5fd;user-select:none;">Throughput &amp; trends</summary>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                    <div class="rounded-lg p-3" style="background:rgba(15,23,42,0.46);border:1px solid rgba(148,163,184,0.14);">
                        <p class="text-xs font-semibold mb-2" style="color:#93c5fd">Throughput &amp; Momentum</p>
                        <div class="grid grid-cols-3 gap-2 text-xs mb-3">
                            <div class="rounded px-2 py-2" style="background:rgba(2,6,23,0.24);color:#e5e7eb;">Today<br><span style="color:#bae6fd">{html.escape(str(day_window.get("throughput_total", 0)))}</span></div>
                            <div class="rounded px-2 py-2" style="background:rgba(2,6,23,0.24);color:#e5e7eb;">7d avg<br><span style="color:#bae6fd">{html.escape(str(week_window.get("throughput_avg", 0)))}</span></div>
                            <div class="rounded px-2 py-2" style="background:rgba(2,6,23,0.24);color:#e5e7eb;">30d avg<br><span style="color:#bae6fd">{html.escape(str(month_window.get("throughput_avg", 0)))}</span></div>
                        </div>
                        <p class="text-xs mb-2" style="color:#cbd5e1">Momentum vs 7d: <span style="color:#a7f3d0">{_delta_text(delta_7)}</span> · vs 30d: <span style="color:#bfdbfe">{_delta_text(delta_30)}</span></p>
                        <div class="flex flex-wrap gap-2 mb-2">{domain_mix_html}</div>
                        <div class="flex flex-wrap gap-2">{report_status_html}</div>
                    </div>
                    <div class="rounded-lg p-3" style="background:rgba(15,23,42,0.46);border:1px solid rgba(148,163,184,0.14);">
                        <p class="text-xs font-semibold mb-2" style="color:#93c5fd">Built from prior data</p>
                        <p class="text-xs mb-1" style="color:#6ee7b7">Increasing</p>
                        <ul style="margin:0;padding-left:1rem;">{increasing_html}</ul>
                        <p class="text-xs mt-2 mb-1" style="color:#fbbf24">Stalling</p>
                        <ul style="margin:0;padding-left:1rem;">{stalling_html}</ul>
                        <p class="text-xs mt-2 mb-1" style="color:#93c5fd">Prioritise next</p>
                        <ul style="margin:0;padding-left:1rem;">{priority_html or candidate_html}</ul>
                    </div>
                </div>
            </details>
            <details class="mt-2">
                <summary class="text-xs cursor-pointer" style="color:#94a3b8;user-select:none;">Dimension detail</summary>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">{detail_rows_html}</div>
            </details>
        </div>
    '''
