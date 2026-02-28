# Standalone Personal Feedback App Roadmap (Plan Only) - 2026-02-17

## Status

- This is a planning artifact.
- No standalone app runtime was implemented in this pass.
- NUC transition is explicitly deferred.

## Product intent

Build a standalone GUI that centralizes diary inputs, AI guidance, interventions, and bead actions, with persistent memory that improves as more data arrives.

## MVP scope (Daily Core)

Ship these first screens only:

1. Today
- morning and evening diary fields
- updates stream
- ta-dah/wins
- current guidance

2. Guidance
- AI tips by type (pattern/win/signal/connection/todo)
- daily + tomorrow guidance blocks
- source transparency (what data was used)

3. Actions
- complete open loops/todos safely
- show what was auto-detected vs manually confirmed

4. Beads
- list/filter TODO beads by labels (context/location/purpose/cadence)
- focus filter for `claude-maintenance`

5. Intervention score
- daily `anxiety_reduction_score` (0-10, net relief)
- simple trend view

## Technical direction

- Desktop shell: Tauri (macOS-first UI).
- Backend service: Python API layer over current daemon/cache/scripts.
- Data strategy: read-mostly first, safe writes only.

## Read model mapping (reuse existing data)

- `~/.claude/cache/session-data.json` -> primary read model.
- `~/.claude/daemon/data_collector.py` -> orchestration/freshness source.
- `~/.claude/scripts/write-ai-insights.py` -> ai insights persistence.
- Beads DBs in `HEALTH/WORK/TODO/.beads/` -> task state.

## Safe write policy (phase 1)

Allowed writes:

1. Mark loop complete (existing script path).
2. Mark todo complete (existing script path).
3. Save intervention rating (`anxiety_reduction_score`).
4. Trigger cache refresh (existing daemon-compatible action).

Not allowed in phase 1:

- bulk deletes
- cross-project refactors
- direct edits to historical archives

## API contract (planned)

Auth model:

- bearer token on all endpoints
- LAN-only exposure by default

Endpoints:

1. `GET /v1/today`
- returns current dashboard read model (morning/evening/ai/guidance/open-loops/beads summary)

2. `GET /v1/diary`
- returns latest diary fields including `updates`

3. `GET /v1/beads?project=TODO&label=claude-maintenance`
- returns filtered bead list and metadata

4. `POST /v1/actions/complete`
- body: `{ "type": "loop|todo", "text": "..." }`
- behavior: uses existing completion scripts; returns action result

5. `POST /v1/interventions/rating`
- body: `{ "date": "YYYY-MM-DD", "anxiety_reduction_score": 0-10, "note": "optional" }`
- behavior: persists in `ai_insights.by_date[date]`

6. `POST /v1/refresh`
- body: `{ "scope": "cache|dashboard|all" }`
- behavior: triggers safe refresh path only

## Milestones

M1. API skeleton + auth + read endpoints.
M2. macOS Tauri shell with Today and Guidance screens.
M3. Safe write endpoints wired to current scripts.
M4. Intervention score capture + weekly loop surfacing.
M5. Beads panel with label-driven filtering.
M6. Hardening, logging, and packaging.

## Risks and controls

Risk: stale data mismatches.
Control: include source timestamps/freshness flags in each response.

Risk: accidental destructive writes.
Control: strict allowlist of write actions + input validation.

Risk: AI provider instability.
Control: keep AI-first/heuristic fallback behavior at backend layer.

## Deferred items

- NUC runtime transition and Windows-service rollout are deferred.
- Remote NUC API hosting can be revisited in a separate implementation phase.

## Next decision gates

1. Approve API-first implementation start.
2. Choose first UI slice (Today-first recommended).
3. Approve whether intervention note text is stored alongside score in v1.
