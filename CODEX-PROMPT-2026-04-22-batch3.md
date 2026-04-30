# Codex Session Prompt — 2026-04-22 (Batch 3)

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Close two already-verified pipeline beads, create the missing context-budget-policy.md, remove duplicate governance from AGENTS.md, and slim down the always-loaded Claude instruction surfaces.

**Architecture:** Jim's system has a layered instruction model — core (always loaded), overlay (per-project/session), and on-demand (loaded when requested). The goal is to make that separation real and measurable by moving reference material out of the always-loaded CLAUDE.md into dedicated docs, and removing sections in AGENTS.md that duplicate what CLAUDE.md already governs.

**Tech Stack:** Bash, Python, Markdown. No npm/build step. Verification = file size before/after + grep checks. Changes committed to `.claude` and `WORK` repos.

---

## Who You Are Working With

Jim Cherry, 39. Autistic, ADHD, anxiety. British English. Emoji anchors for visual scanning. Short sentences.

Bead tracking is mandatory — mark `in_progress` before starting, close with a quoted verification comment when done.

## Repository Layout

- `~/.claude/` — global Claude config repo (CLAUDE.md, docs/, scripts/, hooks/, commands/)
- `~/Documents/Claude Projects/WORK/` — WORK project repo (AGENTS.md, .claude/CLAUDE.md)
- `~/Documents/Claude Projects/HEALTH/` — HEALTH project (beads: HEALTH-* IDs)
- `~/Documents/Claude Projects/TODO/` — TODO project (beads: TODO-* IDs)

Bead commands require `cd` into the project that owns the bead first:
- HEALTH-* beads → `cd ~/Documents/Claude\ Projects/HEALTH && bd ...`
- TODO-* beads → `cd ~/Documents/Claude\ Projects/TODO && bd ...`
- WORK-* beads → `cd ~/Documents/Claude\ Projects/WORK && bd ...`

---

## Beads Not In This Batch (Skip These)

Two beads are **excluded** from this session:

- **HEALTH-8xs2** — "Protect the wednesday-thursday hinge" — this is a personal behavioural routine change (setting a hard screen-off time on Wednesday evenings). Not code. Cannot be automated. Leave it open.
- **TODO-ddqh** — "Claude Code TODO session startup handshake timeout" — requires interactive VS Code debugging with live log inspection. Not safe to run non-interactively. Leave it in_progress.

---

## Task 1: Close Already-Verified Beads

Both HEALTH-ou3m and HEALTH-4sl6 have full Phase A / Phase B verification comments in their notes confirming all steps passed. They just haven't been formally closed.

### Files
- No file changes — bead close commands only.

- [ ] **Step 1: Close HEALTH-ou3m**

```bash
cd ~/Documents/Claude\ Projects/HEALTH
bd close HEALTH-ou3m --reason "Phase A verified complete: 0 Syncthing conflict files, .stignore updated, 5-tuple _evaluate_diarium_freshness shipped on NUC, diarium_fresh_source field live in session-data, session-start-fast.sh 3-source hot-aware banner verified 2026-04-17."
```

Expected output: line containing `HEALTH-ou3m` and `closed`.

- [ ] **Step 2: Close HEALTH-4sl6**

```bash
cd ~/Documents/Claude\ Projects/HEALTH
bd close HEALTH-4sl6 --reason "Phase B foundations complete: ntfy-topic.txt (30B), push-notify.sh (570B), shared/pipeline_state.py (8613B), reconcile-sync-conflicts.sh (430B) all created and verified. py_compile clean, smoke test 4 scenarios pass. NTFY topic: jim-pipeline-9e85fb3bf0ab2b13."
```

Expected output: line containing `HEALTH-4sl6` and `closed`.

- [ ] **Step 3: Verify both closed**

```bash
cd ~/Documents/Claude\ Projects/HEALTH
bd show HEALTH-ou3m | grep -E "CLOSED|closed"
bd show HEALTH-4sl6 | grep -E "CLOSED|closed"
```

Expected: two lines each containing `CLOSED`.

---

## Task 2: HEALTH-u1i — Land context-budget-policy.md + Remove AGENTS.md Duplicates

The policy file was written on branch `p1-claude-token-optimisation` but never merged to main. It exists at:
`/Users/jamescherry/.config/superpowers/worktrees/.claude/p1-claude-token-optimisation/docs/context-budget-policy.md`

The target location on main is `~/.claude/docs/context-budget-policy.md`. Copy it across, then remove duplicate governance sections from `WORK/AGENTS.md`.

### Files
- Create: `~/.claude/docs/context-budget-policy.md` (copy from worktree)
- Modify: `~/Documents/Claude Projects/WORK/AGENTS.md` (remove duplicate sections)

- [ ] **Step 1: Mark HEALTH-u1i in_progress**

