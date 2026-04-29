"""Todo extraction from Diarium morning pages — extracted from claude_core.diarium_ingest."""
from __future__ import annotations

import re


def categorise_action(task_text):
    """Categorise action as quick_win, maintenance, or standard."""
    task_lower = task_text.lower()

    quick_keywords = ['pick up', 'grab', 'email', 'call', 'check', 'text',
                      'message', 'quick', 'breakfast', 'lunch', 'snack',
                      'take out', 'put away', 'look at', 'read']
    if any(kw in task_lower for kw in quick_keywords):
        return 'quick_win'

    maintenance_keywords = ['clean', 'vacuum', 'tidy', 'assemble', 'put up',
                           'research', 'figure out', 'discover', 'investigate',
                           'fix', 'update', 'daemon', 'dashboard', 'script',
                           'config', 'system', 'setup', 'install', 'carpet',
                           'attic', 'furniture', 'bed', 'boxes', 'packaging',
                           'reorganise', 'reorganize', 'declutter']
    if any(kw in task_lower for kw in maintenance_keywords):
        return 'maintenance'

    return 'standard'


def estimate_time(task_text):
    """Estimate time needed for a task"""
    task_lower = task_text.lower()

    if any(word in task_lower for word in ['quick', 'email', 'call', 'check', 'review', 'read']):
        return '15m'

    if any(word in task_lower for word in ['apply', 'application', 'prepare', 'write', 'create', 'develop']):
        return '1h'

    return '30m'


def estimate_priority(task_text):
    """Estimate priority of a task"""
    task_lower = task_text.lower()

    if any(word in task_lower for word in ['urgent', 'deadline', 'interview', 'job', 'apply', 'application', 'therapy']):
        return 'High'

    if any(word in task_lower for word in ['maybe', 'consider', 'think about', 'explore', 'research']):
        return 'Low'

    return 'Medium'


def build_todo_source_text(entry):
    """Build forward-looking text bundle for todo extraction."""
    if not isinstance(entry, dict):
        return ""
    fields = [
        entry.get('what_would_make_today_great', ''),
        entry.get('daily_affirmation', ''),
        entry.get('morning_pages', ''),
        entry.get('whats_tomorrow', ''),
        entry.get('remember_tomorrow', ''),
    ]
    return '\n\n'.join(str(v).strip() for v in fields if str(v).strip())


