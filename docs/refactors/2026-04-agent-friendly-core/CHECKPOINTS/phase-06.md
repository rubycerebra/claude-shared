# Phase 06 checkpoint — ancestor-PID helper + sequenced-codex self-conflict fix

## Completed
- Added `walk_ancestor_pids(pid, ppid_lookup=...)` to `claude_core.hooks`.
  - Injectable `ppid_lookup` for tests; default uses `ps -p <pid> -o ppid=`.
  - Stops on cycles, missing ppids, invalid values, max_depth.
- Wired it into `~/.claude/scripts/run-sequenced-codex.py::list_conflicting_sessions` to exclude the entire parent chain of the current process (not just pid+ppid).
- Redeployed `claude_core` via `deploy-claude-core.py` → manifest refreshed, idempotent on re-run.

## Root cause fixed
`sequenced-autopilot-session-start.sh` fires as a SessionStart hook under the active Claude CLI process. The sequencer ran `ps`, saw `claude --output-format stream-json` in its own ancestry, and flagged it as a "conflicting writer" — aborting the autopilot on every session start. Excluding only `my_pid` + `my_ppid` wasn't enough because the Claude CLI is 3-4 hops up the chain.

## Verification
- `python3 -m pytest tests/` → **37 passed in 0.35s** (33 prior + 4 new walk_ancestor_pids tests).
- Live smoke from this Ghostty session (PID 45576 is claude):
  - `walk_ancestor_pids(os.getpid())` → `{1, 45395, 45402, 45403, 45576, 95068, 95072}` (7 PIDs, includes claude).
  - `list_conflicting_sessions()` now returns `1` conflict (a separate VSCode claude session), not 2. The Ghostty claude ancestor is correctly excluded.

## API-server deprecation flood — also fixed this slice
- Replaced `datetime.utcnow().isoformat() + "Z"` (line 2272 of `~/.claude/scripts/api-server.py`) with `datetime.now(timezone.utc).strftime(...)` to preserve the `YYYY-MM-DDTHH:MM:SS.ffffffZ` format consumers expect.
- Restarted Mac (`launchctl`) + NUC (`schtasks /run \Claude\ClaudeRestartApi`).
- Verified live: `/v1/ui/app/today` → `pipeline_status.timestamp = 2026-04-23T18:20:42.729630Z`, `state: ready`. Format unchanged.

## Next recommended slice
1. Convert a registered SessionStart hook with real device branching (candidate: `hooks/icloud-prefetch.sh`) to use `dispatch_by_role`.
2. Port more of `sequenced-autopilot-session-start.sh` orchestration into `claude_core.hooks` (cooldown/lock via the Python primitives) and make the bash file a thin wrapper.
3. Version-control `~/.claude/scripts/run-sequenced-codex.py` and `api-server.py` — right now they're gitignored and change history lives only on disk.
