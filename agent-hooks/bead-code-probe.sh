#!/bin/bash
# Session-start hook: run code probes against open beads.
# Auto-closes verified-done beads and surfaces uncertain ones.
set -euo pipefail

PYTHON_BIN="$HOME/.claude/daemon/venv/bin/python3"
PROBE_SCRIPT="$HOME/.claude/scripts/bead-code-probe.py"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
fi

if [[ -z "${PYTHON_BIN:-}" || ! -f "$PROBE_SCRIPT" ]]; then
    exit 0
fi

"$PYTHON_BIN" "$PROBE_SCRIPT" --quiet || true
