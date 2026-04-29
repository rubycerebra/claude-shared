"""Health metrics — re-export layer for backward compatibility.

All logic has been decomposed into submodules:
  - claude_core.health.discovery  — CSV discovery + parsing primitives
  - claude_core.health.autosleep  — AutoSleep CSV parser
  - claude_core.health.apple      — Apple Health CSV parser
  - claude_core.health.fallback   — Sleep fallback orchestrator
"""
from __future__ import annotations

# Discovery primitives (phase 07)
from .health.discovery import (  # noqa: F401
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

# AutoSleep parser (phase 10)
from .health.autosleep import (  # noqa: F401
    parse_autosleep,
    print_autosleep_table,
    print_table,
    autosleep_main,
)

# Apple Health parser (phase 10)
from .health.apple import (  # noqa: F401
    _coerce_csv_paths,
    _iter_numeric_columns,
    _parse_single_csv,
    _render_apple_health_result,
    parse_apple_health,
    _print_human_report,
    apple_health_main,
)

# Sleep fallback orchestrator (phase 10)
from .health.fallback import (  # noqa: F401
    _try_autosleep_source,
    _try_apple_health_source,
    _try_healthfit_source,
    _build_sleep_result,
    get_sleep_data,
    print_sleep_human,
    print_human,
    sleep_fallback_main,
)

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
