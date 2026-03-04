"""Shared freshness + ideas helpers for dashboard generation."""

from __future__ import annotations

import html
import re
from typing import Callable

FRESHNESS_RANK = {"ok": 0, "info": 1, "warn": 2, "error": 3}


def normalize_freshness_level(level: str) -> str:
    value = str(level or "").strip().lower()
    return value if value in FRESHNESS_RANK else "info"


def build_system_status_html(runtime: dict) -> dict:
    if not isinstance(runtime, dict) or not runtime:
        return {"html": "", "needs_attention": False, "cache_age_minutes": None}

    daemon_ok = bool(runtime.get("daemon_ok"))
    api_ok = bool(runtime.get("api_ok"))
    cache_age = runtime.get("cache_age_minutes")
    checked_at = str(runtime.get("checked_at", "")).strip()
    beads_counts = runtime.get("beads", {}) if isinstance(runtime.get("beads", {}), dict) else {}
    remote_access = runtime.get("remote_access", {}) if isinstance(runtime.get("remote_access", {}), dict) else {}

    daemon_label = "🟢 Daemon" if daemon_ok else "🔴 Daemon"
    daemon_style = (
        "color: #6ee7b7; border: 1px solid rgba(110,231,183,0.28); background: rgba(6,95,70,0.22);"
        if daemon_ok
        else "color: #fca5a5; border: 1px solid rgba(239,68,68,0.28); background: rgba(127,29,29,0.22);"
    )
    api_label = "🟢 API" if api_ok else "🔴 API"
    api_style = (
        "color: #93c5fd; border: 1px solid rgba(147,197,253,0.28); background: rgba(30,64,175,0.2);"
        if api_ok
        else "color: #fca5a5; border: 1px solid rgba(239,68,68,0.28); background: rgba(127,29,29,0.22);"
    )

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

    needs_attention = (
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

    if tailscale_url:
        cloudflare_html = ""
    else:
        if cloudflare_url:
            cf_age_text = f"{cloudflare_age}m" if isinstance(cloudflare_age, int) else "?"
            cf_label = "🟢 CF" if cloudflare_state == "fresh" else "🟠 CF"
            cloudflare_html = f'<a href="{html.escape(cloudflare_url + "/dashboard", quote=True)}" class="system-inline" target="_blank" rel="noopener">{cf_label} {cf_age_text}</a>'
        else:
            cloudflare_html = '<span class="system-inline">⚪ CF</span>'

    html_block = f'''
    <section class="settings-rail system-rail" aria-label="System status">
        <div class="system-line">
            <span class="settings-inline-label">🧩 System</span>
            <button id="sys-heal-btn" onclick="qaHealSystem(this)" class="system-chip system-chip-action" style="background: rgba(6,95,70,0.28); color: #a7f3d0; border: 1px solid rgba(110,231,183,0.3);">🛠️</button>
            <span id="sys-daemon-badge" class="system-chip" style="{daemon_style}">{daemon_label}</span>
            <span id="sys-api-badge" class="system-chip" style="{api_style}">{api_label}</span>
            <span id="sys-cache-badge" class="system-chip" title="Data last refreshed {cache_age if isinstance(cache_age, int) else '?'} min ago — red means some sections may show yesterday&apos;s content" style="{cache_style}">{cache_label}</span>
            <span id="sys-beads-summary" class="system-inline">{beads_summary}</span>
            <span id="sys-checked-at" class="system-inline">{checked_text}</span>
            {tailscale_html}
            {cloudflare_html}
        </div>
    </section>'''
    return {"html": html_block, "needs_attention": needs_attention, "cache_age_minutes": cache_age if isinstance(cache_age, int) else None}


def compute_cache_freshness(cache_age_minutes) -> dict:
    if isinstance(cache_age_minutes, int) and cache_age_minutes <= 10:
        return {"line": f"✅ Cache age healthy ({cache_age_minutes}m).", "level": "ok"}
    if isinstance(cache_age_minutes, int) and cache_age_minutes <= 60:
        return {"line": f"🟡 Cache aging ({cache_age_minutes}m) — watching.", "level": "info"}
    if isinstance(cache_age_minutes, int):
        return {"line": f"⚠️ Cache stale ({cache_age_minutes}m) — refresh recommended.", "level": "warn"}
    return {"line": "ℹ️ Cache age unknown.", "level": "info"}


def compute_diarium_freshness(diarium_fresh: bool, source_date: str, effective_today: str) -> dict:
    source = str(source_date or "").strip()
    if diarium_fresh:
        if source and source != effective_today:
            return {"line": f"⚠️ Journal date mismatch ({source} vs {effective_today}).", "level": "warn"}
        source_label = source or effective_today
        return {"line": f"✅ Journal source is today ({source_label}).", "level": "ok"}
    return {"line": f"🔴 Journal stale (source: {source or 'unknown'}).", "level": "error"}


def compute_diarium_pickup_freshness(diarium_pickup: dict, clock_hhmm: Callable[[str], str]) -> dict:
    payload = diarium_pickup if isinstance(diarium_pickup, dict) else {}
    pickup_status = str(payload.get("status", "") or "").strip().lower()
    pickup_reason = str(payload.get("reason", "") or "").strip()
    pickup_file = str(payload.get("latest_file", "") or "").strip()
    pickup_file_name = pickup_file.split("/")[-1] if pickup_file else "none"
    pickup_mtime = str(payload.get("latest_file_mtime", "") or "").strip()
    pickup_age = payload.get("latest_file_age_seconds")
    try:
        pickup_age = int(pickup_age) if pickup_age is not None else None
    except Exception:
        pickup_age = None
    if pickup_age is None:
        pickup_age_text = "?"
    elif pickup_age < 3600:
        pickup_age_text = f"{pickup_age // 60}m"
    else:
        pickup_age_text = f"{pickup_age // 3600}h"
    pickup_mtime_text = clock_hhmm(pickup_mtime) if pickup_mtime else ""
    if not pickup_mtime_text:
        pickup_mtime_text = pickup_mtime[:16] if pickup_mtime else "unknown"
    pickup_label = pickup_status or "unknown"
    line = f"📓 Pickup: {pickup_label} • {pickup_file_name} • mtime {pickup_mtime_text} • age {pickup_age_text}"
    if pickup_reason:
        line += f" • {pickup_reason}"
    pickup_level_map = {
        "picked_up": "ok",
        "waiting_for_export": "info",
        "export_seen_not_parsed": "warn",
        "stale": "warn",
    }
    return {"line": line, "level": pickup_level_map.get(pickup_status, "info")}


def compute_mood_freshness(
    morning: dict,
    evening: dict,
    mood_entries,
    *,
    current_hour: int,
) -> dict:
    morning_slot = str((morning or {}).get("mood_tag", "") or "").strip().lower() or "unknown"
    evening_slot = str((evening or {}).get("mood_tag", "") or "").strip().lower() or "unknown"
    rows = mood_entries if isinstance(mood_entries, list) else []

    if morning_slot == "unknown":
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "") or row.get("mood", "")).strip().lower()
            context = str(row.get("context", "") or "").strip().lower()
            if not label:
                continue
            if context in {"morning", "general", ""}:
                morning_slot = label
                break

    if evening_slot == "unknown":
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "") or row.get("mood", "")).strip().lower()
            context = str(row.get("context", "") or "").strip().lower()
            if not label:
                continue
            if context == "evening":
                evening_slot = label
                break

    if morning_slot == "unknown":
        return {"line": "⚠️ Morning mood slot missing.", "level": "warn"}
    if evening_slot == "unknown" and current_hour >= 20:
        return {"line": f"⚠️ Evening mood slot still missing (morning: {morning_slot}).", "level": "warn"}
    if evening_slot == "unknown":
        return {"line": f"🟡 Mood slots: morning {morning_slot}, evening pending.", "level": "info"}
    return {"line": f"✅ Mood slots split: morning {morning_slot}, evening {evening_slot}.", "level": "ok"}


