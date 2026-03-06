# CLAUDE.md Sync Audit — 2026-02-17

## Scope Loaded
- `~/.claude/CLAUDE.md`
- `~/.claude/GUARDRAILS.md`
- `~/Documents/Claude Projects/HEALTH/CLAUDE.md`
- `~/Documents/Claude Projects/WORK/CLAUDE.md`
- `~/Documents/Claude Projects/TODO/CLAUDE.md`
- `~/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-HEALTH/memory/MEMORY.md`
- `~/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-WORK/memory/MEMORY.md`
- `~/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-TODO/memory/MEMORY.md`

## What HEALTH Had That WORK/TODO Did Not
- Health-specific file map:
  - `fitness-log.md`
  - `income-log.json`
  - Apple Health / HealthFit / Streaks / Alter transcript paths
- Friday maintenance runbook section (`Friday Tasks (Maintenance Day)`) including digest and therapy archive steps.
- Explicit Friday priority-shift command note for beads (`auto-beads.py friday-shift`).

Status: kept as HEALTH-specific (intentional, not drift).

## What WORK Had That HEALTH/TODO Did Not
- WORK session-start `inbox/action-items/` processing step.
- Application-specific quick-start and reference sections:
  - `Applications: Brief First`
  - `Application Quick Reference`
- WORK-only `Daemon Troubleshooting` block.

Status: kept as WORK-specific (intentional, not drift).

## Contradictions Found (Before Fix)
1. Duplicate `Model Selection` blocks in WORK and TODO with conflicting wording.
2. Model-routing wording tied to `Opus/Task tool` while current workflow is model-agnostic in this environment.
3. TODO included `Applications: Brief First`, conflicting with TODO project boundaries.
4. Shared-context path `weekly-insights-2026-WXX.md` was stale versus current weekly output (`weekly-digest-YYYY-WNN.md`).
5. WORK memory file still referenced a separate `CLAUDE` project routing model.
6. HEALTH memory file used outdated Sonnet/Opus-only directives and stale weekly-insights path.

## Stale Rules / Path Drift
- Stale output reference fixed:
  - `weekly-insights-2026-WXX.md` -> `weekly-digest-YYYY-WNN.md`
- Retired workspace model removed from memory notes:
  - no separate `CLAUDE` workspace; use TODO + labels.

## Fixes Applied
1. Synced model-selection wording across all 3 project CLAUDE files:
   - `~/Documents/Claude Projects/HEALTH/CLAUDE.md`
   - `~/Documents/Claude Projects/WORK/CLAUDE.md`
   - `~/Documents/Claude Projects/TODO/CLAUDE.md`

2. Removed duplicate model-selection blocks (WORK/TODO) so each file now has a single canonical block.

3. Removed TODO-only contradiction:
   - Deleted `Applications: Brief First` from `~/Documents/Claude Projects/TODO/CLAUDE.md`

4. Updated stale shared-context weekly path in all project CLAUDE files:
   - now points to `~/Documents/Claude Projects/claude-shared/weekly-digest-YYYY-WNN.md`

5. Updated WORK memory routing:
   - `~/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-WORK/memory/MEMORY.md`
   - removed `CLAUDE` project routing; replaced with TODO + `claude-maintenance` label model.

6. Updated HEALTH memory model notes:
   - `~/.claude/projects/-Users-jamescherry-Documents-Claude-Projects-HEALTH/memory/MEMORY.md`
   - replaced stale Sonnet/Opus-only text with model-agnostic maintenance/validation guidance.
   - updated weekly reference to weekly digest path.

## Post-Fix State
- No duplicate model-selection sections remain in project CLAUDE files.
- No `weekly-insights-2026-WXX.md` references remain in project CLAUDE files.
- Project boundaries now match intent:
  - WORK: application-first context
  - HEALTH: health/therapy/fitness maintenance context
  - TODO: systems/tasks context without job-application runbook drift
- Memory notes now align with 3-project model and current weekly digest file naming.

