"""Shared action-item helpers for dashboard generation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


TASK_ACTION_STEMS = {
    "apply", "assemble", "book", "buy", "call", "cancel", "change", "check",
    "clean", "collect", "complete", "contact", "create", "do", "email", "file",
    "fill", "find", "finish", "fix", "follow", "get", "give", "install", "log",
    "look", "make", "message", "move", "pack", "pay", "pick", "plan", "post",
    "prepare", "print", "read", "register", "repair", "replace", "reply",
    "request", "research", "review", "schedule", "send", "set", "sign", "sort",
    "submit", "tidy", "unpack", "update", "vacuum", "wash", "write",
}

TASK_OBJECT_STOPWORDS = {
    "the", "and", "this", "that", "with", "from", "into", "onto", "for", "to",
    "after", "before", "right", "left", "one", "some", "any", "just", "then",
    "today", "tonight", "tomorrow", "morning", "afternoon", "evening", "now",
}

TASK_ACTION_VERBS = {
    "apply", "assemble", "book", "buy", "call", "cancel", "change", "check",
    "clean", "collect", "complete", "contact", "create", "do", "email", "file",
    "fill", "finish", "fix", "follow", "get", "give", "install", "log", "make",
    "message", "move", "pack", "pay", "pick", "plan", "post", "prepare", "print",
    "read", "register", "repair", "replace", "reply", "request", "research",
    "review", "schedule", "send", "set", "sign", "sort", "submit", "tidy",
    "unpack", "update", "vacuum", "wash", "write",
}

TASK_VAGUE_OBJECT_TOKENS = {
    "that", "this", "it", "thing", "things", "stuff", "something", "anything",
    "everything", "whatever", "whenever", "sometime", "someday",
}

TASK_EQUIVALENCE_GENERIC_OBJECT_TOKENS = {
    "post", "office", "parcel", "package", "item", "items", "pending", "task", "tasks",
    "todo", "todos", "tomorrow", "today",
}

FUTURE_KEYWORDS = (
    "tomorrow",
    "day after tomorrow",
    "next week",
    "next month",
    "next monday",
    "next tuesday",
    "next wednesday",
    "next thursday",
    "next friday",
    "next saturday",
    "next sunday",
    "this weekend",
    "weekend",
)

WEEKDAY_NAME_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

ACTION_ITEM_DEFER_FILE = Path.home() / ".claude" / "cache" / "action-item-defer.json"
ACTION_ITEM_STATE_FILE = Path.home() / ".claude" / "cache" / "action-item-state.json"
ACTION_ITEM_STATE_CARRY_DAYS = 7
ACTION_ITEM_MODEL_VERSION = 2


def parse_ymd(raw_text: str):
    try:
        return datetime.strptime(str(raw_text or "").strip(), "%Y-%m-%d")
    except Exception:
        return None


def _is_auto_expired(freshness_dt, target_dt, today_dt, stale_days=3) -> bool:
    """True when an item hasn't been seen live in >stale_days AND its target_date is past."""
    if freshness_dt and freshness_dt < (today_dt - timedelta(days=stale_days)):
        if target_dt and target_dt < today_dt:
            return True
    return False


def normalise_action_item_key(raw_text: str) -> str:
    return task_match_key(str(raw_text or ""))


def strip_completion_hash_artifacts(raw_text: str) -> str:
    """Remove Apple Notes/dashboard completion hash suffixes from a task label."""
    text = str(raw_text or "").strip()
    if not text:
        return ""
    previous = None
    while text and text != previous:
        previous = text
        text = re.sub(r"\s*~~+\s*\[?\s*[0-9a-f]{6,16}\s*\]?\s*$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*\[\s*[0-9a-f]{6,16}\s*\]\s*$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"(?:\s+[0-9a-f]{6,12})+\s*$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"^\s*~~+\s*", "", text).strip()
        text = re.sub(r"\s*~~+\s*$", "", text).strip()
    return re.sub(r"\s+", " ", text).strip(" -–—\t")


