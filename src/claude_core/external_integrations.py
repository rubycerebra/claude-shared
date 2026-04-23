from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def parse_alter_transcript(file_path: str | Path):
    with open(file_path, 'r', encoding='utf-8') as fh:
        content = fh.read()
    lines = content.split('\n')

    date_match = re.search(r'Fecha: (.+)|Date: (.+)', lines[0])
    duration_match = re.search(r'Duración: (.+)|Duration: (.+)', lines[1])
    metadata = {}
    if date_match:
        metadata['date'] = date_match.group(1) or date_match.group(2)
    if duration_match:
        metadata['duration'] = duration_match.group(1) or duration_match.group(2)

    filename = Path(file_path).stem
    title_parts = filename.split('-', 4)
    if len(title_parts) > 4:
        metadata['title'] = title_parts[4].replace('-', ' ').title()

    dialogue_lines = []
    for line in lines[3:]:
        if line.strip():
            match = re.match(r'\[[\d:]+(?:-[\d:]+)?\]\s+(.+?):\s+(.+)', line)
            if match:
                dialogue_lines.append({'speaker': match.group(1), 'text': match.group(2)})

    return metadata, dialogue_lines


def find_mental_health_keywords(dialogue_lines):
    keywords = [
        'anxiety', 'anxious', 'worry', 'worried', 'stress', 'stressed',
        'overwhelm', 'overwhelmed', 'panic', 'fear', 'scared',
        'depressed', 'depression', 'sad', 'upset', 'angry', 'frustrated',
        'janna', 'jana', 'wife', 'fight', 'argument', 'conflict',
        'therapy', 'therapist', 'samantha',
        'adhd', 'autism', 'autistic', 'neurodivergent',
        'ruminate', 'ruminating', 'overthinking',
        'boundary', 'boundaries',
        'victim', 'rescuer', 'persecutor', 'drama triangle',
        'affirmation', 'positive', 'gratitude',
    ]
    insights = []
    for entry in dialogue_lines:
        text_lower = entry['text'].lower()
        for keyword in keywords:
            if keyword in text_lower:
                insights.append({'speaker': entry['speaker'], 'keyword': keyword, 'text': entry['text']})
                break
    return insights


def alter_main(argv: list[str] | None = None, *, alter_folder: Path | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    alter_folder = alter_folder or Path.home() / 'Library/Application Support/Alter/Transcripts'
    if argv:
        file_path = argv[0]
        metadata, dialogue = parse_alter_transcript(file_path)
        insights = find_mental_health_keywords(dialogue)
        print('=== ALTER TRANSCRIPT ===')
        print(f"Date: {metadata.get('date', 'Unknown')}")
        print(f"Duration: {metadata.get('duration', 'Unknown')}")
        print(f"Title: {metadata.get('title', 'Untitled')}")
        print()
        if insights:
            print('## Mental Health Insights')
            print(f'Found {len(insights)} relevant exchanges')
            print()
            for insight in insights[:15]:
                print(f"[{insight['keyword']}] {insight['speaker']}: {insight['text'][:100]}...")
                print()
        return 0

    txt_files = list(alter_folder.glob('*.txt'))
    if not txt_files:
        print('No Alter transcripts found')
        return 1
    latest = max(txt_files, key=os.path.getmtime)
    metadata, dialogue = parse_alter_transcript(latest)
    insights = find_mental_health_keywords(dialogue)
    print(f'Most recent: {latest.name}')
    print(f"Date: {metadata.get('date', 'Unknown')}")
    print(f"Duration: {metadata.get('duration', 'Unknown')}")
    print(f"Title: {metadata.get('title', 'Untitled')}")
    print(f'Found {len(insights)} mental health keywords')
    return 0
