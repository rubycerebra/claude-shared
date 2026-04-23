from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .config import build_runtime_config


def _project_root(project_root: Path | None = None) -> Path:
    return build_runtime_config(project_root).project_root


def get_clipboard() -> str | None:
    try:
        result = subprocess.run(['pbpaste'], capture_output=True, text=True, check=True)
        return result.stdout
    except Exception as exc:
        print(f"❌ Error reading clipboard: {exc}")
        return None


def save_conversation(content: str, project_root: Path | None = None) -> Path:
    root = _project_root(project_root)
    inbox_dir = root / 'inbox'
    inbox_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filepath = inbox_dir / f'non-code-conversation_{timestamp}.txt'
    with filepath.open('w', encoding='utf-8') as fh:
        fh.write('# Non-Code Claude Conversation\n')
        fh.write(f"# Imported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write('# Status: Pending review by Code Claude\n\n')
        fh.write('---\n\n')
        fh.write(content)
    return filepath


def import_conversation_main(project_root: Path | None = None, argv: list[str] | None = None) -> int:
    del argv
    print('📋 Importing non-Code conversation from clipboard...')
    content = get_clipboard()
    if not content:
        print('❌ Clipboard is empty')
        return 1
    if len(content) < 50:
        print('⚠️  Clipboard content seems too short. Continue anyway? (y/n)')
        if input().strip().lower() != 'y':
            print('❌ Import cancelled')
            return 1
    filepath = save_conversation(content, project_root=project_root)
    print(f'✅ Conversation imported: {filepath.name}')
    print(f'📁 Location: {filepath}')
    print('Next steps: review and integrate on the next Code Claude session.')
    return 0


def format_time_range(start: str, end: str) -> str:
    try:
        if 'T' not in start:
            return 'All day'
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        return f"{start_dt.astimezone().strftime('%H:%M')} - {end_dt.astimezone().strftime('%H:%M')}"
    except Exception:
        return 'Time TBD'


def get_calendar_summary(data: dict) -> str:
    calendar = data.get('calendar', {})
    if calendar.get('status') != 'success':
        return '⚠️ Calendar unavailable'
    events = calendar.get('events', [])
    if not events:
        return 'No events today'
    output = [f"**{calendar.get('count', len(events))} events today:**", '']
    for event in events:
        output.append(
            f"• {event.get('summary', 'Untitled')} ({format_time_range(event.get('start', ''), event.get('end', ''))})"
        )
    return '\n'.join(output)


def get_recent_wins(wins_file: Path) -> str:
    if not wins_file.exists():
        return 'No wins tracked yet'
    lines = [
        line.strip()
        for line in wins_file.read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.startswith('#')
    ]
    if not lines:
        return 'No wins tracked yet'
    return '\n'.join([f'• {line}' for line in lines[-5:]])


def generate_context(project_root: Path | None = None) -> str:
    cfg = build_runtime_config(project_root)
    cache_file = cfg.paths.cache_root / 'session-data.json'
    wins_file = cfg.paths.claude_shared_root / 'wins.md'
    if not cache_file.exists():
        return '⚠️ **Daemon cache not found** - Run this script on your Mac first'
    data = json.loads(cache_file.read_text(encoding='utf-8'))
    output = [
        '# Context for Non-Code Claude',
        '',
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        '',
        '---',
        '',
        '## About Jim',
        '',
        '**Mission:** Stay grounded, keep meaningful work moving, and protect health + family time.',
        '',
        '**Communication:**',
        '• British English spelling',
        '• Direct, calm, concise responses',
        '• Time-reality checks before big commitments',
        '',
        '---',
        '',
        '## Today',
        '',
        f"**Date:** {data.get('date_full', data.get('date', 'Unknown'))}",
        '',
        get_calendar_summary(data),
        '',
        '---',
        '',
        '## Recent Wins',
        '',
        get_recent_wins(wins_file),
        '',
        '---',
        '',
        '## Notes',
        '',
        '- This context is Claude-first and token-light.',
        '- Canonical deeper context lives in the local filesystem and daemon cache.',
    ]
    return '\n'.join(output) + '\n'


def format_non_code_context_main(project_root: Path | None = None, argv: list[str] | None = None) -> int:
    del argv
    root = _project_root(project_root)
    output_file = root / 'non-code-context.md'
    content = generate_context(project_root=project_root)
    output_file.write_text(content, encoding='utf-8')
    print(f'✅ Wrote {output_file}')
    return 0
