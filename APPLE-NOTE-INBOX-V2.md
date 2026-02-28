# Apple Note Inbox v2

Use a single Apple Note named `💡 IDEAS FOR CLAUDE` as capture inbox, then run triage to route items into project inboxes.

## Note format

Recommended styled template:

```text
💡 IDEAS FOR CLAUDE

[WORK] 💼
[WORK] Follow up Vertigo (WORK-chn)

[HEALTH] 🧠
[HEALTH] Mindfulness target check-in

[TODO] ⚙️
[TODO] Tunnel reliability task (TODO-0mf)
```

Section header lines (`[WORK] 💼`, `[HEALTH] 🧠`, `[TODO] ⚙️`) are ignored by triage.

## Commands

Print template:

```bash
~/.claude/scripts/sync-apple-note-inbox.sh --print-template
```

Create note template if missing:

```bash
~/.claude/scripts/sync-apple-note-inbox.sh --create-note
```

Dry-run triage (no writes):

```bash
~/.claude/scripts/sync-apple-note-inbox.sh --dry-run
```

Run triage (routes items, updates bead status when bead ID present, archives processed lines, clears processed lines from note):

```bash
~/.claude/scripts/sync-apple-note-inbox.sh
```

If your note lives in a specific folder:

```bash
APPLE_NOTE_INBOX_FOLDER="Claude" ~/.claude/scripts/sync-apple-note-inbox.sh
```

## Output

- Project inbox files: `HEALTH/inbox`, `WORK/inbox`, `TODO/inbox`
- Archive: `claude-shared/archive/apple-note-inbox/YYYY-Www.md`
- Dedup state: `~/.claude/cache/apple-note-inbox-state.json`
