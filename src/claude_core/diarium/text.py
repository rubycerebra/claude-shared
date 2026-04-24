"""Diarium text cleaning and parsing — extracted from claude_core.diarium_ingest."""
from __future__ import annotations

import json
import re
import zipfile
from html import unescape
from pathlib import Path


def _parse_diarium_json_payload(raw_payload):
    payload = json.loads(raw_payload)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        entries = payload.get('entries')
        if isinstance(entries, list):
            return [item for item in entries if isinstance(item, dict)]
        return [payload]
    raise ValueError("Unsupported Diarium JSON payload")


def _load_diarium_json_entries(file_path):
    file_path = Path(file_path)

    if file_path.suffix.lower() == '.json':
        raw_payload = file_path.read_text(encoding='utf-8-sig')
        return _parse_diarium_json_payload(raw_payload)

    if file_path.suffix.lower() == '.zip':
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            json_members = sorted(
                name for name in zip_ref.namelist()
                if name.lower().endswith('.json') and not name.endswith('/')
            )
            if not json_members:
                raise ValueError(f"No JSON export found in {file_path}")
            raw_payload = zip_ref.read(json_members[0]).decode('utf-8-sig')
        return _parse_diarium_json_payload(raw_payload)

    raise ValueError(f"Unsupported Diarium JSON source: {file_path}")


def _diarium_html_to_text(html):
    raw_html = str(html or "")
    if not raw_html.strip():
        return ""

    text = raw_html
    replacements = [
        (r'(?i)<br\s*/?>', '\n'),
        (r'(?i)</p\s*>', '\n\n'),
        (r'(?i)</div\s*>', '\n\n'),
        (r'(?i)<li\b[^>]*>', '- '),
        (r'(?i)</li\s*>', '\n'),
        (r'(?i)</ul\s*>', '\n'),
        (r'(?i)</ol\s*>', '\n'),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text).replace('\xa0', ' ')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()]
    cleaned = '\n'.join(line for line in lines if line)
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip()


def _entry_text_from_diarium_json_item(item):
    html_text = _diarium_html_to_text(item.get('html', ''))
    heading = str(item.get('heading') or '').strip()
    heading_lower = heading.lower()
    generic_headings = {'morning pages', 'evening reflections'}

    parts = []
    if heading and heading_lower not in generic_headings and heading_lower not in html_text.lower():
        parts.append(heading)
    if html_text:
        parts.append(html_text)

    return '\n'.join(part for part in parts if part).strip()


def _extract_text_from_diarium_json_source(file_path):
    entries = _load_diarium_json_entries(file_path)
    metadata_lines = []
    for item in entries:
        tracker = item.get('tracker') or []
        tracker_values = [str(value).strip() for value in tracker if str(value).strip()]
        if tracker_values:
            metadata_lines.append(f"Tracker: {', '.join(tracker_values)}")
    blocks = [_entry_text_from_diarium_json_item(item) for item in entries]
    parts = []
    if metadata_lines:
        parts.append('\n'.join(metadata_lines))
    if blocks:
        parts.append('\n\n'.join(block for block in blocks if block))
    return '\n\n'.join(part for part in parts if part).strip()


def _extract_text_for_date_from_diarium_json_source(file_path, target_date):
    """Extract text for a specific date from a multi-entry Diarium JSON/ZIP."""
    entries = _load_diarium_json_entries(file_path)
    matching = [
        item for item in entries
        if isinstance(item, dict) and str(item.get('date', ''))[:10] == target_date
    ]
    if not matching:
        matching = entries
    metadata_lines = []
    for item in matching:
        tracker = item.get('tracker') or []
        tracker_values = [str(v).strip() for v in tracker if str(v).strip()]
        if tracker_values:
            metadata_lines.append(f"Tracker: {', '.join(tracker_values)}")
    blocks = [_entry_text_from_diarium_json_item(item) for item in matching]
    parts = []
    if metadata_lines:
        parts.append('\n'.join(metadata_lines))
    if blocks:
        parts.append('\n\n'.join(block for block in blocks if block))
    return '\n\n'.join(part for part in parts if part).strip()


