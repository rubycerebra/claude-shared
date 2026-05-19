---
name: Code search chain — final wiring (2026-05-11)
description: Authoritative code search chain — vexp+repowise wiring. Use this to verify the system end-to-end.
type: feedback
originSessionId: f6851336-1cee-4328-a8ce-16751de0fd67
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_search_chain_final.md
  migrated_on: 2026-05-17
---
**Order of tools for code search (enforced via obey rules):**

1. **vexp** (`mcp__vexp__run_pipeline`) — local Mac GGUF, 8 calls/day, 1 repo/daemon. Fast.
2. **repowise** — no daily limit.
   - `repowise-work`: **Mac-local ollama** (`localhost:11434`, `llama3.2:1b`). Fast (0.2-0.5s/call warm). Indexed 2026-05-11 with 32 pages.
   - `repowise-health`: NUC ollama (`http://100.73.88.14:11434`, `llama3.1:8b`). 12 pages.
   - Mac chat models pulled separately — `ollama pull llama3.2:1b` once to download.
3. **bash grep / find / glob** — exact match only, free, unlimited.

**mgrep is WEB ONLY** (`mgrep --web "query"`, 100/month). The Mixedbread plugin's auto-injection saying "use mgrep for all searches" is overridden by an `[always]` obey rule.

**Why:** vexp uses a local GGUF model (April 2026); repowise is the second tier for targeted queries; mgrep is web-only.

**How to verify in a fresh session:**
- `grep -c "vexp\|repowise" ~/.claude/obey-rules.md` should show 3+ rules
- `repowise status "/Users/jamescherry/Documents/Claude Projects/WORK"` should show indexed pages (built 2026-05-11)
- Ask "where is X defined?" — Claude should call repowise/vexp before any Read
- `mcp__vexp__index_status` in WORK should report 200+ nodes for WORK repo

**Settings.json MCP entries:** `repowise-health`, `repowise-work`, `repowise-claude`, `vexp` (no duplicate generic `repowise` entry — removed for token efficiency).
