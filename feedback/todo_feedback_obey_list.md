---
name: obey-list as health check
description: Run /obey-list at the start of any session where obey-rules.md is being edited, to catch unwired [tool:X] rules before they cause silent failures
type: feedback
originSessionId: d5bad4a1-6652-4994-a010-bda7bde1ec55
metadata:
  node_type: memory
  type: feedback
  project: TODO
  source_file: feedback_obey_list.md
  migrated_on: 2026-05-17
---
Run `/obey-list` at the start of any session where `~/.claude/obey-rules.md` is being edited or new rules are added.

**Why:** Tool-scoped rules (`[tool:X]`) require a matching settings.json entry to fire in VSCode SDK context. Without one they're silently ignored. `/obey-list` flags unwired rules with ⚠️ and shows ✓ for correctly wired ones.

**How to apply:** Before finishing any obey-rules session, run `/obey-list` and confirm no ⚠️ warnings. If any appear, use `/obey-add` (not direct file edit) to re-add the rule — it auto-wires settings.json.
