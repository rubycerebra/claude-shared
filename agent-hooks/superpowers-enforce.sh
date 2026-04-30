#!/bin/bash
# PreToolUse on Edit|Write — enforce superpowers skill invocation.
# Fires on every Edit/Write until a Skill tool has been invoked this session.

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
if [ -z "$SESSION_ID" ]; then exit 0; fi

# --- Superpowers availability gate ---
_sp_settings="$HOME/.claude/settings.json"
_sp_enabled=$(jq -r '.enabledPlugins["superpowers@claude-plugins-official"] // empty' "$_sp_settings" 2>/dev/null)
if [ -z "$_sp_enabled" ] || [ "$_sp_enabled" = "false" ] || [ "$_sp_enabled" = "null" ]; then exit 0; fi
# --- end gate ---

# Plan mode writes are not code — skip enforcement
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [[ "$FILE_PATH" == "$HOME/.claude/plans/"* ]]; then exit 0; fi

SKILL_MARKER="/tmp/superpowers-skill-invoked-${SESSION_ID}"

# Skill was invoked this session — stay silent
if [ -f "$SKILL_MARKER" ]; then exit 0; fi

# Inject the reminder (fires every edit until a skill is invoked)
cat <<'HOOK_JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "SUPERPOWERS ENFORCEMENT: You are about to write code without having invoked any superpowers skill yet. STOP. Check the trigger table in CLAUDE.md and invoke the appropriate skill NOW:\n\n- superpowers:brainstorming — new feature/creative work\n- superpowers:systematic-debugging — bug/error/unexpected behavior\n- superpowers:test-driven-development — implementing a feature or bugfix\n- superpowers:writing-plans — multi-step task\n- superpowers:verification-before-completion — before claiming done\n\nIf this is genuinely trivial (typo, single-line config change), proceed. Otherwise: invoke the skill first."
  }
}
HOOK_JSON
