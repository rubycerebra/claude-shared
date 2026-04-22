from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "agent-hooks"


def _run_hook(script_name: str, payload: dict, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = HOOKS / script_name
    assert script.exists(), f"Missing hook script: {script_name}"
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=merged_env,
        check=True,
    )


def test_task_switch_clear_alert_emits_context_hint_on_task_change(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".claude" / "config").mkdir(parents=True)
    (home / ".claude" / "cache").mkdir(parents=True)

    (home / ".claude" / "config" / "task-clear.json").write_text(
        json.dumps({
            "enabled": True,
            "notify_on_switch": False,
            "auto_type_clear": False,
            "emit_context_hint": True,
        })
    )
    (home / ".claude" / "cache" / "task-clear-state.json").write_text(
        json.dumps({"last_task_id": "HEALTH-old", "last_notified_at": 0, "last_notified_task_id": ""})
    )

    result = _run_hook(
        "task-switch-clear-alert.sh",
        {"tool_input": {"command": "bd update HEALTH-2eg --status=in_progress"}},
        env={"HOME": str(home)},
    )

    payload = json.loads(result.stdout)
    message = payload["hookSpecificOutput"]["additionalContext"]
    assert "/clear" in message
    assert "HEALTH-old" in message
    assert "HEALTH-2eg" in message


def test_compact_cadence_emits_prompt_at_threshold(tmp_path: Path):
    home = tmp_path / "home"
    session_id = "session-123"
    (home / ".claude" / "config").mkdir(parents=True)
    (home / ".claude" / "cache").mkdir(parents=True)
    (home / ".claude" / "config" / "compact-cadence.json").write_text(
        json.dumps({"enabled": True, "thresholds": [15, 20]})
    )
    (home / ".claude" / "cache" / "compact-cadence-state.json").write_text(
        json.dumps({session_id: {"count": 14, "fired": []}})
    )

    result = _run_hook(
        "compact-cadence.sh",
        {"prompt": "please summarise the current state and latest verification"},
        env={"HOME": str(home), "CLAUDE_SESSION_ID": session_id},
    )

    payload = json.loads(result.stdout)
    message = payload["hookSpecificOutput"]["additionalContext"]
    assert "/compact" in message
    assert "15" in message


@pytest.mark.parametrize(
    ("prompt", "expected_fragment"),
    [
        ("reformat this note into three bullets", "/model haiku"),
        ("quick summary of this file", "/effort low"),
    ],
)
def test_model_effort_routing_suggests_cheap_route_for_routine_tasks(tmp_path: Path, prompt: str, expected_fragment: str):
    home = tmp_path / "home"
    (home / ".claude" / "config").mkdir(parents=True)

    result = _run_hook(
        "model-effort-routing.sh",
        {"prompt": prompt},
        env={"HOME": str(home)},
    )

    payload = json.loads(result.stdout)
    message = payload["hookSpecificOutput"]["additionalContext"]
    assert "/model haiku" in message
    assert "/effort low" in message
    assert expected_fragment in message


def test_model_effort_routing_skips_complex_debug_tasks(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".claude" / "config").mkdir(parents=True)

    result = _run_hook(
        "model-effort-routing.sh",
        {"prompt": "debug the cache invalidation bug in api-server.py"},
        env={"HOME": str(home)},
    )

    assert result.stdout.strip() == ""