def extract_todos_from_morning_pages(text):
    """Extract actionable todos from morning pages text - intelligent parsing"""
    todos = []

    reflective_indicators = [
        'i want to be', 'i wish', 'i feel', 'i am grateful', 'i\'m thinking',
        'i wonder', 'i hope', 'i believe', 'i realize', 'it\'s hard',
        'i struggle', 'i\'m struggling', 'i don\'t know', 'maybe i should',
        'i could', 'i might', 'it would be', 'what if',
        'the thing is', 'part of me', 'i keep'
    ]

    text_lower = text.lower()

    reflective_count = sum(1 for phrase in reflective_indicators if phrase in text_lower)
    if reflective_count > 3 and len(text) < 500:
        return []

    action_verbs = (
        "apply", "book", "buy", "call", "change", "check", "clean", "close",
        "complete", "create", "email", "figure", "fill", "find", "finish",
        "fix", "get", "grab", "install", "look", "make", "move", "organise",
        "organize", "pack", "pick", "prepare", "put", "read", "register",
        "repair", "replace", "research", "review", "schedule", "send", "set",
        "sort", "submit", "take", "tidy", "unpack", "update", "vacuum",
        "wash", "write",
    )
    action_verbs_pattern = r'(?:' + "|".join(action_verbs) + r')'

    trigger_patterns = [
        r'\b(?:i\s+(?:do\s+)?(?:need to|have to|must|should|gotta|will|plan to|am going to|\'m going to)|'
        r'we(?:\'ve)?\s+(?:got to|need to|have to|must|should|gotta)|let(?:\'s| us)|remember to|don\'t forget to)\s+(.+)',
        r'\btoday would be great if i can\s+(.+)',
        r'\bas soon as i [^,]+,\s*i(?:\'m| am)\s+going [^,]{0,40} to\s+(.+)',
        r'\ball i need to do is\s+(.+)',
    ]

    _retro_patterns = re.compile(
        r'(?:should have|should\'ve|could have|could\'ve|ought to have|wish i had|'
        r'i should have|i could have|i wish i had)',
        re.IGNORECASE
    )

    skip_phrases = [
        'feel bad', 'terrible person', 'awful person', 'bad person', 'denigrate',
        'childish', 'be more', 'be less', 'think about', 'why i', 'how i',
        'i need to be', 'i need to feel', 'i want to be', 'i want to feel',
        'not get overwhelmed', 'not feel like',
        'get myself ready', 'ready for school', 'girls ready',
        'body feels', 'feeling a little', 'feeling quite', 'feeling really',
        'check body', 'check feeling', 'check sensation', 'check energy',
    ]

    def _normalise_candidate(raw_task):
        task_text = re.sub(r'\s+', ' ', str(raw_task or '')).strip().strip('.,;:!?-\u2014')
        task_text = re.sub(r'^(?:and|then|so|just|for now|now)\s+', '', task_text, flags=re.IGNORECASE).strip()
        task_text = re.sub(r'^go\s+(?=' + action_verbs_pattern + r'\b)', '', task_text, flags=re.IGNORECASE).strip()
        task_text = re.sub(r'^to\s+', '', task_text, flags=re.IGNORECASE).strip()
        if not task_text:
            return ""

        lower = task_text.lower()
        if any(phrase in lower for phrase in skip_phrases):
            return ""
        if re.match(r'^(?:not|be|feel|worry|overwhelm|panic)\b', lower):
            return ""
        if not re.match(action_verbs_pattern + r'\b', lower):
            return ""
        if len(task_text) < 8 or len(task_text) > 120:
            return ""
        task_words = [w for w in re.findall(r"[a-zA-Z']+", task_text) if len(w) > 2]
        if len(task_words) < 2:
            return ""
        return task_text[0].upper() + task_text[1:]

    sentence_parts = re.split(r'[\n\r]+|(?<=[.!?])\s+', text)
    for sentence in sentence_parts:
        sentence = re.sub(r'\s+', ' ', sentence).strip()
        if not sentence:
            continue
        if _retro_patterns.search(sentence):
            continue

        candidate_chunks = []
        for pattern in trigger_patterns:
            match = re.search(pattern, sentence, re.IGNORECASE)
            if match:
                candidate_chunks.append(match.group(1).strip())

        if re.match(r'^(?:go\s+)?' + action_verbs_pattern + r'\b', sentence, re.IGNORECASE):
            candidate_chunks.append(sentence)

        for chunk in candidate_chunks:
            pieces = re.split(
                r'\s*(?:,|;|\band\b|\bthen\b)\s*(?=(?:to\s+)?(?:go\s+)?' + action_verbs_pattern + r'\b|not\b)',
                chunk,
                flags=re.IGNORECASE,
            )
            for piece in pieces:
                task_text = _normalise_candidate(piece)
                if not task_text:
                    continue
                time_est = estimate_time(task_text)
                priority = estimate_priority(task_text)
                category = categorise_action(task_text)
                todos.append({
                    'task': task_text,
                    'time': time_est,
                    'priority': priority,
                    'category': category
                })

    seen = set()
    unique_todos = []
    for todo in todos:
        task_lower = todo['task'].lower()
        task_key = re.sub(r'\b(?:the|that|this|a|an)\b', ' ', task_lower)
        task_key = re.sub(r'[^a-z0-9\s]', '', task_key)
        task_key = re.sub(r'\s+', ' ', task_key).strip()
        if task_key not in seen:
            seen.add(task_key)
            unique_todos.append(todo)

    return unique_todos[:10]