def extract_text_from_file(file_path, target_date=None):
    """Extract text from a .txt, .docx, .json, or Diarium .zip file."""
    file_path = Path(file_path)

    if file_path.suffix in ('.txt', '.md'):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading {file_path}: {e}"

    elif file_path.suffix == '.docx':
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                xml_content = zip_ref.read('word/document.xml').decode('utf-8')
                text = re.sub('<[^>]+>', '\n', xml_content)
                _MOJIBAKE = [
                    ('\u00e2\u20ac\u201d', '\u2014'),
                    ('\u00e2\u20ac\u201c', '\u2013'),
                    ('\u00e2\u20ac\u02dc', '\u2018'),
                    ('\u00e2\u20ac\u2122', '\u2019'),
                    ('\u00e2\u20ac\u0153', '\u201c'),
                    ('\u00e2\u20ac\u00a6', '\u2026'),
                    ('\u00e2\u20ac\u00a2', '\u2022'),
                    ('\u00c3\u00a9', '\u00e9'),
                    ('\u00c3\u00a0', '\u00e0'),
                    ('\u00c3\u00a8', '\u00e8'),
                    ('\u00c3\u00aa', '\u00ea'),
                    ('\u00c3\u00b1', '\u00f1'),
                ]
                for mojibake, correct in _MOJIBAKE:
                    text = text.replace(mojibake, correct)
                return text
        except Exception as e:
            return f"Error reading {file_path}: {e}"

    elif file_path.suffix.lower() in ('.json', '.zip'):
        try:
            if target_date:
                return _extract_text_for_date_from_diarium_json_source(file_path, target_date)
            return _extract_text_from_diarium_json_source(file_path)
        except Exception as e:
            return f"Error reading {file_path}: {e}"

    else:
        return f"Unsupported file type: {file_path.suffix}"


def cleanup_transcription(text):
    """Clean up Apple voice transcription for readability."""
    if not text or len(text) < 20:
        return text

    corrections_file = Path.home() / ".claude" / "config" / "transcription-fixes.json"
    custom_fixes = {}
    if corrections_file.exists():
        try:
            with open(corrections_file) as f:
                custom_fixes = json.load(f)
        except Exception:
            pass

    for wrong, right in custom_fixes.items():
        if ' ' in wrong:
            text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
        else:
            text = re.sub(r'\b' + re.escape(wrong) + r'\b', right, text, flags=re.IGNORECASE)

    fillers = [
        r'\bso yeah\b', r'\byeah yeah\b', r'\bto be honest\b',
        r'\byou know\b', r'\bI guess\b', r'\bI mean\b',
        r'\bkind of\b', r'\bsort of\b', r'\bbasically\b',
        r'(?<=[.!?]\s)\byeah\b[,\s]*',
    ]
    for filler in fillers:
        text = re.sub(filler + r'[,\s]*', ' ', text, flags=re.IGNORECASE)

    text = re.sub(r'\b(\w+)\s+\1\b', r'\1', text, flags=re.IGNORECASE)

    conjunctions = r'(?:so|and then|but then|but|which|because)'
    sentences = re.split(r'(?<=[.!?])\s+', text)

    cleaned_sentences = []
    for sentence in sentences:
        if len(sentence) > 120:
            parts = re.split(r'\s+(' + conjunctions + r')\s+', sentence, flags=re.IGNORECASE)
            current = ""
            for part in parts:
                if re.match(conjunctions, part, re.IGNORECASE) and len(current) > 50:
                    cleaned_sentences.append(current.strip())
                    current = ""
                else:
                    current += part + " "
            if current.strip():
                cleaned_sentences.append(current.strip())
        else:
            cleaned_sentences.append(sentence.strip())

    result = []
    for s in cleaned_sentences:
        if not s:
            continue
        s = s.strip()
        if s and s[-1] not in '.!?':
            s += '.'
        s = s[0].upper() + s[1:] if len(s) > 1 else s.upper()
        result.append(s)

    text = ' '.join(result)

    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\.\s*\.', '.', text)
    text = re.sub(r',\s*\.', '.', text)

    return text.strip()


