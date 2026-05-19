---
name: feedback-persona-removed
description: The Ori/Colleagues persona mechanism was removed weeks ago — do not try to load persona files or treat it as live
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 884f7472-0595-4fd6-9436-8cf8f7cc58e6
  project: TODO
  source_file: feedback_persona_removed.md
  migrated_on: 2026-05-17
---

Persona/Colleagues was removed weeks before 2026-05-16. Do not attempt to read or reference `.claude/persona/`, `~/Documents/Claude Projects/claude-shared/colleagues/`, or any "Ori voice" instructions. Those directories do not exist; references in CLAUDE.md / settings.json / SessionStart hooks were stripped on 2026-05-16.

**Why:** Stale persona-load hooks and CLAUDE.md sections kept injecting "MANDATORY PERSONA LOAD" into session starts, causing dead-path reads, false starts, and confusion at the top of every conversation.

**How to apply:** If a SessionStart hook or stray doc still mentions persona / Ori / colleagues / claude-shared — strip it, don't try to honour it. Voice guidance now comes from `~/.claude/CLAUDE.md` "Core stance" and project CLAUDE.md only.
