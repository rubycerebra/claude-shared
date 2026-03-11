#!/usr/bin/env python3
"""
Generate pure HTML dashboard for Apple Notes.

No CSS, no images - just HTML that Apple Notes can render natively.
All text is selectable and copyable.

Usage:
    python3 generate-notes-dashboard.py  # Returns HTML string
"""

import json
import re
from pathlib import Path
from datetime import datetime

# Paths
DAEMON_CACHE = Path.home() / ".claude" / "cache" / "session-data.json"
SHARED_DIR = Path.home() / "Documents" / "Claude Projects" / "claude-shared"
WINS_FILE = SHARED_DIR / "wins.md"


def load_daemon_cache():
    """Load the daemon cache"""
    if DAEMON_CACHE.exists():
        try:
            with open(DAEMON_CACHE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading cache: {e}")
    return {}


def format_number(n):
    """Format large numbers compactly (12844 -> 12.8k)"""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def parse_wins(wins_text):
    """Parse wins from wins.md - extract recent wins only"""
    wins = []
    lines = wins_text.split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('- ') and 'rejection' not in line.lower():
            win = line[2:].strip()
            if win and len(win) > 5:
                # Truncate long wins
                if len(win) > 60:
                    win = win[:57] + "..."
                wins.append(win)
    return wins[:4]  # Max 4 wins


def generate_html(cache):
    """Generate pure HTML dashboard from cache data"""
    now = datetime.now()
    date_str = now.strftime("%d %b %Y")
    time_str = now.strftime("%H:%M")

    # Extract data
    diarium = cache.get("diarium", {})
    calendar_data = cache.get("calendar", {})
    open_loops = cache.get("open_loops", {})
    streaks = cache.get("streaks", {})
    apple_health = cache.get("apple_health", {})

    html_parts = []

    # Header
    html_parts.append(f"<h2>📊 Dashboard - {date_str}</h2>")

    # Morning Context
    grateful = diarium.get("grateful", "")
    intent = diarium.get("intent", "")
    affirmation = diarium.get("daily_affirmation", "")

    if grateful or intent or affirmation:
        html_parts.append("<h3>🌅 Morning</h3>")
        if grateful:
            html_parts.append(f"<p><b>Grateful:</b> {grateful}</p>")
        if intent:
            html_parts.append(f"<p><b>Intent:</b> {intent}</p>")
        if affirmation:
            html_parts.append(f"<p><b>Affirmation:</b> {affirmation}</p>")

    # Calendar
    if calendar_data.get("status") == "success":
        events = calendar_data.get("events", [])
        if events:
            html_parts.append("<h3>📅 Today</h3>")
            html_parts.append("<table>")
            for event in events[:8]:  # Max 8 events
                summary = event.get("summary", "")
                start = event.get("start", "")
                if 'T' in start:
                    try:
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                        time_display = start_dt.strftime("%H:%M")
                    except:
                        time_display = "TBD"
                else:
                    time_display = "All day"
                html_parts.append(f"<tr><td><b>{time_display}</b></td><td>{summary}</td></tr>")
            html_parts.append("</table>")

    # Open Loops
    if open_loops.get("status") == "found":
        items = open_loops.get("items", [])
        count = open_loops.get("count", len(items))
        if items:
            html_parts.append(f"<h3>⚠️ Open Loops ({count})</h3>")
            html_parts.append("<ul>")
            for item in items[:5]:  # Max 5 loops
                html_parts.append(f"<li>{item}</li>")
            html_parts.append("</ul>")

    # Job Search section removed — freelance-first (2026-03-10)

    # Health (7 days)
    if apple_health.get("status") == "success":
        metrics = apple_health.get("daily_metrics", [])[-7:]
        if metrics:
            html_parts.append("<h3>🏃 Health (7 days)</h3>")
            html_parts.append("<table>")

            # Day row
            day_cells = "<tr><td><b>Day</b></td>"
            steps_cells = "<tr><td><b>Steps</b></td>"
            exercise_cells = "<tr><td><b>Exercise</b></td>"

            for m in metrics:
                date = m.get("date", "")
                day = date[-2:] if date else ""
                steps = format_number(m.get("steps", 0))
                exercise = f"{m.get('exercise_minutes', 0)}m"

                day_cells += f"<td>{day}</td>"
                steps_cells += f"<td>{steps}</td>"
                exercise_cells += f"<td>{exercise}</td>"

            day_cells += "</tr>"
            steps_cells += "</tr>"
            exercise_cells += "</tr>"

            html_parts.append(day_cells)
            html_parts.append(steps_cells)
            html_parts.append(exercise_cells)
            html_parts.append("</table>")

            # Average
            total_steps = sum(m.get("steps", 0) for m in metrics)
            avg_steps = total_steps // len(metrics) if metrics else 0
            html_parts.append(f"<p><b>Avg:</b> {format_number(avg_steps)} steps/day</p>")

    # Habits
    if streaks.get("status") == "success":
        habits = streaks.get("habits", [])[:5]
        if habits:
            html_parts.append("<h3>🔥 Habits</h3>")
            html_parts.append("<table>")
            for h in habits:
                name = h.get("habit", "")[:25]
                rate = h.get("rate", 0)
                html_parts.append(f"<tr><td>{name}</td><td>{rate}%</td></tr>")
            html_parts.append("</table>")

    # Wins
    if WINS_FILE.exists():
        wins = parse_wins(WINS_FILE.read_text())
        if wins:
            html_parts.append("<h3>🏆 Wins</h3>")
            html_parts.append("<ul>")
            for win in wins:
                html_parts.append(f"<li>{win}</li>")
            html_parts.append("</ul>")

    # Mental Health Insight
    keywords = diarium.get("keyword_detections", [])
    if keywords:
        insight = keywords[0] if isinstance(keywords[0], str) else ""
        if insight:
            # Truncate very long insights
            if len(insight) > 200:
                insight = insight[:197] + "..."
            html_parts.append("<h3>🧠 Insight</h3>")
            html_parts.append(f"<p><i>\"{insight}\"</i></p>")

    # Footer
    html_parts.append(f"<br><p><i>Generated {time_str}</i></p>")

    return "\n".join(html_parts)


def main():
    """Generate and print HTML dashboard"""
    cache = load_daemon_cache()
    html = generate_html(cache)
    print(html)
    return html


if __name__ == "__main__":
    main()
