#!/usr/bin/env python3
"""Lock-gated Akiflow task reconciliation.

Rules enforced:
- Never mark completion because task time passed.
- Never mark completion because a task is visible on calendar.
- Only score completion after daily lock confirmation.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import build_runtime_config as _build_cfg

_paths = _build_cfg().paths
CACHE_FILE_DEFAULT = _paths.session_data
TRACKER_DIR_DEFAULT = _paths.akiflow_tracker_dir
LOCK_PHRASE_RE = re.compile(
    r"^✅ Time blocking finalised for (\d{4}-\d{2}-\d{2})\. Please start locked tracking\.$"
)
STATE_ORDER = [
    "scheduled_locked",
    "rescheduled",
    "completed_confirmed",
    "completed_inferred",
    "deleted_or_uncertain",
    "overdue_not_done",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalise_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def extract_date(start: str | None, fallback: str | None) -> str | None:
    if fallback and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fallback)):
        return str(fallback)
    dt = parse_iso(start)
    return dt.date().isoformat() if dt else None


def duration_minutes(start: str | None, end: str | None) -> int | None:
    start_dt = parse_iso(start)
    end_dt = parse_iso(end)
    if not start_dt or not end_dt:
        return None
    minutes = int((end_dt - start_dt).total_seconds() // 60)
    return minutes if minutes >= 0 else None


def completion_signal(raw_task: dict[str, Any]) -> bool:
    if raw_task.get("completed") is True:
        return True
    if raw_task.get("done") is True:
        return True
    status = str(raw_task.get("status", "")).strip().lower()
    return status in {"done", "completed", "complete", "closed"}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def state_path(tracker_dir: Path, date_str: str) -> Path:
    return tracker_dir / f"{date_str}.json"


def load_state(tracker_dir: Path, date_str: str) -> dict[str, Any] | None:
    path = state_path(tracker_dir, date_str)
    if not path.exists():
        return None
    return read_json(path)


def save_state(tracker_dir: Path, date_str: str, payload: dict[str, Any]) -> Path:
    path = state_path(tracker_dir, date_str)
    write_json(path, payload)
    return path


def parse_lock_phrase(phrase: str) -> str:
    match = LOCK_PHRASE_RE.fullmatch(phrase.strip())
    if not match:
        raise ValueError(
            "Lock phrase must exactly be: "
            "✅ Time blocking finalised for YYYY-MM-DD. Please start locked tracking."
        )
    return match.group(1)


def extract_tasks(cache_payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw_tasks = ((cache_payload.get("akiflow_tasks") or {}).get("tasks") or [])

    for raw in raw_tasks:
        title = (raw.get("summary") or raw.get("title") or "").strip()
        if not title:
            continue

        start = raw.get("start")
        end = raw.get("end")
        date_str = extract_date(start, raw.get("date"))
        if not date_str:
            continue

        title_norm = normalise_text(title)
        dur = duration_minutes(start, end)
        signature = f"{title_norm}|{start or ''}|{end or ''}|{date_str}"

        out.append(
            {
                "title": title,
                "title_norm": title_norm,
                "date": date_str,
                "start": start,
                "end": end,
                "duration_minutes": dur,
                "akiflow_task_id": raw.get("id") or raw.get("task_id"),
                "signature": signature,
                "completion_signal": completion_signal(raw),
                "raw": raw,
            }
        )

    if out:
        return out

    # Fallback: infer task entries from calendar task calendar.
    raw_events = ((cache_payload.get("calendar") or {}).get("events") or [])
    for raw in raw_events:
        cal_name = str(raw.get("calendar", "")).lower()
        if "task" not in cal_name and "akiflow" not in cal_name:
            continue

        title = (raw.get("summary") or "").strip()
        if not title:
            continue

        start = raw.get("start")
        end = raw.get("end")
        date_str = extract_date(start, None)
        if not date_str:
            continue

        title_norm = normalise_text(title)
        dur = duration_minutes(start, end)
        signature = f"{title_norm}|{start or ''}|{end or ''}|{date_str}"

        out.append(
            {
                "title": title,
                "title_norm": title_norm,
                "date": date_str,
                "start": start,
                "end": end,
                "duration_minutes": dur,
                "akiflow_task_id": None,
                "signature": signature,
                "completion_signal": False,
                "raw": raw,
            }
        )

    return out


def today_from_cache(cache_payload: dict[str, Any]) -> str:
    date_value = cache_payload.get("date")
    if isinstance(date_value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
        return date_value
    return utc_now().date().isoformat()


def ensure_unlocked_state(date_str: str) -> dict[str, Any]:
    return {
        "date": date_str,
        "time_blocking_final": False,
        "locked_at": None,
        "lock_source": None,
        "tasks": {},
        "snapshots": [],
        "last_reconciled_at": None,
    }


def baseline_fingerprint(task: dict[str, Any]) -> str:
    if task.get("akiflow_task_id"):
        return str(task["akiflow_task_id"])
    dur = task.get("duration_minutes")
    dur_part = str(dur) if dur is not None else "na"
    return f"{task['title_norm']}|{dur_part}|{task['date']}|akiflow"


def build_locked_state(
    date_str: str,
    today_tasks: list[dict[str, Any]],
    all_tasks: list[dict[str, Any]],
    lock_phrase: str | None,
) -> dict[str, Any]:
    captured_at = iso_now()
    tasks_sorted = sorted(today_tasks, key=lambda t: (t.get("start") or "", t["title_norm"]))

    tasks_map: dict[str, Any] = {}
    for idx, task in enumerate(tasks_sorted, start=1):
        task_key = f"task-{idx:03d}"
        tasks_map[task_key] = {
            "task_key": task_key,
            "title": task["title"],
            "start": task.get("start"),
            "end": task.get("end"),
            "akiflow_task_id": task.get("akiflow_task_id"),
            "fingerprint": baseline_fingerprint(task),
            "state": "scheduled_locked",
            "confidence": "high",
            "movement_history": [],
            "last_seen_at": captured_at,
            "completed_at": None,
            "date": task["date"],
            "duration_minutes": task.get("duration_minutes"),
            "title_norm": task["title_norm"],
            "baseline_signature": task["signature"],
        }

    return {
        "date": date_str,
        "time_blocking_final": True,
        "locked_at": captured_at,
        "lock_source": "diary_export_confirmation",
        "lock_phrase": lock_phrase,
        "tasks": tasks_map,
        "lock_all_signatures": sorted({task["signature"] for task in all_tasks}),
        "post_lock_seen_signatures": [],
        "snapshots": [
            {
                "captured_at": captured_at,
                "today_signatures": sorted({task["signature"] for task in today_tasks}),
                "all_signatures": sorted({task["signature"] for task in all_tasks}),
                "source": "lock",
            }
        ],
        "last_reconciled_at": captured_at,
    }


def find_reschedule_candidate(
    baseline_task: dict[str, Any],
    all_tasks: list[dict[str, Any]],
    post_lock_signatures: set[str],
) -> tuple[dict[str, Any] | None, bool]:
    baseline_start = parse_iso(baseline_task.get("start"))
    baseline_date = baseline_task.get("date")
    candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []

    for task in all_tasks:
        if task["signature"] == baseline_task.get("baseline_signature"):
            continue
        if task["signature"] not in post_lock_signatures:
            continue
        if task["title_norm"] != baseline_task.get("title_norm"):
            continue

        baseline_dur = baseline_task.get("duration_minutes")
        dur = task.get("duration_minutes")
        if baseline_dur is not None and dur is not None and baseline_dur != dur:
            continue

        if baseline_date and task.get("date"):
            day_delta = abs((datetime.fromisoformat(task["date"]) - datetime.fromisoformat(baseline_date)).days)
            if day_delta > 7:
                continue
        else:
            day_delta = 999

        task_start = parse_iso(task.get("start"))
        if baseline_start and task_start:
            minute_delta = int(abs((task_start - baseline_start).total_seconds()) // 60)
        else:
            minute_delta = 999999

        candidates.append(((day_delta, minute_delta), task))

    if not candidates:
        return None, False

    candidates.sort(key=lambda row: row[0])
    best_score = candidates[0][0]
    best = [candidate for score, candidate in candidates if score == best_score]
    if len(best) > 1:
        return None, True
    return best[0], False


def completion_evidence(baseline_task: dict[str, Any], all_tasks: list[dict[str, Any]]) -> bool:
    baseline_id = baseline_task.get("akiflow_task_id")
    for task in all_tasks:
        if not task.get("completion_signal"):
            continue
        if baseline_id and task.get("akiflow_task_id") == baseline_id:
            return True
        if task["title_norm"] == baseline_task.get("title_norm"):
            return True
    return False


def update_task_state(
    baseline_task: dict[str, Any],
    today_signatures: set[str],
    all_tasks: list[dict[str, Any]],
    post_lock_signatures: set[str],
    now: datetime,
) -> None:
    now_iso = now.isoformat().replace("+00:00", "Z")

    if baseline_task.get("baseline_signature") in today_signatures:
        baseline_task["last_seen_at"] = now_iso
        end_dt = parse_iso(baseline_task.get("end"))
        if end_dt and now > end_dt:
            baseline_task["state"] = "overdue_not_done"
            baseline_task["confidence"] = "high"
            baseline_task["completed_at"] = None
        else:
            baseline_task["state"] = "scheduled_locked"
            baseline_task["confidence"] = "high"
            baseline_task["completed_at"] = None
        return

    if completion_evidence(baseline_task, all_tasks):
        baseline_task["state"] = "completed_confirmed"
        baseline_task["confidence"] = "high"
        baseline_task["completed_at"] = now_iso
        return

    candidate, ambiguous_move = find_reschedule_candidate(
        baseline_task, all_tasks, post_lock_signatures
    )
    if ambiguous_move:
        baseline_task["state"] = "deleted_or_uncertain"
        baseline_task["confidence"] = "low"
        baseline_task["completed_at"] = None
        return

    if candidate:
        baseline_task["state"] = "rescheduled"
        baseline_task["confidence"] = "medium"
        baseline_task["last_seen_at"] = now_iso

        event = {
            "captured_at": now_iso,
            "from_start": baseline_task.get("start"),
            "from_end": baseline_task.get("end"),
            "to_start": candidate.get("start"),
            "to_end": candidate.get("end"),
            "to_date": candidate.get("date"),
            "to_signature": candidate.get("signature"),
        }
        history = baseline_task.setdefault("movement_history", [])
        if not history or history[-1].get("to_signature") != event["to_signature"]:
            history.append(event)
        if len(history) > 20:
            baseline_task["movement_history"] = history[-20:]
        baseline_task["completed_at"] = None
        return

    baseline_task["state"] = "completed_inferred"
    baseline_task["confidence"] = "medium"
    baseline_task["completed_at"] = now_iso


def state_counts(tasks_map: dict[str, Any]) -> Counter:
    return Counter(task.get("state", "unknown") for task in tasks_map.values())


def cmd_lock(args: argparse.Namespace) -> int:
    cache = read_json(args.cache_file)
    date_str = args.date
    lock_phrase = None
    if args.phrase:
        parsed_date = parse_lock_phrase(args.phrase)
        lock_phrase = args.phrase.strip()
        if date_str and date_str != parsed_date:
            raise ValueError(f"Date mismatch: --date={date_str} vs lock phrase={parsed_date}")
        date_str = parsed_date
    if not date_str:
        date_str = today_from_cache(cache)

    all_tasks = extract_tasks(cache)
    today_tasks = [task for task in all_tasks if task.get("date") == date_str]

    state = build_locked_state(date_str, today_tasks, all_tasks, lock_phrase)
    path = save_state(args.tracker_dir, date_str, state)

    print(f"✅ Akiflow day locked: {date_str}")
    print(f"📁 State file: {path}")
    print(f"📋 Baseline tasks captured: {len(today_tasks)}")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    cache = read_json(args.cache_file)
    date_str = args.date or today_from_cache(cache)

    state = load_state(args.tracker_dir, date_str)
    if state is None:
        state = ensure_unlocked_state(date_str)
        path = save_state(args.tracker_dir, date_str, state)
        print(f"⚠️ Akiflow tracking not locked for {date_str}.")
        print("No completion scoring performed (time_blocking_final=false).")
        print(f"📁 Created placeholder state: {path}")
        return 0

    if not state.get("time_blocking_final"):
        path = save_state(args.tracker_dir, date_str, state)
        print(f"⚠️ Akiflow tracking not locked for {date_str}.")
        print("No completion scoring performed (time_blocking_final=false).")
        print(f"📁 State file: {path}")
        return 0

    all_tasks = extract_tasks(cache)
    today_tasks = [task for task in all_tasks if task.get("date") == date_str]
    today_signatures = {task["signature"] for task in today_tasks}
    all_signatures = {task["signature"] for task in all_tasks}

    lock_signatures = set(state.get("lock_all_signatures") or [])
    post_lock_signatures = set(state.get("post_lock_seen_signatures") or [])
    post_lock_signatures.update(sig for sig in all_signatures if sig not in lock_signatures)

    now = utc_now()
    for task in (state.get("tasks") or {}).values():
        update_task_state(task, today_signatures, all_tasks, post_lock_signatures, now)

    now_iso = now.isoformat().replace("+00:00", "Z")
    snapshots = state.setdefault("snapshots", [])
    snapshots.append(
        {
            "captured_at": now_iso,
            "today_signatures": sorted(today_signatures),
            "all_signatures": sorted(all_signatures),
            "source": "reconcile",
        }
    )
    if len(snapshots) > 48:
        del snapshots[:-48]

    state["post_lock_seen_signatures"] = sorted(post_lock_signatures)
    state["last_reconciled_at"] = now_iso

    path = save_state(args.tracker_dir, date_str, state)
    counts = state_counts(state.get("tasks") or {})

    print(f"✅ Akiflow reconciliation updated: {date_str}")
    print(f"📁 State file: {path}")
    print("📊 State counts:")
    for key in STATE_ORDER:
        print(f"- {key}: {counts.get(key, 0)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cache = read_json(args.cache_file)
    date_str = args.date or today_from_cache(cache)
    state = load_state(args.tracker_dir, date_str)

    if state is None:
        print(f"⚠️ No Akiflow tracker file for {date_str}")
        print("Use lock phrase to initialise:")
        print("✅ Time blocking finalised for YYYY-MM-DD. Please start locked tracking.")
        return 0

    print(f"📅 Date: {date_str}")
    print(f"🔒 time_blocking_final: {bool(state.get('time_blocking_final'))}")
    print(f"🕒 locked_at: {state.get('locked_at') or 'n/a'}")
    print(f"🧾 lock_source: {state.get('lock_source') or 'n/a'}")
    print(f"♻️ last_reconciled_at: {state.get('last_reconciled_at') or 'n/a'}")

    tasks = state.get("tasks") or {}
    counts = state_counts(tasks)
    print("📊 State counts:")
    for key in STATE_ORDER:
        print(f"- {key}: {counts.get(key, 0)}")

    if not tasks:
        print("(No locked baseline tasks for this date)")
        return 0

    print("\n📋 Tasks:")
    sorted_tasks = sorted(tasks.values(), key=lambda t: (t.get("start") or "", t.get("title", "")))
    for task in sorted_tasks:
        state_name = task.get("state", "unknown")
        confidence = task.get("confidence", "unknown")
        title = task.get("title", "(untitled)")
        start = task.get("start") or "no-start"
        print(f"- [{state_name} | {confidence}] {title} @ {start}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Akiflow lock-gated task tracker")
    parser.add_argument(
        "--cache-file",
        type=Path,
        default=CACHE_FILE_DEFAULT,
        help=f"Path to session-data.json (default: {CACHE_FILE_DEFAULT})",
    )
    parser.add_argument(
        "--tracker-dir",
        type=Path,
        default=TRACKER_DIR_DEFAULT,
        help=f"Tracker state directory (default: {TRACKER_DIR_DEFAULT})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    lock_parser = sub.add_parser("lock", help="Lock today after time blocking is final")
    lock_parser.add_argument("--date", help="Date to lock (YYYY-MM-DD)")
    lock_parser.add_argument(
        "--phrase",
        help="Exact lock phrase: ✅ Time blocking finalised for YYYY-MM-DD. Please start locked tracking.",
    )
    lock_parser.set_defaults(func=cmd_lock)

    reconcile_parser = sub.add_parser("reconcile", help="Reconcile current snapshot against locked baseline")
    reconcile_parser.add_argument("--date", help="Date to reconcile (YYYY-MM-DD)")
    reconcile_parser.set_defaults(func=cmd_reconcile)

    status_parser = sub.add_parser("status", help="Show tracker status")
    status_parser.add_argument("--date", help="Date to show (YYYY-MM-DD)")
    status_parser.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"❌ Missing file: {exc}")
        return 1
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
