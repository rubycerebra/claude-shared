---
name: vexp MCP setup — stdio not HTTP
description: vexp connects to Claude Code via stdio, not HTTP. The daemon HTTP port is irrelevant.
type: feedback
originSessionId: 6e5b8832-d0e9-4d50-a729-631770962318
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_vexp_mcp_setup.md
  migrated_on: 2026-05-17
---
Claude Code connects to vexp via `vexp mcp` stdio (configured in `.mcp.json` with `"type": "stdio"`). The daemon runs separately via socket (`~/.vexp/daemon.sock`). The MCP HTTP port (7821) is NOT used by Claude Code — "MCP HTTP: not listening" in `vexp daemon-cmd status` is expected and not a problem.

**Why:** Discovered 2026-04-17 when vexp 2.0.11 showed HTTP not listening but stdio/socket was healthy.

**How to apply:** When checking vexp health, socket connectivity and index counts are the meaningful signals — not HTTP port status.
