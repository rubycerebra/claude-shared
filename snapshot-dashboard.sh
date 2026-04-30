#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Snapshot Dashboard
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 📸
# @raycast.packageName Claude Code

# @Documentation:
# @raycast.description Generate a static dashboard snapshot to iCloud Drive for offline/phone viewing
# @raycast.author Jim Cherry

python3 "$HOME/.claude/scripts/snapshot-dashboard.py"
