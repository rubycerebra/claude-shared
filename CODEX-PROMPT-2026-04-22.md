# Codex Session Prompt — 2026-04-22

## Working defaults

Jim Cherry, 39. British English. Keep replies short, grounded, and visually scannable.

Use the session brief and session-data cache first. Treat deeper docs, reports, and governance files as on-demand context rather than startup payload.

## Runtime map

- Cache first: `~/.claude/cache/session-data.json` and `~/.claude/cache/session-brief-WORK.md`
- Tracking: `bd` in `HEALTH`, `WORK`, `TODO`
- Shared docs: `~/Documents/Claude Projects/claude-shared/`
- Policy refs: `~/.claude/docs/context-budget-policy.md`, `~/.claude/docs/token-routing-policy.md`

## Startup rules

- Finish or park current work before starting unrelated work
- Prefer `/compact` before long threads get expensive
- Prefer `/clear` or a fresh session when switching workstreams
- If blocked, create/update a bead and move on

---

## Startup task overlay

### TASK 1 — protect the wednesday-thursday hinge — screen-off and commit to thursday rest
**Bead:** HEALTH-8xs2 | **Project:** HEALTH | **Priority:** P1 | **Type:** task 

Late wednesday nights consistently produce thursday HRV crashes (46ms → 29ms), relationship friction, and emotional collapse — the month's single most actionable finding. The fix has two parts: a hard screen-off time wednesday evening, and treating thursday yoga/rest as infrastructure rather than optional. Both sides of the hinge need protecting.

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-8xs2 --reason="Completed in Codex session"`

---

### TASK 2 — raise job-search avoidance in therapy now while freelance cover exists
**Bead:** HEALTH-uj9y | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

Three consecutive weeks at zero applications is fine while chris milton freelance is active, but the avoidance is dormant rather than resolved. Raising cold-call anxiety and application resistance in therapy now — while there's no financial pressure — is lower cost than addressing it urgently later.

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-uj9y --reason="Completed in Codex session"`

---

### TASK 3 — name uncloseable loops as a distinct category in therapy
**Bead:** HEALTH-w4jc | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

The £160 scam loop destabilised more than its value warranted because completion wasn't available — standard productivity tools don't help when there's no closing action. Bringing this to therapy as its own category (acceptance, deliberate parking, ritual close) could unlock a different set of responses.

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-w4jc --reason="Completed in Codex session"`

---

### TASK 4 — try rest-first then reframe-as-choice when facing a stalled demanding task
**Bead:** HEALTH-yozi | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

Both the chris email and the film premiere succeeded via the same sequence: rest first, then reframe as 'I'm choosing this' rather than 'I have to'. Pressure consistently extended the stall. Worth trying this deliberately next time a task sits untouched for 24+ hours.

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-yozi --reason="Completed in Codex session"`

---

### TASK 5 — build a specific stop condition for when the hyperfocus loop is spotted
**Bead:** HEALTH-ftdb | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

Metacognitive awareness jumped this month — real-time catching of hyperfocus as compulsion is now happening. The next edge isn't more awareness, it's a pre-decided action: 'I notice I'm in the loop, so I [specific thing].' Worth naming the specific action in therapy while the pattern recognition is fresh.

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-ftdb --reason="Completed in Codex session"`

---

### TASK 6 — Direct transcription → daemon cache pipe
**Bead:** HEALTH-jtn1 | **Project:** HEALTH | **Priority:** P2 | **Type:** task 

After /transcribe-diarium sets clipboard, also write cleaned markdown to ~/.claude/cache/diarium-md/{date}.md matching existing section headers from diarium-zip-to-md.py. Merge don't overwrite if file exists. Non-blocking. iPhone limitation documented. Diarium ZIP continues for photos/metadata.

**Success criteria:**
- Work is complete and validated
- Run: `bd close HEALTH-jtn1 --reason="Completed in Codex session"`

---

### TASK 7 — Watchdog: Beads integrity issues (2026-04-22)
**Bead:** TODO-qu4k | **Project:** TODO | **Priority:** P2 | **Type:** task 

Automated bead from beads-integrity-watchdog.

Warnings: 1
Log: /Users/jamescherry/.claude/logs/beads-integrity-watchdog.log

Details:
- WORK: Prefix contamination: 3 foreign issue(s) in JSONL: HEALTH-52y, HEALTH-e0v, HEALTH-3tz.

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-qu4k --reason="Completed in Codex session"`

