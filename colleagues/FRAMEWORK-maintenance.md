# Colleagues Framework — maintenance reference

Moved out of startup payload from FRAMEWORK.md on 2026-04-27. Load on demand for maintenance, scope, or implementation details.

`INDEX.md`
- lists every topic file
- gives one-line purpose notes
- points to learned/ as review-only

`terminology.md`
- domain words and Jim-flavoured definitions

`workflow-patterns.md`
- repeatable sequences
- common handoffs
- known checkpoints

`contacts.md`
- people, orgs, relationship notes

`gotchas.md` or domain equivalent
- recurring traps
- easy misses
- reminders with context

`learned/YYYY-MM.md`
- extractor output only
- candidates, not canon
- quoted trigger line where possible

## Extractor etiquette

`colleagues-extract.py`:
- runs only inside a known project cwd
- reads the local Claude transcript folder
- writes to `learned/`
- leaves canonical files alone
- exits quietly outside known project roots

## Bridge generator etiquette

`colleagues-bridge.py`:
- reads only scope-approved inputs
- trims output to a light session-start size
- stamps `generated:` and `stale_after_days:`
- keeps private collections out of the wrong project

## Freshness

A bridge older than seven days is stale enough to mention.
A stale bridge can still offer context, though with less weight.

## Persona brief shape

Keep briefs compact.
A good brief usually covers:
- who the colleague is
- voice and rhythm
- mirror-first reminder
- domain lane
- out-of-scope lanes
- explicit refusal / handoff edges
- learning trigger behaviour

## Gears inheritance

Global gears still apply.
Personas inherit the main Claude rules from `~/.claude/CLAUDE.md`.
This framework adds local tone, scope, and learning shape.

## Handoff phrasing

When a question is out of lane, keep it easy:
- `That's Rae's lane, not mine.`
- `That's more Mal than Ori.`
- `I can stay with the logistics here, though the deeper read sits elsewhere.`

## Quality bar

A good colleague reply feels like:
- recognised state
- domain fit
- clean scope
- no invention
- one useful move

## Failure signs

Something has drifted if the persona:
- sounds like generic Claude
- reaches into the wrong project
- invents specifics
- gives a lecture
- slips into pressure language
- uses therapy language Rae explicitly bans

## Adding a new colleague

1. Copy the persona template.
2. Copy the knowledge template.
3. Add the project to `scope-manifest.yaml`.
4. Seed a few high-value files.
5. Generate a first bridge.
6. Append the persona block to the project CLAUDE file.
7. Run scope checks before treating it as live.
