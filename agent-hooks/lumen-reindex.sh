#!/bin/bash
# lumen-reindex.sh — Re-index current project at session start (background, silent)

LUMEN_BIN="$HOME/.local/bin/lumen"
[[ -x "$LUMEN_BIN" ]] || exit 0

export OLLAMA_HOST="http://100.73.88.14:11434"
export LUMEN_EMBED_MODEL="nomic-embed-text"

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
[[ -d "$PROJECT_DIR" ]] || exit 0

# Fail silently if NUC is unreachable (away from home without Tailscale)
if ! curl -sf --connect-timeout 2 "$OLLAMA_HOST/api/tags" > /dev/null 2>&1; then
    exit 0
fi

# Incremental re-index in background — only embeds changed files
"$LUMEN_BIN" index "$PROJECT_DIR" > /dev/null 2>&1 &

exit 0
