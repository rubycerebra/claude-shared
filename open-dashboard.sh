#!/bin/bash

# Raycast Script Command
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Open Daily Dashboard
# @raycast.mode silent
# @raycast.packageName Claude
# @raycast.icon 🌟

# Optional parameters:
# @raycast.description Open the React dashboard via API server
# @raycast.author Jim
# @raycast.authorURL https://github.com/jim

# Open the React dashboard app (API-served)
open "http://127.0.0.1:8765/app?focus=now"