```bash
cd ~/Documents/Claude\ Projects/WORK
bd update HEALTH-u1i --status=in_progress
```

- [ ] **Step 2: Verify policy file is missing from main**

```bash
ls -la ~/.claude/docs/context-budget-policy.md 2>&1
```

Expected: `No such file or directory`. If it already exists (already landed), skip Step 3.

- [ ] **Step 3: Copy policy file from worktree to main**

```bash
cp /Users/jamescherry/.config/superpowers/worktrees/.claude/p1-claude-token-optimisation/docs/context-budget-policy.md \
   ~/.claude/docs/context-budget-policy.md
```

- [ ] **Step 4: Verify the file landed**

```bash
wc -l ~/.claude/docs/context-budget-policy.md
```

Expected: > 80 lines.

- [ ] **Step 5: Read WORK/AGENTS.md current line count**

```bash
wc -l ~/Documents/Claude\ Projects/WORK/AGENTS.md
```

Record the number. Target after edit: ≤ 80 lines.

- [ ] **Step 6: Remove duplicate governance sections from WORK/AGENTS.md**

The following sections must be removed from `~/Documents/Claude Projects/WORK/AGENTS.md`. Do NOT remove: Quality Gate, Refactor Completion Confidence Gate, Session Start (Codex), Personal Priority Stack (Codex), Neuro Visual Style (Codex), RTK Token Savings (Codex).

Sections to delete (exact headings):
- `## Wrap-Up Trigger (Codex)` and its content (lines with `wrap up`, `close session`, session-wrap-up.sh, personal snapshot)
- `## Task Tracking` and its content (the `bd update`, `bd close`, `bd sync` block)
- `## Beads Workflow Enforcement (Mandatory)` and all its sub-content (Before/During/After/Closing a bead)
- `## Akiflow Completion Guardrail (Codex)` and its content

Use the Edit tool to make these removals. Read the file first to get exact line content before editing.

- [ ] **Step 7: Verify AGENTS.md line count reduced**

```bash
wc -l ~/Documents/Claude\ Projects/WORK/AGENTS.md
```

Expected: ≤ 85 lines (from ~110). If still > 85, re-read the file and identify what wasn't removed.

- [ ] **Step 8: Commit policy file to .claude repo**

```bash
cd ~/.claude
git add docs/context-budget-policy.md
git commit -m "chore: add context-budget-policy.md per HEALTH-u1i"
```

- [ ] **Step 9: Commit AGENTS.md trim to WORK repo**

```bash
cd ~/Documents/Claude\ Projects/WORK
git add AGENTS.md
git commit -m "chore: remove duplicate governance from AGENTS.md per context-budget-policy"
```

- [ ] **Step 10: Push both repos**

```bash
cd ~/.claude && git push
cd ~/Documents/Claude\ Projects/WORK && git push
```

- [ ] **Step 11: Close HEALTH-u1i with verification comment**

```bash
cd ~/Documents/Claude\ Projects/WORK
bd comment HEALTH-u1i "context-budget-policy.md created at ~/.claude/docs/context-budget-policy.md ($(wc -l < ~/.claude/docs/context-budget-policy.md) lines). AGENTS.md reduced from original to $(wc -l < ~/Documents/Claude\ Projects/WORK/AGENTS.md) lines. Duplicate sections removed: Wrap-Up Trigger, Task Tracking, Beads Workflow Enforcement, Akiflow Completion Guardrail. Both repos committed and pushed."
bd close HEALTH-u1i --reason "Policy doc created and AGENTS.md duplicate governance removed."
```

---

## Task 3: HEALTH-k8f — Slim Down ~/.claude/CLAUDE.md Startup Surface

The always-loaded `~/.claude/CLAUDE.md` contains several sections that are reference material, not runtime rules. Moving them out (or replacing with a pointer to the detailed doc) reduces startup token cost without changing behaviour.

**Sections to slim or replace (in order of safety):**

1. `## Architecture Quick Reference` — keep the 6-row table (genuinely useful at session start), but remove the full `## NUC Service Management` command block directly below it (those commands already live in `~/.claude/docs/architecture.md` and can be looked up)
2. `## Shared Context Paths` — remove the bullet list, replace with one line: `See ~/.claude/docs/architecture.md for shared paths.`
3. `## Code Search Priority` — remove entirely from `~/.claude/CLAUDE.md`. It belongs only in WORK/.claude/CLAUDE.md (where it already lives). HEALTH and TODO projects have their own search rules.

**Do NOT touch:**
- `## Agent` section (identity + gears table) — core
- `## Execution Rules` — core
- `## Visual Design Principles` — core (affects every session with UI)
- `## 🔴 Opus Plans, Sonnet Enacts` — core (routing protocol)
- `## vexp` section — borderline, but leave it: it contains MANDATORY language that breaks sessions if missing
- `@RTK.md` — leave the include

