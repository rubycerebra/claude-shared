---
name: beads-project-scoped-db
description: bd CLI is project-scoped — must cd into each project directory (HEALTH, TODO, WORK) to see that project's beads. Running bd from WORK only sees WORK's empty DB.
type: feedback
originSessionId: 1a870645-c8d9-463a-b51c-913e4622850b
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_beads_project_scoped.md
  migrated_on: 2026-05-17
---
bd list/search/show only sees beads in the current directory's .beads/ database. Each project (HEALTH, TODO, WORK) has its own isolated beads DB.

**Why:** Wasted an entire session investigating "missing" beads because bd was running from WORK (which has no issues, only memory entries). All HEALTH and TODO beads appeared nonexistent.

**How to apply:** When checking beads across projects, always `cd` into each project directory first:
- `cd ~/Documents/Claude\ Projects/HEALTH && bd list`
- `cd ~/Documents/Claude\ Projects/TODO/.helpers && bd list`
- `cd ~/Documents/Claude\ Projects/WORK && bd list`

Never trust `bd list` results from a single directory as representing all beads.
