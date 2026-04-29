from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from claude_core.health_metrics import (
    find_health_csvs,
    find_latest_autosleep_csv,
    get_sleep_data,
    parse_apple_health,
    parse_autosleep,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_find_latest_autosleep_csv_prefers_newest_match_in_supplied_roots(tmp_path: Path) -> None:
    export_dir = tmp_path / "Apple Health"
    export_dir.mkdir()
    older = export_dir / "AutoSleep-older.csv"
    newer = export_dir / "AutoSleep-newer.csv"
    rows = [{"bedtime": "2026-04-22 23:00:00", "waketime": "2026-04-23 07:00:00"}]
    _write_csv(older, rows)
    _write_csv(newer, rows)
    os.utime(older, (10, 10))
    os.utime(newer, (20, 20))

    assert find_latest_autosleep_csv([export_dir]) == str(newer)


def test_find_health_csvs_sorts_newest_first_in_supplied_roots(tmp_path: Path) -> None:
    export_dir = tmp_path / "Apple Health"
    export_dir.mkdir()
    older = export_dir / "Export_old.csv"
    newer = export_dir / "Export_new.csv"
    rows = [{"Date": "2026-04-22 08:00:00", "Time asleep(hr)": "7"}]
    _write_csv(older, rows)
    _write_csv(newer, rows)
    os.utime(older, (10, 10))
    os.utime(newer, (20, 20))

    assert find_health_csvs([export_dir]) == [str(newer), str(older)]


def test_parse_autosleep_builds_last_night_summary_and_freshness(tmp_path: Path) -> None:
    export_dir = tmp_path / "Apple Health"
    export_dir.mkdir()
    csv_file = export_dir / "AutoSleep-sample.csv"
    recent_wake = datetime.now().replace(hour=7, minute=15, second=0, microsecond=0) - timedelta(days=1)
    recent_bed = recent_wake - timedelta(hours=7, minutes=0)
    older_wake = recent_wake - timedelta(days=1)
    older_bed = older_wake - timedelta(hours=6, minutes=30)
    _write_csv(
        csv_file,
        [
            {
                "bedtime": recent_bed.strftime("%Y-%m-%d %H:%M:%S"),
                "waketime": recent_wake.strftime("%Y-%m-%d %H:%M:%S"),
                "inBed": "07:30:00",
                "asleep": "07:00:00",
                "deep": "01:20:00",
                "efficiency": "93",
                "sleepBPM": "58",
                "sleepHRV": "42",
                "SpO2Avg": "97",
                "apnea": "0.8",
            },
            {
                "bedtime": older_bed.strftime("%Y-%m-%d %H:%M:%S"),
                "waketime": older_wake.strftime("%Y-%m-%d %H:%M:%S"),
                "inBed": "07:00:00",
                "asleep": "06:30:00",
                "deep": "01:00:00",
                "efficiency": "88",
                "sleepBPM": "60",
                "sleepHRV": "40",
                "SpO2Avg": "96",
                "apnea": "1.1",
            },
        ],
    )

    result = parse_autosleep(csv_file=csv_file, days=14)

    assert result["status"] == "success"
    assert result["fresh"] is True
    assert result["most_recent_date"] == recent_wake.strftime("%Y-%m-%d")
    assert result["last_night"] == {
        "date": recent_wake.strftime("%Y-%m-%d"),
        "asleep": "7.0h",
        "efficiency": "93.0%",
        "deep": "1.33h",
        "sleep_hr": "58.0 bpm",
    }
    assert result["daily_metrics"][0]["sleep_hrv"] == 42.0


def test_parse_apple_health_merges_multiple_exports_and_tracks_sleep_freshness(
    tmp_path: Path,
    capsys,
) -> None:
    export_dir = tmp_path / "Apple Health"
    export_dir.mkdir()
    sleep_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    sleep_export = export_dir / "Export_sleep.csv"
    activity_export = export_dir / "Export_activity.csv"
    _write_csv(
        sleep_export,
        [
            {
                "Date": f"{sleep_date} 07:30:00",
                "Time asleep(hr)": "7.5",
                "Heart rate variability (SDNN)(ms)": "45",
                "Resting heart rate(count/min)": "58",
                "Mindfulness(min)": "10",
            }
        ],
    )
    _write_csv(
        activity_export,
        [
            {
                "Date": f"{sleep_date} 18:00:00",
                "Steps (count)": "5000",
                "Exercise Time (min)": "30",
                "Active Energy (kcal)": "450",
            }
        ],
    )

    result = parse_apple_health([sleep_export, activity_export], output_json=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["sleep_fresh"] is True
    assert payload["most_recent_date"] == sleep_date
    assert result == payload
    assert result["daily_metrics"] == [
        {
            "date": sleep_date,
            "sleep_hours": 7.5,
            "steps": 5000,
            "exercise_minutes": 30.0,
            "hrv": 45.0,
            "resting_hr": 58.0,
            "mindful_minutes": 10.0,
            "active_energy": 450.0,
        }
    ]


def test_get_sleep_data_prefers_fresh_autosleep() -> None:
    result = get_sleep_data(
        autosleep_parser=lambda: {
            "status": "success",
            "fresh": True,
            "data_age_days": 0,
            "daily_metrics": [
                {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "asleep_hours": 7.25,
                    "sleep_hrv": 42.0,
                    "deep_hours": 1.5,
                    "efficiency": 92.0,
                    "sleep_hr": 58.0,
                }
            ],
        },
        health_csv_finder=lambda: [],
        apple_health_parser=lambda *_args, **_kwargs: {"status": "error"},
    )

    assert result["source"] == "autosleep"
    assert result["sleep_hours"] == 7.25
    assert result["fallback_chain"] == [{"source": "autosleep", "status": "used", "date": datetime.now().strftime("%Y-%m-%d")}]


def test_get_sleep_data_falls_back_to_apple_health_when_autosleep_is_stale() -> None:
    sleep_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    result = get_sleep_data(
        max_stale_days=1,
        autosleep_parser=lambda: {
            "status": "success",
            "fresh": False,
            "data_age_days": 3,
            "most_recent_date": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
            "stale_reason": "Most recent sleep entry is 3 days old",
            "daily_metrics": [{"date": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"), "asleep_hours": 5.0}],
        },
        health_csv_finder=lambda: ["Export_recent.csv"],
        apple_health_parser=lambda *_args, **_kwargs: {
            "status": "success",
            "sleep_fresh": True,
            "sleep_age_days": 1,
            "sleep_most_recent": sleep_date,
            "daily_metrics": [
                {
                    "date": sleep_date,
                    "sleep_hours": 6.5,
                    "hrv": 38.0,
                }
            ],
        },
    )

    assert result["source"] == "apple_health"
    assert result["sleep_hours"] == 6.5
    assert result["hrv"] == 38.0
    assert result["fallback_chain"][0]["status"] == "stale"
    assert result["fallback_chain"][1] == {"source": "apple_health", "status": "used", "date": sleep_date}


def test_get_sleep_data_reports_all_sources_exhausted() -> None:
    result = get_sleep_data(
        autosleep_parser=lambda: {"status": "error", "message": "No AutoSleep CSV found"},
        health_csv_finder=lambda: [],
        apple_health_parser=lambda *_args, **_kwargs: {"status": "error"},
        healthfit_parser=None,
    )

    assert result["source"] is None
    assert result["fresh"] is False
    assert result["stale_reason"] == "All sleep sources stale or unavailable"
    assert [entry["source"] for entry in result["fallback_chain"]] == ["autosleep", "apple_health", "healthfit"]
