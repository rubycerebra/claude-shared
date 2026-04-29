"""Sleep fallback orchestrator — extracted from claude_core.health_metrics.

Implements the AutoSleep → Apple Health → HealthFit fallback chain.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime
from typing import Any, Callable, Sequence

from .autosleep import parse_autosleep
from .apple import parse_apple_health
from .discovery import find_health_csvs


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
    """Get sleep data using the AutoSleep -> Apple Health -> HealthFit fallback chain."""
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