def build_stale_notice_html(*, diarium_fresh: bool, source_date: str, reason: str) -> str:
    if diarium_fresh:
        return ""
    src = str(source_date or "").strip() or "unknown"
    why = str(reason or "").strip() or "Latest Diarium export does not match today's effective date."
    return f'''
    <div class="card" style="border: 1px solid rgba(251,191,36,0.35); background: rgba(120,53,15,0.18);">
        <p class="text-sm font-semibold" style="color: #fde68a">⚠️ Diarium data is stale</p>
        <p class="text-xs mt-1" style="color: #fcd34d">Source date: {html.escape(src)} • {html.escape(why)}</p>
        <p class="text-xs mt-1" style="color: #9ca3af">Morning/Evening journal sections are hidden until a fresh export is detected.</p>
    </div>'''


def build_important_thing_warning_html(*, diarium_fresh: bool, important_thing_missing: bool) -> str:
    if (not diarium_fresh) or (not important_thing_missing):
        return ""
    return '''
    <div class="card mt-2" style="border: 1px solid rgba(251,191,36,0.35); background: rgba(120,53,15,0.16);">
        <p class="text-sm font-semibold" style="color: #fde68a">⚠️ Missing “important thing” in morning transcription</p>
        <p class="text-xs mt-1" style="color: #fcd34d">Add one priority action in morning pages so today’s focus can be extracted cleanly.</p>
    </div>'''


