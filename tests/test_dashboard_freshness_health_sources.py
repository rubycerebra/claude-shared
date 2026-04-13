from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashboard_freshness_ideas as dfi


def _build_registry(cache: dict):
    return dfi.build_today_section_freshness_registry(
        cache,
        today='2026-04-13',
        cache_timestamp='2026-04-13T07:10:48',
        diarium_fresh=True,
        diarium_source_date='2026-04-13',
        diarium_fresh_reason='',
        morning_note='Morning note',
        evening_note='Evening note',
        diary_updates='',
        guidance_lines=[],
        action_items=[],
        future_action_items=[],
        action_items_updated_at='2026-04-13T07:00:00',
        action_items_stale_reason='',
        ideas_payload={},
        mood_entries=[],
        mood_state={},
        updates_state={},
        cache_state={},
        narrative_state={},
    )


def test_health_live_success_counts_as_health_source_for_freshness():
    registry = _build_registry({
        'health_live': {
            'status': 'success',
            'source': 'health_auto_export',
            'age_hours': 0.0,
            'sleep': {'asleep_hours': 6.2, 'date': '2026-04-13 00:00:00 +0100'},
        }
    })

    health = registry['items']['health']

    assert health['level'] == 'info'
    assert health['line'] == 'Health section is running on a thinner source mix.'
