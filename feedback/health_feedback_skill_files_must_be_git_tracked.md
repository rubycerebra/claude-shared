---
name: skill-files-must-be-git-tracked
description: Skills in ~/.claude/skills/ only appear in Claude Code sessions if they are git-tracked in the ~/.claude repo
metadata:
  type: feedback
  project: HEALTH
  source_file: feedback_skill_files_must_be_git_tracked.md
  migrated_on: 2026-05-17
---

Skills in `~/.claude/skills/` are NOT auto-discovered from the filesystem alone. The Claude Code VS Code extension uses the git index in `~/.claude` as the canonical source for skill discovery.

**Why:** Untracked files are invisible to the loader even with valid frontmatter and correct filenames.

**How to apply:** After creating or renaming any skill file in `~/.claude/skills/`, always:
1. `git -C ~/.claude add skills/<filename>.md`
2. `git -C ~/.claude commit -m "..."`
3. `git -C ~/.claude push`
4. Reload VS Code window (`Cmd+Shift+P` → Developer: Reload Window)

Confirmed root cause 2026-05-13 after extended debugging session.
