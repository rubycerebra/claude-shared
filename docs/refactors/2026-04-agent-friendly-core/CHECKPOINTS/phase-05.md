# Phase 05 checkpoint — deploy hardening

## Completed
- Rewrote `claude_core.runtime_deploy.deploy_shared_core` with:
  - per-file SHA-256 checksums recorded in the manifest (`files[]`)
  - idempotent copy — unchanged files keep their mtime; only drift/new files copied
  - stale-file sweep in target when source files are removed
  - `changed[]` in the plan reporting what was actually touched
- Added `verify_deployment(runtime_root)` and `DeployVerificationError` — re-hashes the deployed tree, raises on missing/drifted files.
- Added `--verify` flag to `scripts/deploy-claude-core.py`.
- Added 4 new deploy tests (drift, idempotency, manifest contents, verify pass/fail). Existing dry-run test updated to match new plan shape.

## Verification
- `python3 -m pytest tests/` → **33 passed in 0.35s** (29 prior + 4 new).
- Real deploy run:
  - `python3 scripts/deploy-claude-core.py` → 12 files deployed to `~/.claude/scripts/claude_core`.
  - `python3 scripts/deploy-claude-core.py` (second run) → `changed: []` (idempotent).
  - `python3 scripts/deploy-claude-core.py --verify` → `{"ok": true, "verified_files": 12}`.
  - Import smoke: `from claude_core.hooks import ...` resolves from `~/.claude/scripts` path; role detection returns `MAC_INTERFACE`.

## Next recommended slice
1. Convert a registered SessionStart hook that actually branches on device. Candidates:
   - `hooks/icloud-prefetch.sh` — macOS-only, currently no guard; wrap with `dispatch_by_role` so it's a no-op on NUC.
   - `hooks/wsl-guard.sh` — refusal guard; narrow surface for a proof conversion.
2. Wire `CooldownGate` / `LockFile` from `claude_core.hooks` into `sequenced-autopilot-session-start.sh` once a CLI entry is exposed (e.g. `python3 -m claude_core.hooks cooldown-gate --state=... --seconds=...`).
3. Audit the remaining duplicate helpers Codex hasn't touched (`dashboard_pipeline.py` is still a 220-byte placeholder) and decide whether they warrant extraction.
