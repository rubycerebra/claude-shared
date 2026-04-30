#!/bin/bash
# PostToolUse on Skill — marks that a skill was invoked this session.
# Used by superpowers-enforce.sh to silence enforcement once a skill is called.
SESSION_ID=$(jq -r '.session_id // empty' 2>/dev/null)
[ -z "$SESSION_ID" ] && exit 0

# --- Superpowers availability gate ---
_sp_settings="$HOME/.claude/settings.json"
_sp_enabled=$(jq -r '.enabledPlugins["superpowers@claude-plugins-official"] // empty' "$_sp_settings" 2>/dev/null)
if [ -z "$_sp_enabled" ] || [ "$_sp_enabled" = "false" ] || [ "$_sp_enabled" = "null" ]; then exit 0; fi
# --- end gate ---

touch "/tmp/superpowers-skill-invoked-${SESSION_ID}"
exit 0
