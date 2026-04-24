"""Tests for claude_core.diarium.location — location normalisation and extraction."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from claude_core.diarium.location import (
    _normalise_location_key,
    extract_location_from_diarium,
    load_known_locations,
    normalise_known_location,
)


# --- _normalise_location_key ---

def test_normalise_key_strips_non_alnum():
    assert _normalise_location_key("Home - Living Room!") == "homelivingroom"


def test_normalise_key_lowercases():
    assert _normalise_location_key("UPPER") == "upper"


def test_normalise_key_empty_and_none():
    assert _normalise_location_key("") == ""
    assert _normalise_location_key(None) == ""


# --- load_known_locations ---

def test_load_known_locations_from_file(tmp_path):
    locations_file = tmp_path / "known-locations.json"
    locations_file.write_text(json.dumps({
        "locations": [
            {"canonical": "Home", "aliases": ["home", "my house", "the house"]},
            {"canonical": "Gym", "aliases": ["gym", "the gym", "PureGym"]},
        ]
    }))

    import claude_core.diarium.location as loc_mod
    original = loc_mod.KNOWN_LOCATIONS_FILE
    loc_mod.KNOWN_LOCATIONS_FILE = locations_file
    try:
        result = load_known_locations()
        assert len(result) == 2
        assert result[0]["canonical"] == "Home"
        assert "home" in result[0]["alias_keys"]
        assert result[1]["canonical"] == "Gym"
    finally:
        loc_mod.KNOWN_LOCATIONS_FILE = original


def test_load_known_locations_missing_file(tmp_path):
    import claude_core.diarium.location as loc_mod
    original = loc_mod.KNOWN_LOCATIONS_FILE
    loc_mod.KNOWN_LOCATIONS_FILE = tmp_path / "nonexistent.json"
    try:
        result = load_known_locations()
        assert result == []
    finally:
        loc_mod.KNOWN_LOCATIONS_FILE = original


def test_load_known_locations_skips_empty_canonical():
    """Entries with no canonical name should be skipped."""
    import claude_core.diarium.location as loc_mod
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"locations": [{"canonical": "", "aliases": ["foo"]}]}, f)
        f.flush()
        original = loc_mod.KNOWN_LOCATIONS_FILE
        loc_mod.KNOWN_LOCATIONS_FILE = Path(f.name)
        try:
            result = load_known_locations()
            assert result == []
        finally:
            loc_mod.KNOWN_LOCATIONS_FILE = original
            Path(f.name).unlink(missing_ok=True)


# --- normalise_known_location ---

SAMPLE_KNOWN = [
    {"canonical": "Home", "alias_keys": ["home", "myhouse", "thehouse"]},
    {"canonical": "Gym", "alias_keys": ["gym", "thegym", "puregym"]},
]


def test_normalise_exact_match():
    assert normalise_known_location("home", SAMPLE_KNOWN) == "Home"


def test_normalise_substring_match():
    assert normalise_known_location("at the gym today", SAMPLE_KNOWN) == "Gym"


def test_normalise_no_match():
    result = normalise_known_location("office downtown", SAMPLE_KNOWN)
    assert result == "office downtown"


def test_normalise_empty_input():
    assert normalise_known_location("", SAMPLE_KNOWN) == ""
    assert normalise_known_location(None, SAMPLE_KNOWN) == ""


# --- extract_location_from_diarium ---

def test_extract_explicit_location():
    entry = {"location_raw": "Home"}
    result = extract_location_from_diarium(entry, "", known_locations=SAMPLE_KNOWN)
    assert result["location"] == "Home"
    assert result["location_raw"] == "Home"


def test_extract_detected_from_text():
    entry = {"location_raw": ""}
    result = extract_location_from_diarium(
        entry, "I went to the gym this morning", known_locations=SAMPLE_KNOWN
    )
    assert result["location"] == "Gym"
    assert "Gym" in result["locations_detected"]


def test_extract_multiple_detected():
    entry = {"location_raw": ""}
    result = extract_location_from_diarium(
        entry, "Left home then went to the gym", known_locations=SAMPLE_KNOWN
    )
    assert len(result["locations_detected"]) == 2
    assert "Home" in result["locations_detected"]
    assert "Gym" in result["locations_detected"]


def test_extract_no_location():
    entry = {"location_raw": ""}
    result = extract_location_from_diarium(
        entry, "Nothing about places", known_locations=SAMPLE_KNOWN
    )
    assert result["location"] == ""
    assert result["locations_detected"] == []
