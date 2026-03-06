# Command Audit — 17 February 2026

## Scope
This audit answers: what still works in Codex if Code Claude chat tokens run out.

Important distinction:
- **Code Claude chat tokens**: limit chat sessions.
- **API/provider keys** (`anthropic-api-key`, optional `openai-api-key`): control AI generation quality in scripts.

Most local commands still work when chat tokens are exhausted.

## Quick status
- ✅ `bd` task tracking works.
- ✅ Dashboard generation and updates work.
- ✅ Quick Actions API server is running on `127.0.0.1:8765`.
- ✅ Loop/todo completion scripts work.
- ⚠️ AI-heavy scripts degrade to heuristics/fallback if provider key is missing.

## Verified working now (provider-agnostic/local)
1. `bd` CLI (`/Users/jamescherry/.local/bin/bd`).
2. `~/Documents/Claude Projects/claude-shared/generate-dashboard.py`.
3. `~/Documents/Claude Projects/claude-shared/trigger-dashboard.sh --force --no-open`.
4. `~/.claude/scripts/close-loop.py "<loop text>"`.
5. `~/.claude/scripts/complete-todo.py "<todo text>"`.
6. `~/.claude/scripts/check-loops.py`.
7. API health endpoints:
   - `GET /health` -> `{"status":"ok"}`
   - `GET /v1/health` -> `{"status":"ok", ...}`

## Works, but launch method matters
1. `~/.claude/scripts/api-server.py`
   - Use `~/.claude/scripts/start-api-server.sh` (uses daemon venv Python).
   - Running with plain `python3 ~/.claude/scripts/api-server.py` may fail if `fastapi` is not installed in system Python.

## AI-dependent (fallback exists)
1. `~/.claude/daemon/data_collector.py`
   - Runs without provider key.
   - AI insight quality drops to heuristic fallback.
2. `~/.claude/scripts/write-ai-insights.py`
   - Still writes payloads and keeps date-scoped storage.
   - AI semantic consolidation/completion matching falls back to heuristics if AI unavailable.
3. `~/.claude/scripts/friday-weekly-review.py`
   - Attempts Anthropic generation.
   - Has fallback paths and still produces structural output.
4. `~/.claude/scripts/generate-therapy-brief.py`
   - Falls back to deterministic brief if AI unavailable.

## Deprecated command
1. `~/.claude/scripts/feedback-api.py`
   - Deprecated shim only.
   - Unified server is `~/.claude/scripts/api-server.py`.

## Open loops reliability changes applied
1. `~/.claude/daemon/data_collector.py`
   - Open loops now detect from:
     - yesterday + today journal carry-forward/reminder markers
     - today `diarium.updates`
     - today `diarium.remember_tomorrow`
2. `~/Documents/Claude Projects/claude-shared/trigger-dashboard.sh`
   - Now recomputes `open_loops` after refreshing diary data.
   - Prevents loops disappearing between full daemon cycles.

## Current live result
- Cache now contains one open loop from today’s update:
  - `I should explore that before accepting anything`
- Dashboard now shows that loop in:
  - Open Loops card
  - Quick Actions loop dropdown

## Practical guidance
1. If chat tokens are exhausted, you can still run your local operational commands and keep the system moving.
2. If AI text quality drops, check provider key availability (`~/.claude/anthropic-api-key` or routed OpenAI config).
3. Start/restart API via `~/.claude/scripts/start-api-server.sh` rather than raw `python3`.