def compute_freshness_overview(
    *,
    diarium_fresh_level: str,
    diarium_pickup_level: str,
    narrative_fresh_level: str,
    updates_freshness_level: str,
    mood_fresh_level: str,
    cache_fresh_level: str,
) -> dict:
    updates_fresh_level = normalize_freshness_level(updates_freshness_level)
    overall_rank = max(
        FRESHNESS_RANK.get(normalize_freshness_level(diarium_fresh_level), 1),
        FRESHNESS_RANK.get(normalize_freshness_level(diarium_pickup_level), 1),
        FRESHNESS_RANK.get(normalize_freshness_level(narrative_fresh_level), 1),
        FRESHNESS_RANK.get(updates_fresh_level, 1),
        FRESHNESS_RANK.get(normalize_freshness_level(mood_fresh_level), 1),
        FRESHNESS_RANK.get(normalize_freshness_level(cache_fresh_level), 1),
    )
    if overall_rank >= 3:
        overall_line = "🔴 Freshness auto-check: critical issue detected."
        overall_level = "error"
    elif overall_rank >= 2:
        overall_line = "🟡 Freshness auto-check: issue detected, dashboard is guarding."
        overall_level = "warn"
    elif overall_rank == 1:
        overall_line = "🔵 Freshness auto-check: waiting for later-day inputs."
        overall_level = "info"
    else:
        overall_line = "🟢 Freshness auto-check: all clear."
        overall_level = "ok"
    return {
        "updates_fresh_level": updates_fresh_level,
        "overall_line": overall_line,
        "overall_level": overall_level,
        "auto_open": overall_level in {"warn", "error"},
    }


def friendly_ai_path_name(raw_path: str) -> str:
    path_key = str(raw_path or "").strip().lower()
    if path_key.startswith("ai_claude_cli"):
        return "Claude CLI"
    if path_key.startswith("ai_codex_cli"):
        return "Codex CLI"
    if path_key.startswith("ai_codex"):
        return "Codex API"
    if path_key.startswith("ai_claude_api"):
        return "Claude API"
    if path_key.startswith("heuristic"):
        return "Heuristic fallback"
    if path_key.startswith("error"):
        return "Error fallback"
    return "Unknown"


