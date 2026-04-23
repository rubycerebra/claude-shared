# Next Action

## Do next
1. Add progress + verification comments to:
   - `TODO-isgj`
   - `HEALTH-o2s1`
   - `HEALTH-74g`
2. Continue from the new `claude_core.health_metrics` boundary and choose one of:
   - split hook/session-start surfaces by device role (NUC runtime vs Mac interface)
   - harden deploy path and compatibility shims for `claude_core` into `~/.claude/scripts`
   - archive duplicate backups once the canonical shared surfaces are proven stable
3. If continuing immediately, prefer the hook/session-start split next because the health parser + fallback boundary is now centralised.
4. Keep updating `MIGRATION_LEDGER.yaml`, `CLAUDE-START-HERE.md`, `TEST_MATRIX.md`, and a new checkpoint file at the end of each slice.
