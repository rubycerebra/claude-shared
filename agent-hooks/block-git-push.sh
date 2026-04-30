#!/usr/bin/env python3
"""Block `git push` unless CLAUDE_ALLOW_PUSH=1 is set inline.

Guardrail installed after a subagent pushed to main without authorization
(HEALTH-aheb, 2026-04-17). Requires explicit opt-in per push command.
"""
import json
import re
import sys


def command_contains_git_push(cmd: str) -> bool:
    stripped = re.sub(r"'[^']*'", "", cmd)
    stripped = re.sub(r'"[^"]*"', "", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    for seg in re.split(r"[;&|`]|\|\|", stripped):
        if re.search(r"(?:^|\s)git\b[^;&|`]*?\bpush\b", seg):
            return True
    return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    cmd = str(data.get("tool_input", {}).get("command", ""))

    if not command_contains_git_push(cmd):
        sys.exit(0)

    if "CLAUDE_ALLOW_PUSH=1" in cmd:
        sys.exit(0)

    print(
        "Blocked: `git push` requires explicit authorization.\n"
        "To proceed, prefix the command with CLAUDE_ALLOW_PUSH=1, e.g.:\n"
        "  CLAUDE_ALLOW_PUSH=1 git push origin main\n"
        "Reason: guardrail added after an unauthorised push to main\n"
        "(HEALTH-aheb subagent, 2026-04-17).",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