def resolve_ai_path_status(data: dict, clock_hhmm: Callable[[str], str]) -> dict:
    ai_path_payload = data.get("aiPathStatus", {}) if isinstance(data.get("aiPathStatus", {}), dict) else {}
    ai_last_path = str(ai_path_payload.get("last_path", "") or "").strip()
    ai_last_timestamp = str(ai_path_payload.get("last_timestamp", "") or "").strip()
    ai_last_clock = clock_hhmm(ai_last_timestamp) if ai_last_timestamp else ""
    ai_status = str(ai_path_payload.get("status", "") or "").strip().lower()
    ai_recent_count = _safe_int(ai_path_payload.get("recent_count", 0))

    if not ai_last_path:
        ai_insights = data.get("aiInsights", {}) if isinstance(data.get("aiInsights", {}), dict) else {}
        intervention_selector = ai_insights.get("intervention_selector", {}) if isinstance(ai_insights.get("intervention_selector", {}), dict) else {}
        schedule_analysis = data.get("schedule_analysis", {}) if isinstance(data.get("schedule_analysis", {}), dict) else {}
        diarium_analysis = data.get("diariumAnalysis", {}) if isinstance(data.get("diariumAnalysis", {}), dict) else {}
        fallback_candidates = [
            ("ai_insights.generator_path", ai_insights.get("generator_path", "")),
            ("ai_insights.intervention_selector.path", intervention_selector.get("path", "")),
            ("schedule_analysis.path", schedule_analysis.get("path", "")),
            ("diarium.analysis_path", diarium_analysis.get("analysis_path", "")),
        ]
        for _fallback_label, fallback_path in fallback_candidates:
            candidate = str(fallback_path or "").strip()
            if not candidate:
                continue
            candidate_key = candidate.lower()
            if not (candidate_key.startswith("ai_") or candidate_key.startswith("heuristic") or candidate_key.startswith("error")):
                continue
            ai_last_path = candidate
            ai_status = "cached_fallback"
            break

    line = "ℹ️ AI path telemetry unavailable."
    level = "info"
    ai_path_lower = ai_last_path.lower()
    if ai_last_path:
        ai_path_label = friendly_ai_path_name(ai_last_path)
        if ai_path_lower.startswith("ai_claude_cli"):
            level = "ok"
        elif ai_path_lower.startswith("heuristic"):
            level = "warn"
        elif ai_path_lower.startswith("error"):
            level = "error"
        line = f"🤖 AI path last run: {ai_path_label}"
        if ai_last_clock:
            line += f" • {ai_last_clock}"
        if ai_recent_count > 0:
            line += f" • {ai_recent_count} events"
    elif ai_status == "empty":
        line = "ℹ️ AI path telemetry ready (no calls yet this run)."

    return {
        "line": line,
        "level": level,
    }


def build_freshness_watch_html(
    *,
    ai_path_line: str,
    ai_path_level: str,
    freshness_overall_line: str,
    freshness_overall_level: str,
    auto_open: bool,
    diarium_fresh_level: str,
    diarium_fresh_line: str,
    diarium_pickup_level: str,
    diarium_pickup_line: str,
    narrative_fresh_level: str,
    narrative_fresh_line: str,
    updates_fresh_level: str,
    updates_freshness_line: str,
    mood_fresh_level: str,
    mood_fresh_line: str,
    cache_fresh_level: str,
    cache_fresh_line: str,
) -> str:
    details_open = " open" if auto_open else ""
    return f'''
    <div id="qa-freshness-watch" class="card mt-2" style="border: 1px solid rgba(125,211,252,0.28); background: rgba(15,23,42,0.55);">
        <p id="qa-fresh-ai-path-inline" data-level="{ai_path_level}" class="text-xs mb-2" style="color: #cbd5e1">{html.escape(ai_path_line)}</p>
        <details{details_open}>
            <summary id="qa-fresh-overall" data-level="{freshness_overall_level}" class="text-sm font-semibold cursor-pointer" style="color: #a7f3d0">{html.escape(freshness_overall_line)}</summary>
            <div class="mt-2 space-y-1">
                <p id="qa-fresh-diarium" data-level="{diarium_fresh_level}" class="text-xs" style="color: #cbd5e1">{html.escape(diarium_fresh_line)}</p>
                <p id="qa-fresh-diarium-pickup" data-level="{diarium_pickup_level}" class="text-xs" style="color: #94a3b8">{html.escape(diarium_pickup_line)}</p>
                <p id="qa-fresh-narrative" data-level="{narrative_fresh_level}" class="text-xs" style="color: #cbd5e1">{html.escape(narrative_fresh_line)}</p>
                <p id="qa-fresh-updates" data-level="{updates_fresh_level}" class="text-xs" style="color: #cbd5e1">{html.escape(updates_freshness_line)}</p>
                <p id="qa-fresh-mood" data-level="{mood_fresh_level}" class="text-xs" style="color: #cbd5e1">{html.escape(mood_fresh_line)}</p>
                <p id="qa-fresh-cache" data-level="{cache_fresh_level}" class="text-xs" style="color: #cbd5e1">{html.escape(cache_fresh_line)}</p>
                <p id="qa-fresh-ai-path" data-level="{ai_path_level}" class="text-xs" style="color: #cbd5e1">{html.escape(ai_path_line)}</p>
            </div>
            <p id="qa-fresh-updated" class="text-xs mt-2" style="color: #94a3b8">Auto-check runs every 30s while this tab is open.</p>
        </details>
    </div>'''


