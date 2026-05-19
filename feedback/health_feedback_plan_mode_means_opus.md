---
name: plan mode means opus
description: When Jim enters plan mode (EnterPlanMode or says "plan mode"), use Opus to plan and Sonnet to implement
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_plan_mode_means_opus.md
  migrated_on: 2026-05-17
---

When Jim says "plan mode", "set plan mode", "enter plan mode", or the EnterPlanMode tool is invoked — this always activates the Opus Plans, Sonnet Enacts protocol.

**Why:** Jim clarified this explicitly. Plan mode = Opus plans, Sonnet implements. No exceptions.

**How to apply:** Treat EnterPlanMode and any "plan mode" phrasing as a direct trigger for spawning `subagent_type="Plan"`, `model="opus"` before writing any code.