def task_match_key(raw_text: str) -> str:
    text = strip_completion_hash_artifacts(raw_text)
    text = re.sub(r"\s+", " ", str(text or "").strip().lower())
    # Strip possessive 's before removing non-alpha (avoids orphan "s" tokens)
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def task_completion_hash(raw_text: str) -> str:
    key = task_match_key(raw_text) or str(raw_text or "").strip().lower()
    if not key:
        return ""
    return hashlib.md5(key.encode()).hexdigest()[:12]


def task_completion_hash_legacy(raw_text: str) -> str:
    seed = str(raw_text or "").strip().lower()
    if not seed:
        return ""
    return hashlib.md5(seed.encode()).hexdigest()[:12]


def _prefix_match(key_a: str, key_b: str, n: int = 3) -> bool:
    """True if the first *n* tokens of both normalised keys are identical."""
    a, b = key_a.split(), key_b.split()
    pfx = min(n, len(a), len(b))
    return pfx >= n and a[:pfx] == b[:pfx]


def task_object_tokens(raw_text: str) -> set[str]:
    key = task_match_key(raw_text)
    tokens = {t for t in key.split() if t}
    return {
        t for t in tokens
        if t not in TASK_ACTION_STEMS and t not in TASK_OBJECT_STOPWORDS and not t.isdigit() and len(t) > 2
    }


def task_matches_completed_text(raw_text: str, completed_text_keys: list[str]) -> bool:
    candidate_key = task_match_key(raw_text)
    if not candidate_key or not completed_text_keys:
        return False
    candidate_tokens = {t for t in candidate_key.split() if t}
    candidate_object_tokens = task_object_tokens(candidate_key)
    candidate_is_multipart = (
        len(candidate_object_tokens) >= 3
        and any(token in str(raw_text or "").lower() for token in (" and ", ",", "kind of thing"))
    )
    for done_raw in completed_text_keys:
        done_key = task_match_key(done_raw)
        if not done_key:
            continue
        if candidate_key == done_key:
            return True
        if _prefix_match(candidate_key, done_key):
            return True
        done_object_tokens = task_object_tokens(done_key)
        if candidate_is_multipart and candidate_object_tokens and done_object_tokens:
            overlap_ratio = len(candidate_object_tokens & done_object_tokens) / max(len(candidate_object_tokens), 1)
        else:
            overlap_ratio = 1.0
        if len(candidate_key) >= 10 and candidate_key in done_key:
            return True
        if len(done_key) >= 10 and done_key in candidate_key and overlap_ratio >= 0.75:
            return True
        done_tokens = {t for t in done_key.split() if t}
        if done_object_tokens and candidate_object_tokens:
            obj_overlap = done_object_tokens & candidate_object_tokens
            meaningful_overlap = {
                tok for tok in obj_overlap
                if tok not in TASK_EQUIVALENCE_GENERIC_OBJECT_TOKENS
            }
            min_obj = min(len(done_object_tokens), len(candidate_object_tokens))
            if candidate_is_multipart and len(meaningful_overlap) / max(len(candidate_object_tokens), 1) < 0.75:
                continue
            if len(obj_overlap) >= 2 and meaningful_overlap:
                return True
            if min_obj >= 3 and len(meaningful_overlap) / max(min_obj, 1) >= 0.5:
                return True
            # Short-task rule: 1 specific shared noun (≥5 chars) on short tasks
            # Both sides must be short — a long candidate sharing 1 noun with a
            # short completed task is not the same task (e.g. "bedtime boundary
            # before freelance" vs "set bedtime alarm tonight").
            max_obj = max(len(done_object_tokens), len(candidate_object_tokens))
            specific_overlap = {tok for tok in meaningful_overlap if len(tok) >= 5}
            if specific_overlap and min_obj <= 4 and max_obj <= 4:
                return True
        overlap = len(candidate_tokens & done_tokens)
        union = len(candidate_tokens | done_tokens)
        if overlap >= 2 and union and (overlap / union) >= 0.66:
            return True
    return False


