"""AutoSleep CSV parser — extracted from claude_core.health_metrics."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from .discovery import (
    find_latest_autosleep_csv,
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
