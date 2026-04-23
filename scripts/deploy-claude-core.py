#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from claude_core.runtime_deploy import deploy_shared_core


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Deploy claude_core from claude-shared into ~/.claude/scripts.')
    parser.add_argument('--shared-root', default=str(ROOT), help='Path to canonical claude-shared repo root')
    parser.add_argument('--runtime-root', default=str(Path.home() / '.claude' / 'scripts'), help='Runtime scripts directory')
    parser.add_argument('--dry-run', action='store_true', help='Print deploy plan without copying files')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    plan = deploy_shared_core(Path(args.shared_root), runtime_root=Path(args.runtime_root), dry_run=args.dry_run)
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
