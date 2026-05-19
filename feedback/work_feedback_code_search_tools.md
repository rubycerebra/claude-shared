---
name: Code search tool priority — WORK and TODO projects
description: repowise-work + vexp (local GGUF) are the current code search tools for WORK and TODO sessions
type: feedback
originSessionId: 19f5dec6-bff6-4e16-a1cd-0cd3b3c4b003
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_code_search_tools.md
  migrated_on: 2026-05-17
---
Code search chain for WORK/TODO sessions:

1. **repowise-work MCP** (`mcp__repowise-work__*`) — code questions, symbol lookup, architectural queries
2. **vexp MCP** (`mcp__vexp__run_pipeline`) — semantic search across all repos (health, work, claude-scripts, daemon). Local GGUF model, no quota.
3. **bash grep** — exact string/symbol matches, free and unlimited
4. **mgrep --web** — web search only, 100/month quota

**Why:** vexp runs a local GGUF model (vexp-devmind-v1-Q4_K_M.gguf) with all 5 repos indexed — no free-tier limit applies. repowise-work is configured as MCP in settings.json.

**How to apply:** In WORK sessions use repowise-work for targeted code questions, vexp run_pipeline for broader semantic exploration. Never use mgrep for local file search.
