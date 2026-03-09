"""Shared freshness + ideas helpers for dashboard generation."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

FRESHNESS_RANK = {"ok": 0, "info": 1, "warn": 2, "error": 3}
SECTION_FRESHNESS_ORDER = [
    "actions",
    "mood",
    "morning",
    "updates",
    "narrative",
    "guidance",
    "evening",
    "review",
    "weekly",
    "health",
    "film",
    "jobs",
    "ideas",
    "pieces",
    "system",
]
SECTION_FRESHNESS_LABELS = {
    "actions": "✅ Actions",
    "mood": "🙂 Mood",
    "morning": "🌅 Morning",
    "updates": "📝 Updates",
    "narrative": "🧭 Narrative",
    "guidance": "💡 Guidance",
    "evening": "🌙 Evening",
    "review": "💭 Review",
    "weekly": "📅 Weekly",
    "health": "🏥 Health",
    "film": "🎬 Film",
    "jobs": "💼 Jobs",
    "ideas": "💡 Ideas",
    "pieces": "🧩 Pieces",
    "system": "🧰 System",
}


def normalize_freshness_level(level: str) -> str:
    value = str(level or "").strip().lower()
    return value if value in FRESHNESS_RANK else "info"


def build_section_freshness_item(
    section_id: str,
    *,
    label: str = "",
    level: str = "info",
    line: str = "",
    updated_at: str = "",
    source_date: str = "",
    stale_reason: str = "",
    fallback_in_use: bool = False,
) -> dict:
    norm_level = normalize_freshness_level(level)
    return {
        "id": str(section_id or "").strip(),
        "label": str(label or SECTION_FRESHNESS_LABELS.get(section_id, section_id.title() or "Section")).strip(),
        "freshness_state": norm_level,
        "level": norm_level,
        "line": str(line or "").strip(),
        "updated_at": str(updated_at or "").strip(),
        "source_date": str(source_date or "").strip(),
        "stale_reason": str(stale_reason or "").strip(),
        "fallback_in_use": bool(fallback_in_use),
    }


def build_section_freshness_registry(
    sections: dict,
    *,
    order: list[str] | None = None,
) -> dict:
    if not isinstance(sections, dict):
        return {"items": {}, "ordered": [], "counts": {}, "worst_level": "info", "attention_count": 0}

    ordered_ids = []
    raw_order = list(order or SECTION_FRESHNESS_ORDER)
    for section_id in raw_order:
        if section_id not in ordered_ids:
            ordered_ids.append(section_id)
    for section_id in sections.keys():
        if section_id not in ordered_ids:
            ordered_ids.append(section_id)

    items = {}
    counts = {"ok": 0, "info": 0, "warn": 0, "error": 0}
    worst_level = "ok"
    attention_count = 0

    for section_id in ordered_ids:
        raw_item = sections.get(section_id)
        if not isinstance(raw_item, dict):
            continue
        item = build_section_freshness_item(
            section_id,
            label=raw_item.get("label", ""),
            level=raw_item.get("level", raw_item.get("freshness_state", "info")),
            line=raw_item.get("line", ""),
            updated_at=raw_item.get("updated_at", ""),
            source_date=raw_item.get("source_date", ""),
            stale_reason=raw_item.get("stale_reason", ""),
            fallback_in_use=bool(raw_item.get("fallback_in_use", False)),
        )
        items[section_id] = item
        level = item.get("level", "info")
        counts[level] = counts.get(level, 0) + 1
        if FRESHNESS_RANK.get(level, 1) > FRESHNESS_RANK.get(worst_level, 0):
            worst_level = level
        if level in {"warn", "error"}:
            attention_count += 1

    ordered = [items[section_id] for section_id in ordered_ids if section_id in items]
    return {
        "items": items,
        "ordered": ordered,
        "counts": counts,
        "worst_level": worst_level,
        "attention_count": attention_count,
    }


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
    diarium_fresh: bool = True,
) -> dict:
    use_diarium_slots = bool(diarium_fresh)
    morning_slot = (
        str((morning or {}).get("mood_tag", "") or "").strip().lower() if use_diarium_slots else ""
    ) or "unknown"
    evening_slot = (
        str((evening or {}).get("mood_tag", "") or "").strip().lower() if use_diarium_slots else ""
    ) or "unknown"
    rows = mood_entries if isinstance(mood_entries, list) else []

    if morning_slot == "unknown":
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            source = str(row.get("source", "") or "").strip().lower()
            if (not use_diarium_slots) and source == "diarium":
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
            source = str(row.get("source", "") or "").strip().lower()
            if (not use_diarium_slots) and source == "diarium":
                continue
            label = str(row.get("label", "") or row.get("mood", "")).strip().lower()
            context = str(row.get("context", "") or "").strip().lower()
            if not label:
                continue
            if context == "evening":
                evening_slot = label
                break

    if not use_diarium_slots and morning_slot == "unknown" and evening_slot == "unknown":
        return {"line": "⚠️ Mood slots unavailable while journal is stale. Add a manual mood check-in.", "level": "warn"}
    if morning_slot == "unknown":
        return {"line": "⚠️ Morning mood slot missing.", "level": "warn"}
    if evening_slot == "unknown" and current_hour >= 23:
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
        "auto_open": overall_level in {"error", "warn"},
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


def _compact_ai_path_pill_label(ai_path_line: str) -> str:
    raw = str(ai_path_line or "").strip()
    lower = raw.lower()
    if "last run:" in lower:
        label = raw.split(":", 1)[1].split("•", 1)[0].strip()
        if label:
            return f"🤖 {label}"
    if "no calls yet" in lower:
        return "🤖 Ready"
    if "unavailable" in lower:
        return "🤖 AI path"
    return "🤖 AI"


def _compact_ai_path_pill_short_label(ai_path_line: str) -> str:
    full_label = _compact_ai_path_pill_label(ai_path_line)
    lower = full_label.lower()
    if "codex cli" in lower:
        return "🤖 CLI"
    if "claude" in lower:
        return "🤖 Claude"
    if "ready" in lower:
        return "🤖 Ready"
    return "🤖 AI"


def _compact_freshness_pill_label(level: str) -> str:
    return {
        "ok": "🧭 Fresh",
        "info": "🧭 Watching",
        "warn": "🧭 Attention",
        "error": "🧭 Stale",
    }.get(normalize_freshness_level(level), "🧭 Watching")


def _compact_freshness_pill_short_label(level: str) -> str:
    return {
        "ok": "🧭 Fresh",
        "info": "🧭 Watch",
        "warn": "🧭 Alert",
        "error": "🧭 Stale",
    }.get(normalize_freshness_level(level), "🧭 Watch")


def _ideas_compact_status(ideas_payload: dict, clock_hhmm: Callable[[str], str]) -> dict:
    payload = ideas_payload if isinstance(ideas_payload, dict) else {}
    status = str(payload.get("status", "") or "").strip().lower() or "unknown"
    counts = payload.get("counts", {}) if isinstance(payload.get("counts", {}), dict) else {}
    ideas_new = _safe_int(counts.get("new_items", payload.get("new_items_count", 0)))
    ideas_created = _safe_int(counts.get("beads_created", 0))
    ideas_failed = _safe_int(counts.get("beads_failed", 0))
    ideas_retried = _safe_int(counts.get("retried", 0))
    ideas_retry_queue = _safe_int(payload.get("retry_queue_count", 0))
    ideas_last_run = str(payload.get("last_run", "") or "").strip()
    last_run_label = clock_hhmm(ideas_last_run) or ideas_last_run[:16]

    level = "ok"
    label = "💡 Ideas ok"
    if status not in {"success", "ok"}:
        level = "error" if status == "error" else "warn"
        label = "💡 Ideas issue"
    elif ideas_failed or ideas_retry_queue:
        level = "warn"
        label = "💡 Ideas retry"
    elif ideas_new or ideas_created:
        level = "ok"
        label = f"💡 {ideas_new or ideas_created} new"
    elif ideas_retried:
        level = "info"
        label = "💡 Ideas checked"

    if last_run_label:
        label = f"{label} {last_run_label}"

    title_bits = [
        f"status {status}",
        f"new {ideas_new}",
        f"beads {ideas_created}",
        f"failed {ideas_failed}",
        f"retried {ideas_retried}",
        f"queue {ideas_retry_queue}",
    ]
    if ideas_last_run:
        title_bits.append(f"last run {ideas_last_run}")
    return {
        "label": label,
        "short_label": (
            "💡 issue"
            if status not in {"success", "ok"}
            else "💡 retry"
            if ideas_failed or ideas_retry_queue
            else f"💡 {ideas_new or ideas_created} new"
            if ideas_new or ideas_created
            else "💡 checked"
            if ideas_retried
            else "💡 ok"
        ),
        "level": level,
        "title": " • ".join(title_bits),
    }


def build_backend_status_pills_html(
    *,
    ai_path_line: str,
    ai_path_level: str,
    freshness_overall_line: str,
    freshness_overall_level: str,
    ideas_payload: dict,
    section_registry: dict,
    clock_hhmm: Callable[[str], str],
) -> str:
    ai_label = _compact_ai_path_pill_label(ai_path_line)
    ai_short_label = _compact_ai_path_pill_short_label(ai_path_line)
    fresh_label = _compact_freshness_pill_label(freshness_overall_level)
    fresh_short_label = _compact_freshness_pill_short_label(freshness_overall_level)
    ideas_meta = _ideas_compact_status(ideas_payload, clock_hhmm)
    section_payload = section_registry if isinstance(section_registry, dict) else {}
    section_attention_count = int(section_payload.get("attention_count", 0) or 0)
    section_level = normalize_freshness_level(section_payload.get("worst_level", "info"))
    section_label = (
        f"🧭 Sections {section_attention_count}"
        if section_attention_count
        else "🧭 Sections ok"
    )
    section_short_label = (
        f"🧭 Sect {section_attention_count}"
        if section_attention_count
        else "🧭 Sect ok"
    )
    section_title = (
        f"Section freshness • attention {section_attention_count} • "
        f"ok {section_payload.get('counts', {}).get('ok', 0) if isinstance(section_payload.get('counts', {}), dict) else 0} • "
        f"info {section_payload.get('counts', {}).get('info', 0) if isinstance(section_payload.get('counts', {}), dict) else 0} • "
        f"warn {section_payload.get('counts', {}).get('warn', 0) if isinstance(section_payload.get('counts', {}), dict) else 0} • "
        f"error {section_payload.get('counts', {}).get('error', 0) if isinstance(section_payload.get('counts', {}), dict) else 0}"
    )
    pill_defs = [
        {
            "id": "qa-fresh-ai-path-inline",
            "level": normalize_freshness_level(ai_path_level),
            "label": ai_label,
            "short_label": ai_short_label,
            "title": ai_path_line,
        },
        {
            "id": "qa-backend-fresh-pill",
            "level": normalize_freshness_level(freshness_overall_level),
            "label": fresh_label,
            "short_label": fresh_short_label,
            "title": freshness_overall_line,
        },
        {
            "id": "qa-backend-ideas-pill",
            "level": normalize_freshness_level(ideas_meta.get("level", "info")),
            "label": str(ideas_meta.get("label", "💡 Ideas")),
            "short_label": str(ideas_meta.get("short_label", "💡 ok")),
            "title": str(ideas_meta.get("title", "")),
        },
        {
            "id": "qa-backend-sections-pill",
            "level": section_level,
            "label": section_label,
            "short_label": section_short_label,
            "title": section_title,
        },
    ]
    summary_level = "ok"
    attention_count = 0
    summary_title_bits = []
    for pill in pill_defs:
        level = normalize_freshness_level(pill.get("level", "info"))
        if FRESHNESS_RANK.get(level, 1) > FRESHNESS_RANK.get(summary_level, 0):
            summary_level = level
        if level in {"warn", "error"}:
            attention_count += 1
        title = str(pill.get("title", "")).strip()
        label = str(pill.get("label", "")).strip()
        summary_title_bits.append(f"{label} — {title}" if title else label)
    summary_label = {
        "ok": "🟢 Live ok",
        "info": "🔵 Live watching",
        "warn": f"🟡 Live attention {attention_count}" if attention_count else "🟡 Live attention",
        "error": f"🔴 Live alert {attention_count}" if attention_count else "🔴 Live alert",
    }.get(summary_level, "🔵 Live watching")
    summary_short_label = {
        "ok": "🟢 Live",
        "info": "🔵 Live",
        "warn": "🟡 Live",
        "error": "🔴 Live",
    }.get(summary_level, "🔵 Live")
    show_details = attention_count > 0
    summary_hidden_attr = ' hidden="hidden"' if show_details else ""
    detail_hidden_attr = "" if show_details else ' hidden="hidden"'
    parts = [
        '<span class="backend-pill-row" role="note" aria-label="Live status summary">',
        (
            f'<span id="qa-backend-summary-pill" class="backend-pill backend-pill-summary" '
            f'data-level="{html.escape(summary_level, quote=True)}" '
            f'data-full-label="{html.escape(summary_label, quote=True)}" '
            f'data-short-label="{html.escape(summary_short_label, quote=True)}" '
            f'title="{html.escape(" • ".join(summary_title_bits), quote=True)}"{summary_hidden_attr}>'
            f'{html.escape(summary_label)}</span>'
        ),
    ]
    for pill in pill_defs:
        parts.append(
            f'<span id="{html.escape(str(pill.get("id", "")), quote=True)}" '
            f'class="backend-pill backend-pill-detail" '
            f'data-level="{html.escape(normalize_freshness_level(pill.get("level", "info")), quote=True)}" '
            f'data-full-label="{html.escape(str(pill.get("label", "")), quote=True)}" '
            f'data-short-label="{html.escape(str(pill.get("short_label", pill.get("label", ""))), quote=True)}" '
            f'title="{html.escape(str(pill.get("title", "")), quote=True)}"{detail_hidden_attr}>'
            f'{html.escape(str(pill.get("label", "")))}</span>'
        )
    parts.append("</span>")
    return "".join(parts)


def build_section_freshness_html(section_registry: dict, clock_hhmm: Callable[[str], str]) -> str:
    registry = section_registry if isinstance(section_registry, dict) else {}
    ordered = registry.get("ordered", []) if isinstance(registry.get("ordered", []), list) else []
    if not ordered:
        return ""

    counts = registry.get("counts", {}) if isinstance(registry.get("counts", {}), dict) else {}
    attention_count = int(registry.get("attention_count", 0) or 0)
    worst_level = normalize_freshness_level(registry.get("worst_level", "info"))
    summary_label = (
        f"🧭 Section freshness ({attention_count} need attention)"
        if attention_count
        else "🧭 Section freshness (all monitored)"
    )
    summary_colour = {
        "ok": "#a7f3d0",
        "info": "#93c5fd",
        "warn": "#fde68a",
        "error": "#fca5a5",
    }.get(worst_level, "#93c5fd")
    details_open = " open" if attention_count else ""

    badge_rows = []
    for item in ordered:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        level = normalize_freshness_level(item.get("level", "info"))
        tone = {
            "ok": ("🟢", "#a7f3d0", "rgba(6,95,70,0.22)", "rgba(110,231,183,0.22)"),
            "info": ("🔵", "#bfdbfe", "rgba(30,64,175,0.18)", "rgba(147,197,253,0.22)"),
            "warn": ("🟡", "#fde68a", "rgba(120,53,15,0.22)", "rgba(251,191,36,0.22)"),
            "error": ("🔴", "#fca5a5", "rgba(127,29,29,0.22)", "rgba(239,68,68,0.22)"),
        }.get(level, ("🔵", "#bfdbfe", "rgba(30,64,175,0.18)", "rgba(147,197,253,0.22)"))
        updated_at = str(item.get("updated_at", "")).strip()
        source_date = str(item.get("source_date", "")).strip()
        stale_reason = str(item.get("stale_reason", "")).strip()
        fallback_in_use = bool(item.get("fallback_in_use"))
        line = str(item.get("line", "")).strip()
        meta_bits = []
        if source_date:
            meta_bits.append(f"source {html.escape(source_date)}")
        if updated_at:
            pretty_updated = clock_hhmm(updated_at) or updated_at[:16]
            meta_bits.append(f"updated {html.escape(pretty_updated)}")
        if fallback_in_use:
            meta_bits.append("fallback")
        meta_html = (
            f'<p class="text-xs mt-1" style="color:#94a3b8">{" • ".join(meta_bits)}</p>'
            if meta_bits else ""
        )
        reason_html = (
            f'<p class="text-xs mt-1" style="color:#fcd34d">{html.escape(stale_reason)}</p>'
            if stale_reason and level in {"warn", "error"} else ""
        )
        badge_rows.append(
            f'<div class="rounded-lg px-3 py-2.5" style="border:1px solid {tone[3]}; background:{tone[2]};">'
            f'<div class="flex items-center gap-2 flex-wrap">'
            f'<span class="text-xs font-semibold" style="color:{tone[1]}">{tone[0]} {html.escape(label)}</span>'
            f'</div>'
            f'<p class="text-xs mt-1" style="color:#e5e7eb">{html.escape(line or "No freshness note.")}</p>'
            f'{meta_html}'
            f'{reason_html}'
            f'</div>'
        )

    counts_label = (
        f"ok {counts.get('ok', 0)} • info {counts.get('info', 0)} • "
        f"warn {counts.get('warn', 0)} • error {counts.get('error', 0)}"
    )
    rows_html = "".join(badge_rows)
    return f'''
    <div class="card mt-2" style="border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.58);">
        <details{details_open}>
            <summary class="text-sm font-semibold cursor-pointer" style="color: {summary_colour};">{html.escape(summary_label)}</summary>
            <p class="text-xs mt-2" style="color:#94a3b8">Every major card now reports its own freshness state • {html.escape(counts_label)}</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                {rows_html}
            </div>
        </details>
    </div>'''

def _is_same_day_iso(raw_value: str, date_key: str) -> bool:
    return bool(str(raw_value or "").strip().startswith(str(date_key or "").strip()))

def _latest_timestamp_from_rows(rows: list) -> str:
    latest = ""
    if not isinstance(rows, list):
        return latest
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("timestamp", "updated_at", "logged_at", "created_at", "captured_at"):
            raw = str(row.get(key, "") or "").strip()
            if raw and raw > latest:
                latest = raw
    return latest

def _file_mtime_iso(path: Path | str | None) -> str:
    if not path:
        return ""
    try:
        file_path = Path(path)
    except Exception:
        return ""
    if not file_path.exists():
        return ""
    try:
        return datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
    except Exception:
        return ""

def build_today_section_freshness_registry(
    cache: dict,
    *,
    today: str,
    cache_timestamp: str,
    diarium_fresh: bool,
    diarium_source_date: str,
    diarium_fresh_reason: str,
    morning_note: str,
    evening_note: str,
    diary_updates: str,
    guidance_lines: list,
    action_items: list,
    future_action_items: list,
    action_items_updated_at: str,
    action_items_stale_reason: str,
    ideas_payload: dict,
    mood_entries: list,
    mood_state: dict,
    updates_state: dict,
    cache_state: dict,
    narrative_state: dict,
    weekly_current_file: Path | str | None = None,
    now: datetime | None = None,
) -> dict:
    payload = cache if isinstance(cache, dict) else {}
    now_dt = now if isinstance(now, datetime) else datetime.now()
    hour_now = now_dt.hour
    film_data = payload.get("film_data", {}) if isinstance(payload.get("film_data", {}), dict) else {}
    pieces_activity = payload.get("pieces_activity", {}) if isinstance(payload.get("pieces_activity", {}), dict) else {}
    calendar_data = payload.get("calendar", {}) if isinstance(payload.get("calendar", {}), dict) else {}
    job_boards = payload.get("job_boards", {}) if isinstance(payload.get("job_boards", {}), dict) else {}
    linkedin_jobs = payload.get("linkedin_jobs", {}) if isinstance(payload.get("linkedin_jobs", {}), dict) else {}
    applications = payload.get("applications", {}) if isinstance(payload.get("applications", {}), dict) else {}
    healthfit = payload.get("healthfit", {}) if isinstance(payload.get("healthfit", {}), dict) else {}
    streaks = payload.get("streaks", {}) if isinstance(payload.get("streaks", {}), dict) else {}
    apple_health = payload.get("apple_health", {}) if isinstance(payload.get("apple_health", {}), dict) else {}
    autosleep = payload.get("autosleep", {}) if isinstance(payload.get("autosleep", {}), dict) else {}

    mood_updated_at = _latest_timestamp_from_rows(mood_entries)
    actions_today_count = len(action_items) if isinstance(action_items, list) else 0
    actions_future_count = len(future_action_items) if isinstance(future_action_items, list) else 0
    actions_total = actions_today_count + actions_future_count
    if _is_same_day_iso(action_items_updated_at, today):
        actions_level = "ok" if actions_total else "info"
        actions_line = (
            f"Action queue current • today {actions_today_count} • future {actions_future_count}"
            if actions_total else "Action queue checked today • no current or future items."
        )
        actions_reason = ""
    else:
        actions_level = "warn"
        actions_line = "Action queue may be stale."
        actions_reason = action_items_stale_reason or "Dashboard action queue has not been regenerated for today."

    if diarium_fresh and morning_note:
        morning_level = "ok"
        morning_line = "Morning section is sourced from today's journal."
        morning_reason = ""
    elif not diarium_fresh:
        morning_level = "warn"
        morning_line = "Morning section hidden because journal source is stale."
        morning_reason = diarium_fresh_reason
    elif hour_now < 12:
        morning_level = "info"
        morning_line = "Morning section waiting for more written input."
        morning_reason = ""
    else:
        morning_level = "warn"
        morning_line = "Morning section is thin or missing."
        morning_reason = "No morning note content was found for today's journal."

    if diarium_fresh and evening_note:
        evening_level = "ok"
        evening_line = "Evening section is ready from today's journal."
        evening_reason = ""
    elif not diarium_fresh:
        evening_level = "warn"
        evening_line = "Evening section hidden because journal source is stale."
        evening_reason = diarium_fresh_reason
    elif hour_now < 18:
        evening_level = "info"
        evening_line = "Evening section not expected yet."
        evening_reason = ""
    elif hour_now < 23:
        evening_level = "info"
        evening_line = "Evening section still waiting for reflection."
        evening_reason = ""
    else:
        evening_level = "warn"
        evening_line = "Evening section still missing late in the day."
        evening_reason = "No evening reflection found after the evening window."

    if guidance_lines:
        guidance_level = "ok" if diarium_fresh else "info"
        guidance_line = f"Guidance ready • {len(guidance_lines)} line{'s' if len(guidance_lines) != 1 else ''}."
        guidance_reason = diarium_fresh_reason if not diarium_fresh else ""
    elif not diarium_fresh:
        guidance_level = "warn"
        guidance_line = "Guidance suppressed because today's journal source is stale."
        guidance_reason = diarium_fresh_reason
    elif hour_now < 10:
        guidance_level = "info"
        guidance_line = "Guidance still warming up for the day."
        guidance_reason = ""
    else:
        guidance_level = "warn"
        guidance_line = "Guidance missing despite fresh day data."
        guidance_reason = "No guidance lines were generated."

    review_level = "ok" if calendar_data.get("status") == "success" else "warn"
    review_line = (
        f"Review section ready • {len(calendar_data.get('events', []))} calendar event(s)."
        if review_level == "ok" else "Review section missing calendar data."
    )
    review_reason = "" if review_level == "ok" else str(calendar_data.get("message", "")).strip()

    weekly_exists = bool(weekly_current_file and Path(weekly_current_file).exists())
    iso_week = now_dt.isocalendar()
    weekly_label = f"{iso_week.year}-W{iso_week.week:02d}"
    weekly_needs_generation = bool(iso_week.weekday == 7 and not weekly_exists)
    if weekly_exists:
        weekly_level = "ok"
        weekly_line = f"Weekly digest current for {weekly_label}."
        weekly_reason = ""
    elif weekly_needs_generation:
        weekly_level = "warn"
        weekly_line = "Weekly digest due today."
        weekly_reason = "Current week digest file is missing."
    else:
        weekly_level = "info"
        weekly_line = "Weekly digest waiting for Sunday."
        weekly_reason = ""

    health_sources_ok = sum(
        1 for source_payload in (healthfit, streaks, apple_health, autosleep)
        if isinstance(source_payload, dict) and str(source_payload.get("status", "")).strip().lower() == "success"
    )
    health_updated_at = (
        str(streaks.get("updated_at", "")).strip()
        or str(healthfit.get("latest_date", "")).strip()
        or cache_timestamp
    )
    if health_sources_ok >= 2:
        health_level = "ok"
        health_line = f"Health section backed by {health_sources_ok} fresh source(s)."
        health_reason = ""
    elif health_sources_ok == 1:
        health_level = "info"
        health_line = "Health section is running on a thinner source mix."
        health_reason = ""
    else:
        health_level = "warn"
        health_line = "Health section is missing source feeds."
        health_reason = "No health source reported success."

    film_fetched_at = str(film_data.get("fetched_at", "")).strip()
    film_source_date = film_fetched_at[:10] if film_fetched_at else ""
    if film_data.get("status") == "success" and not bool(film_data.get("stale")) and _is_same_day_iso(film_fetched_at, today):
        film_level = "ok"
        film_line = "Film section synced today from Letterboxd."
        film_reason = ""
    elif film_data.get("status") == "success" and not bool(film_data.get("stale")):
        film_level = "info"
        film_line = "Film section available, but last sync was not today."
        film_reason = ""
    else:
        film_level = "warn"
        film_line = "Film section is stale or unavailable."
        film_reason = str(film_data.get("message", "")).strip() or "Letterboxd/film sync needs attention."

    jobs_timestamp = str(job_boards.get("timestamp", "") or job_boards.get("cached_at", "")).strip()
    jobs_today = _is_same_day_iso(jobs_timestamp, today)
    if job_boards.get("status") == "success" and jobs_today:
        jobs_level = "ok"
        jobs_line = f"Jobs section refreshed today • boards {job_boards.get('total_count', 0)}."
        jobs_reason = ""
    elif linkedin_jobs.get("status") == "success" or applications.get("status") == "success":
        jobs_level = "info"
        jobs_line = "Jobs section available from partial feeds."
        jobs_reason = ""
    else:
        jobs_level = "warn"
        jobs_line = "Jobs section is missing live feeds."
        jobs_reason = (
            str(job_boards.get("message", "")).strip()
            or str(linkedin_jobs.get("message", "")).strip()
            or str(applications.get("message", "")).strip()
        )

    ideas_last_run = str(ideas_payload.get("last_run", "")).strip()
    ideas_has_content = bool(ideas_payload.get("has_content"))
    if _is_same_day_iso(ideas_last_run, today):
        ideas_level = "ok" if ideas_has_content else "info"
        ideas_line = "Ideas pickup checked today." if not ideas_has_content else "Ideas pickup ran today with note content."
        ideas_reason = ""
    else:
        ideas_level = "warn"
        ideas_line = "Ideas pickup has not run today."
        ideas_reason = "Ideas card is showing an older run snapshot."

    pieces_fetched_at = str(pieces_activity.get("fetched_at", "")).strip()
    if pieces_activity.get("status") == "ok" and _is_same_day_iso(pieces_fetched_at, today):
        pieces_level = "ok"
        pieces_line = "Pieces section has same-day activity context."
        pieces_reason = ""
    elif pieces_activity.get("status") == "ok":
        pieces_level = "info"
        pieces_line = "Pieces section available, but not refreshed today."
        pieces_reason = ""
    else:
        pieces_level = "warn"
        pieces_line = "Pieces section is unavailable."
        pieces_reason = str(pieces_activity.get("message", "")).strip()

    system_level = str(cache_state.get("level", "info")).strip().lower() or "info"
    system_line = str(cache_state.get("line", "")).strip() or "System freshness inherited from cache state."

    section_rows = {
        "actions": build_section_freshness_item(
            "actions",
            level=actions_level,
            line=actions_line,
            updated_at=action_items_updated_at or cache_timestamp,
            source_date=today,
            stale_reason=actions_reason,
        ),
        "mood": build_section_freshness_item(
            "mood",
            level=str(mood_state.get("level", "info")),
            line=str(mood_state.get("line", "")),
            updated_at=mood_updated_at or cache_timestamp,
            source_date=today,
            stale_reason=diarium_fresh_reason if str(mood_state.get("level", "")) in {"warn", "error"} and not diarium_fresh else "",
            fallback_in_use=not diarium_fresh,
        ),
        "morning": build_section_freshness_item(
            "morning",
            level=morning_level,
            line=morning_line,
            updated_at=cache_timestamp,
            source_date=diarium_source_date or today,
            stale_reason=morning_reason,
            fallback_in_use=not diarium_fresh,
        ),
        "updates": build_section_freshness_item(
            "updates",
            level=str(updates_state.get("level", "info")),
            line=str(updates_state.get("line", "")),
            updated_at=cache_timestamp,
            source_date=diarium_source_date or today,
            stale_reason=diarium_fresh_reason if not diary_updates and not diarium_fresh else "",
            fallback_in_use=not diarium_fresh and bool(diary_updates),
        ),
        "narrative": build_section_freshness_item(
            "narrative",
            level=str(narrative_state.get("level", "info")),
            line=str(narrative_state.get("line", "")),
            updated_at=cache_timestamp,
            source_date=diarium_source_date or today,
            stale_reason="",
            fallback_in_use=not diarium_fresh and str(narrative_state.get("level", "")) in {"warn", "error"},
        ),
        "guidance": build_section_freshness_item(
            "guidance",
            level=guidance_level,
            line=guidance_line,
            updated_at=cache_timestamp,
            source_date=diarium_source_date or today,
            stale_reason=guidance_reason,
            fallback_in_use=not diarium_fresh and bool(guidance_lines),
        ),
        "evening": build_section_freshness_item(
            "evening",
            level=evening_level,
            line=evening_line,
            updated_at=cache_timestamp,
            source_date=diarium_source_date or today,
            stale_reason=evening_reason,
            fallback_in_use=not diarium_fresh,
        ),
        "review": build_section_freshness_item(
            "review",
            level=review_level,
            line=review_line,
            updated_at=cache_timestamp,
            source_date=today,
            stale_reason=review_reason,
        ),
        "weekly": build_section_freshness_item(
            "weekly",
            level=weekly_level,
            line=weekly_line,
            updated_at=_file_mtime_iso(weekly_current_file) if weekly_exists else cache_timestamp,
            source_date=today,
            stale_reason=weekly_reason,
        ),
        "health": build_section_freshness_item(
            "health",
            level=health_level,
            line=health_line,
            updated_at=health_updated_at,
            source_date=today,
            stale_reason=health_reason,
        ),
        "film": build_section_freshness_item(
            "film",
            level=film_level,
            line=film_line,
            updated_at=film_fetched_at,
            source_date=film_source_date or today,
            stale_reason=film_reason,
        ),
        "jobs": build_section_freshness_item(
            "jobs",
            level=jobs_level,
            line=jobs_line,
            updated_at=jobs_timestamp or cache_timestamp,
            source_date=(jobs_timestamp[:10] if jobs_timestamp else today),
            stale_reason=jobs_reason,
        ),
        "ideas": build_section_freshness_item(
            "ideas",
            level=ideas_level,
            line=ideas_line,
            updated_at=ideas_last_run,
            source_date=(ideas_last_run[:10] if ideas_last_run else today),
            stale_reason=ideas_reason,
        ),
        "pieces": build_section_freshness_item(
            "pieces",
            level=pieces_level,
            line=pieces_line,
            updated_at=pieces_fetched_at or cache_timestamp,
            source_date=(pieces_fetched_at[:10] if pieces_fetched_at else today),
            stale_reason=pieces_reason,
        ),
        "system": build_section_freshness_item(
            "system",
            level=system_level,
            line=system_line,
            updated_at=cache_timestamp,
            source_date=today,
            stale_reason="",
        ),
    }
    return build_section_freshness_registry(section_rows)


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
    # Prominent retry alert when items are stuck
    ideas_retry_alert = ""
    if ideas_retry_queue > 0 or ideas_failed > 0:
        _alert_count = ideas_retry_queue or ideas_failed
        ideas_retry_alert = (
            f'<div style="background:rgba(153,27,27,0.18);border:1px solid rgba(248,113,113,0.22);border-radius:0.5rem;padding:0.5rem 0.7rem;margin-top:0.4rem;">'
            f'<p class="text-xs" style="color:#fca5a5;font-weight:600;">⚠️ {_alert_count} item{"s" if _alert_count != 1 else ""} stuck in retry queue</p>'
            f'{ideas_fail_summary}</div>'
        )
        ideas_fail_summary = ""  # already included in alert

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
    ideas_meta = _ideas_compact_status(ideas_payload, clock_hhmm)
    details_open = " open" if ideas_status not in {"success", "ok"} or ideas_new > 0 or ideas_failed > 0 or ideas_retry_queue > 0 else ""

    # Last processed timestamp (when items were actually triaged, not just scanned)
    ideas_last_processed = str(ideas_payload.get("last_processed_at", "") or "").strip()
    ideas_last_processed_clock = clock_hhmm(ideas_last_processed) if ideas_last_processed else ""
    ideas_last_processed_html = ""
    if ideas_last_processed_clock:
        ideas_last_processed_html = f'<p class="text-xs mt-1" style="color: #86efac">Last processed: {html.escape(ideas_last_processed_clock)}</p>'
    elif ideas_last_run:
        # Fall back to last_run if no separate processed timestamp
        ideas_last_processed_html = f'<p class="text-xs mt-1" style="color: #94a3b8">Last checked: {html.escape(clock_hhmm(ideas_last_run) if ideas_last_run else ideas_last_run)}</p>'

    return f'''
    <div id="qa-ideas-status" class="card mt-2" style="border: 1px solid rgba(148,163,184,0.24); background: rgba(15,23,42,0.58);">
        <details{details_open}>
            <summary class="text-sm font-semibold cursor-pointer" style="color: #a7f3d0">{html.escape(str(ideas_meta.get("label", "💡 Ideas pickup")))}</summary>
            <div class="mt-2">
                <p class="text-xs mt-1" style="color: {status_colour};">Status: {html.escape(ideas_status)} • new {ideas_new} • beads {ideas_created} • failed {ideas_failed} • retried {ideas_retried} • queue {ideas_retry_queue}</p>
                {ideas_last_processed_html}
                {ideas_retry_alert}
                {ideas_clean_meta_html}
                {ideas_fail_summary}
                {ideas_cleanup_html}
                {ideas_preview_html}
                {ideas_context_html}
            </div>
        </details>
    </div>'''
