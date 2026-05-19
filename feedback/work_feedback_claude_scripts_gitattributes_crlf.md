---
name: claude-scripts-gitattributes-crlf
description: "claude-scripts repo has a .gitattributes eol=crlf rule that causes perpetual M status on 7 .ps1/.bat files on both Mac and NUC; rebase machinery can't survive it"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 4b1e000c-5c73-488d-bf7f-c1f9fb9d6d64
  project: WORK
  source_file: feedback_claude_scripts_gitattributes_crlf.md
  migrated_on: 2026-05-17
---

In claude-scripts, `.gitattributes` declares `*.ps1 text eol=crlf` and `*.bat text eol=crlf`. Origin blobs are stored LF; smudge filter writes CRLF on checkout; clean filter fails to normalize CRLF→LF for status comparison, so 7 specific files perpetually show as `M`:

- `nuc-task-wrappers/run-GmailToReader.ps1`
- `nuc-task-wrappers/run-InvoiceTaxEmail.ps1`
- `nuc-task-wrappers/run-LetterboxdSync.ps1`
- `nuc-task-wrappers/run-SyncRecurringBeads.ps1`
- `nuc-task-wrappers/run-TodoistBeadBacksync.ps1`
- `qmd-daily-update.bat`
- `readwise-cleanup.bat`

**Why:** These M files block every rebase/pull workflow. `git checkout HEAD -- <files>`, `git stash`, `core.autocrlf=true/false/input`, and `git update-index --assume-unchanged` all fail to fix it — assume-unchanged works for status but rebase's tree-merge still hits the dirty WT and aborts.

**How to apply:** When working in `~/.claude/scripts` and these 7 files appear M (likely on every fresh checkout):
1. Don't waste time chasing line-endings normalization. The clean filter is broken in this repo's configuration.
2. To pull: `git checkout -- <7 files>` + `git update-index --assume-unchanged <7 files>` + `git pull --rebase`. Works for pull-only.
3. To rebase locally without push interference: use destructive reset + cherry-pick instead — `git reset --hard origin/main && git cherry-pick <real commits>`. This bypasses the entire smudge-filter rabbit hole.
4. Don't `git commit` these files unless you mean to permanently store their current CRLF bytes in blob — doesn't solve the underlying mismatch.

No active bead tracks this CRLF issue (an earlier reference to TODO-ymqp was stale — bead doesn't exist). The distinct .venv case-conflict Syncthing breakage is tracked in TODO-uu0d (created 2026-05-16). See [[claude-scripts-git-sync]] for the broader Mac/NUC sync model.
