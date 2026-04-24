#!/usr/bin/env python3
"""
Parse Diarium .docx exports and extract mental health insights.

Diarium exports entries as .docx files directly to the Export folder.
DOCX files are ZIP archives internally containing XML + media - this script
reads them directly without needing to extract from an outer archive.

Usage:
    python parse_diarium.py                    # Parse today's entry
    python parse_diarium.py path/to/file.docx  # Parse specific file
    python parse_diarium.py --json             # Output as JSON

Supports:
    - .docx files (preferred - includes images)
    - .txt files (fallback)
    - Image extraction from DOCX media folder
    - Mental health keyword detection
    - Todo extraction from morning pages
"""
import os
import sys
import re
import json
import zipfile
from pathlib import Path
from datetime import datetime, timedelta

# Image cache directory
IMAGE_CACHE_DIR = Path.home() / ".claude" / "cache" / "diarium-images"
KNOWN_LOCATIONS_FILE = Path(__file__).resolve().parent / "known-locations.json"
SECTION_STATUS_ABSENT = "ABSENT"
SECTION_STATUS_PRESENT_EMPTY = "PRESENT_EMPTY"
SECTION_STATUS_PRESENT_VALUE = "PRESENT_VALUE"


def _section_status_from_value(value, present=False):
    if isinstance(value, str) and value.strip():
        return SECTION_STATUS_PRESENT_VALUE
    if value:
        return SECTION_STATUS_PRESENT_VALUE
    return SECTION_STATUS_PRESENT_EMPTY if present else SECTION_STATUS_ABSENT


# --- Re-exports from submodules for backward compatibility ---

# Location helpers (phase 07)
from .diarium.location import (  # noqa: E402,F401
    KNOWN_LOCATIONS_FILE as _LOCATION_FILE,
    _normalise_location_key,
    load_known_locations,
    normalise_known_location,
    extract_location_from_diarium,
)

# Media/image extraction (phase 11)
from .diarium.media import (  # noqa: E402,F401
    extract_images_from_docx,
    extract_images_from_diarium_zip,
    extract_images_from_file,
)

# Text cleaning and parsing (phase 11)
from .diarium.text import (  # noqa: E402,F401
    _parse_diarium_json_payload,
    _load_diarium_json_entries,
    _diarium_html_to_text,
    _entry_text_from_diarium_json_item,
    _extract_text_from_diarium_json_source,
    _extract_text_for_date_from_diarium_json_source,
    extract_text_from_file,
    cleanup_transcription,
    strip_section_markers,
    trim_combined_evening_spillover,
    strip_chatgpt_contamination,
    strip_updates_metadata,
    strip_tracker_metadata,
)

# Mental health keyword detection (phase 11)
from .diarium.keywords import (  # noqa: E402,F401
    find_mental_health_keywords,
    find_mental_health_keywords_categorised,
)

# Todo extraction (phase 11)
from .diarium.todos import (  # noqa: E402,F401
    extract_todos_from_morning_pages,
    build_todo_source_text,
    categorise_action,
    estimate_time,
    estimate_priority,
)

# --- Functions that remain in this module ---
# parse_diarium_entry, extract_structured_morning/evening_pages,
# hydrate_entry_from_structured_morning, get_analysis_context,
# file discovery functions, main()

# NOTE: The old function bodies for extract_images_*, extract_text_from_file,
# cleanup_transcription, strip_*, find_mental_health_keywords*,
# extract_todos_from_morning_pages, build_todo_source_text, categorise_action,
# estimate_time, estimate_priority have been removed from this file.
# They now live in their respective submodules and are re-exported above.




