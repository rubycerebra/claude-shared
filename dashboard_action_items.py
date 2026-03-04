"""Shared action-item helpers for dashboard generation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime


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

FUTURE_KEYWORDS = ("tomorrow", "tonight", "next week", "next month", "later today", "this evening")


def task_match_key(raw_text: str) -> str:
    text = re.sub(r"\s+", " ", str(raw_text or "").strip().lower())
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
    for done_raw in completed_text_keys:
        done_key = task_match_key(done_raw)
        if not done_key:
            continue
        if candidate_key == done_key:
            return True
        if len(candidate_key) >= 10 and candidate_key in done_key:
            return True
        if len(done_key) >= 10 and done_key in candidate_key:
            return True
        done_tokens = {t for t in done_key.split() if t}
        done_object_tokens = task_object_tokens(done_key)
        if done_object_tokens and candidate_object_tokens:
            obj_overlap = done_object_tokens & candidate_object_tokens
            min_obj = min(len(done_object_tokens), len(candidate_object_tokens))
            if len(obj_overlap) >= 2:
                return True
            if min_obj >= 3 and len(obj_overlap) / max(min_obj, 1) >= 0.75:
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
    left_obj = task_object_tokens(left_text)
    right_obj = task_object_tokens(right_text)
    if left_obj and right_obj:
        obj_overlap = left_obj & right_obj
        min_obj = min(len(left_obj), len(right_obj))
        if len(obj_overlap) >= 2:
            return True
        if min_obj >= 3 and len(obj_overlap) / max(min_obj, 1) >= 0.75:
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
                        re.sub(r"\s+", " ", str(item).strip().lower())
                        for item in payload.get("completed_texts", [])
                        if str(item).strip()
                    ]
                if isinstance(payload.get("completed_labels"), list):
                    labels = [
                        str(item).strip()
                        for item in payload.get("completed_labels", [])
                        if str(item).strip()
                    ]
                if not labels and isinstance(payload.get("completed_texts"), list):
                    labels = [
                        str(item).strip().capitalize()
                        for item in payload.get("completed_texts", [])
                        if str(item).strip()
                    ]
    except Exception:
        hashes, text_keys, labels = set(), [], []
    return hashes, text_keys, labels


def collect_akiflow_today_items(akiflow_payload) -> list[dict]:
    routine_lower = {
        "weights", "yoga", "walk dog", "walk the dog", "get ready", "meditation", "stretch",
        "break", "lunch", "dinner", "breakfast", "shower", "morning routine", "evening routine",
    }
    rows = []
    seen_summary = set()
    if isinstance(akiflow_payload, dict) and akiflow_payload.get("status") == "ok":
        for task in akiflow_payload.get("tasks", []):
            if task.get("days_from_now") != 0:
                continue
            summary = str(task.get("summary", "")).strip()
            if not summary or summary.lower() in routine_lower:
                continue
            summary_key = re.sub(r"\s+", " ", summary.lower()).strip()
            if summary_key in seen_summary:
                continue
            time_est = "30m"
            start_iso = str(task.get("start", "")).strip()
            try:
                start = datetime.fromisoformat(task["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(task["end"].replace("Z", "+00:00"))
                mins = int((end - start).total_seconds() / 60)
                if mins > 0:
                    time_est = (f"{mins}m" if mins < 60 else f"{mins//60}h{mins%60}m" if mins % 60 else f"{mins//60}h")
            except Exception:
                pass
            seen_summary.add(summary_key)
            rows.append({"summary": summary, "time_est": time_est, "start": start_iso})
    rows.sort(
        key=lambda row: (
            str(row.get("start", "")).strip(),
            re.sub(r"\s+", " ", str(row.get("summary", "")).strip().lower()),
        )
    )
    return rows