---

### TASK 8 — Complete Blossom referral form — Mrs Cuesta (Gordon Primary)
**Bead:** TODO-ogks.1 | **Project:** TODO | **Priority:** P2 | **Type:** task 

Referral form received from Mrs Cuesta (SENCO) at the 2026-04-21 meeting. Discussed: NHS route, Right to Choose, private assessments. Form sent — verify submission is complete and confirm what happens next. Todoist task: 6gQwJRv4G3cjWq65 (Blossom project).

**Notes:**
SESSION PROMPT:

## Session Context

Bead: TODO-ogks.1 — Complete Blossom referral form — Mrs Cuesta (Gordon Primary)
Parent bead: TODO-ogks (School SENCO meeting)
Todoist task: 6gQwJRv4G3cjWq65 — project: Blossom Autism Assessment
Tracker file: .plan/blossom.md

## Starting State

2026-04-21: Jim and Janna attended meeting with Mrs Cuesta (SENCO). Discussed NHS, R2C, private assessments. Form received and sent. Todoist task created 11:44 UTC.

## Goal

Confirm form fully completed and submitted. Capture what it covers, update tracker, identify next step.

## Tasks

1. Read .plan/blossom.md for full current state
2. Fetch Todoist task 6gQwJRv4G3cjWq65 for any added notes
3. Ask Jim: what does the form cover? Is it school-internal or external? Fully filled in? What did Mrs Cuesta say happens next? Any timelines mentioned?
4. Update blossom.md with meeting summary, form details, submission status, next steps
5. Comment on TODO-ogks and TODO-ogks.1 with outcome; advance state where confirmed

## Constraints

- Never invent form fields or school next steps — log only what Jim confirms
- Never claim confirmed/submitted without Jim stating it
- PDA framing: choice not obligation, no urgency, British English

## Done When

blossom.md updated, submission status confirmed or parked with next action, beads updated.

**Success criteria:**
- Work is complete and validated
- Run: `bd close TODO-ogks.1 --reason="Completed in Codex session"`

---

> Additional ready beads omitted from the startup overlay: 8. Run `bd ready` or `bd show <id>` when you need the next item.


## Session Close Protocol (Do This At The End)

> WARNING: Only use the `bd` subcommands shown below (close, export).
> Do NOT invent commands like `bd sync`, `bd dolt push`, or any others.

```bash
# 1. Close completed beads (add/remove IDs as appropriate)
bd close HEALTH-8xs2 HEALTH-uj9y HEALTH-w4jc HEALTH-yozi HEALTH-ftdb HEALTH-jtn1 TODO-qu4k TODO-ogks.1 TODO-c07v TODO-np34 TODO-2vbg TODO-m7g6 TODO-45v4 TODO-m1zz TODO-5cg0 TODO-l0xk

# 2. Export beads to JSONL (must run inside each project dir)
cd ~/Documents/Claude\ Projects/HEALTH && bd export -o .beads/issues.jsonl
cd ~/Documents/Claude\ Projects/WORK && bd export -o .beads/issues.jsonl
cd ~/Documents/Claude\ Projects/TODO && bd export -o .beads/issues.jsonl

# 3. Git commit + push each project that changed
cd ~/Documents/Claude\ Projects/HEALTH && git add -A && git commit -m "Codex session: [what you did]" && git push
cd ~/Documents/Claude\ Projects/WORK && git add -A && git commit -m "Codex session: [what you did]" && git push
cd ~/Documents/Claude\ Projects/TODO && git add -A && git commit -m "Codex session: [what you did]" && git push

# 4. Sync to Apple Notes (known: AppleEvent -10000 is non-fatal, ignore)
~/.claude/scripts/sync-journal-to-apple-notes.sh
```

---

*Generated automatically by `~/.claude/scripts/generate-codex-prompt.py`*
*2026-04-22 — 16 task(s) from ready beads*