### Files
- Modify: `~/.claude/CLAUDE.md`

- [ ] **Step 1: Mark HEALTH-k8f in_progress**

```bash
cd ~/Documents/Claude\ Projects/WORK
bd update HEALTH-k8f --status=in_progress
```

- [ ] **Step 2: Record baseline line count**

```bash
wc -l ~/.claude/CLAUDE.md
```

Record output. Target: reduce by 15–25 lines.

- [ ] **Step 3: Read ~/.claude/CLAUDE.md to locate exact content**

Read the full file before making any edit. Locate:
- The `## NUC Service Management — ONLY use Scheduled Tasks` heading and its content (the bash block + NEVER note + NUC IPs line)
- The `## Shared Context Paths (all projects)` heading and its 5 bullet lines
- The `## Code Search Priority` heading and its 4 lines

- [ ] **Step 4: Remove NUC Service Management section**

Using the Edit tool, delete the entire `## NUC Service Management — ONLY use Scheduled Tasks` section: from the heading through the **NEVER** line and `NUC IPs: Tailscale ...` line.

Add a one-line replacement pointer directly after the Architecture Quick Reference table:

```
NUC restart commands: see `~/.claude/docs/architecture.md` (schtasks only — never nssm).
```

- [ ] **Step 5: Replace Shared Context Paths section**

Delete the `## Shared Context Paths (all projects)` heading and its 5 bullet lines. Replace with:

```markdown
Shared paths (journal, patterns, wins): `~/Documents/Claude Projects/claude-shared/`. Diarium exports: `~/My Drive (james.cherry01@gmail.com)/Diarium/Export`.
```

- [ ] **Step 6: Remove Code Search Priority section**

Delete the `## Code Search Priority` heading and its content (the 3-item numbered list + "Never Grep/Glob/Read" line). No replacement needed — this is project-specific and already in WORK/.claude/CLAUDE.md.

- [ ] **Step 7: Verify line count reduced**

```bash
wc -l ~/.claude/CLAUDE.md
```

Expected: at least 15 fewer lines than baseline. If reduction is < 10, re-read the file to check edits landed.

- [ ] **Step 8: Sanity-check key sections still present**

```bash
grep -n "Opus Plans" ~/.claude/CLAUDE.md
grep -n "gears table\|Gear\|Mirror" ~/.claude/CLAUDE.md
grep -n "Execution Rules" ~/.claude/CLAUDE.md
grep -n "Visual Design" ~/.claude/CLAUDE.md
```

Expected: all four return at least one matching line each. If any return empty, the wrong section was deleted — run `git diff` and revert that specific edit.

- [ ] **Step 9: Run git diff to review changes**

```bash
cd ~/.claude && git diff CLAUDE.md
```

Read the full diff. Confirm: only NUC block, Shared Paths, and Code Search Priority were removed. Nothing else changed.

- [ ] **Step 10: Commit and push**

```bash
cd ~/.claude
git add CLAUDE.md
git commit -m "chore: slim CLAUDE.md startup surface per HEALTH-k8f — remove NUC block, shared paths, code search priority"
git push
```

- [ ] **Step 11: Close HEALTH-k8f with verification comment**

```bash
cd ~/Documents/Claude\ Projects/WORK
bd comment HEALTH-k8f "~/.claude/CLAUDE.md reduced from [baseline] to $(wc -l < ~/.claude/CLAUDE.md) lines. Removed: NUC Service Management block, Shared Context Paths list, Code Search Priority. All core sections (Agent, Execution Rules, Visual Design, Opus Plans, vexp) confirmed present via grep. Pushed to origin."
bd close HEALTH-k8f --reason "Startup surface slimmed per context-budget-policy. NUC block, shared paths, code search priority moved to on-demand layer."
```

---

## Final Checks

- [ ] Run `wc -l ~/.claude/CLAUDE.md ~/.claude/RTK.md ~/Documents/Claude\ Projects/WORK/AGENTS.md ~/Documents/Claude\ Projects/WORK/.claude/CLAUDE.md` and confirm all are within budget targets in the policy doc.
- [ ] Run `cd ~/Documents/Claude\ Projects/HEALTH && bd list` — confirm HEALTH-ou3m and HEALTH-4sl6 show as closed.
- [ ] Run `cd ~/Documents/Claude\ Projects/WORK && bd list --status all | grep -E "k8f|u1i"` — confirm both show as closed.
- [ ] Run `git log --oneline -5` in both `~/.claude` and `WORK` repos to confirm commits landed.

---

## Summary of What Is NOT Done (for Jim's next session)

| Bead | Why skipped | Next step |
|------|------------|-----------|
| HEALTH-8xs2 | Behavioural routine, not code | Jim sets a Wednesday screen-off reminder manually |
| TODO-ddqh | Needs interactive VS Code log debugging | Open a TODO project session and trace the MCP hang |
