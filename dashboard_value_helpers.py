"""Small shared coercion/format helpers for dashboard generation."""

from __future__ import annotations

from datetime import datetime


def coerce_optional_int(value, min_val: int, max_val: int):
    try:
        if value is None or value == "":
            return None
        n = int(value)
    except Exception:
        return None
    if n < min_val or n > max_val:
        return None
    return n


def coerce_choice(value, allowed, *, empty_value=None):
    raw = str(value or "").strip().lower()
    return raw if raw in allowed else empty_value


def input_num_text(value, min_v, max_v) -> str:
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


def end_day_status_text(state: dict) -> str:
    if not isinstance(state, dict) or not bool(state.get("done_today")):
        return "⬜ End Day not run yet."
    ran_at = str(state.get("ran_at", "")).strip()
    if ran_at:
        try:
            return f"✅ End Day already run at {datetime.fromisoformat(ran_at).strftime('%H:%M')}."
        except Exception:
            pass
    return "✅ End Day already run today."
