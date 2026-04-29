"""Tests for claude_core.health.discovery — CSV discovery and parsing primitives."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from claude_core.health.discovery import (
    _normalise_search_roots,
    find_autosleep_csvs,
    find_health_csvs,
    find_latest_autosleep_csv,
    find_latest_csv,
    find_latest_health_csv,
    parse_duration,
    parse_float,
    _parse_timestamp,
    _calculate_data_age_days,
)


# --- parse_duration ---

def test_parse_duration_normal():
    assert parse_duration("07:30:00") == 7.5


def test_parse_duration_no_seconds():
    assert parse_duration("08:15") == 8.25


def test_parse_duration_empty():
    assert parse_duration("") == 0.0
    assert parse_duration(None) == 0.0
    assert parse_duration("   ") == 0.0


def test_parse_duration_invalid():
    assert parse_duration("not-a-time") == 0.0


# --- parse_float ---

def test_parse_float_normal():
    assert parse_float("3.14") == 3.14


def test_parse_float_integer():
    assert parse_float("42") == 42.0


def test_parse_float_empty():
    assert parse_float("") is None
    assert parse_float(None) is None
    assert parse_float("   ") is None


def test_parse_float_invalid():
    assert parse_float("abc") is None


# --- _parse_timestamp ---

def test_parse_timestamp_valid():
    result = _parse_timestamp("2026-04-24 08:30:00")
    assert result is not None
    assert result.hour == 8
    assert result.minute == 30


def test_parse_timestamp_invalid():
    assert _parse_timestamp("not-a-date") is None
    assert _parse_timestamp("") is None
    assert _parse_timestamp(None) is None


# --- _normalise_search_roots ---

def test_normalise_deduplicates(tmp_path):
    roots = _normalise_search_roots([tmp_path, tmp_path, tmp_path])
    assert len(roots) == 1
    assert roots[0] == tmp_path


def test_normalise_expands_user():
    roots = _normalise_search_roots(["~/some-path"])
    assert "~" not in str(roots[0])


# --- find CSV functions with tmp dirs ---

def test_find_health_csvs_finds_exports(tmp_path):
    (tmp_path / "Export_2026-04-24.csv").write_text("header\n")
    (tmp_path / "Export_2026-04-23.csv").write_text("header\n")
    (tmp_path / "random.csv").write_text("header\n")

    results = find_health_csvs(search_roots=[tmp_path])
    assert len(results) == 2
    assert all("Export_" in r for r in results)


def test_find_health_csvs_empty_dir(tmp_path):
    results = find_health_csvs(search_roots=[tmp_path])
    assert results == []


def test_find_health_csvs_nonexistent_root():
    results = find_health_csvs(search_roots=[Path("/nonexistent/path")])
    assert results == []


def test_find_latest_health_csv(tmp_path):
    (tmp_path / "Export_old.csv").write_text("old\n")
    import time; time.sleep(0.05)
    (tmp_path / "Export_new.csv").write_text("new\n")

    result = find_latest_health_csv(search_roots=[tmp_path])
    assert result is not None
    assert "Export_new.csv" in result


def test_find_latest_health_csv_none(tmp_path):
    assert find_latest_health_csv(search_roots=[tmp_path]) is None


def test_find_autosleep_csvs(tmp_path):
    (tmp_path / "AutoSleep-2026-04-24.csv").write_text("header\n")
    results = find_autosleep_csvs(search_roots=[tmp_path])
    assert len(results) == 1


def test_find_latest_autosleep_csv(tmp_path):
    (tmp_path / "AutoSleep-2026-04-24.csv").write_text("header\n")
    result = find_latest_autosleep_csv(search_roots=[tmp_path])
    assert result is not None
    assert "AutoSleep-" in result


def test_find_latest_csv_is_alias(tmp_path):
    """find_latest_csv is a compatibility alias for find_latest_autosleep_csv."""
    (tmp_path / "AutoSleep-2026-04-24.csv").write_text("header\n")
    assert find_latest_csv(search_roots=[tmp_path]) == find_latest_autosleep_csv(search_roots=[tmp_path])


# --- _calculate_data_age_days ---

def test_data_age_today():
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    assert _calculate_data_age_days(today) == 0


def test_data_age_none():
    assert _calculate_data_age_days(None) is None
