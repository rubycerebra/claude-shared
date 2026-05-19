---
name: feedback-save-all-channels
description: "When user asks to save/remember anything, cover ALL persistence channels by default — memory file + MEMORY.md index + obey rule (if behavioural) + vexp observation. Don't pick one."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd40a4ed-00f6-43ca-9e2a-eca413848829
  project: TODO
  source_file: feedback_save_all_channels.md
  migrated_on: 2026-05-17
---

When Jim says "save this", "remember this", "add a rule", "make a memory", etc. — cover **all** applicable persistence channels in the same turn, without asking which one. The defaults:

1. **Memory file** — write `feedback_*.md` / `project_*.md` / `user_*.md` / `reference_*.md` under `~/.claude/projects/<project>/memory/` with the standard frontmatter (`name`, `description`, `metadata.type`).
2. **MEMORY.md index** — add a one-line pointer in that project's `MEMORY.md` so the file is loaded into future session context.
3. **Obey rule** — if it's a behavioural/structural rule (something Claude must do/avoid at tool-call time), append to `~/.claude/obey-rules.md` via the `/obey` skill with the correct `[always]` or `[tool:X]` scope, and wire the settings.json hook entry if needed.
4. **Vexp observation** — call `mcp__vexp__save_observation` (type=insight/decision/error) AND append to `~/.claude/projects/-Users-jamescherry/memory/vexp_observations.md` as backup.

**Why:** On 2026-05-17, Jim flagged that he'd had to repeat "save it as a rule, memory, observation" three times in one session. He wants a single "save" instruction to fan out automatically across every channel that applies.

**How to apply:** When you detect a save/remember request, run the relevant writes in parallel in one turn. Only skip a channel if it's clearly inapplicable (e.g. a pure user-biography fact doesn't need an obey rule, a transient pin doesn't need vexp), and briefly say which channels you wrote and which you skipped + why. Never ask Jim to pick — pick yourself and tell him.

Related: [[feedback-goal-char-limit]] is an example of doing this right (memory + MEMORY.md + obey + vexp all in one shot).
