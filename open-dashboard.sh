#!/bin/bash

# Raycast Script Command
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Open Daily Dashboard
# @raycast.mode silent
# @raycast.packageName Claude
# @raycast.icon 🌟

# Optional parameters:
# @raycast.description Generate and open Jim's daily dashboard in browser
# @raycast.author Jim
# @raycast.authorURL https://github.com/jim

# Run the Python generator (reads fresh data, outputs HTML, opens browser)
python3 ~/Documents/Claude\ Projects/claude-shared/generate-dashboard.py
