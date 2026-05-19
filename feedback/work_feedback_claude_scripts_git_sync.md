---
name: claude-scripts syncs by git, not Syncthing
description: Mac and NUC copies of ~/.claude/scripts (C:\SyncData\claude-scripts on NUC) drift through git, not file sync. Always check divergence before running any fixer.
type: feedback
originSessionId: 28e1046d-a0b6-479a-b32e-4b8bd5947012
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_claude_scripts_git_sync.md
  migrated_on: 2026-05-17
---
Mac `~/.claude/scripts` and NUC `C:\SyncData\claude-scripts` are independent git working copies of the same repo (rubycerebra/claude-scripts). They sync **via commit/push/pull**, not Syncthing.

**Why:** On 2026-05-11, ran `ruff --fix` on NUC to clear "50 lint errors" and produced 262 changes — only to discover Mac's `origin/main` already had commit `2ddb761 fix: ruff lint cleanup (UP038, B904, E741)`. NUC's `main` had diverged at `d36b3af` with 3 unpushed commits (library_media refactor, film pick regex fix, shopping dir fix). The fixes were duplicate work; the real problem was diverged history.

A `git pull --rebase origin main` on NUC further failed because dozens of NUC-only untracked files (CODEX-*.md, autoharness-*, todoist-*, .claude/CLAUDE.md, .mcp.json) collide with the same paths that exist as *tracked* files in origin/main. The "(NUC-edit only)" CLAUDE.md note exists to prevent *new* drift but does nothing about pre-existing drift like this.

**How to apply:**
- Before running any codebase-wide fixer (ruff, prettier, codemods) on either Mac or NUC `claude-scripts`, run on both sides: `git fetch && git status -sb && git log --oneline -5`. If the branches have diverged or untracked-vs-tracked collisions exist, **stop and report** — do not auto-fix.
- The "9 quarantined sync-conflict files" prelude note is likely a symptom of this same divergence and warrants a dedicated cleanup session, not piecemeal lint fixes.
- Resolving requires human decisions: which set of 3 commits to keep, which untracked NUC files to add/discard. Not a Claude-autonomous task.

**Addendum 2026-05-12: outer vs inner repo distinction.**

The above rule applies to the **inner** `scripts/` repo (Mac `~/.claude/scripts/` ↔ NUC `C:\SyncData\claude-scripts\`). The **outer** `~/.claude/` repo (which contains `skills/`, `commands/`, `hooks/`, `memory/`, etc.) is **only a git working copy on Mac** — NUC's `~/.claude/` has no `.git` directory.

Empirically on 2026-05-12: NUC's `commands/iron-out.md` had received a fresh edit via some unknown sync, but `skills/iron-out.md` did not exist on NUC at all. Outer-repo sync to NUC is partial/unreliable.

**For files under `~/.claude/<dir>/` where `<dir>` is not `scripts/`:**
1. Edit on Mac, commit and push from Mac.
2. **Also** `scp` each changed file directly to NUC: `sshpass -p 'Trekbike21' scp <local> "James Cherry@100.73.88.14:.claude/<rel/path>"` (relative-from-home, no leading slash).
3. Verify with `findstr` over SSH using ASCII-only patterns — em-dashes and other unicode break `findstr` matching, leading to false negatives.
