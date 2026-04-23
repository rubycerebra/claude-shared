# Claude Code continue prompt (command-first)

Paste this into Claude Code when resuming:

```text
Continue the Claude-first shared-core refactor from filesystem handoff, not chat memory.

Run these commands first and read the files they show:
1. cd /Users/jamescherry/.config/superpowers/worktrees/claude-shared/claude-core-refactor
2. sed -n '1,220p' docs/refactors/2026-04-agent-friendly-core/CLAUDE-START-HERE.md
3. sed -n '1,220p' docs/refactors/2026-04-agent-friendly-core/NEXT_ACTION.md
4. sed -n '1,260p' docs/refactors/2026-04-agent-friendly-core/MIGRATION_LEDGER.yaml
5. /usr/bin/git status --short

Then use only these worktrees:
- /Users/jamescherry/.config/superpowers/worktrees/claude-shared/claude-core-refactor
- /Users/jamescherry/.config/superpowers/worktrees/HEALTH/claude-core-refactor
- /Users/jamescherry/.config/superpowers/worktrees/WORK/claude-core-refactor
- /Users/jamescherry/.config/superpowers/worktrees/TODO/claude-core-refactor

Canonical bead: TODO-isgj
Tracking beads: HEALTH-o2s1, HEALTH-74g

Then continue the next action from NEXT_ACTION.md. Do not re-plan from scratch unless the handoff files prove the approach is broken.
```
