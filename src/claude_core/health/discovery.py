"""Health-data CSV discovery + small parsing primitives.

Extracted from claude_core.health_metrics so the parser module can
shrink. Public surface is re-exported from health_metrics for
backward compatibility with existing wrappers.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence


def _default_health_roots() -> list[Path]:
    from ..config import build_runtime_config
    return build_runtime_config().paths.apple_health_roots


def _normalise_search_roots(search_roots: Sequence[str | Path] | None = None) -> list[Path]:
    candidates = search_roots or _default_health_roots()
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw in candidates:
        root = Path(raw).expanduser()
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def _find_matching_files(pattern: str, search_roots: Sequence[str | Path] | None = None) -> list[str]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for root in _normalise_search_roots(search_roots):
        if not root.exists():
            continue
        for match in root.glob(pattern):
            resolved = match.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            matches.append(resolved)
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [str(path) for path in matches]


def find_health_csvs(search_roots: Sequence[str | Path] | None = None) -> list[str]:
    """Find all Apple Health exports, newest first."""
    return _find_matching_files("Export_*.csv", search_roots)


def find_latest_health_csv(search_roots: Sequence[str | Path] | None = None) -> str | None:
    csvs = find_health_csvs(search_roots)
    return csvs[0] if csvs else None


def find_autosleep_csvs(search_roots: Sequence[str | Path] | None = None) -> list[str]:
    """Find all AutoSleep exports, newest first."""
    return _find_matching_files("AutoSleep-*.csv", search_roots)


def find_latest_autosleep_csv(search_roots: Sequence[str | Path] | None = None) -> str | None:
    csvs = find_autosleep_csvs(search_roots)
    return csvs[0] if csvs else None


def find_latest_csv(search_roots: Sequence[str | Path] | None = None) -> str | None:
    """Compatibility alias for the legacy AutoSleep helper."""
    return find_latest_autosleep_csv(search_roots)


def parse_duration(duration_str: str | None) -> float:
    """Parse HH:MM:SS duration string to hours (float)."""
    if not duration_str or duration_str.strip() == "":
        return 0.0
    try:
        parts = duration_str.strip().split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) > 2 else 0
        return hours + minutes / 60 + seconds / 3600
    except (ValueError, IndexError):
        return 0.0


def parse_float(value: str | None) -> float | None:
    """Safely parse a float value."""
    if not value or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _calculate_data_age_days(date_value: str | None) -> int | None:
    if not date_value:
        return None
    return (datetime.now() - datetime.strptime(date_value, "%Y-%m-%d")).days