def tasks_equivalent(left_text: str, right_text: str) -> bool:
    left_key = task_match_key(left_text)
    right_key = task_match_key(right_text)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if len(left_key) >= 10 and left_key in right_key:
        return True
    if len(right_key) >= 10 and right_key in left_key:
        return True
    # Prefix match: catches voice transcription variants like "set tomorrow plan
    # before sleep" vs "set tomorrow plan before closing the evening"
    if _prefix_match(left_key, right_key):
        return True
    left_obj = task_object_tokens(left_text)
    right_obj = task_object_tokens(right_text)
    if left_obj and right_obj:
        obj_overlap = left_obj & right_obj
        meaningful_overlap = {
            tok for tok in obj_overlap
            if tok not in TASK_EQUIVALENCE_GENERIC_OBJECT_TOKENS
        }
        min_obj = min(len(left_obj), len(right_obj))
        if len(obj_overlap) >= 2 and meaningful_overlap:
            return True
        if min_obj >= 3 and len(meaningful_overlap) / max(min_obj, 1) >= 0.5:
            return True
        # Short-task rule: if both tasks are brief and share 1 specific physical noun
        # (e.g. "Fix the bathroom shelf" ≡ "Finish the bathroom"), treat as same work.
        # Both sides must be short — a long task sharing 1 noun with a short task
        # is not equivalence (e.g. "bedtime boundary before freelance" ≠ "set bedtime alarm").
        max_obj = max(len(left_obj), len(right_obj))
        specific_overlap = {tok for tok in meaningful_overlap if len(tok) >= 5}
        if specific_overlap and min_obj <= 4 and max_obj <= 4:
            return True
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return bool(overlap >= 2 and union and (overlap / union) >= 0.66)


