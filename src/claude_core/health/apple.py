"""Apple Health CSV parser — extracted from claude_core.health_metrics."""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .discovery import (
    find_health_csvs,
    _calculate_data_age_days,
)


def _coerce_csv_paths(csv_files: str | Path | Sequence[str | Path] | None) -> list[str]:
    if csv_files is None:
        return []
    if isinstance(csv_files, (str, Path)):
        return [str(Path(csv_files).expanduser())]
    return [str(Path(csv_file).expanduser()) for csv_file in csv_files]


def _iter_numeric_columns(row: dict[str, str], columns: Iterable[str]) -> float | None:
    for column in columns:
        if row.get(column):
            try:
                return float(row[column])
            except (ValueError, TypeError, KeyError):
                continue
    return None


def _parse_single_csv(csv_file: str | Path, daily_metrics: dict[str, Any], days: int = 14) -> None:
    with Path(csv_file).open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date_col = row.get("Date") or row.get("Start") or row.get("date") or ""
            if not date_col:
                continue

            date_str = date_col.split(" ")[0]
            parsed_date: datetime | None = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    break
                except (ValueError, TypeError):
                    continue
            if parsed_date is None or (datetime.now() - parsed_date).days > days:
                continue

            date_key = parsed_date.strftime("%Y-%m-%d")

            sleep_hours = _iter_numeric_columns(row, ["Time asleep(hr)", "Sleep Duration (hr)", "asleep", "Time Asleep (hours)"])
            if sleep_hours is not None:
                daily_metrics[date_key]["sleep_hours"] += sleep_hours

            steps = _iter_numeric_columns(row, ["Steps (count)", "Step Count (count)", "steps", "Step count(count)", "Step count (count)"])
            if steps is not None:
                daily_metrics[date_key]["steps"] += int(steps)

            exercise = _iter_numeric_columns(
                row,
                ["Exercise Time (min)", "Apple Exercise Time (min)", "exercise", "Exercise time(min)", "Exercise time (min)"],
            )
            if exercise is not None:
                daily_metrics[date_key]["exercise_minutes"] += exercise

            hrv = _iter_numeric_columns(row, ["Heart rate variability (SDNN)(ms)", "Heart Rate Variability (ms)", "HRV"])
            if hrv is not None:
                daily_metrics[date_key]["hrv"].append(hrv)

            resting_hr = _iter_numeric_columns(
                row,
                ["Resting heart rate(count/min)", "Resting Heart Rate (count/min)", "resting_hr"],
            )
            if resting_hr is not None:
                daily_metrics[date_key]["resting_hr"].append(resting_hr)

            mindful = _iter_numeric_columns(row, ["Mindfulness(min)", "Mindful Minutes (min)", "mindful"])
            if mindful is not None:
                daily_metrics[date_key]["mindful_minutes"] += mindful

            active_energy = _iter_numeric_columns(
                row,
                ["Active Energy (kcal)", "Active energy burned(kcal)", "active_energy", "Active energy (kcal)"],
            )
            if active_energy is not None:
                daily_metrics[date_key]["active_energy"] += active_energy


def _render_apple_health_result(daily_metrics: dict[str, Any]) -> dict[str, Any]:
    sorted_dates = sorted(daily_metrics.keys())
    metrics_list = []
    for date in sorted_dates:
        metrics = daily_metrics[date]
        hrv_values = metrics["hrv"]
        resting_hr_values = metrics["resting_hr"]
        avg_hrv = sum(hrv_values) / len(hrv_values) if hrv_values else 0
        avg_resting_hr = sum(resting_hr_values) / len(resting_hr_values) if resting_hr_values else 0
        metrics_list.append(
            {
                "date": date,
                "sleep_hours": round(float(metrics["sleep_hours"]), 1),
                "steps": int(metrics["steps"]),
                "exercise_minutes": round(float(metrics["exercise_minutes"]), 0),
                "hrv": round(avg_hrv, 0),
                "resting_hr": round(avg_resting_hr, 0),
                "mindful_minutes": round(float(metrics["mindful_minutes"]), 0),
                "active_energy": round(float(metrics["active_energy"]), 0),
            }
        )

    most_recent_date = sorted_dates[-1] if sorted_dates else None
    data_age_days = _calculate_data_age_days(most_recent_date)
    is_fresh = data_age_days is not None and data_age_days <= 1
    dates_with_sleep = [date for date in sorted_dates if float(daily_metrics[date]["sleep_hours"]) > 0]
    sleep_most_recent = dates_with_sleep[-1] if dates_with_sleep else None
    sleep_age_days = _calculate_data_age_days(sleep_most_recent)
    sleep_fresh = sleep_age_days is not None and sleep_age_days <= 1

    result: dict[str, Any] = {
        "status": "success",
        "fresh": is_fresh,
        "most_recent_date": most_recent_date,
        "data_age_days": data_age_days,
        "sleep_fresh": sleep_fresh,
        "sleep_most_recent": sleep_most_recent,
        "sleep_age_days": sleep_age_days,
        "daily_metrics": metrics_list,
    }
    if not is_fresh:
        if data_age_days is None:
            result["stale_reason"] = "No health entries found in CSV"
        else:
            result["stale_reason"] = f"Most recent entry is {data_age_days} days old ({most_recent_date})"
    return result


