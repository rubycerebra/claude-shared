---
name: opus-rule-retired
description: "The 'Opus Plans, Sonnet Enacts MANDATORY' section in TODO/CLAUDE.md was deliberately removed on 2026-05-17 — do not re-add unless explicitly re-mandated"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d13ea64b-f677-438d-95aa-757b2a1ffabd
  project: TODO
  source_file: feedback_opus_rule_retired.md
  migrated_on: 2026-05-17
---

The "🔴 Opus Plans, Sonnet Enacts — MANDATORY (NOT OPTIONAL)" section that previously lived at TODO/CLAUDE.md line 99 was **deliberately removed** on 2026-05-17 as part of closing TODO-j0w2.

**Why:** The matching enforcement hook (`opus-trigger-detect.sh`) had been archived to `~/.claude/hooks/archive/` weeks earlier and never re-wired. A verbal-only MANDATORY rule is the exact failure mode the rule-reliability playbook (TODO-4nmb) flags as "probabilistic — will fail under context pressure." The trigger word list (debug/fix/dashboard/daemon/script/cache/pipeline/automation) was also too broad — it would have fired on most prompts.

**How to apply:**
- If a future session sees a similar "MANDATORY trigger-word → auto-Plan-subagent" rule appear in any CLAUDE.md, treat it as a regression unless paired with an active hook.
- If Jim wants the protocol back, the right path is: move the script from `archive/` back to `~/.claude/hooks/`, wire into `UserPromptSubmit` in `settings.json`, then add the prose rule. Hook first, prose second — never prose-only.
- The retired hook script still exists at `~/.claude/hooks/archive/opus-trigger-detect.sh` for revival.

Related: [[feedback_persona_removed]] (same shape — system was retired but stale references kept reappearing).
