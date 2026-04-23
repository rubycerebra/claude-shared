from __future__ import annotations

from collections import defaultdict
from contextlib import redirect_stdout
import csv
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Sequence


# Discovery + small parsing primitives moved to claude_core.health.discovery.
# Re-exported here for backward compatibility with existing wrappers.
from .health.discovery import (  # noqa: E402,F401
    _default_health_roots,
    _normalise_search_roots,
    _find_matching_files,
    find_health_csvs,
    find_latest_health_csv,
    find_autosleep_csvs,
    find_latest_autosleep_csv,
    find_latest_csv,
    parse_duration,
    parse_float,
    _parse_timestamp,
    _calculate_data_age_days,
)


def parse_autosleep(
    csv_file: str | Path | None = None,
    days: int = 14,
    search_roots: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Parse AutoSleep CSV and return daily sleep metrics."""
    if csv_file is None:
        csv_file = find_latest_autosleep_csv(search_roots)

    path = Path(csv_file).expanduser() if csv_file else None
    if path is None or not path.exists():
        return {"status": "error", "message": "No AutoSleep CSV found"}

    cutoff = datetime.now() - timedelta(days=days)
    daily: list[dict[str, Any]] = []

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bedtime = _parse_timestamp(row.get("bedtime"))
            waketime = _parse_timestamp(row.get("waketime"))
            if bedtime is None or waketime is None or waketime < cutoff:
                continue

            daily.append(
                {
                    "date": waketime.strftime("%Y-%m-%d"),
                    "bedtime": bedtime.strftime("%H:%M"),
                    "waketime": waketime.strftime("%H:%M"),
                    "in_bed_hours": round(parse_duration(row.get("inBed")), 2),
                    "asleep_hours": round(parse_duration(row.get("asleep")), 2),
                    "deep_hours": round(parse_duration(row.get("deep")), 2),
                    "efficiency": parse_float(row.get("efficiency")),
                    "sleep_hr": parse_float(row.get("sleepBPM")),
                    "sleep_hrv": parse_float(row.get("sleepHRV")),
                    "spo2_avg": parse_float(row.get("SpO2Avg")),
                    "apnea": parse_float(row.get("apnea")),
                }
            )

    daily.sort(key=lambda item: item["date"], reverse=True)

    file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
    file_age_hours = (datetime.now() - file_mtime).total_seconds() / 3600
    most_recent_date = daily[0]["date"] if daily else None
    data_age_days = _calculate_data_age_days(most_recent_date)
    is_fresh = data_age_days is not None and data_age_days <= 1

    result: dict[str, Any] = {
        "status": "success",
        "source": path.name,
        "days_parsed": len(daily),
        "fresh": is_fresh,
        "most_recent_date": most_recent_date,
        "data_age_days": data_age_days,
        "file_age_hours": round(file_age_hours, 1),
        "daily_metrics": daily,
    }
    if not is_fresh:
        if data_age_days is None:
            result["stale_reason"] = "No sleep entries found in CSV"
        else:
            result["stale_reason"] = f"Most recent sleep entry is {data_age_days} days old ({most_recent_date})"

    if daily:
        last = daily[0]
        result["last_night"] = {
            "date": last["date"],
            "asleep": f"{last['asleep_hours']}h",
            "efficiency": f"{last['efficiency']}%" if last["efficiency"] else "—",
            "deep": f"{last['deep_hours']}h",
            "sleep_hr": f"{last['sleep_hr']} bpm" if last["sleep_hr"] else "—",
        }

    return result


def print_autosleep_table(data: dict[str, Any]) -> None:
    """Print human-readable sleep table."""
    if data["status"] != "success":
        print(f"❌ {data['message']}")
        return

    print(f"\n# AutoSleep Metrics (Last {len(data['daily_metrics'])} nights)\n")
    print("| Date | Bed | Wake | Asleep | Deep | Eff% | HR | HRV | SpO2 | Apnea |")
    print("|------|-----|------|--------|------|------|-----|-----|------|-------|")

    total_sleep = 0.0
    total_deep = 0.0
    count = 0

    for entry in data["daily_metrics"]:
        efficiency = f"{entry['efficiency']:.0f}" if entry["efficiency"] else "—"
        sleep_hr = f"{entry['sleep_hr']:.0f}" if entry["sleep_hr"] else "—"
        sleep_hrv = f"{entry['sleep_hrv']:.0f}" if entry["sleep_hrv"] else "—"
        spo2 = f"{entry['spo2_avg']:.0f}" if entry["spo2_avg"] else "—"
        apnea = f"{entry['apnea']:.1f}" if entry["apnea"] else "—"
        print(
            f"| {entry['date']} | {entry['bedtime']} | {entry['waketime']} | {entry['asleep_hours']}h | "
            f"{entry['deep_hours']}h | {efficiency} | {sleep_hr} | {sleep_hrv} | {spo2} | {apnea} |"
        )
        total_sleep += entry["asleep_hours"]
        total_deep += entry["deep_hours"]
        count += 1

    if count > 0:
        avg_sleep = total_sleep / count
        print(f"\n**Avg sleep:** {avg_sleep:.1f}h | **Avg deep:** {total_deep / count:.1f}h")
        if avg_sleep >= 7:
            print("✅ Good sleep duration")
        elif avg_sleep >= 6:
            print("⚠️ Fair — could use more")
        else:
            print("❌ Poor — sleep impacting anxiety")


print_table = print_autosleep_table


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


def autosleep_main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    output_json = "--json" in args
    positional = [arg for arg in args if not arg.startswith("--")]
    csv_file = positional[0] if positional else None
    result = parse_autosleep(csv_file=csv_file)
    if output_json:
        print(json.dumps(result, indent=2))
    else:
        print_autosleep_table(result)
    return 0 if result["status"] == "success" else 1


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


def _try_autosleep_source(
    max_stale_days: int,
    autosleep_parser: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        result = autosleep_parser()
    except Exception as exc:
        return {
            "usable": False,
            "chain_entry": {"source": "autosleep", "status": "error", "reason": str(exc)},
            "data": None,
        }

    if result.get("status") != "success" or not result.get("daily_metrics"):
        return {
            "usable": False,
            "chain_entry": {
                "source": "autosleep",
                "status": "no_data",
                "reason": result.get("message", "No entries"),
            },
            "data": None,
        }

    is_fresh = result.get("fresh", False)
    age = result.get("data_age_days")
    if not is_fresh and age is not None and age > max_stale_days:
        return {
            "usable": False,
            "chain_entry": {
                "source": "autosleep",
                "status": "stale",
                "data_age_days": age,
                "most_recent_date": result.get("most_recent_date"),
                "reason": result.get("stale_reason", f"Data is {age} days old"),
            },
            "data": None,
        }

    last = result["daily_metrics"][0]
    return {
        "usable": True,
        "chain_entry": {"source": "autosleep", "status": "used", "date": last["date"]},
        "data": {
            "date": last["date"],
            "sleep_hours": last["asleep_hours"],
            "sleep_hrv": last.get("sleep_hrv"),
            "hrv": last.get("sleep_hrv"),
            "deep_hours": last.get("deep_hours"),
            "efficiency": last.get("efficiency"),
            "sleep_hr": last.get("sleep_hr"),
        },
    }


def _try_apple_health_source(
    max_stale_days: int,
    health_csv_finder: Callable[[], list[str]],
    apple_health_parser: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    try:
        csv_files = health_csv_finder()
        if not csv_files:
            return {
                "usable": False,
                "chain_entry": {
                    "source": "apple_health",
                    "status": "no_files",
                    "reason": "No Health CSV exports found",
                },
                "data": None,
            }
        with redirect_stdout(io.StringIO()):
            result = apple_health_parser(csv_files, output_json=False)
    except Exception as exc:
        return {
            "usable": False,
            "chain_entry": {"source": "apple_health", "status": "error", "reason": str(exc)},
            "data": None,
        }

    if not result or result.get("status") != "success":
        return {
            "usable": False,
            "chain_entry": {"source": "apple_health", "status": "no_data", "reason": "Parse failed"},
            "data": None,
        }

    sleep_fresh = result.get("sleep_fresh", False)
    sleep_age = result.get("sleep_age_days")
    sleep_date = result.get("sleep_most_recent")
    if not sleep_fresh and sleep_age is not None and sleep_age > max_stale_days:
        return {
            "usable": False,
            "chain_entry": {
                "source": "apple_health",
                "status": "stale",
                "sleep_age_days": sleep_age,
                "sleep_most_recent": sleep_date,
                "reason": f"Sleep data is {sleep_age} days old",
            },
            "data": None,
        }

    if not sleep_date:
        return {
            "usable": False,
            "chain_entry": {
                "source": "apple_health",
                "status": "no_sleep",
                "reason": "No sleep entries in Health data",
            },
            "data": None,
        }

    day_data = None
    for metrics in reversed(result["daily_metrics"]):
        if metrics["date"] == sleep_date and metrics["sleep_hours"] > 0:
            day_data = metrics
            break

    if not day_data:
        return {
            "usable": False,
            "chain_entry": {
                "source": "apple_health",
                "status": "no_sleep",
                "reason": "Could not locate sleep entry",
            },
            "data": None,
        }

    return {
        "usable": True,
        "chain_entry": {"source": "apple_health", "status": "used", "date": day_data["date"]},
        "data": {
            "date": day_data["date"],
            "sleep_hours": day_data["sleep_hours"],
            "sleep_hrv": None,
            "hrv": day_data.get("hrv"),
            "deep_hours": None,
            "efficiency": None,
            "sleep_hr": None,
        },
    }


def _try_healthfit_source(
    max_stale_days: int,
    healthfit_parser: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    if healthfit_parser is None:
        return {
            "usable": False,
            "chain_entry": {
                "source": "healthfit",
                "status": "not_implemented",
                "reason": "parse_healthfit.py not yet available",
            },
            "data": None,
        }

    try:
        result = healthfit_parser()
    except Exception as exc:
        return {
            "usable": False,
            "chain_entry": {"source": "healthfit", "status": "error", "reason": str(exc)},
            "data": None,
        }

    if not result or result.get("status") != "success":
        return {
            "usable": False,
            "chain_entry": {"source": "healthfit", "status": "no_data", "reason": "Parse failed"},
            "data": None,
        }

    sleep_date = result.get("most_recent_date")
    sleep_age = result.get("data_age_days")
    sleep_fresh = sleep_age is not None and sleep_age <= max_stale_days
    if not sleep_fresh:
        return {
            "usable": False,
            "chain_entry": {
                "source": "healthfit",
                "status": "stale",
                "data_age_days": sleep_age,
                "reason": f"HealthFit data is {sleep_age} days old" if sleep_age is not None else "No data",
            },
            "data": None,
        }

    return {
        "usable": True,
        "chain_entry": {"source": "healthfit", "status": "used", "date": sleep_date},
        "data": {
            "date": sleep_date,
            "sleep_hours": result.get("sleep_hours"),
            "sleep_hrv": None,
            "hrv": result.get("hrv"),
            "deep_hours": None,
            "efficiency": None,
            "sleep_hr": None,
        },
    }


def _build_sleep_result(source: str, data: dict[str, Any], chain: list[dict[str, Any]]) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    data_date = str(data.get("date", "")).strip()[:10]
    is_fresh = data_date == today
    return {
        "source": source,
        "fresh": is_fresh,
        "stale_reason": None if is_fresh else f"Sleep date {data_date} is not today ({today})",
        **data,
        "fallback_chain": chain,
    }


def get_sleep_data(
    max_stale_days: int = 1,
    autosleep_parser: Callable[[], dict[str, Any]] | None = None,
    health_csv_finder: Callable[[], list[str]] | None = None,
    apple_health_parser: Callable[..., dict[str, Any]] | None = None,
    healthfit_parser: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Get sleep data using the AutoSleep → Apple Health → HealthFit fallback chain."""
    autosleep_parser = autosleep_parser or parse_autosleep
    health_csv_finder = health_csv_finder or find_health_csvs
    apple_health_parser = apple_health_parser or parse_apple_health

    chain: list[dict[str, Any]] = []

    autosleep = _try_autosleep_source(max_stale_days, autosleep_parser)
    chain.append(autosleep["chain_entry"])
    if autosleep["usable"]:
        return _build_sleep_result("autosleep", autosleep["data"], chain)

    apple_health = _try_apple_health_source(max_stale_days, health_csv_finder, apple_health_parser)
    chain.append(apple_health["chain_entry"])
    if apple_health["usable"]:
        return _build_sleep_result("apple_health", apple_health["data"], chain)

    healthfit = _try_healthfit_source(max_stale_days, healthfit_parser)
    chain.append(healthfit["chain_entry"])
    if healthfit["usable"]:
        return _build_sleep_result("healthfit", healthfit["data"], chain)

    return {
        "source": None,
        "fresh": False,
        "stale_reason": "All sleep sources stale or unavailable",
        "sleep_hours": None,
        "sleep_hrv": None,
        "hrv": None,
        "deep_hours": None,
        "efficiency": None,
        "sleep_hr": None,
        "date": None,
        "fallback_chain": chain,
    }


def print_sleep_human(result: dict[str, Any]) -> None:
    """Print human-readable sleep summary."""
    if not result["source"]:
        print("❌ No fresh sleep data available")
        print("\nFallback chain:")
        for entry in result["fallback_chain"]:
            print(f"  {entry['source']}: {entry['status']} — {entry.get('reason', '')}")
        return

    source_labels = {
        "autosleep": "AutoSleep (full)",
        "apple_health": "Apple Health (basic)",
        "healthfit": "HealthFit Sheets (basic)",
    }

    print(f"\n# Sleep Data — {result['date']}")
    print(f"**Source:** {source_labels.get(result['source'], result['source'])}")
    print(f"**Sleep:** {result['sleep_hours']}h" if result["sleep_hours"] else "**Sleep:** —")

    if result.get("deep_hours") is not None:
        print(f"**Deep:** {result['deep_hours']}h")
    if result.get("efficiency") is not None:
        print(f"**Efficiency:** {result['efficiency']}%")
    if result.get("sleep_hrv") is not None:
        print(f"**Sleep HRV:** {result['sleep_hrv']}")
    elif result.get("hrv"):
        print(f"**Waking HRV:** {result['hrv']} (no sleep HRV available)")
    if result.get("sleep_hr") is not None:
        print(f"**Sleep HR:** {result['sleep_hr']} bpm")

    skipped = [entry for entry in result["fallback_chain"] if entry["status"] != "used"]
    if skipped:
        print("\nFallback chain:")
        for entry in result["fallback_chain"]:
            icon = "✅" if entry["status"] == "used" else "⏭️"
            print(f"  {icon} {entry['source']}: {entry['status']}")


print_human = print_sleep_human


def sleep_fallback_main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    result = get_sleep_data()
    if "--json" in args:
        print(json.dumps(result, indent=2))
    else:
        print_sleep_human(result)
    return 0 if result["source"] else 1


__all__ = [
    "apple_health_main",
    "autosleep_main",
    "find_autosleep_csvs",
    "find_health_csvs",
    "find_latest_autosleep_csv",
    "find_latest_csv",
    "find_latest_health_csv",
    "get_sleep_data",
    "parse_apple_health",
    "parse_autosleep",
    "parse_duration",
    "parse_float",
    "print_autosleep_table",
    "print_human",
    "print_sleep_human",
    "print_table",
    "sleep_fallback_main",
]