def narrative_contradiction_reason(
    raw_text: str,
    *,
    current_hour: int,
    tadah_total: int,
    steps_val: int,
    ex_val: int,
    session_type: str,
) -> str:
    text = str(raw_text or "").strip().lower()
    if not text:
        return ""
    if current_hour < 18:
        end_day_mentions = list(re.finditer(r"\b(end(?:ed)?\s+(?:the\s+)?day|end of (?:the )?day)\b", text))
        for match in end_day_mentions:
            start = max(0, match.start() - 24)
            end = min(len(text), match.end() + 28)
            nearby = text[start:end]
            if re.search(r"\b(before|by|until|pending|yet|not|hasn['’]t|haven['’]t|didn['’]t|won['’]t|will)\b", nearby):
                continue
            return "contains end-of-day claim before evening window"
    if current_hour < 18 and re.search(r"\b(no\s+ta[\-\s]?dah|no\s+movement|no\s+health|untracked)\b", text):
        return "contains absence claim before evening window"
    no_tadah_patterns = (
        r"\bno\s+ta[\-\s]?dah\b",
        r"\bno\s+ta[\-\s]?dah\s+items\b",
        r"\bwithout\s+ta[\-\s]?dah\b",
    )
    if int(tadah_total or 0) > 0 and any(re.search(pattern, text) for pattern in no_tadah_patterns):
        return "claims no ta-dah despite recorded ta-dah items"
    has_movement_data = bool((steps_val and steps_val > 0) or (ex_val and ex_val > 0) or str(session_type or "").strip())
    no_movement_patterns = (
        r"\bno health(?:\s+or\s+movement)?\b",
        r"\bno movement\b",
        r"\bno health or movement updates logged\b",
        r"\bremained?\s+untracked\b",
        r"\bleft\s+those\s+parts\s+of\s+the\s+day\s+untracked\b",
        r"\bwithout\s+(?:any\s+)?(?:health|movement)\s+updates\b",
    )
    if has_movement_data and any(re.search(pattern, text) for pattern in no_movement_patterns):
        return "claims no movement/health tracking despite movement data"
    return ""


def is_internalised_tracking_line(raw_line: str) -> bool:
    normalised = re.sub(r"\s+", " ", str(raw_line or "").strip()).lower()
    if not normalised:
        return False
    return bool(
        re.match(
            r"^(?:•\s*)?(?:todo:\s*)?\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[—-]\s*internalised\s+\d+\s+item\(s\);\s*",
            normalised,
            flags=re.IGNORECASE,
        )
    )


def _safe_int(raw, default: int = 0) -> int:
    try:
        return int(raw or 0)
    except Exception:
        return default


