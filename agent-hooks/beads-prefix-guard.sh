#!/usr/bin/env python3
"""
PreToolUse hook — blocks cross-project beads writes.
Fires when `bd create/note/remember/update/in-progress/close/edit/comment/link/sync/import/flush`
is called with an ID that doesn't match the project's configured issue-prefix.

Escape hatch: set BD_ALLOW_CROSS_PREFIX=1 in the environment to bypass.
"""
import json
import os
import re
import sys
from pathlib import Path

WRITE_COMMANDS = re.compile(
    r'\bbd\s+(?:create|note|remember|update|in-progress|close|edit|comment|link|sync|import|flush|delete|reopen|defer|undefer|assign|priority|label|rename)\b'
)
ID_PATTERN = re.compile(r'\b(HEALTH|WORK|TODO)-[a-z0-9]{3,}\b')

def find_beads_config(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        cfg = p / '.beads' / 'config.yaml'
        if cfg.exists():
            return cfg
    return None

def read_prefix(config_path: Path) -> str | None:
    try:
        for line in config_path.read_text().splitlines():
            m = re.match(r'^issue-prefix:\s*["\']?([A-Z]+)["\']?', line.strip())
            if m:
                return m.group(1)
    except Exception:
        pass
    return None

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if os.environ.get('BD_ALLOW_CROSS_PREFIX') == '1':
        sys.exit(0)

    tool_input = payload.get('tool_input', {})
    command = tool_input.get('command', '')

    if not WRITE_COMMANDS.search(command):
        sys.exit(0)

    # Resolve project prefix from BEADS_DIR in command or CWD
    beads_dir_match = re.search(r'BEADS_DIR=["\']?([^\s"\']+)', command)
    if beads_dir_match:
        beads_path = Path(beads_dir_match.group(1))
        config_path = beads_path / 'config.yaml'
    else:
        cwd = Path(payload.get('cwd', os.getcwd()))
        config_path = find_beads_config(cwd)

    if not config_path or not config_path.exists():
        sys.exit(0)

    project_prefix = read_prefix(config_path)
    if not project_prefix:
        sys.exit(0)

    # Find any IDs in the command with a different prefix
    ids = ID_PATTERN.findall(command)
    foreign = [p for p in ids if p != project_prefix]

    if not foreign:
        sys.exit(0)

    foreign_prefixes = ', '.join(sorted(set(foreign)))
    result = {
        "decision": "block",
        "reason": (
            f"Cross-prefix write blocked: command references {foreign_prefixes}-* IDs "
            f"but current project prefix is {project_prefix}. "
            f"Run from the correct project directory, or set BD_ALLOW_CROSS_PREFIX=1 to override."
        )
    }
    print(json.dumps(result))
    sys.exit(0)

main()
