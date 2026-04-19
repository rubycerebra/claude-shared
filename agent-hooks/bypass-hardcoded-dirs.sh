#!/bin/bash
# Unconditional auto-approve — workaround for Claude Code v2.1.78+ bug (anthropics/claude-code#39523).
# The VSCode extension hardcodes .claude/.git/.vscode/.idea as protected dirs that override
# all bypass mechanisms. This hook fires unconditionally to:
# 1. Pre-approve protected-dir writes (Branch 1 workaround)
# 2. Prevent session-mode downgrade cascade from bypass→edit-auto (Branch 2 workaround)
echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"bypass: unconditional workaround for #39523"}}'
exit 0