def build_ideas_status_html(ideas_payload: dict, clock_hhmm: Callable[[str], str]) -> str:
    if not isinstance(ideas_payload, dict) or not ideas_payload:
        return ""

    ideas_status = str(ideas_payload.get("status", "") or "").strip().lower() or "unknown"
    ideas_counts = ideas_payload.get("counts", {}) if isinstance(ideas_payload.get("counts", {}), dict) else {}
    ideas_new = _safe_int(ideas_counts.get("new_items", ideas_payload.get("new_items_count", 0)))
    ideas_created = _safe_int(ideas_counts.get("beads_created", 0))
    ideas_failed = _safe_int(ideas_counts.get("beads_failed", 0))
    ideas_retried = _safe_int(ideas_counts.get("retried", 0))
    ideas_retry_queue = _safe_int(ideas_payload.get("retry_queue_count", 0))
    ideas_last_run = str(ideas_payload.get("last_run", "") or "").strip()

    ideas_preview = ideas_payload.get("cleaned_note_lines_preview", []) if isinstance(ideas_payload.get("cleaned_note_lines_preview", []), list) else []
    if not ideas_preview:
        ideas_preview = ideas_payload.get("latest_items_preview", []) if isinstance(ideas_payload.get("latest_items_preview", []), list) else []
    ideas_preview = [str(item).strip() for item in ideas_preview if str(item).strip() and not is_internalised_tracking_line(item)]

    ideas_context_text = str(ideas_payload.get("cleaned_note_full_text", "") or "").strip()
    ideas_context_line_count = _safe_int(ideas_payload.get("cleaned_note_line_count", 0))
    if ideas_context_text:
        clean_context_lines = [
            str(line).strip()
            for line in ideas_context_text.splitlines()
            if str(line).strip() and not is_internalised_tracking_line(line)
        ]
        ideas_context_text = "\n".join(clean_context_lines).strip()
        ideas_context_line_count = len(clean_context_lines)

    ideas_snapshot_at = str(ideas_payload.get("cleaned_note_snapshot_at", "") or "").strip()
    ideas_snapshot_clock = clock_hhmm(ideas_snapshot_at) if ideas_snapshot_at else ""
    ideas_filtered_meta = _safe_int(ideas_payload.get("filtered_meta_lines_count", 0))
    ideas_deduped_count = _safe_int(ideas_payload.get("deduped_lines_count", 0))
    ideas_cleanup_closed = _safe_int(ideas_payload.get("cleanup_closed_count", 0))
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
            for item in ideas_preview[:6]
            if str(item).strip()
        )
        if preview_items:
            ideas_preview_html = f'<ul class="text-xs mt-2 space-y-1">{preview_items}</ul>'

    ideas_context_html = ""
    if ideas_context_text:
        ideas_meta_bits = [f"{ideas_context_line_count} line{'s' if ideas_context_line_count != 1 else ''}"]
        if ideas_snapshot_clock:
            ideas_meta_bits.append(f"snapshot {ideas_snapshot_clock}")
        ideas_meta = " • ".join(ideas_meta_bits)
        ideas_context_html = (
            '<details class="mt-2">'
            f'<summary class="text-xs cursor-pointer" style="color: #93c5fd">Context: {html.escape(ideas_meta)}</summary>'
            f'<pre class="text-xs mt-2 p-2 rounded" style="max-height: 180px; overflow: auto; white-space: pre-wrap; background: rgba(15,23,42,0.45); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.18);">{html.escape(ideas_context_text)}</pre>'
            '</details>'
        )

    ideas_cleanup_html = ""
    if ideas_cleanup_closed > 0:
        ideas_cleanup_html = f'<p class="text-xs mt-1" style="color: #86efac">Cleanup: closed {ideas_cleanup_closed} recursive tracking bead(s).</p>'

    ideas_clean_meta_html = (
        f'<p class="text-xs mt-1" style="color: #94a3b8">Cleaned note lines: {ideas_context_line_count} • meta filtered {ideas_filtered_meta} • deduped {ideas_deduped_count}</p>'
    )

    status_colour = "#86efac" if ideas_status == "success" else ("#fca5a5" if ideas_status == "error" else "#fde68a")

    return f'''
    <div class="card mt-2" style="border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.58);">
        <p class="text-sm font-semibold" style="color: #a7f3d0">💡 Ideas pickup</p>
        <p class="text-xs mt-1" style="color: {status_colour};">Status: {html.escape(ideas_status)} • new {ideas_new} • beads {ideas_created} • failed {ideas_failed} • retried {ideas_retried} • queue {ideas_retry_queue}</p>
        {f'<p class="text-xs mt-1" style="color: #94a3b8">Last run: {html.escape(ideas_last_run)}</p>' if ideas_last_run else ''}
        {ideas_clean_meta_html}
        {ideas_fail_summary}
        {ideas_cleanup_html}
        {ideas_preview_html}
        {ideas_context_html}
    </div>'''
