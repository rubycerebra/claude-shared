# Recovery — System 2.0 / Compounding Insights / QMD (2026-03-08)

## What was recovered

This recovery note ties together the in-flight work across `claude-shared/`, `TODO/.beads`, and shared personal context.

### QMD / document retrieval
- QMD work is already tracked in `TODO-xzpc` and `HEALTH-xc1`.
- The Reddit-triggered research request is the origin for the current QMD bead: `HEALTH-xc1`.
- QMD is confirmed live locally:
  - health endpoint: `http://localhost:8181/health`
  - MCP endpoint: `http://localhost:8181/mcp`
  - config source: `~/.claude.json`
- Intended role: default personal-document retrieval layer for journal, patterns, wins, therapy, work docs, and future compounding memory recall.

### Compounding insights / longitudinal memory
- Existing bead chain:
  - `TODO-h3uy` — compounding insights + lower-friction data ingestion
  - `TODO-h3uy.1` — daily state vector + compounding dashboard insights
- The missing capability was not just more dashboard cards, but a reusable memory layer across:
  - dashboard prioritisation
  - weekly synthesis
  - recollection in future sessions
  - conversation context / “what has been building over time?”

### PDA / neurodivergence integration
Already reflected in:
- `mental-health-insights.md`
- `patterns.md`
- `journal/2026-03-08.md`
- `wins.md`

This means the “deeper system” work is not only QMD retrieval — it is QMD + PDA-aware interpretation + compounding longitudinal evidence.

## Weekly report state

### Active weekly artifacts
- Substantive weekly digest: `weekly-digest-2026-W10.md`
- Deep analysis markdown placeholder: `weekly-deep-analysis-2026-W10.md`
- Current display artifact for dashboard linking: `weekly-deep-analysis-2026-W10.html`

### Important nuance
The W10 deep-analysis HTML exists and should be treated as the current user-facing artifact, but it is still placeholder content (`Opus unavailable` / `Requires Opus`).

So the system should:
- link to that HTML as the current-week artifact
- but mark it as **needs regeneration**, not “ready”

## Dashboard issues Claude had already started fixing
- tomorrow-plan meta prompts leaking into action items
- weekly report card preferring stale/missing paths
- Ta-Dah API unavailable / scratch retry behavior
- short-task completion matching for beads / maintenance work
- film logic over-weighting recent watchlist adds

## What this implementation pass adds
- longitudinal dashboard history at `~/.claude/cache/dashboard-history.json`
- compounding memory snapshot for future retrieval at `claude-shared/reports/compounding-memory-latest.md`
- trend-aware state vector output for day / 7d / 30d
- compounding priority candidates instead of latest-item bias
- weekly report placeholder detection

## Active references
- `TODO-xzpc`
- `HEALTH-xc1`
- `TODO-h3uy`
- `TODO-h3uy.1`
- `weekly-digest-2026-W10.md`
- `weekly-deep-analysis-2026-W10.html`
