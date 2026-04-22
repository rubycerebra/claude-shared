from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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


def test_noisy_command_rewrite_wraps_pytest_and_preserves_original_command(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".claude" / "scripts").mkdir(parents=True)
    (home / ".claude" / "scripts" / "compact-command-output.py").write_text("#!/usr/bin/env python3\n")

    result = _run_hook(
        "noisy-command-rewrite.sh",
        {"tool_input": {"command": "python3 -m pytest -q tests/test_token_efficiency_tools.py"}},
        env={"HOME": str(home)},
    )

    payload = json.loads(result.stdout)
    updated = payload["hookSpecificOutput"]["updatedInput"]["command"]
    assert "compact-command-output.py" in updated
    assert "python3 -m pytest -q tests/test_token_efficiency_tools.py" in updated


def test_noisy_command_rewrite_ignores_small_commands(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".claude" / "scripts").mkdir(parents=True)
    (home / ".claude" / "scripts" / "compact-command-output.py").write_text("#!/usr/bin/env python3\n")

    result = _run_hook(
        "noisy-command-rewrite.sh",
        {"tool_input": {"command": "echo hello"}},
        env={"HOME": str(home)},
    )

    assert result.stdout.strip() == ""
