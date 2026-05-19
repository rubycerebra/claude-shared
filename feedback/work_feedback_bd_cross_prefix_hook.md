---
name: feedback-bd-cross-prefix-hook
description: How to write to TODO/HEALTH beads from a WORK session — beads-prefix-guard.py hook needs absolute BEADS_DIR or env-set BD_ALLOW_CROSS_PREFIX
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2cdffbe9-75b4-4e8b-9d16-3c52ed309c8f
  project: WORK
  source_file: feedback_bd_cross_prefix_hook.md
  migrated_on: 2026-05-17
---

When operating on `TODO-*` or `HEALTH-*` beads from inside the WORK session, `bd update/close/note/etc` calls are blocked by `~/.claude/hooks/beads-prefix-guard.py` with: *"Cross-prefix write blocked: command references TODO-* IDs but current project prefix is WORK."*

**Why:** The hook runs in Claude's parent env, not inside the bash command. Two bypass paths in the hook source:
1. `BD_ALLOW_CROSS_PREFIX=1` must be set in **Claude's env**, not prefixed inside the bash command — inline `BD_ALLOW_CROSS_PREFIX=1 bd ...` does NOT work.
2. The hook resolves the project prefix from `BEADS_DIR=` *in the command* using `Path(...)`. A relative path like `BEADS_DIR=.beads` resolves against WORK's cwd (the parent shell), not the post-`cd` cwd, so it still finds WORK's config.

**How to apply:** Use the **absolute** path:
```
cd "/Users/jamescherry/Documents/Claude Projects/TODO" && \
  BEADS_DIR="/Users/jamescherry/Documents/Claude Projects/TODO/.beads" \
  bd close TODO-xxxx --reason "..."
```

This makes the hook read TODO's `config.yaml` directly → `project_prefix=TODO` → no foreign IDs → passes.

**Related:** `bd close` uses `--reason` (not `--notes`).
