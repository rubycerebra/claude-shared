#!/usr/bin/env bash
# Manual RTK rewrite: npm test → rtk npm test
# Runs before rtk-rewrite.sh to handle commands the RTK binary doesn't map.

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$CMD" ] && exit 0
[ "$CMD" != "npm test" ] && exit 0

ORIGINAL_INPUT=$(echo "$INPUT" | jq -c '.tool_input')
UPDATED_INPUT=$(echo "$ORIGINAL_INPUT" | jq --arg cmd "rtk npm test" '.command = $cmd')

jq -n \
  --argjson updated "$UPDATED_INPUT" \
  '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "allow",
      "permissionDecisionReason": "RTK manual rewrite: npm test → rtk npm test",
      "updatedInput": $updated
    }
  }'
