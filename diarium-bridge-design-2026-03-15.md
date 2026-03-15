# Diarium bridge design — 2026-03-15

## Current state
- The daemon currently watches `~/My Drive (james.cherry01@gmail.com)/Diarium/Export`.
- Same-day Diarium ingestion depends on manual export of `.docx` or `.txt` files into that folder.
- Parsed source of truth is then merged into `~/.claude/cache/session-data.json`.
- There is already a lighter-weight capture path via `~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/claude-capture-queue.jsonl`.
- The capture queue already supports:
  - `morning_pages`
  - `update`
  - `evening_reflection`
  - `mood_check_in`
  - `mindful_minutes`

## Main friction
- full Diarium state still depends on manual export
- mobile capture path only covers a few free-text sections
- structured morning/evening fields are not first-class in the capture queue
- dashboard freshness can only be as good as the latest exported docx unless the user manually mirrors content elsewhere

## Best bridge direction
Use the existing capture queue / local API as the lower-friction bridge instead of replacing Diarium outright.

## Recommended phased design
### Phase 1 — structured same-day capture
Add capture queue entry types for structured Diarium sections:
- `grateful`
- `anxious_about`
- `one_important_thing`
- `letting_go`
- `daily_affirmation`
- `body_check`
- `three_things`
- `ta_dah`
- `remember_tomorrow`
- `whats_tomorrow`
- `letting_go_tonight`

These should merge into `data["diarium"]` with source metadata like `capture_queue` / timestamp.

### Phase 2 — authenticated API ingress
Add a small authenticated API endpoint on `:8765`, e.g.:
- `POST /v1/diarium/capture`

This lets iPhone/iPad Shortcuts send structured payloads directly when remote, instead of only writing a queue file.

### Phase 3 — freshness / precedence rules
Suggested merge rules:
- exported Diarium docx remains canonical historical source
- same-day capture entries can fill missing fields before export lands
- once a same-day docx export arrives, it should override weaker capture text where appropriate, but preserve unique later updates where export is older / less complete

### Phase 4 — UX shortcuts
Create Apple Shortcuts for:
- morning check-in
- quick update
- evening reflection
- ta-dah capture
- tomorrow note

All should target the same capture schema.

## Best next implementation
The smallest useful next step is:
1. extend `process_capture_queue()` to accept structured Diarium field entry types
2. add a shared merge helper for string/list Diarium fields
3. optionally expose `POST /v1/diarium/capture` in the API server using the same schema

## Why this path
- reuses infrastructure that already exists
- works locally and remotely
- avoids building a second diary system
- reduces dependency on repeated docx exports without throwing away Diarium