def parse_apple_health(
    csv_files: str | Path | Sequence[str | Path] | None,
    output_json: bool = False,
    days: int = 14,
    search_roots: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Parse Apple Health CSV(s) and generate mental health metrics report."""
    csv_paths = _coerce_csv_paths(csv_files)
    if not csv_paths:
        csv_paths = find_health_csvs(search_roots)

    if not csv_paths:
        result = {"status": "error", "message": "No health CSV found in Google Drive"}
        if output_json:
            print(json.dumps(result))
        return result

    daily_metrics: dict[str, Any] = defaultdict(
        lambda: {
            "sleep_hours": 0.0,
            "hrv": [],
            "steps": 0,
            "active_energy": 0.0,
            "mindful_minutes": 0.0,
            "exercise_minutes": 0.0,
            "resting_hr": [],
        }
    )

    for csv_file in csv_paths:
        try:
            _parse_single_csv(csv_file, daily_metrics, days=days)
        except Exception as exc:
            if not output_json:
                print(f"Warning: Error parsing {csv_file}: {exc}")

    result = _render_apple_health_result(daily_metrics)
    result["source_files"] = [str(Path(csv_file).expanduser()) for csv_file in csv_paths]

    if output_json:
        print(json.dumps(result))
        return result

    _print_human_report(daily_metrics)
    return result


def _print_human_report(daily_metrics: dict[str, Any]) -> None:
    """Print human-readable report."""
    print("\n# Apple Health Mental Health Metrics (Last 14 Days)\n")
    display_dates = sorted(daily_metrics.keys(), reverse=True)
    print("| Date | Sleep (hrs) | Steps | Exercise | Avg HRV | Resting HR | Mindful (min) |")
    print("|------|-------------|-------|----------|---------|------------|---------------|")

    total_sleep = 0.0
    total_hrv: list[float] = []
    total_mindful = 0.0
    total_steps = 0
    days_with_data = 0

    for date in display_dates:
        metrics = daily_metrics[date]
        sleep = metrics["sleep_hours"]
        steps = metrics["steps"]
        exercise = metrics["exercise_minutes"]
        avg_hrv = sum(metrics["hrv"]) / len(metrics["hrv"]) if metrics["hrv"] else 0
        avg_resting_hr = sum(metrics["resting_hr"]) / len(metrics["resting_hr"]) if metrics["resting_hr"] else 0
        mindful = metrics["mindful_minutes"]

        if sleep > 0 or avg_hrv > 0 or steps > 0:
            days_with_data += 1
            total_sleep += sleep
            total_steps += steps
            if avg_hrv > 0:
                total_hrv.append(avg_hrv)
            total_mindful += mindful

        sleep_str = f"{sleep:.1f}" if sleep > 0 else "-"
        steps_str = f"{steps:,}" if steps > 0 else "-"
        exercise_str = f"{exercise:.0f}m" if exercise > 0 else "-"
        hrv_str = f"{avg_hrv:.0f}ms" if avg_hrv > 0 else "-"
        resting_hr_str = f"{avg_resting_hr:.0f} bpm" if avg_resting_hr > 0 else "-"
        mindful_str = f"{mindful:.0f}" if mindful > 0 else "-"

        print(f"| {date} | {sleep_str} | {steps_str} | {exercise_str} | {hrv_str} | {resting_hr_str} | {mindful_str} |")

    print("\n## Summary\n")
    if days_with_data > 0:
        avg_sleep = total_sleep / days_with_data
        avg_hrv = sum(total_hrv) / len(total_hrv) if total_hrv else 0
        avg_mindful = total_mindful / days_with_data
        avg_steps = total_steps / days_with_data
        print(f"**Average Sleep**: {avg_sleep:.1f} hours/night")
        print(f"**Average Steps**: {avg_steps:,.0f}/day")
        print(f"**Average HRV**: {avg_hrv:.0f}ms (Higher = better stress resilience)")
        print(f"**Average Mindful Minutes**: {avg_mindful:.0f} min/day")
    else:
        print("No health data found in last 14 days")


def apple_health_main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    output_json = "--json" in args
    positional = [arg for arg in args if not arg.startswith("--")]
    result = parse_apple_health(positional or None, output_json=output_json)
    if result["status"] != "success" and not output_json:
        print(f"Error: {result['message']}")
        if not positional:
            print("Export from Health app to Google Drive.")
        return 1
    return 0 if result["status"] == "success" else 1