def is_actionable_task(raw_text: str) -> bool:
    text = re.sub(r"\s+", " ", str(raw_text or "").strip())
    if len(text) < 10 or len(text) > 220:
        return False
    lower = text.lower()
    if "tomorrow" in lower and re.search(r"\bpay(?:ing)?\b", lower):
        concrete_targets = ("rent", "invoice", "bill", "tax", "credit card", "subscription", "council")
        if not any(token in lower for token in concrete_targets):
            return False
    if any(tok in lower for tok in ("payment", "paid")):
        if lower.startswith(("get paid", "be paid", "receive payment", "check if", "check whether", "check that", "wait for", "waiting for")):
            return False
        if any(tok in lower for tok in ("tomorrow", "by noon", "by midday", "arrive", "arrives", "arrived", "land", "lands", "come through")):
            return False
    if re.match(r"^(and|or|but|so|because|me|him|her|them|us|it|that|which)\b", lower):
        return False
    if re.match(r"^(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower):
        return False
    if lower.startswith("make sure"):
        return False
    if any(phrase in lower for phrase in ("can wait", "could wait", "should wait", "wait for later", "wait until later", "at some point", "eventually")):
        return False
    if any(phrase in lower for phrase in ("obviously not", "not the most important", ", but that's not", ", but that is not", "but obviously")):
        return False
    if any(marker in lower for marker in ("i'm a terrible person", "denigrate", "feel bad about", "childish")):
        return False
    candidate = re.sub(
        r"^(?:i need to|i have to|i must|i'm going to|i will|need to|must|to)\s+",
        "",
        lower,
    ).strip()
    words = re.findall(r"[a-z']+", candidate)
    if len(words) < 2:
        return False
    if words[0] not in TASK_ACTION_VERBS:
        return False
    if words[0] in {"do", "get", "make"} and words[1] in TASK_VAGUE_OBJECT_TOKENS:
        return False
    object_tokens = [
        token for token in words[1:]
        if token not in {"up", "out", "off", "on", "in", "to", "for", "with", "and", "or", "then", "now"}
    ]
    if object_tokens and all(token in TASK_VAGUE_OBJECT_TOKENS for token in object_tokens):
        return False
    return True


def compact_task_text(raw_text: str, max_len: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(raw_text or "").strip())
    if len(text) <= max_len:
        return text
    first_clause = re.split(r"(?<=[\.\!\?])\s+| — | - |; ", text, maxsplit=1)[0].strip()
    if 24 <= len(first_clause) <= max_len:
        return first_clause.rstrip(".!?:;,- ") + "..."
    return text[: max_len - 3].rstrip() + "..."


def is_future_facing_task(raw_text: str, future_keywords=FUTURE_KEYWORDS) -> bool:
    task_lower = str(raw_text or "").lower()
    return any(kw in task_lower for kw in future_keywords)


def infer_target_date_from_text(raw_text: str, effective_today: str) -> str:
    """Infer YYYY-MM-DD target date from natural-language timing markers in task text."""
    task_lower = str(raw_text or "").strip().lower()
    if not task_lower:
        return ""
    try:
        base_dt = datetime.strptime(str(effective_today or "").strip(), "%Y-%m-%d")
    except Exception:
        return ""

    if "day after tomorrow" in task_lower:
        return (base_dt + timedelta(days=2)).strftime("%Y-%m-%d")
    if "tomorrow" in task_lower:
        return (base_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    if "next week" in task_lower:
        return (base_dt + timedelta(days=7)).strftime("%Y-%m-%d")
    if "next month" in task_lower:
        return (base_dt + timedelta(days=30)).strftime("%Y-%m-%d")
    if "this weekend" in task_lower or "weekend" in task_lower:
        days_until_sat = (5 - base_dt.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        return (base_dt + timedelta(days=days_until_sat)).strftime("%Y-%m-%d")

    for name, idx in WEEKDAY_NAME_TO_INDEX.items():
        if f"next {name}" in task_lower:
            delta = (idx - base_dt.weekday()) % 7
            if delta == 0:
                delta = 7
            return (base_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
        if re.search(rf"\b(?:on\s+)?{name}\b", task_lower):
            delta = (idx - base_dt.weekday()) % 7
            if delta == 0:
                delta = 7
            return (base_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
    return ""


def load_action_item_defer_targets(effective_date: str) -> dict[str, str]:
    """Return task-key -> target_date for active user deferrals."""
    if not ACTION_ITEM_DEFER_FILE.exists():
        return {}
    today_dt = parse_ymd(effective_date)
    if not today_dt:
        return {}
    try:
        payload = json.loads(ACTION_ITEM_DEFER_FILE.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}

    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        return {}

    targets: dict[str, str] = {}
    target_texts: dict[str, str] = {}
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        target_date = str(row.get("target_date", "")).strip()
        key = normalise_action_item_key(text)
        target_dt = parse_ymd(target_date)
        if not key or not target_dt or target_dt <= today_dt:
            continue
        equivalent_keys = [
            existing_key
            for existing_key, existing_text in target_texts.items()
            if existing_key == key or tasks_equivalent(text, existing_text)
        ]
        if not equivalent_keys:
            equivalent_keys = [key]
        strongest_target = target_date
        for existing_key in equivalent_keys:
            previous = str(targets.get(existing_key, "")).strip()
            if previous and previous > strongest_target:
                strongest_target = previous
        for existing_key in set(equivalent_keys + [key]):
            targets[existing_key] = strongest_target
            existing_text = str(target_texts.get(existing_key, "")).strip()
            if len(text) >= len(existing_text):
                target_texts[existing_key] = text
            elif existing_text:
                target_texts[existing_key] = existing_text
    return targets


def load_action_item_defer_rows(effective_date: str) -> list[dict]:
    """Return defer rows that should still influence today's/tomorrow's queue."""
    if not ACTION_ITEM_DEFER_FILE.exists():
        return []
    today_dt = parse_ymd(effective_date)
    if not today_dt:
        return []
    try:
        payload = json.loads(ACTION_ITEM_DEFER_FILE.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        return []

    rows: list[dict] = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        target_date = str(row.get("target_date", "")).strip()
        key = normalise_action_item_key(text)
        target_dt = parse_ymd(target_date)
        if not key or not target_dt or target_dt < today_dt:
            continue
        candidate = {
            "task_key": key,
            "text": text,
            "target_date": target_date,
        }
        match_idx = None
        for idx, existing in enumerate(rows):
            if key == existing.get("task_key") or tasks_equivalent(text, existing.get("text", "")):
                match_idx = idx
                break
        if match_idx is None:
            rows.append(candidate)
            continue
        existing = rows[match_idx]
        existing_target = str(existing.get("target_date", "")).strip()
        if target_date > existing_target:
            existing["target_date"] = target_date
        if len(text) > len(str(existing.get("text", ""))):
            existing["text"] = text
            existing["task_key"] = key
    return rows


def load_action_item_state_payload() -> dict:
    if not ACTION_ITEM_STATE_FILE.exists():
        return {"schema_version": ACTION_ITEM_MODEL_VERSION, "items": []}
    try:
        payload = json.loads(ACTION_ITEM_STATE_FILE.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        payload = {"schema_version": ACTION_ITEM_MODEL_VERSION, "items": []}
    if not isinstance(payload, dict):
        payload = {"schema_version": ACTION_ITEM_MODEL_VERSION, "items": []}
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []
    payload["schema_version"] = ACTION_ITEM_MODEL_VERSION
    payload["items"] = items
    return payload


def persist_action_item_state(payload: dict) -> None:
    try:
        ACTION_ITEM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(f"{ACTION_ITEM_STATE_FILE}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ACTION_ITEM_STATE_FILE)
    except Exception:
        pass


def load_active_action_item_state_rows(
    effective_date: str,
    carry_days: int = ACTION_ITEM_STATE_CARRY_DAYS,
) -> dict[str, dict]:
    today_dt = parse_ymd(effective_date)
    if not today_dt:
        return {}
    payload = load_action_item_state_payload()
    rows_by_key: dict[str, dict] = {}
    cutoff_dt = today_dt - timedelta(days=max(1, int(carry_days)))
    for row in payload.get("items", []):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        key = str(row.get("task_key", "")).strip() or normalise_action_item_key(text)
        if not text or not key:
            continue
        status = str(row.get("status", "open")).strip().lower()
        if status == "done":
            continue
        target_date = str(row.get("target_date", "")).strip()
        target_dt = parse_ymd(target_date)
        last_live_date = str(row.get("last_live_seen_date", "")).strip()
        last_seen_date = str(row.get("last_seen_date", "")).strip()
        first_seen_date = str(row.get("first_seen_date", "")).strip()
        freshness_dt = parse_ymd(last_live_date) or parse_ymd(last_seen_date) or parse_ymd(first_seen_date)
        keep = False
        if target_dt and target_dt >= (today_dt - timedelta(days=1)):
            keep = True
        elif freshness_dt and freshness_dt >= cutoff_dt:
            keep = True
        if not keep:
            continue
        if _is_auto_expired(freshness_dt, target_dt, today_dt):
            continue
        rows_by_key[key] = {
            "task_key": key,
            "text": text,
            "category": str(row.get("category", "standard")).strip() or "standard",
            "priority": str(row.get("priority", "Medium")).strip() or "Medium",
            "time": str(row.get("time", "15m")).strip() or "15m",
            "target_date": target_date,
            "status": status,
            "source": str(row.get("source", "")).strip(),
            "first_seen_date": first_seen_date,
            "last_live_seen_date": last_live_date,
            "last_seen_date": last_seen_date,
            "queue_bucket": str(row.get("queue_bucket", "")).strip(),
            "queue_rank": row.get("queue_rank"),
            "due_today_override": bool(row.get("due_today_override", False)),
            "defer_target_date": str(row.get("defer_target_date", "")).strip(),
            "inferred_target_date": str(row.get("inferred_target_date", "")).strip(),
        }
    return rows_by_key


def save_action_item_state(
    effective_date: str,
    items: list[dict],
    *,
    today_items: list[dict] | None = None,
    future_items: list[dict] | None = None,
    completed_items: list[dict] | None = None,
    carry_days: int = ACTION_ITEM_STATE_CARRY_DAYS,
) -> None:
    today_dt = parse_ymd(effective_date)
    if not today_dt:
        return
    now_iso = datetime.now().isoformat(timespec="seconds")
    payload = load_action_item_state_payload()

    previous_rows: dict[str, dict] = {}
    for row in payload.get("items", []):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        key = str(row.get("task_key", "")).strip() or normalise_action_item_key(text)
        if key:
            previous_rows[key] = row

    queue_meta: dict[str, dict] = {}

    def _capture_queue(rows, bucket):
        if not isinstance(rows, list):
            return
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            text = str(row.get("task", "") or row.get("text", "")).strip()
            key = normalise_action_item_key(text)
            if not key:
                continue
            queue_meta[key] = {"queue_bucket": bucket, "queue_rank": idx}

    _capture_queue(today_items, "today")
    _capture_queue(future_items, "future")
    _capture_queue(completed_items, "done")

    next_rows: dict[str, dict] = {}
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("task", "") or item.get("text", "")).strip()
        key = normalise_action_item_key(text)
        if not text or not key:
            continue
        prev = previous_rows.get(key, {})
        source = str(item.get("source", "")).strip().lower()
        target_date = str(item.get("target_date", "")).strip()
        is_done = bool(item.get("done"))
        queue_info = queue_meta.get(key, {})
        queue_bucket = str(queue_info.get("queue_bucket", "")).strip()
        if not queue_bucket:
            if is_done:
                queue_bucket = "done"
            elif target_date and target_date > effective_date and not bool(item.get("due_today_override")):
                queue_bucket = "future"
            else:
                queue_bucket = "today"
        due_today_override = bool(item.get("due_today_override", False))
        if queue_bucket == "future" and target_date and target_date > effective_date:
            due_today_override = False
        queue_rank = queue_info.get("queue_rank")
        if queue_rank is None:
            try:
                queue_rank = int(prev.get("queue_rank"))
            except Exception:
                queue_rank = 9999
        first_seen_date = str(prev.get("first_seen_date", "")).strip() or effective_date
        last_live_seen_date = str(prev.get("last_live_seen_date", "")).strip()
        if source and source != "persisted":
            last_live_seen_date = effective_date
        elif not last_live_seen_date:
            last_live_seen_date = str(prev.get("last_seen_date", "")).strip() or effective_date

        next_rows[key] = {
            "task_key": key,
            "text": text,
            "category": str(item.get("category", "standard")).strip() or "standard",
            "priority": str(item.get("priority", prev.get("priority", "Medium"))).strip() or "Medium",
            "time": str(item.get("time", "15m")).strip() or "15m",
            "target_date": target_date,
            "status": "done" if is_done else "open",
            "source": source or str(prev.get("source", "")).strip(),
            "queue_bucket": queue_bucket,
            "queue_rank": int(queue_rank),
            "due_today_override": due_today_override,
            "defer_target_date": str(item.get("defer_target_date", "")).strip(),
            "inferred_target_date": str(item.get("inferred_target_date", "")).strip(),
            "first_seen_date": first_seen_date,
            "last_seen_date": effective_date,
            "last_live_seen_date": last_live_seen_date,
            "updated_at": now_iso,
        }
        if is_done:
            next_rows[key]["completed_date"] = effective_date

        # Auto-escalate stale open items: Medium → High after 7 days (once only)
        row = next_rows[key]
        if row["status"] == "open" and row.get("first_seen_date") and not row.get("auto_escalated"):
            _first_dt = parse_ymd(row["first_seen_date"])
            _days_open = (today_dt - _first_dt).days if _first_dt else 0
            if _days_open >= 7 and row.get("priority", "Medium") in ("Medium", ""):
                row["priority"] = "High"
                row["auto_escalated"] = True
                row["escalated_at"] = effective_date

    cutoff_dt = today_dt - timedelta(days=max(1, int(carry_days)))
    for key, prev in previous_rows.items():
        if key in next_rows:
            continue
        status = str(prev.get("status", "open")).strip().lower()
        if status == "done":
            continue
        target_date = str(prev.get("target_date", "")).strip()
        target_dt = parse_ymd(target_date)
        last_live_dt = parse_ymd(str(prev.get("last_live_seen_date", "")).strip())
        last_seen_dt = parse_ymd(str(prev.get("last_seen_date", "")).strip())
        first_seen_dt = parse_ymd(str(prev.get("first_seen_date", "")).strip())
        freshness_dt = last_live_dt or last_seen_dt or first_seen_dt
        keep = False
        if target_dt and target_dt >= (today_dt - timedelta(days=1)):
            keep = True
        elif freshness_dt and freshness_dt >= cutoff_dt:
            keep = True
        if not keep:
            continue
        if _is_auto_expired(freshness_dt, target_dt, today_dt):
            continue
        carried = dict(prev)
        carried["task_key"] = key
        carried["status"] = "open"
        carried["updated_at"] = now_iso
        carried.setdefault("queue_bucket", "future" if target_date and target_date > effective_date else "today")
        try:
            carried["queue_rank"] = int(carried.get("queue_rank", 9999))
        except Exception:
            carried["queue_rank"] = 9999
        next_rows[key] = carried

    # Deduplicate equivalent items — keep the one with the freshest live-seen date
    deduped: dict[str, dict] = {}
    for key, row in next_rows.items():
        merged = False
        for existing_key, existing_row in list(deduped.items()):
            if tasks_equivalent(row.get("text", ""), existing_row.get("text", "")):
                # Keep whichever was seen more recently
                row_fresh = row.get("last_live_seen_date", "") or row.get("last_seen_date", "")
                ex_fresh = existing_row.get("last_live_seen_date", "") or existing_row.get("last_seen_date", "")
                if row_fresh >= ex_fresh:
                    deduped[existing_key] = {**row, "task_key": existing_key}
                merged = True
                break
        if not merged:
            deduped[key] = row

    payload["updated_at"] = now_iso
    payload["schema_version"] = ACTION_ITEM_MODEL_VERSION
    payload["items"] = sorted(
        deduped.values(),
        key=lambda row: (
            {"today": 0, "future": 1, "done": 2}.get(str(row.get("queue_bucket", "today")).strip(), 3),
            int(row.get("queue_rank", 9999)),
            str(row.get("target_date", "")),
            str(row.get("task_key", "")),
        ),
    )
    persist_action_item_state(payload)


def _normalise_state_row(row: dict, effective_date: str) -> dict | None:
    text = str(row.get("text", "")).strip()
    key = str(row.get("task_key", "")).strip() or normalise_action_item_key(text)
    if not text or not key:
        return None
    target_date = str(row.get("target_date", "")).strip()
    status = str(row.get("status", "open")).strip().lower() or "open"
    bucket = str(row.get("queue_bucket", "")).strip()
    if not bucket:
        if status == "done":
            bucket = "done"
        elif target_date and target_date > effective_date:
            bucket = "future"
        else:
            bucket = "today"
    try:
        queue_rank = int(row.get("queue_rank", 9999))
    except Exception:
        queue_rank = 9999
    due_today_override = bool(row.get("due_today_override", False))
    if bucket == "future" and target_date and target_date > effective_date:
        due_today_override = False
    return {
        "task_key": key,
        "text": text,
        "task": text,
        "category": str(row.get("category", "standard")).strip() or "standard",
        "priority": str(row.get("priority", "Medium")).strip() or "Medium",
        "time": str(row.get("time", "15m")).strip() or "15m",
        "target_date": target_date,
        "source": str(row.get("source", "")).strip(),
        "status": status,
        "done": status == "done",
        "bucket": bucket,
        "queue_rank": queue_rank,
        "due_today_override": due_today_override,
        "defer_target_date": str(row.get("defer_target_date", "")).strip(),
        "inferred_target_date": str(row.get("inferred_target_date", "")).strip(),
        "first_seen_date": str(row.get("first_seen_date", "")).strip(),
        "last_seen_date": str(row.get("last_seen_date", "")).strip(),
        "last_live_seen_date": str(row.get("last_live_seen_date", "")).strip(),
        "completed_date": str(row.get("completed_date", "")).strip(),
        "updated_at": str(row.get("updated_at", "")).strip(),
    }


def load_dashboard_action_state(effective_date: str) -> dict:
    """Load the persisted unified action queue used by the dashboard and API."""
    payload = load_action_item_state_payload()
    rows = payload.get("items", []) if isinstance(payload.get("items", []), list) else []
    today_items: list[dict] = []
    future_items: list[dict] = []
    done_items: list[dict] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _normalise_state_row(row, effective_date)
        if not item:
            continue
        bucket = item.get("bucket")
        if bucket == "done" or item.get("done"):
            done_items.append(item)
        elif bucket == "future":
            future_items.append(item)
        else:
            today_items.append(item)

    def _sort_key(item: dict):
        return (
            int(item.get("queue_rank", 9999)),
            str(item.get("target_date", "")).strip(),
            str(item.get("category", "")).strip(),
            str(item.get("text", "")).strip().lower(),
        )

    today_items.sort(key=_sort_key)
    future_items.sort(key=_sort_key)
    done_items.sort(
        key=lambda item: (
            str(item.get("completed_date", "")).strip(),
            int(item.get("queue_rank", 9999)),
            str(item.get("text", "")).strip().lower(),
        ),
        reverse=True,
    )
    return {
        "schema_version": ACTION_ITEM_MODEL_VERSION,
        "today": today_items,
        "future": future_items,
        "done": done_items,
        "updated_at": str(payload.get("updated_at", "")).strip(),
    }


def load_completed_todo_state(completed_file, effective_today: str) -> tuple[set[str], list[str], list[str]]:
    hashes: set[str] = set()
    text_keys: list[str] = []
    labels: list[str] = []
    try:
        if completed_file.exists():
            payload = json.loads(completed_file.read_text(encoding="utf-8", errors="replace"))
            if (
                isinstance(payload, dict)
                and str(payload.get("date", "")).strip() == effective_today
                and isinstance(payload.get("completed"), list)
            ):
                hashes = {
                    str(item).strip().lower()
                    for item in payload.get("completed", [])
                    if str(item).strip()
                }
                if isinstance(payload.get("completed_texts"), list):
                    text_keys = [
                        task_match_key(item)
                        for item in payload.get("completed_texts", [])
                        if str(item).strip() and task_match_key(item)
                    ]
                if isinstance(payload.get("completed_labels"), list):
                    seen_label_keys: set[str] = set()
                    cleaned_labels: list[str] = []
                    for item in payload.get("completed_labels", []):
                        text = strip_completion_hash_artifacts(item)
                        if not text:
                            continue
                        key = task_match_key(text)
                        if not key or key in seen_label_keys:
                            continue
                        seen_label_keys.add(key)
                        cleaned_labels.append(text)
                    labels = cleaned_labels
                if not labels and isinstance(payload.get("completed_texts"), list):
                    labels = [
                        strip_completion_hash_artifacts(str(item).strip().capitalize())
                        for item in payload.get("completed_texts", [])
                        if str(item).strip() and strip_completion_hash_artifacts(str(item).strip().capitalize())
                    ]
    except Exception:
        hashes, text_keys, labels = set(), [], []
    return hashes, text_keys, labels