def parse_diarium_entry(text):
    """Parse a Diarium entry and extract key sections"""
    entry = {}

    # Strip iOS shortcut preamble e.g. "Here's your final entry, ready to paste into Diarium:"
    text = re.sub(r"(?i)here[''\u2019]s your final entry,?\s*ready to paste into diarium:?\s*\n*", '', text)
    # Strip standalone "Morning Journal" heading that follows the preamble
    text = re.sub(r'(?m)^Morning Journal\s*\n+', '', text)
    # Strip iOS Shortcut "Final Diarium Entry" header and footer artifacts
    text = re.sub(r'(?m)^Final Diarium Entry\s*\n*', '', text)
    text = re.sub(r'(?m)^Copied/ready to paste into Diarium\.?\s*$', '', text)
    # Normalise numbered section prefixes from iOS Shortcut format
    # e.g. "1. How I woke up" → "How I woke up", "10. Updates (optional)" → "Updates (optional)"
    text = re.sub(r'(?m)^\d{1,2}\.\s+', '', text)
    # Strip boilerplate / separators that appear in combined JSON exports
    text = re.sub(
        r"(?im)^\s*All sections complete\.\s*Here['\u2019]?s your full evening entry, ready for Diarium:?\s*$",
        '',
        text,
    )
    text = re.sub(r'(?m)^\s*(?:---+|⸻+)\s*$', '', text)

    # Extract date from first line
    date_match = re.search(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\w+\s+\d+,\s+\d+)', text)
    if date_match:
        entry['date'] = date_match.group(2)

    # Extract sections — ordered by template position
    # Morning: grateful -> letting_go -> what_would_make_today_great -> daily_affirmation -> body_check -> morning_pages -> updates
    # Evening: three_things -> ta_dah -> brave -> whats_tomorrow -> remember_tomorrow -> evening_reflections
    sections = {
        # Primary = Diarium native headers. Aliases = old transcription-skill output (line-anchored
        # with (?:^|\n) to avoid false matches mid-paragraph, e.g. in ## Three things I'm grateful for today).
        # Note: ## header format entries are handled by extract_structured_morning/evening_pages —
        # these traditional patterns are fallbacks for old non-## format entries.
        'grateful': r'(?:I am grateful for…|(?:^|\n)Grateful for:?|(?:^|\n)Three things I[\'’]m grateful for today:?)(.*?)(?:What I[\'’]m anxious or uncertain about|(?:^|\n)My one important thing today|What am I letting go of\?|(?:^|\n)Letting go|What would make today great\?|Daily affirmation|Morning pages|$)',
        'letting_go': r'(?:What am I letting go of\?|(?:^|\n)Letting go:?)(.*?)(?:\nUpdates\b|What would make today great\?|Daily affirmation|Morning pages|(?:^|\n)Three things that happened today\b|(?:^|\n)Ta[-\s]?[Dd]ah(?:\s+list)?\b|(?:^|\n)Where was I brave\??|(?:^|\n)What\'s tomorrow\??|(?:^|\n)What feels important for tomorrow\??|(?:^|\n)Anything worth remembering for tomorrow\??|(?:^|\n)Evening Reflections\b|(?:^|\n)Letting go tonight\b|$)',
        'what_would_make_today_great': r'(?:What would make today great\?|(?:^|\n)What would make today great:?|(?:^|\n)My one important thing today:?)(.*?)(?:Letting go|Updates|Daily affirmation|Morning pages|$)',
        'daily_affirmation': r'(?:^|\n)Daily affirmation:?(.*?)(?:How does my body feel\?|(?:^|\n)Body check|(?:^|\n)Three things I[\'’]m grateful for today|(?:^|\n)What I[\'’]m anxious or uncertain about|(?:^|\n)My one important thing today|Morning pages|$)',
        'body_check': r'(?:How does my body feel\?|(?:^|\n)Body check:?)(.*?)(?:Sensory check|Daily affirmation|(?:^|\n)What[\''']s on my mind|Morning pages|Priorities|Tasks|Three things|$)',
        'sensory_check': r'(?:^|\n)Sensory check:?(.*?)(?:Daily affirmation|(?:^|\n)Three things I[\''']m grateful for today|(?:^|\n)What I[\''']m anxious or uncertain about|(?:^|\n)My one important thing today|Morning pages|$)',
        "morning_pages": "(?:^|\\n)(?:##\\s*)?(?:Morning pages|What[‘\\u2019]s on my mind):?(.*?)(?:\\n##\\s|\\nUpdates\\n|\\nUpdates$|(?:^|\\n)Three things I[‘\\u2019]m grateful for today|(?:^|\\n)What I[‘\\u2019]m anxious or uncertain about|(?:^|\\n)My one important thing today|Priorities|Tasks|Three things|Ta-Dah|Where was I brave|How could I have made|What\u2019s tomorrow|What feels important for tomorrow|$)",
        'updates': r'(?:^|\n)Updates:?\n(.*?)(?:\n##(?:\s|$)|Three things that happened today|Ta-Dah list|Where was I brave|What\'s tomorrow|What feels important for tomorrow|Evening Reflections|$)',
        'three_things': r'Three things that happened today:?(.*?)(?:Ta-Dah list|Where was I brave|How could I have made|$)',
        'ta_dah': r'(?:(?:^|\n)(?:##\s*)?Ta[-\s]?[Dd]ah(?:\s+list)?:?)(.*?)(?:\n##\s|Where was I brave|How could I have made|What\'s tomorrow|What feels important for tomorrow|$)',
        'follow_up': r'(?:Follow[- ]?up|Ideas to revisit|Unfinished from yesterday):?(.*?)(?:Updates|Three things|Ta-Dah|Where was I brave|What\'s tomorrow|What feels important for tomorrow|Evening Reflections|$)',
        'brave': r'(?:Where was I brave\?|How could I have made today better\?|(?:^|\n)Brave:?)(.*?)(?:What\'s tomorrow|What feels important for tomorrow|What do I need to remember|Anything worth remembering for tomorrow|(?:^|\n)Remember tomorrow|Evening Reflections|Weather|$)',
        'whats_tomorrow': r'(?:What\'s tomorrow\??|What feels important for tomorrow\??)(.*?)(?:What do I need to remember|Anything worth remembering for tomorrow|(?:^|\n)(?:##\s*)?Remember tomorrow|(?:^|\n)##\s*Evening Reflections|Evening Reflections|Weather|Location|$)',
        'remember_tomorrow': r'(?:What do I need to remember for tomorrow\?|Anything worth remembering for tomorrow\?|(?:^|\n)(?:##\s*)?Remember tomorrow:?)(.*?)(?:(?:\d+[.)]\s+)?(?:##\s*)?Evening Reflections|Weather|Location|$)',
        'evening_reflections': r'(?:^|\n)(?:\d+[.)]\s+)?Evening Reflections:?(.*?)(?:(?:\d+[.)]\s+)?Letting go tonight|Weather|Location|$)',
        'letting_go_tonight': r'(?:^|\n)(?:\d+[.)]\s+)?Letting go tonight:?(.*?)(?:Weather|Location|$)',
        'weather': r'(?:^|\n)Weather:?(.*?)(?:Location|$)',
        'location': r'(?:^|\n)Location:?(.*)$',
    }

    section_presence = {}
    for key, pattern in sections.items():
        flags = re.DOTALL | re.IGNORECASE
        match = re.search(pattern, text, flags)
        if match:
            section_presence[key] = True
            content = match.group(1).strip()
            # Clean up excessive newlines
            content = re.sub(r'\n{3,}', '\n\n', content)
            if content:
                # If regex fallback captured the whole evening template block, recover only
                # the true Evening Reflections section from structured ## headers.
                if key == 'evening_reflections' and '##' in content:
                    try:
                        ep_inline = extract_structured_evening_pages(content)
                    except Exception:
                        ep_inline = {}
                    structured_reflection = str((ep_inline or {}).get('evening_reflections', '')).strip()
                    if structured_reflection:
                        content = structured_reflection
                # Strip section separator markers (##, ##.) from all fields
                content = strip_section_markers(content)
                # Strip AI-generated contamination from relevant sections
                if key in {'morning_pages', 'letting_go', 'letting_go_tonight'}:
                    content = strip_chatgpt_contamination(content)
                # Clean voice-transcribed sections (all except short structured ones)
                transcribed_sections = {'morning_pages', 'three_things', 'ta_dah', 'follow_up', 'brave', 'whats_tomorrow', 'what_would_make_today_great', 'grateful', 'daily_affirmation', 'body_check', 'sensory_check', 'letting_go', 'updates', 'remember_tomorrow', 'evening_reflections', 'letting_go_tonight'}
                if key in transcribed_sections:
                    entry[f'{key}_raw'] = content
                    content = cleanup_transcription(content)
                if key == 'updates':
                    content = strip_updates_metadata(content)
                elif key in {'letting_go', 'evening_reflections', 'remember_tomorrow', 'whats_tomorrow', 'three_things', 'ta_dah', 'brave', 'letting_go_tonight'}:
                    content = strip_tracker_metadata(content)
                entry[key] = content

    # Preserve section lifecycle metadata for non-destructive downstream merges.
    entry['whats_tomorrow_status'] = _section_status_from_value(
        entry.get('whats_tomorrow', ''),
        present=bool(section_presence.get('whats_tomorrow')),
    )
    entry['remember_tomorrow_status'] = _section_status_from_value(
        entry.get('remember_tomorrow', ''),
        present=bool(section_presence.get('remember_tomorrow')),
    )

    # New transcription template fallback (2026+):
    # If legacy patterns miss these sections, recover them explicitly.
    if not entry.get('morning_pages'):
        mind_match = re.search(
            r"(?:^|\n)(?:##\s*)?What[\’’]s on my mind:?(.*?)(?:\n##\s|\n(?:##\s*)?(?:Body check|Daily affirmation|Three things I[\’’]m grateful for today|What I[\’’]m anxious or uncertain about|My one important thing today|Letting go|Updates)\b|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if mind_match:
            recovered = strip_section_markers(mind_match.group(1).strip())
            recovered = strip_chatgpt_contamination(recovered)
            if recovered:
                entry['morning_pages_raw'] = recovered
                entry['morning_pages'] = cleanup_transcription(recovered)

    if not entry.get('what_would_make_today_great'):
        important_match = re.search(
            r"(?:^|\n)My one important thing today:?(.*?)(?:\n(?:Letting go|Updates|What do I need to remember|Evening Reflections|$))",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if important_match:
            recovered = strip_section_markers(important_match.group(1).strip())
            if recovered:
                entry['what_would_make_today_great_raw'] = recovered
                entry['what_would_make_today_great'] = cleanup_transcription(recovered)

    def _extract_named_mood_tag(name):
        """Extract mood tags from variants like:
        - Tracker: Morning Mood: calm
        - Morning Mood: calm
        - Morning mood tag: calm
        """
        patterns = [
            rf"Tracker:\s*{name}\s*Mood(?:\s*Tag)?\s*:\s*(.+?)(?:\n|$)",
            rf"(?:^|\n)\s*{name}\s*Mood(?:\s*Tag)?\s*:\s*(.+?)(?:\n|$)",
            rf"(?:^|\n)\s*{name}\s*:\s*(.+?)(?:\n|$)",
        ]
        for pattern in patterns:
            m_local = re.search(pattern, text, re.IGNORECASE)
            if m_local:
                return m_local.group(1).strip().lower()
        return ""

    def _clean_mood_label(raw):
        label = str(raw or "").strip().lower()
        if not label:
            return ""
        label = re.sub(r'^\s*mood\s*[:\-]?\s*', '', label, flags=re.IGNORECASE)
        label = re.sub(r'^\s*(morning|evening)\s*(mood)?\s*[:\-]?\s*', '', label, flags=re.IGNORECASE)
        label = re.sub(r'\s+', ' ', label).strip(' ,.;')
        return label

    # Extract mood tags from Diarium tracker.
    # Backwards compatibility:
    # - mood_tag (legacy single-day tag, kept as unscoped metadata)
    # - mood_tag_morning / mood_tag_evening (slot-specific tags)
    mood_tag = ""
    tracker_line = ""
    m_tracker = re.search(r'(?:^|\n)\s*Tracker\s*:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
    if m_tracker:
        tracker_line = str(m_tracker.group(1) or "").strip()
        m_mood = re.search(r'\bMood(?:\s*Tag)?\s*:\s*(.+)$', tracker_line, re.IGNORECASE)
        if m_mood:
            mood_tag = _clean_mood_label(m_mood.group(1))

    mood_tag_morning = _clean_mood_label(_extract_named_mood_tag("Morning"))
    mood_tag_evening = _clean_mood_label(_extract_named_mood_tag("Evening"))

    # Fallback for compact unscoped tracker format: "Mood: X, Mood: Y"
    if tracker_line and (not mood_tag_morning or not mood_tag_evening):
        tracker_moods = [
            _clean_mood_label(part)
            for part in re.findall(r'\bMood(?:\s*Tag)?\s*:\s*([^,\n]+)', tracker_line, flags=re.IGNORECASE)
        ]
        tracker_moods = [part for part in tracker_moods if part]
        if len(tracker_moods) >= 2:
            if not mood_tag_morning:
                mood_tag_morning = tracker_moods[0]
            if not mood_tag_evening:
                mood_tag_evening = tracker_moods[1]

    entry['mood_tag'] = mood_tag
    entry['mood_tag_morning'] = mood_tag_morning
    entry['mood_tag_evening'] = mood_tag_evening

    # Extract rating: count filled star characters (★ = filled, ☆ = empty)
    diarium_rating = 0
    m = re.search(r'Rating:\s*([★☆]+)', text)
    if m:
        diarium_rating = m.group(1).count('★')
    entry['diarium_rating'] = diarium_rating

    return entry

def extract_structured_morning_pages(text):
    """Extract structured sections from morning pages when written with headers.

    Looks for ## headers matching the morning pages template:
      ## How I woke up
      ## What's on my mind
      ## Body check
      ## Three things I'm grateful for today
      ## What I'm anxious or uncertain about
      ## My one important thing today
      ## Letting go

    Returns a dict of section_key -> content, or empty dict if no headers found.
    """
    if not text:
        return {}

    # Normalise numbered section prefixes from iOS Shortcut format
    # e.g. "1. How I woke up" → "How I woke up"
    text = re.sub(r'(?m)^\d{1,2}\.\s+', '', text)

    # Define the expected headers (order matters for regex boundaries)
    # Each entry: (key, ## pattern, bare-header pattern for docx-extracted text)
    header_patterns = [
        ('how_i_woke_up', r"##\s*How I woke up", r"How I woke up"),
        ('whats_on_my_mind', r"##\s*What'?s on my mind", r"What['\u2019]?s on my mind"),
        ('body_check', r"##\s*Body check", r"Body check"),
        ('sensory_check', r"##\s*Sensory check", r"Sensory check"),
        ('daily_affirmation', r"##\s*Daily affirmation", r"Daily affirmation"),
        ('grateful_for_today', r"##\s*(?:Three things I'?m grateful for today|Grateful(?:\s+for)?)", r"(?:Three things I['\u2019]?m grateful for today|Grateful(?:\s+for)?)"),
        ('anxious_about', r"##\s*What I'?m anxious or uncertain about", r"What I['\u2019]?m anxious or uncertain about"),
        ('one_important_thing', r"##\s*(?:My one important thing today|What would make today great\??)", r"(?:My one important thing today|What would make today great\??)"),
        ('letting_go_mp', r"##\s*Letting go", r"Letting go"),
        ('follow_up', r"##\s*Follow[- ]?up", r"Follow[- ]?up"),
    ]

    # Choose header patterns: ## format (Markdown) or bare (docx-extracted)
    use_bare = '##' not in text
    selected_patterns = [(key, bare_pat if use_bare else md_pat) for key, md_pat, bare_pat in header_patterns]

    if use_bare:
        # Bare headers in docx must appear at start of a line (after 1+ newlines) to avoid
        # false matches inside paragraph text.
        anchored = [(key, rf"(?:^|\n)(?:{pat})[ \t]*(?:\n|$)") for key, pat in selected_patterns]
    else:
        anchored = selected_patterns

    # Build a combined pattern to split on any of the headers
    all_headers = '|'.join(f'(?:{pat})' for _, pat in anchored)
    splits = re.split(f'({all_headers})', text, flags=re.IGNORECASE)

    if len(splits) < 3:
        return {}

    structured = {}
    i = 1  # skip content before first header
    while i < len(splits) - 1:
        header_text = splits[i].strip()
        content = splits[i + 1].strip() if i + 1 < len(splits) else ''
        # Match header to key
        for key, pattern in anchored:
            if re.match(pattern, header_text, re.IGNORECASE):
                # Clean placeholder text in parentheses
                cleaned = re.sub(r'^\(.*?\)\s*', '', content, flags=re.DOTALL).strip()
                # Remove Diarium auto-appended metadata (Updates, Weather, Location)
                cleaned = re.sub(r'\s*\n+Updates\s*\n.*$', '', cleaned, flags=re.DOTALL).strip()
                cleaned = re.sub(r'\s*\n+Weather:.*$', '', cleaned, flags=re.DOTALL).strip()
                cleaned = re.sub(r'\s*\n+Location:.*$', '', cleaned, flags=re.DOTALL).strip()
                cleaned = strip_section_markers(cleaned)
                if key == 'letting_go_mp':
                    cleaned = trim_combined_evening_spillover(cleaned)
                cleaned = strip_tracker_metadata(cleaned)
                cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
                if cleaned:
                    structured[key] = cleaned
                break
        i += 2

    return structured


def extract_structured_evening_pages(text):
    """Extract structured sections from evening pages when written with ## headers.

    Looks for ## headers matching the evening pages template:
      ## Three things that happened today
      ## Ta-Dah list
      ## Where was I brave?
      ## What's tomorrow? / ## What feels important for tomorrow?
      ## What do I need to remember for tomorrow? / ## Anything worth remembering for tomorrow?
      ## Evening Reflections
      ## Letting go tonight

    Returns a dict of section_key -> content, or empty dict if no headers found.
    """
    if not text or '##' not in text:
        return {}

    header_patterns = [
        ('three_things_happened', r"##\s*Three things that happened today"),
        ('ta_dah_list', r"##\s*(?:Ta-?Dah list|Ta[\s\-]Dah)"),
        ('where_was_i_brave', r"##\s*(?:Where was I brave|Brave)\??"),
        ('whats_tomorrow', r"##\s*(?:What'?s tomorrow|What feels important for tomorrow)\??"),
        ('remember_tomorrow', r"##\s*(?:What do I need to remember for tomorrow|Anything worth remembering for tomorrow|Remember tomorrow)\??"),
        ('evening_reflections', r"##\s*Evening Reflections"),
        ('letting_go_tonight', r"##\s*Letting go tonight"),
    ]

    all_headers = '|'.join(f'(?:{pat})' for _, pat in header_patterns)
    splits = re.split(f'({all_headers})', text, flags=re.IGNORECASE)

    if len(splits) < 3:
        return {}

    structured = {}
    i = 1
    while i < len(splits) - 1:
        header_text = splits[i].strip()
        content = splits[i + 1].strip() if i + 1 < len(splits) else ''
        for key, pattern in header_patterns:
            if re.match(pattern, header_text, re.IGNORECASE):
                cleaned = re.sub(r'^\(.*?\)\s*', '', content, flags=re.DOTALL).strip()
                # Remove Diarium auto-appended metadata (Updates, Weather, Location)
                cleaned = re.sub(r'\s*\n+Updates\s*\n.*$', '', cleaned, flags=re.DOTALL).strip()
                cleaned = re.sub(r'\s*\n+Weather:.*$', '', cleaned, flags=re.DOTALL).strip()
                cleaned = re.sub(r'\s*\n+Location:.*$', '', cleaned, flags=re.DOTALL).strip()
                cleaned = strip_section_markers(cleaned)
                cleaned = strip_tracker_metadata(cleaned)
                cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
                if cleaned:
                    structured[key] = cleaned
                break
        i += 2

    return structured


def hydrate_entry_from_structured_morning(entry, mp_structured):
    """Promote structured morning sections into the legacy entry fields."""
    if not mp_structured:
        return entry

    field_map = {
        'how_i_woke_up': 'how_i_woke_up',
        'whats_on_my_mind': 'morning_pages',
        'body_check': 'body_check',
        'sensory_check': 'sensory_check',
        'daily_affirmation': 'daily_affirmation',
        'grateful_for_today': 'grateful',
        'one_important_thing': 'what_would_make_today_great',
        'letting_go_mp': 'letting_go',
    }

    for source_key, target_key in field_map.items():
        value = str(mp_structured.get(source_key) or '').strip()
        if not value:
            continue
        if source_key == 'letting_go_mp':
            value = trim_combined_evening_spillover(value)
        entry[target_key] = value
        if target_key in {
            'morning_pages',
            'body_check',
            'sensory_check',
            'daily_affirmation',
            'grateful',
            'what_would_make_today_great',
            'letting_go',
        }:
            entry[f'{target_key}_raw'] = value

    return entry


def get_analysis_context(entry, use_ai=False):
    """
    Prepare context for Claude's intelligent analysis of the entry.
    Returns a dict with full text and suggested focus areas.

    AI-FIRST PATTERN:
    - When use_ai=True: Tries AI-based emotional tone + todo extraction first
    - When use_ai=False (default): Uses heuristic keyword analysis only
    - Daemon overlays AI-extracted todos on top regardless

    suggested_actions are populated from regex extraction here as a baseline.
    The daemon overlays AI-extracted todos (via Haiku) on top for richer results.
    """
    context = {
        'full_morning_pages': entry.get('morning_pages', ''),
        'grateful': entry.get('grateful', ''),
        'intent': entry.get('what_would_make_today_great', '') or entry.get('daily_affirmation', ''),
        'emotional_tone': None,
        'suggested_actions': [],
        'open_loops': [],
        'analysis_path': 'heuristic',  # Track which path was used
    }

    morning_pages = context['full_morning_pages'].lower()

    # --- AI-FIRST: Try AI emotional tone + todo extraction ---
    ai_analysis_done = False
    if use_ai and context['full_morning_pages']:
        try:
            scripts_dir = str(Path.home() / ".claude" / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from shared.ai_service import try_ai_analysis

            ai_prompt = f"""Determine emotional tone (anxious/low_energy/positive/frustrated/reflective/avoidant/neutral), tone scores (0-5), and action items from this morning pages entry.

{context['full_morning_pages'][:1500]}

JSON: {{"emotional_tone": "anxious", "tone_scores": {{"anxious": 4, "positive": 1}}, "todos": [{{"task": "...", "category": "standard", "priority": "Medium"}}]}}"""

            analysis = try_ai_analysis(
                ai_prompt,
                fallback_fn=lambda: None,
                label="parse_diarium_analysis",
                max_tokens=512
            )

            if analysis["path"] == "ai" and analysis["result"]:
                ai_data = analysis["result"]
                context['emotional_tone'] = ai_data.get('emotional_tone', 'neutral')
                context['tone_scores'] = ai_data.get('tone_scores', {})
                context['analysis_path'] = 'ai'
                ai_analysis_done = True

                # Populate AI-extracted todos
                for todo in ai_data.get('todos', []):
                    context['suggested_actions'].append({
                        'task': todo.get('task', ''),
                        'category': todo.get('category', 'standard'),
                        'time_estimate': todo.get('time', '30m'),
                        'priority': todo.get('priority', 'Medium'),
                        'source': 'ai',
                        'addressee': todo.get('addressee', 'self')
                    })
        except Exception:
            pass  # Fall through to heuristic

    # --- HEURISTIC FALLBACK: Keyword-based analysis ---
    if not ai_analysis_done:
        # Detect emotional tone -- check for multiple signals, pick strongest
        tone_scores = {
            'anxious': sum(1 for w in ['anxious', 'worried', 'stress', 'overwhelm', 'panic', 'scared', 'dread', 'nervous', 'racing'] if w in morning_pages),
            'low_energy': sum(1 for w in ['sad', 'down', 'low', 'depressed', 'tired', 'exhausted', 'drained', 'numb', 'empty', 'hopeless'] if w in morning_pages),
            'positive': sum(1 for w in ['excited', 'hopeful', 'motivated', 'ready', 'good', 'proud', 'grateful', 'happy', 'calm', 'strong', 'progress'] if w in morning_pages),
            'frustrated': sum(1 for w in ['frustrated', 'angry', 'annoyed', 'stuck', 'unfair', 'resentment', 'irritated'] if w in morning_pages),
            'reflective': sum(1 for w in ['thinking about', 'wondering', 'reflecting', 'realise', 'realize', 'noticed', 'pattern', 'learning'] if w in morning_pages),
            'avoidant': sum(1 for w in ['avoiding', 'procrastinat', "can't face", 'putting off', 'later', 'not ready', 'too much'] if w in morning_pages),
        }
        # Pick the tone with highest score, default to neutral
        max_tone = max(tone_scores, key=tone_scores.get) if any(tone_scores.values()) else 'neutral'
        context['emotional_tone'] = max_tone if tone_scores.get(max_tone, 0) > 0 else 'neutral'
        context['tone_scores'] = {k: v for k, v in tone_scores.items() if v > 0}  # Only non-zero

    # Categorised keyword analysis (always run -- lightweight, supplements both paths)
    categorised = find_mental_health_keywords_categorised(context['full_morning_pages'])
    context['categories_hit'] = categorised.get('categories_hit', {})
    context['categorised_insights'] = categorised.get('insights', [])[:10]

    # Populate suggested_actions from regex-extracted todos (baseline)
    # These supplement AI-extracted todos (if any) -- deduplication happens downstream
    if not ai_analysis_done:
        todos = extract_todos_from_morning_pages(build_todo_source_text(entry))
        for todo in todos:
            context['suggested_actions'].append({
                'task': todo['task'],
                'category': todo.get('category', 'standard'),
                'time_estimate': todo.get('time', '30m'),
                'priority': todo.get('priority', 'Medium'),
                'source': 'regex',  # Will be 'ai' when daemon overlays
                'addressee': 'self'  # Default; AI extraction detects 'claude' addressee
            })

    # Detect open loops (things mentioned but not actionable yet)
    open_loop_patterns = [
        r'(?:need to think about|should consider|maybe|might) ([^.!?\n]+)',
        r'(?:waiting for|waiting on) ([^.!?\n]+)',
        r'(?:haven\'t heard|no response from) ([^.!?\n]+)',
    ]

    for pattern in open_loop_patterns:
        matches = re.finditer(pattern, context['full_morning_pages'], re.IGNORECASE)
        for match in matches:
            loop = match.group(1).strip()
            if len(loop) > 10 and len(loop) < 80:
                context['open_loops'].append(loop)

    # Detect conflict content in whats_tomorrow — flag for targeted coaching
    whats_tomorrow_text = entry.get('whats_tomorrow', '') or entry.get('whats_tomorrow_raw', '')
    if whats_tomorrow_text:
        conflict_keywords = [
            'fight', 'argument', 'argued', 'shouted', 'screamed', 'violent',
            'physical', 'blocked', 'pushed', 'hit', 'threw', 'horrible',
            'disgusting', 'awful', 'upset me', 'angry at', 'in front of the',
        ]
        wt_lower = whats_tomorrow_text.lower()
        conflict_hits = [kw for kw in conflict_keywords if kw in wt_lower]
        if conflict_hits:
            context['conflict_context'] = {
                'detected': True,
                'keywords': conflict_hits,
                'text': whats_tomorrow_text[:300],
                'source': 'whats_tomorrow',
            }

    return context


def _is_temp_export_file(path):
    """Return True for transient/system files we should ignore."""
    name = str(path.name or "")
    lower = name.lower()
    if not name:
        return True
    if lower in {".ds_store"}:
        return True
    if name.startswith(".") or name.startswith("~$"):
        return True
    if lower.endswith(("~", ".tmp", ".part", ".crdownload", ".download", ".icloud")):
        return True
    return False


def _diarium_copy_index(path):
    """Extract Finder/Drive duplicate suffix index from filename (e.g. '(2)')."""
    stem = str(getattr(path, "stem", "") or "")
    match = re.search(r"\((\d+)\)\s*$", stem)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _diarium_export_sort_key(path):
    """Stable oldest->newest ordering for same-day exports (handles '(1)' copies)."""
    try:
        mtime_ns = int(path.stat().st_mtime_ns)
    except Exception:
        mtime_ns = 0
    copy_index = _diarium_copy_index(path)
    # Tie-breaker order matters when mtimes are equal (copy variants often share second-level mtime).
    return (mtime_ns, copy_index, str(path.name).lower())


def _looks_like_diarium_export(text):
    """Heuristic confidence check for Diarium-like body content."""
    if not text:
        return False
    raw = str(text)
    if raw.startswith("Error reading "):
        return False
    compact = re.sub(r"\s+", " ", raw).strip().lower()
    if len(compact) < 120:
        return False

    markers = [
        "i am grateful",
        "grateful for",
        "what would make today great",
        "what am i letting go",
        "daily affirmation",
        "body check",
        "morning pages",
        "ta dah",
        "three things",
        "what's tomorrow",
    ]
    hits = sum(1 for marker in markers if marker in compact)
    return hits >= 2


def _fallback_candidate_score(path, text, today, now):
    """Score a recent file for fallback parsing when expected filename is absent."""
    score = 0.0
    lower_name = path.name.lower()
    text_lower = str(text or "").lower()

    if today in lower_name:
        score += 7.0
    if today in text_lower:
        score += 5.0

    if path.suffix.lower() == ".docx":
        score += 1.0

    marker_boosts = {
        "grateful": 1.2,
        "what would make today great": 1.5,
        "morning pages": 1.2,
        "ta dah": 1.0,
        "three things": 1.0,
        "what's tomorrow": 0.8,
    }
    for marker, boost in marker_boosts.items():
        if marker in text_lower:
            score += boost

    try:
        age_hours = max(0.0, (now - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600.0)
    except Exception:
        age_hours = 999.0
    if age_hours <= 48:
        score += max(0.0, 3.0 - (age_hours / 16.0))

    return score


def find_diarium_files_for_date(export_folder, today, now=None):
    """Find same-day Diarium exports, preferring ZIP/JSON over DOCX/TXT."""
    now = now or datetime.now()
    export_folder = Path(export_folder)

    candidate_groups = []
    for suffix in ('.zip', '.json', '.docx', '.txt'):
        matches = [
            p for p in export_folder.glob(f"Diarium_{today}*{suffix}")
            if p.is_file() and not _is_temp_export_file(p)
        ]
        if suffix in {'.zip', '.json'}:
            valid_matches = [
                p for p in matches
                if _looks_like_diarium_export(extract_text_from_file(p))
            ]
            candidate_groups.append(valid_matches)
        else:
            candidate_groups.append(matches)

    for matches in candidate_groups:
        if matches:
            return sorted(matches, key=_diarium_export_sort_key), False, ""

    # Check for date-range bulk exports (e.g. Diarium_2026-04-01_2026-04-12.zip)
    # where the target date falls within the export's date range.
    _range_pat = re.compile(r"Diarium_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})")
    for suffix in ('.zip', '.json'):
        range_matches = []
        for p in export_folder.glob(f"Diarium_*{suffix}"):
            if not p.is_file() or _is_temp_export_file(p):
                continue
            m = _range_pat.match(p.stem.split(" ")[0])
            if not m:
                continue
            start_d, end_d = m.group(1), m.group(2)
            if start_d < end_d and start_d <= today <= end_d:
                range_matches.append(p)
        if range_matches:
            return sorted(range_matches, key=_diarium_export_sort_key), False, ""

    matching_files, fallback_reason = find_fallback_diarium_files(export_folder, today, now=now)
    return matching_files, bool(matching_files), fallback_reason


def find_fallback_diarium_files(export_folder, today, now=None, recent_hours=48, max_scan=30):
    """Find recent Diarium-like files when standard Diarium_YYYY-MM-DD* files are missing."""
    now = now or datetime.now()
    supported_suffixes = {".zip", ".json", ".docx", ".txt"}
    ranked = []
    scanned = 0

    try:
        files = sorted(export_folder.iterdir(), key=os.path.getmtime, reverse=True)
    except Exception:
        return [], ""

    for path in files:
        if scanned >= max_scan:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in supported_suffixes:
            continue
        if _is_temp_export_file(path):
            continue

        scanned += 1

        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            continue
        if now - mtime > timedelta(hours=recent_hours):
            continue

        text = extract_text_from_file(path)
        if not _looks_like_diarium_export(text):
            continue

        score = _fallback_candidate_score(path, text, today, now)
        mentions_today = today in path.name or today in str(text)
        ranked.append({
            "path": path,
            "mtime": mtime,
            "score": score,
            "mentions_today": mentions_today,
        })

    if not ranked:
        return [], ""

    today_matches = [row for row in ranked if row["mentions_today"]]
    if today_matches:
        selected = sorted(today_matches, key=lambda row: (_diarium_export_sort_key(row["path"]), row["mtime"]))
        reason = f"fallback recent match for {today}"
        return [row["path"] for row in selected], reason

    best = max(ranked, key=lambda row: row["score"])
    threshold = best["score"] - 2.0
    recent_window = timedelta(hours=8)
    selected = [
        row for row in ranked
        if row["score"] >= threshold and abs(row["mtime"] - best["mtime"]) <= recent_window
    ]
    if not selected:
        selected = [best]

    selected = sorted(selected, key=lambda row: (_diarium_export_sort_key(row["path"]), row["mtime"]))
    reason = f"fallback best-confidence recent export ({len(selected)} file{'s' if len(selected) != 1 else ''})"
    return [row["path"] for row in selected], reason

def main():
    # Read diarium_export_dir from daemon config if available (NUC Windows uses C:\SyncData\Diarium-Export)
    _daemon_export_dir = None
    _daemon_config_paths = [
        # Service-local config (always accessible regardless of user profile context)
        Path("C:/SyncData/claude-daemon/config.json"),
        # User-profile config paths (work when Path.home() resolves correctly)
        Path.home() / ".claude" / "daemon" / "config.json",
        Path("C:/Users/James Cherry/.claude/daemon/config.json"),
    ]
    for _cfg_path in _daemon_config_paths:
        try:
            _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
            if _cfg.get("diarium_export_dir"):
                _daemon_export_dir = Path(_cfg["diarium_export_dir"])
                break
        except Exception:
            pass

    _candidate_dirs = [
        # Daemon config override (NUC Windows: C:\SyncData\Diarium-Export)
        *([_daemon_export_dir] if _daemon_export_dir else []),
        # NUC Windows hardcoded fallback (Syncthing-synced export dir)
        Path("C:/SyncData/Diarium-Export"),
        # macOS: Google Drive for Desktop (stream mode)
        Path.home() / "My Drive (james.cherry01@gmail.com)" / "Diarium" / "Export",
        # macOS: Google Drive for Desktop (mirror mode / CloudStorage)
        Path.home() / "Library" / "CloudStorage" / "GoogleDrive-james.cherry01@gmail.com" / "My Drive" / "Diarium" / "Export",
        # Windows native: Google Drive for Desktop mounts as a drive letter (e.g. G:\My Drive\Diarium\Export)
        *(Path(f"{d}:/My Drive/Diarium/Export") for d in "GHIJKLMNOPQRSTUVWXYZ"),
        # Windows/WSL: Google Drive for Desktop mounts as a drive letter
        *(Path(f"/mnt/{d.lower()}") / "My Drive" / "Diarium" / "Export" for d in "GHIJKLMNOPQRSTUVWXYZ"),
    ]
    export_folder = next((p for p in _candidate_dirs if p.exists()), None)

    # Check for --json flag
    json_output = '--json' in sys.argv
    if json_output:
        sys.argv.remove('--json')

    # Check for --ai flag (enables AI-first analysis for emotional tone + todos)
    use_ai = '--ai' in sys.argv
    if use_ai:
        sys.argv.remove('--ai')

    # Check for --no-images flag (fast path — skips image extraction for speed)
    skip_images = '--no-images' in sys.argv
    if skip_images:
        sys.argv.remove('--no-images')

    if len(sys.argv) > 1:
        # Parse specific file
        file_path = sys.argv[1]
        text = extract_text_from_file(file_path)
        entry = parse_diarium_entry(text)
        insights = find_mental_health_keywords(text, use_ai=use_ai)

        # Extract images from supported export bundles (skipped in fast-path mode)
        images = [] if skip_images else extract_images_from_file(file_path)

        morning_pages_structured = extract_structured_morning_pages(text)
        if morning_pages_structured:
            hydrate_entry_from_structured_morning(entry, morning_pages_structured)
            entry['morning_pages_structured'] = morning_pages_structured
        if morning_pages_structured and not entry.get('morning_pages'):
            parts = [v for v in morning_pages_structured.values() if v]
            entry['morning_pages'] = '\n\n'.join(parts)

        evening_pages_structured = extract_structured_evening_pages(text)
        if evening_pages_structured:
            entry['evening_pages_structured'] = evening_pages_structured

        # Extract todos from morning pages
        todos = []
        todo_source_text = build_todo_source_text(entry)
        if todo_source_text:
            todos = extract_todos_from_morning_pages(todo_source_text)

        # Get analysis context for Claude's intelligent parsing
        analysis_context = get_analysis_context(entry, use_ai=use_ai)

        # Extract + normalise location from structured sections and free text
        known_locations = load_known_locations()
        location_data = extract_location_from_diarium(entry, text, known_locations)
        if location_data.get('location'):
            entry['location'] = location_data['location']
        if location_data.get('location_raw'):
            entry['location_raw'] = location_data['location_raw']
        if location_data.get('locations_detected'):
            entry['locations_detected'] = location_data['locations_detected']

        if json_output:
            # Output as JSON
            output = {
                'source_file': file_path,
                'parsed_at': datetime.now().isoformat(),
                'date': entry.get('date', datetime.now().strftime('%Y-%m-%d')),
                'sections': entry,
                'mental_health_keywords': insights[:10],
                'todos_extracted': todos,
                'images': images,
                'analysis_context': analysis_context,
                'morning_pages_structured': morning_pages_structured,
                'evening_pages_structured': evening_pages_structured,
            }
            print(json.dumps(output, indent=2))
        else:
            # Original text output
            print("=== DIARIUM ENTRY ===")
            if 'date' in entry:
                print(f"Date: {entry['date']}")
            print()

            for key, value in entry.items():
                if key != 'date':
                    print(f"## {key.replace('_', ' ').title()}")
                    print(value)
                    print()

            if insights:
                print("## Mental Health Insights")
                for insight in insights[:10]:  # Limit to 10
                    print(f"- {insight}")

            if todos:
                print("\n## Extracted Todos")
                for todo in todos:
                    print(f"- [{todo['priority']}] {todo['task']} ({todo['time']})")

            if images:
                print("\n## Images")
                for img in images:
                    if 'error' in img:
                        print(f"  Error: {img['error']}")
                    else:
                        size_kb = img['size'] / 1024
                        print(f"  {img['filename']} ({size_kb:.1f} KB)")
                        print(f"  URL: {img['url']}")
                        print()

    else:
        # Find today's entry - check both .docx and .txt
        # Prefer .docx for images (DOCX files are now exported directly)
        # Use 3am rollover: before 3am, treat as previous day
        now = datetime.now()
        if now.hour < 3:
            from datetime import timedelta as _td
            today = (now - _td(days=1)).strftime("%Y-%m-%d")
        else:
            today = now.strftime("%Y-%m-%d")

        fallback_used = False
        fallback_reason = ""

        if export_folder is None:
            matching_files = []
            fallback_used = False
            fallback_reason = ""
        else:
            matching_files, fallback_used, fallback_reason = find_diarium_files_for_date(
                export_folder,
                today,
                now=now,
            )

        # Markdown fallback: Syncthing-synced Diarium export
        _md_fallback_used = False
        if not matching_files:
            md_fallback = Path.home() / ".claude" / "cache" / "diarium-md" / f"{today}.md"
            if md_fallback.exists():
                _md_fallback_used = True
                text = md_fallback.read_text(encoding="utf-8")
                entry = parse_diarium_entry(text)
                insights = find_mental_health_keywords(text, use_ai=use_ai)
                images = []
                todos = []
                mp_structured = extract_structured_morning_pages(text)
                if not mp_structured and entry.get('morning_pages'):
                    mp_structured = extract_structured_morning_pages(entry['morning_pages'])
                if mp_structured:
                    hydrate_entry_from_structured_morning(entry, mp_structured)
                    entry['morning_pages_structured'] = mp_structured
                todo_source_text = build_todo_source_text(entry)
                if todo_source_text:
                    todos = extract_todos_from_morning_pages(todo_source_text)
                analysis_context = get_analysis_context(entry, use_ai=use_ai)
                known_locations = load_known_locations()
                location_data = extract_location_from_diarium(entry, text, known_locations)
                if location_data.get('location'):
                    entry['location'] = location_data['location']
                if location_data.get('location_raw'):
                    entry['location_raw'] = location_data['location_raw']
                if location_data.get('locations_detected'):
                    entry['locations_detected'] = location_data['locations_detected']
                ep_structured = extract_structured_evening_pages(text)
                if ep_structured:
                    entry['evening_pages_structured'] = ep_structured
                if json_output:
                    output = {
                        'status': 'success',
                        'source_file': str(md_fallback),
                        'source_files': [str(md_fallback)],
                        'merged_count': 1,
                        'fallback_used': True,
                        'fallback_reason': 'md_fallback',
                        'parsed_at': datetime.now().isoformat(),
                        'date': entry.get('date', today),
                        'sections': entry,
                        'mental_health_keywords': insights[:10],
                        'todos_extracted': todos,
                        'images': images,
                        'analysis_context': analysis_context,
                        'morning_pages_structured': mp_structured,
                        'evening_pages_structured': ep_structured,
                    }
                    print(json.dumps(output, indent=2))
                else:
                    print(f"Found today's entry (md fallback): {md_fallback.name}")
                    print("\n=== TODAY'S DIARIUM ENTRY ===")
                    for key, value in entry.items():
                        if key != 'date':
                            print(f"## {key.replace('_', ' ').title()}")
                            print(str(value)[:200] if not isinstance(value, dict) else json.dumps(value, separators=(',', ':'))[:200])
                            print()
                    if insights:
                        print("## Mental Health Insights")
                        for insight in insights[:5]:
                            print(f"- {insight}")
                    if todos:
                        print("\n## Extracted Todos")
                        for todo in todos[:5]:
                            print(f"- [{todo['priority']}] {todo['task']} ({todo['time']})")

        if _md_fallback_used:
            pass  # Already printed JSON above; skip DOCX and no_file paths
        elif matching_files:
            # MULTI-EXPORT MERGE: Parse ALL matching files and merge fields.
            # Morning export has: grateful, letting_go, what_would_make_today_great,
            #   daily_affirmation, body_check, morning_pages
            # Evening export adds: three_things, ta_dah, brave, whats_tomorrow
            # Non-empty values from later exports win (preserves morning + adds evening).
            merged_entry = {}
            all_texts = []
            all_images = []
            ordered_files = sorted(matching_files, key=_diarium_export_sort_key)
            merged_tomorrow_status = SECTION_STATUS_ABSENT
            merged_remember_status = SECTION_STATUS_ABSENT

            # Clean up any stale ghost images for today (e.g. created from yesterday's fallback
            # before today's real export arrived). Safe to delete before extraction loop.
            if not fallback_used:
                for stale in IMAGE_CACHE_DIR.glob(f"{today}_image*"):
                    stale.unlink(missing_ok=True)

            for file in ordered_files:
                text = extract_text_from_file(file, target_date=today)
                all_texts.append(text)
                file_entry = parse_diarium_entry(text)
                # Merge: non-empty values from later files override earlier ones.
                # Tomorrow/remember-tomorrow are handled explicitly with section status
                # so explicit blanks can clear and absences can preserve.
                merged_entry.update({
                    k: v for k, v in file_entry.items()
                    if v and k not in {
                        'whats_tomorrow',
                        'remember_tomorrow',
                        'whats_tomorrow_status',
                        'remember_tomorrow_status',
                    }
                })
                wt_status = str(file_entry.get('whats_tomorrow_status', SECTION_STATUS_ABSENT) or SECTION_STATUS_ABSENT).strip().upper()
                rt_status = str(file_entry.get('remember_tomorrow_status', SECTION_STATUS_ABSENT) or SECTION_STATUS_ABSENT).strip().upper()

                if wt_status == SECTION_STATUS_PRESENT_VALUE:
                    merged_entry['whats_tomorrow'] = file_entry.get('whats_tomorrow', '')
                    if 'whats_tomorrow_raw' in file_entry:
                        merged_entry['whats_tomorrow_raw'] = file_entry.get('whats_tomorrow_raw', '')
                    merged_tomorrow_status = SECTION_STATUS_PRESENT_VALUE
                elif wt_status == SECTION_STATUS_PRESENT_EMPTY:
                    merged_entry['whats_tomorrow'] = ''
                    merged_entry.pop('whats_tomorrow_raw', None)
                    merged_tomorrow_status = SECTION_STATUS_PRESENT_EMPTY

                if rt_status == SECTION_STATUS_PRESENT_VALUE:
                    merged_entry['remember_tomorrow'] = file_entry.get('remember_tomorrow', '')
                    if 'remember_tomorrow_raw' in file_entry:
                        merged_entry['remember_tomorrow_raw'] = file_entry.get('remember_tomorrow_raw', '')
                    merged_remember_status = SECTION_STATUS_PRESENT_VALUE
                elif rt_status == SECTION_STATUS_PRESENT_EMPTY:
                    merged_entry['remember_tomorrow'] = ''
                    merged_entry.pop('remember_tomorrow_raw', None)
                    merged_remember_status = SECTION_STATUS_PRESENT_EMPTY
                # Collect images from all exports — skip if using fallback (yesterday's file)
                # to prevent yesterday's photo being labelled as today's.
                # Also skip in fast-path mode (--no-images) for speed; nightly full refresh repopulates.
                if not fallback_used and not skip_images:
                    all_images.extend(extract_images_from_file(file, today))

            merged_entry['whats_tomorrow_status'] = merged_tomorrow_status
            merged_entry['remember_tomorrow_status'] = merged_remember_status

            entry = merged_entry
            # Combine all text for keyword analysis
            combined_text = '\n\n'.join(all_texts)
            insights = find_mental_health_keywords(combined_text, use_ai=use_ai)
            images = all_images

            # Extract todos from morning pages
            todos = []
            mp_structured = {}

            # Try structured parsing (new ## header template) on combined_text first,
            # fall back to entry['morning_pages'] for old template
            mp_structured = extract_structured_morning_pages(combined_text)
            if not mp_structured and entry.get('morning_pages'):
                mp_structured = extract_structured_morning_pages(entry['morning_pages'])

            # Reconstruct morning_pages from structured sections if empty (new template)
            if mp_structured and not entry.get('morning_pages'):
                parts = [v for v in mp_structured.values() if v]
                entry['morning_pages'] = '\n\n'.join(parts)
                entry['morning_pages_structured'] = mp_structured
            elif mp_structured:
                hydrate_entry_from_structured_morning(entry, mp_structured)
                entry['morning_pages_structured'] = mp_structured

            # Fallback: plain-text morning header (no ## prefix)
            if not str((mp_structured or {}).get('one_important_thing', '')).strip():
                important_fallback = str(entry.get('what_would_make_today_great', '')).strip()
                if not important_fallback:
                    important_match = re.search(
                        r"(?:^|\n)\s*My one important thing today:?\s*\n(.*?)(?=\n(?:Letting go|Updates|What do I need to remember|Evening Reflections|What(?:'|’)s tomorrow)\b|\n##|$)",
                        combined_text,
                        re.DOTALL | re.IGNORECASE,
                    )
                    if important_match:
                        important_fallback = cleanup_transcription(
                            strip_section_markers(important_match.group(1).strip())
                        )
                if important_fallback:
                    mp_structured = dict(mp_structured or {})
                    mp_structured['one_important_thing'] = important_fallback
                    entry['morning_pages_structured'] = mp_structured

            # Extract structured evening pages (## header template)
            ep_structured = extract_structured_evening_pages(combined_text)
            # Suppress evening sections from a single morning-only export (before 14:00).
            # Multi-export merges (morning + evening file) are preserved.
            _export_hour = None
            if ordered_files:
                try:
                    _export_hour = datetime.fromtimestamp(ordered_files[-1].stat().st_mtime).hour
                    if ep_structured and _export_hour < 14 and len(ordered_files) <= 1:
                        ep_structured = {}
                except Exception:
                    pass
            if ep_structured:
                # Sanitize tracker/rating leakage in structured sections
                for key in (
                    'evening_reflections',
                    'letting_go_tonight',
                    'remember_tomorrow',
                    'whats_tomorrow',
                    'where_was_i_brave',
                    'three_things_happened',
                    'ta_dah_list',
                ):
                    if ep_structured.get(key):
                        ep_structured[key] = strip_tracker_metadata(ep_structured[key])

                entry['evening_pages_structured'] = ep_structured
                if ep_structured.get('three_things_happened') and not entry.get('three_things'):
                    entry['three_things'] = ep_structured['three_things_happened']
                if ep_structured.get('ta_dah_list') and not entry.get('ta_dah'):
                    entry['ta_dah'] = ep_structured['ta_dah_list']
                if ep_structured.get('where_was_i_brave') and not entry.get('brave'):
                    entry['brave'] = ep_structured['where_was_i_brave']
                if ep_structured.get('whats_tomorrow') and (not entry.get('whats_tomorrow') or len(str(entry.get('whats_tomorrow', ''))) > len(str(ep_structured.get('whats_tomorrow', ''))) * 3):
                    entry['whats_tomorrow'] = ep_structured['whats_tomorrow']
                if ep_structured.get('remember_tomorrow') and (not entry.get('remember_tomorrow') or len(str(entry.get('remember_tomorrow', ''))) > len(str(ep_structured.get('remember_tomorrow', ''))) * 3):
                    entry['remember_tomorrow'] = ep_structured['remember_tomorrow']
                if ep_structured.get('evening_reflections'):
                    current_evening = str(entry.get('evening_reflections', '') or '').strip()
                    nested_headers = bool(re.search(
                        r'##\s*(Three things that happened today|Ta-?Dah list|Where was I brave\??|What[\'’]?s tomorrow\??|What feels important for tomorrow\??|What do I need to remember for tomorrow\??|Anything worth remembering for tomorrow\??)',
                        current_evening,
                        re.IGNORECASE,
                    ))
                    if (not current_evening) or nested_headers:
                        entry['evening_reflections'] = ep_structured['evening_reflections']
                if ep_structured.get('letting_go_tonight') and not entry.get('letting_go_tonight'):
                    entry['letting_go_tonight'] = ep_structured['letting_go_tonight']

            todo_source_text = build_todo_source_text(entry)
            if todo_source_text:
                todos = extract_todos_from_morning_pages(todo_source_text)

            # Get analysis context for Claude's intelligent parsing
            analysis_context = get_analysis_context(entry)

            # Extract + normalise location from structured sections and free text
            known_locations = load_known_locations()
            location_data = extract_location_from_diarium(entry, combined_text, known_locations)
            if location_data.get('location'):
                entry['location'] = location_data['location']
            if location_data.get('location_raw'):
                entry['location_raw'] = location_data['location_raw']
            if location_data.get('locations_detected'):
                entry['locations_detected'] = location_data['locations_detected']

            if json_output:
                # Output as JSON
                source_files = [str(f) for f in ordered_files]
                output = {
                    'status': 'success',
                    'source_file': source_files[-1],  # Latest for backwards compat
                    'source_files': source_files,
                    'merged_count': len(matching_files),
                    'fallback_used': fallback_used,
                    'fallback_reason': fallback_reason,
                    'parsed_at': datetime.now().isoformat(),
                    'date': entry.get('date', today),
                    'sections': entry,
                    'mental_health_keywords': insights[:10],
                    'todos_extracted': todos,
                    'images': images,
                    'analysis_context': analysis_context,
                    'morning_pages_structured': mp_structured,
                    'evening_pages_structured': ep_structured,
                    'export_hour': _export_hour,
                    'export_count': len(ordered_files),
                }
                print(json.dumps(output, indent=2))
            else:
                # Original text output
                file_names = [f.name for f in ordered_files]
                if fallback_used and fallback_reason:
                    print(f"Fallback file discovery used ({fallback_reason})")
                if len(file_names) > 1:
                    print(f"Found {len(file_names)} exports for today (merged): {', '.join(file_names)}")
                else:
                    print(f"Found today's entry: {file_names[0]}")
                print("\n=== TODAY'S DIARIUM ENTRY ===")
                for key, value in entry.items():
                    if key != 'date':
                        print(f"## {key.replace('_', ' ').title()}")
                        print(str(value)[:200] if not isinstance(value, dict) else json.dumps(value, separators=(',', ':'))[:200])  # Preview
                        print()

                if insights:
                    print("## Mental Health Insights")
                    for insight in insights[:5]:
                        print(f"- {insight}")

                if todos:
                    print("\n## Extracted Todos")
                    for todo in todos[:5]:
                        print(f"- [{todo['priority']}] {todo['task']} ({todo['time']})")

                if images:
                    print("\n## Images")
                    for img in images:
                        if 'error' in img:
                            print(f"  Error: {img['error']}")
                        else:
                            size_kb = img['size'] / 1024
                            print(f"  {img['filename']} ({size_kb:.1f} KB)")
                            print(f"  URL: {img['url']}")
                            print()
        else:
            if json_output:
                print(json.dumps({'status': 'no_file', 'error': f'No Diarium entry found for {today}'}))
            else:
                print(f"No Diarium entry found for {today}")

if __name__ == "__main__":
    main()