def strip_section_markers(text):
    """Strip Diarium section separator markers (##, ##.) that leak into field values."""
    if not text:
        return text
    text = re.sub(r'\n+\s*##\.?\s*$', '', text.strip())
    text = re.sub(r'(?:^|\n)\s*##\.?\s*(?=\n|$)', '', text)
    return text.strip()


def trim_combined_evening_spillover(text):
    """Trim evening-entry spillover from combined day exports."""
    if not text:
        return text

    markers = [
        r'(?:^|\n)\s*---+\s*(?:\n|$)',
        r'(?:^|\n)\s*\u2E3B+\s*(?:\n|$)',
        r"(?:^|\n)\s*All sections complete\.\s*Here['\u2019]?s your full evening entry, ready for Diarium:?\s*(?:\n|$)",
        r'(?:^|\n)\s*Three things that happened today\b',
        r'(?:^|\n)\s*Ta[-\s]?[Dd]ah(?:\s+list)?\b',
        r'(?:^|\n)\s*Where was I brave\??',
        r'(?:^|\n)\s*What feels important for tomorrow\??',
        r'(?:^|\n)\s*Anything worth remembering for tomorrow\??',
        r'(?:^|\n)\s*Evening Reflections\b',
        r'(?:^|\n)\s*Letting go tonight\b',
    ]

    earliest_pos = len(text)
    for marker in markers:
        match = re.search(marker, text, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()

    if earliest_pos < len(text):
        clean = text[:earliest_pos].strip()
        return clean if clean else text

    return text


def strip_chatgpt_contamination(text):
    """Strip ChatGPT-generated expansions from morning pages."""
    if not text:
        return text

    contamination_markers = [
        r"Here['\u2019]?s your clean transcription",
        r"Here['\u2019]?s an expanded continuation",
        r"Here['\u2019]?s a clean(?:ed)? version",
        r"Here['\u2019]?s the transcription",
        r"\u2705\s*Word count:\s*\d+\s+words",
    ]

    earliest_pos = len(text)
    for marker in contamination_markers:
        match = re.search(marker, text, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()

    if earliest_pos < len(text):
        clean = text[:earliest_pos].strip()
        return clean if clean else text

    return text


def strip_updates_metadata(text):
    """Remove template metadata accidentally captured in Updates section."""
    if not text:
        return text

    weather_block_pattern = re.compile(
        r'^\s*(?:\W+)?weather\s*:.*(?:sunrise|sunset|location)\b.*$',
        re.IGNORECASE,
    )
    location_coord_pattern = re.compile(
        r'^\s*(?:\W+)?location\s*:\s*[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+\s*\.?\s*$',
        re.IGNORECASE,
    )
    sunrise_sunset_pattern = re.compile(
        r'^\s*(?:\W+)?(?:sunrise|sunset)\s*:\s*\d{1,2}:\d{2}\b.*$',
        re.IGNORECASE,
    )

    kept_lines = []
    for raw_line in re.split(r'\n+', str(text)):
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        is_weather_block = bool(weather_block_pattern.match(line))
        is_location_line = bool(location_coord_pattern.match(line))
        is_sun_line = bool(sunrise_sunset_pattern.match(line))
        looks_metadata_combo = (
            "weather" in lower
            and ("sunrise" in lower or "sunset" in lower or "location" in lower)
            and bool(re.search(r'[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+', line))
        )

        if is_weather_block or is_location_line or is_sun_line or looks_metadata_combo:
            continue

        kept_lines.append(line)

    result = "\n".join(kept_lines).strip()
    result = re.sub(r'^Tracker:.*$', '', result, flags=re.MULTILINE)
    result = re.sub(r'^Rating:.*$', '', result, flags=re.MULTILINE)
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    return result


def strip_tracker_metadata(text):
    """Remove tracker/status lines that can leak into narrative sections."""
    if not text:
        return text
    cleaned = str(text)
    cleaned = re.sub(r'^\s*Tracker\s*:.*$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'^\s*Rating\s*:.*$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'^\s*(Morning|Evening)\s*Mood(?:\s*Tag)?\s*:.*$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'^\s*CONNECTIONS\s*\(Skipped\).*$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'^\s*(?:CONNECTIONS|TAGS|TRACKER)\s*\(.*?\).*$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'^\s*Copied/ready to paste into Diarium.*$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned
