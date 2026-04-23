# Next Action

## Do next
1. Convert one **registered** SessionStart hook with device branching to use `claude_core.hooks.dispatch_by_role`. Recommended: `~/.claude/hooks/lumen-reindex.sh` (small surface, real device branching present).
2. Then harden `scripts/deploy-claude-core.py` so `claude_core` lands in `~/.claude/scripts` via an idempotent copy + manifest verification, and add a post-deploy test that imports from the deployed path.
3. Begin wiring `CooldownGate` / `LockFile` into `sequenced-autopilot-session-start.sh` once the deploy path is hardened — bash will `python3 -m claude_core.hooks.<name>` instead of reimplementing.
4. Update `MIGRATION_LEDGER.yaml`, `CLAUDE-START-HERE.md`, `TEST_MATRIX.md`, and add a new `CHECKPOINTS/phase-05.md` at the end of the slice.

## Bead updates needed before next slice
- `TODO-isgj` — note phase-04 (hook primitives + surface inventory) complete; point at phase-05 (deploy hardening + first registered-hook conversion).
- `HEALTH-o2s1`, `HEALTH-74g` — mirror status.
