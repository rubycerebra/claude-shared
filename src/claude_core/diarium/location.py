"""Diarium location normalisation — extracted from claude_core.diarium_ingest."""
from __future__ import annotations

import json
import re
from pathlib import Path

KNOWN_LOCATIONS_FILE = Path(__file__).resolve().parent.parent / "known-locations.json"


def _normalise_location_key(text):
    """Collapse a location string to a simple alphanumeric key for matching."""
    return re.sub(r'[^a-z0-9]+', '', str(text or '').lower())


def load_known_locations():
    """Load known locations + alias keys for robust Diarium location matching."""
    if not KNOWN_LOCATIONS_FILE.exists():
        return []

    try:
        with open(KNOWN_LOCATIONS_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except Exception:
        return []

    raw_locations = payload.get('locations', []) if isinstance(payload, dict) else []
    known_locations = []

    for item in raw_locations:
        canonical = str(item.get('canonical', '')).strip()
        if not canonical:
            continue

        aliases = [canonical] + [str(a).strip() for a in item.get('aliases', []) if str(a).strip()]
        alias_keys = []
        seen = set()

        for alias in aliases:
            alias_key = _normalise_location_key(alias)
            if len(alias_key) < 4 or alias_key in seen:
                continue
            seen.add(alias_key)
            alias_keys.append(alias_key)

        if alias_keys:
            known_locations.append({
                'canonical': canonical,
                'alias_keys': alias_keys,
            })

    return known_locations


def normalise_known_location(raw_text, known_locations):
    """Map raw/transcribed location text to canonical location when possible."""
    if not raw_text:
        return ''

    raw_key = _normalise_location_key(raw_text)
    if not raw_key:
        return ''

    for item in known_locations:
        if any(alias in raw_key or raw_key in alias for alias in item.get('alias_keys', [])):
            return item.get('canonical', '')

    return re.sub(r'\s+', ' ', str(raw_text)).strip(' ,.;')


def extract_location_from_diarium(entry, source_text, known_locations=None):
    """Extract + normalise location from explicit section and full Diarium text."""
    if known_locations is None:
        known_locations = load_known_locations()

    explicit_raw = str(entry.get('location_raw') or entry.get('location') or '').strip()
    location_fields = [
        entry.get('location_raw', ''),
        entry.get('location', ''),
        entry.get('morning_pages_raw', ''),
        entry.get('morning_pages', ''),
        entry.get('updates_raw', ''),
        entry.get('updates', ''),
        entry.get('whats_tomorrow_raw', ''),
        entry.get('whats_tomorrow', ''),
        source_text or '',
    ]
    combined_text = '\n'.join([str(field) for field in location_fields if field]).strip()
    combined_key = _normalise_location_key(combined_text)

    detected = []
    for item in known_locations:
        if any(alias_key and alias_key in combined_key for alias_key in item.get('alias_keys', [])):
            detected.append(item.get('canonical', ''))

    seen = set()
    detected_unique = []
    for canonical in detected:
        if canonical and canonical not in seen:
            seen.add(canonical)
            detected_unique.append(canonical)

    normalised_location = normalise_known_location(explicit_raw, known_locations) if explicit_raw else ''
    if not normalised_location and detected_unique:
        normalised_location = detected_unique[0]

    return {
        'location': normalised_location,
        'location_raw': explicit_raw,
        'locations_detected': detected_unique,
    }
